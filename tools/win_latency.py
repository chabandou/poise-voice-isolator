"""
Measure Poise's delay on Windows from outside, on real devices.

    python tools/win_latency.py run --backend portaudio-proc --phases idle:60
    python tools/win_latency.py analyze <run dir>

``run`` starts Poise, capturing CABLE Output and playing to the speakers:
  portaudio-proc  the PortAudio loop in the audio process (audio_host),
                  this process standing in for the UI;
  wasapi-proc     the native path in the audio process, likewise;
  portaudio       the PortAudio loop on a thread of this process, as the
                  GUI runs it (the load threads share its GIL);
  wasapi          the native path on a thread of this process.
It also starts
latmeter.exe (native/latmeter), which plays band-limited noise into
CABLE Input like a video player and records loopback streams of CABLE
Input and of the speakers with their QPC times. ``analyze`` lines the two
recordings up every 250 ms: the delay through Poise over time, which is
what A/V sync sees, plus dropouts.

The engine is DeepFilterNet3 run for its CPU load ("shadow"): every frame
goes through the model, but the frame played is the input delayed by the
model's latency, so the noise stays measurable and the timing is exactly
that of processed audio. "df3" plays the real output (set --atten-lim-db
near 0 so the noise survives); "passthrough" runs no model.

Load phases run one after the other (name:seconds):
  idle      nothing extra
  cpu       one busy process per logical CPU, normal priority
  gil       a Python thread in pure-Python bursts (a busy UI)
  gilblock  a thread that holds the GIL for 80 ms every second inside
            one C call (a UI stuck in a long native call)
  cpugil    cpu and gil together (a busy UI on a busy machine)
"""
import argparse
import ctypes
import json
import multiprocessing
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SR = 48000
SIGNAL_SEC = 10
CAPTURE = "CABLE Output (VB-Audio Virtual Cable)"
PLAY = "CABLE Input (VB-Audio Virtual Cable)"
DEFAULT_SPEAKERS = "Speaker (Realtek(R) Audio)"
LATMETER = ROOT / "build" / "latmeter.exe"


# ---------------------------------------------------------------------------
# Signal
# ---------------------------------------------------------------------------

def make_signal(path: Path, seed: int = 1234) -> np.ndarray:
    """Band-limited noise (200 Hz - 6 kHz), about -26 dBFS RMS: survives the
    resamplers untouched and correlates sharply anywhere."""
    rng = np.random.default_rng(seed)
    n = SR * SIGNAL_SEC
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SR)
    spec[(f < 200) | (f > 6000)] = 0
    x = np.fft.irfft(spec, n)
    x *= 0.05 / np.sqrt(np.mean(x ** 2))
    x = x.astype(np.float32)
    x.tofile(path)
    return x


# ---------------------------------------------------------------------------
# Engines
# ---------------------------------------------------------------------------

def make_engine(kind: str, atten_lim_db: float):
    from stream_denoiser.engines import create_engine
    from stream_denoiser.engines.base import DelayLine, DenoiseEngine

    if kind == "df3":
        return create_engine("deepfilternet3", atten_lim_db=atten_lim_db)

    real = create_engine("deepfilternet3") if kind == "shadow" else None

    class Measured(DenoiseEngine):
        """The input, delayed by DF3's latency; DF3 runs for the load."""
        name = f"{kind}-df3"
        required_frame_size = real.required_frame_size if real else 512
        latency_samples = real.latency_samples if real else 1536
        speech_prob = None

        def __init__(self):
            self._delay = DelayLine(self.latency_samples)

        def process_frame(self, frame):
            if real is not None:
                real.process_frame(frame)
            return self._delay.process(np.asarray(frame, np.float32))

        def reset(self):
            if real is not None:
                real.reset()

        def close(self):
            if real is not None:
                real.close()

    return Measured()


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------

def _burn():
    while True:
        pass


class Load:
    def __init__(self):
        self._procs = []
        self._stop = threading.Event()
        self._thread = None

    def start(self, kind: str):
        self.stop()
        self._stop.clear()
        if kind == "cpugil":
            self.start("cpu")
            kind = "gil"
        if kind == "cpu":
            for _ in range(os.cpu_count() or 4):
                p = multiprocessing.Process(target=_burn, daemon=True)
                p.start()
                self._procs.append(p)
        elif kind == "gil":
            self._thread = threading.Thread(target=self._gil, daemon=True)
            self._thread.start()
        elif kind == "gilblock":
            self._thread = threading.Thread(target=self._gilblock, daemon=True)
            self._thread.start()

    def _gil(self):
        # Pure Python, ~30 ms bursts with short breaks, like a UI redrawing.
        while not self._stop.is_set():
            t = time.perf_counter()
            x = 0
            while time.perf_counter() - t < 0.03:
                for i in range(200):
                    x += i * i
            time.sleep(0.005)

    def _gilblock(self):
        # One regex search over a string with no match: a single C call that
        # never releases the GIL. Sized to ~80 ms here once at start.
        text = "a" * 2000
        pattern = re.compile(r"(a|aa)*c")
        n = 18
        t = time.perf_counter()
        pattern.search(text[:n])
        while time.perf_counter() - t < 0.02 and n < 60:
            n += 1
            t = time.perf_counter()
            pattern.search(text[:n])
        while not self._stop.is_set():
            pattern.search(text[:n + 2])
            self._stop.wait(1.0)

    def stop(self):
        self._stop.set()
        for p in self._procs:
            p.terminate()
        for p in self._procs:
            p.join(2)
        self._procs = []
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def _device_id(name: str, output: bool) -> int:
    import sounddevice as sd
    for i, d in enumerate(sd.query_devices()):
        if sd.query_hostapis(d["hostapi"])["name"] != "Windows WASAPI":
            continue
        ch = d["max_output_channels"] if output else d["max_input_channels"]
        if d["name"] == name and ch > 0:
            return i
    raise SystemExit(f"No WASAPI device named {name!r}")


class NodeWatch:
    """Snapshots of the native node's counters, with QPC-based times."""

    def __init__(self, path: Path):
        self.node = None
        self.host = None      # AudioHost: its stats carry the node's
        self._f = open(path, "w")
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()

    def _run(self):
        while not self._stop.wait(1.0):
            node, host = self.node, self.host
            if host is not None:
                stats = dict(host.stats)
                if "frames_wet" not in stats:
                    continue
                rec = {"t": time.perf_counter(), **stats}
            elif node is None or node._handle is None:
                continue
            else:
                try:
                    rec = {"t": time.perf_counter(), **node.stats(),
                           **node.io_stats(), "latency": node.latency_samples}
                except Exception:
                    continue
            self._f.write(json.dumps(rec) + "\n")
            self._f.flush()

    def stop(self):
        self._stop.set()
        self._t.join(3)
        self._f.close()


def cmd_run(args) -> Path:
    from stream_denoiser.logging_config import ensure_file_logging
    from stream_denoiser.processor import DenoiserAudioProcessor

    phases = []
    for part in args.phases.split(","):
        name, _, sec = part.partition(":")
        if name not in ("idle", "cpu", "gil", "gilblock", "cpugil"):
            raise SystemExit(f"unknown phase {name!r}")
        phases.append((name, float(sec)))
    total = sum(s for _, s in phases)

    out = Path(args.out or ROOT / "build" / "latency"
               / time.strftime(f"%Y%m%d-%H%M%S-{args.backend}"))
    out.mkdir(parents=True, exist_ok=True)
    log_path = ensure_file_logging(log_file=str(out / "poise.log"),
                                   level="INFO")
    sig = out / "signal.f32"
    make_signal(sig)
    if not LATMETER.exists():
        raise SystemExit(f"{LATMETER} missing: build native/latmeter first")

    if args.engine is None:
        args.engine = "df3" if args.backend.endswith("-proc") else "shadow"
    if args.atten_lim_db is None:
        # Real DF3 output: keep 89% of the input so the noise is measurable.
        args.atten_lim_db = -1.0 if args.engine == "df3" else -60.0
    if args.onnx_threads:
        # Before the engine modules are imported (here and in a child).
        os.environ["POISE_ONNX_THREADS"] = str(args.onnx_threads)
    child = args.backend.endswith("-proc")
    if child and args.engine != "df3":
        raise SystemExit(f"{args.backend} builds its own engine: use --engine df3 "
                         "(with --atten-lim-db -1 so the noise stays measurable)")
    proc = None
    if not child:
        engine = make_engine(args.engine, args.atten_lim_db)
        proc = DenoiserAudioProcessor(engine,
                                      frame_size=engine.required_frame_size,
                                      atten_lim_db=args.atten_lim_db)
    stop = threading.Event()
    watch = NodeWatch(out / "node.jsonl")
    started = threading.Event()
    meta = {"backend": args.backend, "engine": args.engine,
            "atten_lim_db": args.atten_lim_db,
            "realtime": not args.no_realtime,
            "onnx_threads": os.environ.get("POISE_ONNX_THREADS"),
            "margin_env": os.environ.get("POISE_WIN_MARGIN_MS"),
            "speakers": args.speakers, "phases": phases, "log": log_path}

    def poise():
        try:
            if args.backend == "wasapi":
                from stream_denoiser.backends import wasapi_backend
                real_node = wasapi_backend.WasapiNode

                class Watched(real_node):
                    def __init__(self, **kw):
                        super().__init__(**kw)
                        watch.node = self

                wasapi_backend.WasapiNode = Watched
                wasapi_backend.run_wasapi_loop(
                    proc, CAPTURE, args.speakers, should_stop=stop,
                    on_started=started.set)
            elif args.backend == "portaudio":
                # In this process, beside the load threads: as in the GUI.
                from stream_denoiser.backends import sounddevice_backend
                sounddevice_backend.run_portaudio_loop(
                    proc, _device_id(CAPTURE, False),
                    _device_id(args.speakers, True), should_stop=stop,
                    on_started=lambda *_: started.set(),
                    realtime=not args.no_realtime)
            else:
                # In the audio process (audio_host), this one being the UI.
                from stream_denoiser.audio_host import AudioHost

                def on_event(msg):
                    if msg.get("event") == "running":
                        started.set()
                    elif msg.get("event") == "error":
                        meta["error"] = msg.get("message")
                        started.set()

                host = AudioHost(on_event)
                watch.host = host
                try:
                    host.start({
                        "backend": args.backend[:-len("-proc")],
                        "model": "deepfilternet3",
                        "atten_lim_db": args.atten_lim_db,
                        "input_device": _device_id(CAPTURE, False),
                        "output_device": _device_id(args.speakers, True),
                        "realtime": not args.no_realtime})
                    stop.wait()
                    meta["final_stats"] = host.stop(timeout=10.0)
                finally:
                    host.shutdown()
        except Exception as e:  # reported in meta
            meta["error"] = repr(e)
            started.set()

    th = threading.Thread(target=poise, daemon=True)
    th.start()
    watch.start()

    def schedule():
        started.wait(30)
        time.sleep(args.settle)
        meter = subprocess.Popen(
            [str(LATMETER), PLAY, args.speakers, str(sig), str(total + 1),
             str(out / "rec"), CAPTURE], stderr=subprocess.PIPE, text=True)
        t0 = time.perf_counter()
        marks = []
        load = Load()
        try:
            time.sleep(0.5)
            if meter.poll() is not None:
                raise RuntimeError("latmeter exited: " + meter.stderr.read())
            for name, sec in phases:
                marks.append({"phase": name, "t": time.perf_counter()})
                print(f"[{time.perf_counter() - t0:6.1f}s] phase {name} "
                      f"for {sec:.0f}s", flush=True)
                load.start(name)
                end = time.perf_counter() + sec
                while time.perf_counter() < end and meter.poll() is None:
                    time.sleep(0.2)
        finally:
            load.stop()
            marks.append({"phase": "end", "t": time.perf_counter()})
            meta["marks"] = marks
            try:
                meta["latmeter"] = meter.communicate(timeout=30)[1]
            except subprocess.TimeoutExpired:
                meter.kill()
            stop.set()

    sched = threading.Thread(target=schedule, daemon=True)
    sched.start()
    th.join()
    sched.join(60)
    watch.stop()
    meta["qpc_freq"] = _qpc_freq()
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    print(f"recorded in {out}")
    if "error" in meta:
        print("Poise error:", meta["error"])
    return out


def _qpc_freq() -> int:
    f = ctypes.c_int64()
    ctypes.windll.kernel32.QueryPerformanceFrequency(ctypes.byref(f))
    return f.value


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def _load_stream(out: Path, tag: str):
    x = np.fromfile(out / f"rec.{tag}.f32", dtype=np.float32)
    pk = np.loadtxt(out / f"rec.{tag}.csv", delimiter=",", skiprows=1,
                    dtype=np.float64, ndmin=2)
    return x, pk


def _times(pk, n):
    """QPC time (s) of every sample, from each packet's first-sample time.
    Within a packet samples are 1/SR apart."""
    t = np.empty(n)
    pos, qpc, frames = pk[:, 0].astype(np.int64), pk[:, 1] / 1e7, pk[:, 2]
    for p, q, f in zip(pos, qpc, frames.astype(np.int64)):
        e = min(p + f, n)
        if p < n:
            t[p:e] = q + np.arange(e - p) / SR
    return t


def _best_lag(seg, ref, lo):
    """Index into ref where seg matches best (FFT cross-correlation), and
    the normalized correlation there."""
    n, m = len(seg), len(ref)
    size = 1 << int(np.ceil(np.log2(n + m)))
    c = np.fft.irfft(np.fft.rfft(ref, size) * np.conj(np.fft.rfft(seg, size)),
                     size)[:m - n + 1]
    i = int(np.argmax(c))
    a = ref[i:i + n]
    den = np.sqrt(np.dot(a, a) * np.dot(seg, seg)) or 1.0
    return lo + i, float(c[i] / den)


def _played_offset(ref, sig, start=SR, end=None, points=12):
    """Recorded index minus played index over ref[start:end] (constant
    until the recording loses audio): the most common one among clear
    matches spread across the stretch. Not just the first: an unflagged
    glitch near a recording's start (another client opening the device)
    would shift every later sample."""
    end = len(ref) - SR // 10 if end is None else min(end, len(ref) - SR // 10)
    if end <= start:
        return None
    looped = np.concatenate([sig, sig])
    found = {}
    for L in np.linspace(start, end - 1, points).astype(int):
        seg = ref[L:L + SR // 10].astype(np.float64)
        if np.dot(seg, seg) < 1e-6 * len(seg):
            continue
        i, corr = _best_lag(seg, looped, 0)
        if corr > 0.95:
            i %= len(sig)
            off = int(L - (i + len(sig) * round((L - i) / len(sig))))
            found[off] = found.get(off, 0) + 1
    return max(found, key=found.get) if found else None


def _holes(pk):
    """Recorded indices where a recording lost audio: packets flagged
    discontinuous (after the first) or time stamps jumping ahead."""
    q = pk[:, 1] / 1e7
    jump = np.diff(q) - pk[:-1, 2] / SR
    idx = set(np.where(jump > 0.005)[0] + 1)
    idx |= set(np.where(pk[1:, 3].astype(int) & 1)[0] + 1)
    return sorted(int(pk[i, 0]) for i in idx)


class _Offsets:
    """Recorded-to-played index offsets, one per stretch between holes."""

    def __init__(self, rec, pk, sig):
        bounds = [0] + _holes(pk) + [len(rec)]
        self.parts = []
        for a, b in zip(bounds, bounds[1:]):
            off = _played_offset(rec, sig, start=a + SR // 10, end=b)
            self.parts.append((a, b, off))

    def __call__(self, i):
        for a, b, off in self.parts:
            if a <= i < b:
                return off
        return None


def _split(rows) -> dict:
    """VB-Cable's part and the rest, where the tap recording has them."""
    cable = rows[:, 4]
    ok = np.isfinite(cable)
    if ok.sum() < 4:
        return {}
    rest = rows[ok, 1] - cable[ok]
    return {"cable_ms": {"median": round(float(np.median(cable[ok])), 2),
                         "min": round(float(cable[ok].min()), 2),
                         "max": round(float(cable[ok].max()), 2)},
            "poise_ms": {"median": round(float(np.median(rest)), 2),
                         "min": round(float(rest.min()), 2),
                         "max": round(float(rest.max()), 2)}}


def analyze(out: Path, step_ms: float = 250.0, win_ms: float = 100.0):
    """Delay every step_ms, two ways:

    av_ms: speakers' loopback time (an estimate of when the sound leaves
        the speakers) minus the time CABLE Input's clock says the sample
        played: the A/V offset a player that syncs to its audio clock
        (IAudioClock) gets.
    loop_ms: speakers' loopback time minus CABLE Input's loopback time.
        Both are the drivers' "heard at" estimates, so VB-Cable's
        reported latency (~150 ms) counts against it.
    cable_ms / poise_ms: av_ms split at CABLE Output, recorded beside
        Poise (when latmeter had a tap): VB-Cable's part (CABLE Input's
        clock to CABLE Output's capture time) and the rest (Poise, the
        speakers' buffer and their reported latency).
    """
    meta = json.loads((out / "meta.json").read_text())
    ref, ref_pk = _load_stream(out, "ref")
    lis, lis_pk = _load_stream(out, "lis")
    t_ref, t_lis = _times(ref_pk, len(ref)), _times(lis_pk, len(lis))
    sig = np.fromfile(out / "signal.f32", dtype=np.float32).astype(np.float64)
    clk = np.loadtxt(out / "rec.clk.csv", delimiter=",", skiprows=1, ndmin=2)
    # Device position only moves forward; keep its first time at each value.
    dev, first = np.unique(clk[:, 1], return_index=True)
    dev_t = clk[first, 2] / 1e7
    offset = _Offsets(ref, ref_pk, sig)
    tap = tap_t = tap_offsets = None
    if (out / "rec.tap.f32").exists():
        tap, tap_pk = _load_stream(out, "tap")
        tap_t = _times(tap_pk, len(tap))
        tap_offsets = _Offsets(tap, tap_pk, sig)
        # played index -> tap index: the stretch whose offset fits.
        tap_parts = [(a - off, b - off, off) for a, b, off in tap_offsets.parts
                     if off is not None]
    win, step = int(SR * win_ms / 1000), int(SR * step_ms / 1000)
    search = SR // 2
    rows = []
    guess = None
    misses = 0
    for L in range(SR, len(lis) - win, step):
        seg = lis[L:L + win].astype(np.float64)
        if np.dot(seg, seg) < 1e-6 * win:
            rows.append((t_lis[L], np.nan, np.nan, 0.0, np.nan))
            continue
        # Where in the reference recording this audio should be: about one
        # latency earlier (first window, or after a second without a
        # match, as when PortAudio drops a startup backlog: anywhere
        # within 2 s).
        if misses >= 4:
            guess, misses = None, 0
        if guess is None:
            centre = np.searchsorted(t_ref, t_lis[L] - 0.15)
            half = SR * 2
        else:
            centre = np.searchsorted(t_ref, t_lis[L] - guess)
            half = search
        lo = max(0, centre - half)
        hi = min(len(ref), centre + half + win)
        if hi - lo < win * 2:
            continue
        R, corr = _best_lag(seg, ref[lo:hi].astype(np.float64), lo)
        lat = t_lis[L] - t_ref[R]
        if corr > 0.8:
            guess, misses = lat, 0
        else:
            misses += 1
        av = cable = np.nan
        off = offset(R)
        if off is not None and dev[0] <= R - off <= dev[-1]:
            played = R - off
            av = t_lis[L] - np.interp(played, dev, dev_t)
            for a, b, toff in (tap_parts if tap is not None else ()):
                if a <= played < b:
                    cable = tap_t[played + toff] - np.interp(played, dev, dev_t)
                    break
        rows.append((t_lis[L], av * 1000.0, lat * 1000.0, corr, cable * 1000.0))
    rows = np.array(rows)
    np.savetxt(out / "latency.csv", rows, delimiter=",",
               header="qpc_s,av_ms,loop_ms,corr,cable_ms", comments="")

    # Gaps in each recording: packets flagged discontinuous, or holes in
    # the timestamps.
    def holes(pk):
        return len(_holes(pk))

    # Dropouts: runs of silence in what the speakers played (the signal is
    # continuous noise, so any is a gap), as (QPC time, samples).
    quiet = np.abs(lis) < 1e-4
    edges = np.diff(np.concatenate([[0], quiet.view(np.int8), [0]]))
    g0, g1 = np.where(edges == 1)[0], np.where(edges == -1)[0]
    keep = (g1 - g0) >= 64
    gaps = np.column_stack([t_lis[g0[keep]], (g1 - g0)[keep]])

    marks = meta.get("marks", [])
    report = {"backend": meta["backend"], "engine": meta["engine"],
              "recording_holes": {"ref": holes(ref_pk), "lis": holes(lis_pk)},
              "phases": []}
    if tap is not None:
        report["recording_holes"]["tap"] = holes(tap_pk)
    for a, b in zip(marks, marks[1:]):
        sel = (rows[:, 0] >= a["t"] + 1.0) & (rows[:, 0] < b["t"])
        good = sel & (rows[:, 3] > 0.8) & np.isfinite(rows[:, 1])
        lat = rows[good, 1]
        in_phase = (gaps[:, 0] >= a["t"]) & (gaps[:, 0] < b["t"])
        dropouts = {"speaker_gaps": int(in_phase.sum()),
                    "speaker_gap_ms": round(float(gaps[in_phase, 1].sum())
                                            * 1000.0 / SR, 1)}
        if len(lat) < 4:
            report["phases"].append({"phase": a["phase"], "windows": int(sel.sum()),
                                     "bad_windows": int(sel.sum() - good.sum()),
                                     **dropouts})
            continue
        tt = rows[good, 0]
        slope = np.polyfit(tt - tt[0], lat, 1)[0] * 60.0
        report["phases"].append({
            "phase": a["phase"],
            "start_s": round(a["t"] - marks[0]["t"], 1),
            "windows": int(sel.sum()),
            "bad_windows": int(sel.sum() - good.sum()),
            "av_ms": {
                "first": round(float(lat[:8].mean()), 2),
                "last": round(float(lat[-8:].mean()), 2),
                "median": round(float(np.median(lat)), 2),
                "min": round(float(lat.min()), 2),
                "max": round(float(lat.max()), 2),
                "p99_minus_p1": round(float(np.percentile(lat, 99)
                                            - np.percentile(lat, 1)), 2),
            },
            "loop_ms_median": round(float(np.median(rows[good, 2])), 2),
            **dropouts,
            **_split(rows[good]),
            "drift_ms_per_min": round(float(slope), 3),
        })
    node = out / "node.jsonl"
    if node.exists() and node.stat().st_size:
        recs = [json.loads(l) for l in node.read_text().splitlines()]
        for ph, a, b in zip(report["phases"], marks, marks[1:]):
            inside = [r for r in recs if a["t"] <= r["t"] < b["t"]]
            if len(inside) >= 2:
                ph["frames_dry"] = inside[-1]["frames_dry"] - inside[0]["frames_dry"]
                ph["frames_wet"] = inside[-1]["frames_wet"] - inside[0]["frames_wet"]
        last = recs[-1]
        report["node_final"] = {k: last[k] for k in (
            "frames_wet", "frames_dry", "frames_late", "frames_skipped",
            "fifo_starved", "fifo_inserted", "fifo_resyncs", "fifo_dropped",
            "capture_glitches", "render_underruns", "render_late",
            "render_gap_max_us", "rate_ppb", "fifo_target", "fifo_level",
            "fifo_headroom", "capture_period", "render_period",
            "render_buffer", "render_fill", "latency", "mmcss", "fifo_stalls",
            "render_queue", "capture_age_us", "capture_restarts", "holes",
            "holes_removed", "holes_left") if k in last}
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report


def cmd_cable(args) -> None:
    """VB-Cable's own delay: play into CABLE Input, capture CABLE Output,
    no Poise; each of ``--starts`` fresh starts gets its own streams (the
    delay differs per start). Times after CABLE Input's clock says the
    sample played: the capture's time stamp, and when it was readable."""
    base = ROOT / "build" / "latency" / f"cable-{args.label}"
    base.mkdir(parents=True, exist_ok=True)
    sig = make_signal(base / "signal.f32").astype(np.float64)
    results = []
    for i in range(args.starts):
        prefix = base / f"s{i}" / "rec"
        prefix.parent.mkdir(exist_ok=True)
        subprocess.run([str(LATMETER), PLAY, DEFAULT_SPEAKERS,
                        str(base / "signal.f32"), str(args.seconds),
                        str(prefix), CAPTURE], check=True, capture_output=True)
        tap, tpk = _load_stream(prefix.parent, "tap")
        off = _played_offset(tap, sig)
        clk = np.loadtxt(prefix.parent / "rec.clk.csv", delimiter=",",
                         skiprows=1, ndmin=2)
        dev, first = np.unique(clk[:, 1], return_index=True)
        dev_t = clk[first, 2] / 1e7
        stamp, readable = [], []
        for p in range(2 * SR, int(dev[-1]) - SR, SR // 2):
            j = np.searchsorted(tpk[:, 0], p + off, side="right") - 1
            t_clock = np.interp(p, dev, dev_t)
            stamp.append(tpk[j, 1] / 1e7 + (p + off - tpk[j, 0]) / SR - t_clock)
            readable.append(tpk[j, 4] / 1e7 - t_clock)
        results.append((np.median(stamp) * 1000, np.median(readable) * 1000))
        print(f"start {i}: time stamp {results[-1][0]:6.1f} ms, readable "
              f"{results[-1][1]:6.1f} ms after CABLE Input's clock", flush=True)
    r = np.array(results)
    summary = {"label": args.label, "starts": args.starts,
               "stamp_ms": {"median": round(float(np.median(r[:, 0])), 1),
                            "min": round(float(r[:, 0].min()), 1),
                            "max": round(float(r[:, 0].max()), 1)},
               "readable_ms": {"median": round(float(np.median(r[:, 1])), 1),
                               "min": round(float(r[:, 1].min()), 1),
                               "max": round(float(r[:, 1].max()), 1)}}
    (base / "report.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--backend", choices=("wasapi", "wasapi-proc", "portaudio",
                                         "portaudio-proc"),
                   default="wasapi-proc")
    r.add_argument("--engine", choices=("shadow", "df3", "passthrough"),
                   default=None, help="default: df3 for the -proc backends, "
                   "else shadow")
    r.add_argument("--atten-lim-db", type=float, default=None,
                   help="default: -1 with df3")
    r.add_argument("--phases", default="idle:60")
    r.add_argument("--speakers", default=DEFAULT_SPEAKERS)
    r.add_argument("--settle", type=float, default=3.0,
                   help="seconds Poise runs before the measurement starts")
    r.add_argument("--out", default=None)
    r.add_argument("--no-realtime", action="store_true",
                   help="PortAudio loop thread without MMCSS (A/B tests)")
    r.add_argument("--onnx-threads", type=int, default=0,
                   help="ONNX Runtime intra-op threads (default: Poise's)")
    a = sub.add_parser("analyze")
    a.add_argument("dir")
    c = sub.add_parser("cable", help="VB-Cable's own delay, without Poise")
    c.add_argument("label", help="names build/latency/cable-<label>")
    c.add_argument("--starts", type=int, default=6)
    c.add_argument("--seconds", type=float, default=8.0)
    args = ap.parse_args()
    if args.cmd == "run":
        out = cmd_run(args)
        print(json.dumps(analyze(out), indent=1))
    elif args.cmd == "cable":
        cmd_cable(args)
    else:
        print(json.dumps(analyze(Path(args.dir)), indent=1))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
