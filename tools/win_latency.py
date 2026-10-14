"""
Measure Poise's delay on Windows from outside, on real devices.

    python tools/win_latency.py run --backend wasapi --phases idle:60,cpu:60
    python tools/win_latency.py analyze <run dir>

``run`` starts Poise in this process (native WASAPI path or the PortAudio
fallback), capturing CABLE Output and playing to the speakers, and starts
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
        self._f = open(path, "w")
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._t.start()

    def _run(self):
        while not self._stop.wait(1.0):
            node = self.node
            if node is None or node._handle is None:
                continue
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

    engine = make_engine(args.engine, args.atten_lim_db)
    proc = DenoiserAudioProcessor(engine, frame_size=engine.required_frame_size,
                                  atten_lim_db=args.atten_lim_db)
    stop = threading.Event()
    watch = NodeWatch(out / "node.jsonl")
    started = threading.Event()
    meta = {"backend": args.backend, "engine": args.engine,
            "priority_class": not args.no_priority_class,
            "margin_env": os.environ.get("POISE_WIN_MARGIN_MS"),
            "speakers": args.speakers, "phases": phases, "log": log_path}

    def poise():
        try:
            if args.backend == "wasapi":
                from stream_denoiser.backends import wasapi_backend
                if args.no_priority_class:
                    wasapi_backend.ABOVE_NORMAL_PRIORITY_CLASS =                         wasapi_backend.NORMAL_PRIORITY_CLASS
                real_node = wasapi_backend.WasapiNode

                class Watched(real_node):
                    def __init__(self, **kw):
                        super().__init__(**kw)
                        watch.node = self

                wasapi_backend.WasapiNode = Watched
                wasapi_backend.run_wasapi_loop(
                    proc, CAPTURE, args.speakers, should_stop=stop,
                    on_started=started.set)
            else:
                from stream_denoiser.backends import sounddevice_backend
                started.set()
                sounddevice_backend.process_with_sounddevice(
                    proc, _device_id(CAPTURE, False),
                    _device_id(args.speakers, True), backend="portaudio")
        except Exception as e:  # reported in meta
            meta["error"] = repr(e)
            started.set()

    if args.backend == "wasapi":
        th = threading.Thread(target=poise, daemon=True)
        th.start()
    else:
        # PortAudio loop: blocking until KeyboardInterrupt, so it gets the
        # main thread and the schedule runs beside it.
        th = None
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
            if th is None:
                import _thread
                _thread.interrupt_main()

    sched = threading.Thread(target=schedule, daemon=True)
    sched.start()
    if th is None:
        try:
            poise()
        except KeyboardInterrupt:
            pass
    else:
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


def _played_offset(ref, sig, start=SR, end=None):
    """Recorded index minus played index, from the first clear match in
    ref[start:end] (constant until the recording loses audio)."""
    end = len(ref) - SR // 10 if end is None else min(end, len(ref) - SR // 10)
    for L in range(start, end, SR // 2):
        seg = ref[L:L + SR // 10].astype(np.float64)
        if np.dot(seg, seg) < 1e-6 * len(seg):
            continue
        i, corr = _best_lag(seg, np.concatenate([sig, sig]), 0)
        if corr > 0.95:
            i %= len(sig)
            return L - (i + len(sig) * round((L - i) / len(sig)))
    return None


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
    for L in range(SR, len(lis) - win, step):
        seg = lis[L:L + win].astype(np.float64)
        if np.dot(seg, seg) < 1e-6 * win:
            rows.append((t_lis[L], np.nan, np.nan, 0.0, np.nan))
            continue
        # Where in the reference recording this audio should be: about one
        # latency earlier (first window: anywhere in the first seconds).
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
            guess = lat
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
        if len(lat) < 4:
            report["phases"].append({"phase": a["phase"], "windows": int(sel.sum())})
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
            "render_queue", "capture_age_us") if k in last}
    (out / "report.json").write_text(json.dumps(report, indent=1))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--backend", choices=("wasapi", "portaudio"), default="wasapi")
    r.add_argument("--engine", choices=("shadow", "df3", "passthrough"),
                   default="shadow")
    r.add_argument("--atten-lim-db", type=float, default=-60.0)
    r.add_argument("--phases", default="idle:60")
    r.add_argument("--speakers", default=DEFAULT_SPEAKERS)
    r.add_argument("--settle", type=float, default=3.0,
                   help="seconds Poise runs before the measurement starts")
    r.add_argument("--out", default=None)
    r.add_argument("--no-priority-class", action="store_true",
                   help="leave the process at normal priority (A/B tests)")
    a = sub.add_parser("analyze")
    a.add_argument("dir")
    args = ap.parse_args()
    if args.cmd == "run":
        out = cmd_run(args)
        print(json.dumps(analyze(out), indent=1))
    else:
        print(json.dumps(analyze(Path(args.dir)), indent=1))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
