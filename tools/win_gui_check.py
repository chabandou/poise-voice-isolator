"""
The GUI's audio worker end to end, measured from outside.

    python tools/win_gui_check.py [--phases idle:60,gilblock:60,cpugil:60]

Runs gui.worker.AudioWorker as the main window does (a Qt event loop,
its signals, a live change of the reduction strength) and measures the
audio with latmeter like tools/win_latency.py. The load phases run in
this process, beside the event loop: a busy GUI. Default playback is not
switched (latmeter plays into CABLE Input itself). The run lands in
build/latency/<out> with the same report as win_latency.py.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from win_latency import (CAPTURE, DEFAULT_SPEAKERS, LATMETER, PLAY,  # noqa: E402
                         Load, _device_id, _qpc_freq, analyze, make_signal)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--phases", default="idle:60,gilblock:60,cpugil:60")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    phases = [(n, float(s)) for n, _, s in
              (p.partition(":") for p in args.phases.split(","))]
    total = sum(s for _, s in phases)
    out = Path(args.out or ROOT / "build" / "latency"
               / time.strftime("%Y%m%d-%H%M%S-gui"))
    out.mkdir(parents=True, exist_ok=True)

    from PyQt6.QtCore import QCoreApplication, QTimer
    from stream_denoiser.logging_config import ensure_file_logging
    from stream_denoiser.gui.worker import AudioWorker

    log_path = ensure_file_logging(log_file=str(out / "poise.log"), level="INFO")
    make_signal(out / "signal.f32")
    app = QCoreApplication(sys.argv)
    worker = AudioWorker()
    worker.configure(model="deepfilternet3", atten_lim_db=-1.0,
                     output_device=_device_id(DEFAULT_SPEAKERS, True),
                     vb_cable_enabled=False)
    meta = {"backend": "gui-worker", "engine": "df3", "atten_lim_db": -1.0,
            "phases": phases, "log": log_path, "events": [], "marks": []}
    node = open(out / "node.jsonl", "w")
    state = {"meter": None, "load": Load(), "i": 0, "t0": None}

    def event(kind, value=""):
        meta["events"].append({"t": time.perf_counter(), "kind": kind,
                               "value": value})
        print(f"[{kind}] {value}", flush=True)

    def on_stats(stats):
        if "frames_wet" in stats:
            node.write(json.dumps({"t": time.perf_counter(), **stats}) + "\n")

    def next_phase():
        load = state["load"]
        if state["i"] == len(phases):
            load.stop()
            meta["marks"].append({"phase": "end", "t": time.perf_counter()})
            event("stop", "stopping the worker")
            worker.stop()
            return
        name, sec = phases[state["i"]]
        state["i"] += 1
        meta["marks"].append({"phase": name, "t": time.perf_counter()})
        event("phase", name)
        load.start(name)
        if state["i"] == 1:
            # A live change mid-run, as the dial makes it (back to the
            # same value, so the measurement stays comparable).
            QTimer.singleShot(5000, lambda: (worker.set_atten_lim_db(-2.0),
                                             worker.set_atten_lim_db(-1.0),
                                             event("live", "atten_lim_db set")))
        QTimer.singleShot(int(sec * 1000), next_phase)

    def on_status(text):
        event("status", text)
        if text == "Processing" and state["meter"] is None:
            state["meter"] = subprocess.Popen(
                [str(LATMETER), PLAY, DEFAULT_SPEAKERS, str(out / "signal.f32"),
                 str(total + 4), str(out / "rec"), CAPTURE],
                stderr=subprocess.PIPE, text=True)
            QTimer.singleShot(3000, next_phase)   # settle, as win_latency

    def on_stopped():
        event("stopped")
        meter = state["meter"]
        if meter is not None:
            try:
                meta["latmeter"] = meter.communicate(timeout=30)[1]
            except subprocess.TimeoutExpired:
                meter.kill()
        worker.shutdown()
        app.quit()

    worker.status_changed.connect(on_status)
    worker.error_occurred.connect(lambda m: event("error", m))
    worker.started_processing.connect(lambda: event("started"))
    worker.stopped_processing.connect(on_stopped)
    worker.stats_updated.connect(on_stats)
    worker.start()
    app.exec()
    worker.wait(10000)
    node.close()
    meta["qpc_freq"] = _qpc_freq()
    (out / "meta.json").write_text(json.dumps(meta, indent=1))
    if len(meta["marks"]) > 1:
        print(json.dumps(analyze(out), indent=1))
    else:
        print("no measurement (see events above)")


if __name__ == "__main__":
    main()
