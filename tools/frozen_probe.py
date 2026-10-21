"""Frozen-build probe: the GUI's AudioWorker running a session.

Built by PyInstaller with the app's own spec (tools/make_probe_spec.py
swaps the entry script and the name, nothing else), so it freezes what
Poise.exe freezes and starts the audio process the way Poise.exe does:
this executable again, through multiprocessing's freeze_support().

Runs a few seconds of processing (CABLE Output to the default WASAPI
output device, VB-Cable switching off) and writes probe.json next to the
executable: the worker's events, the backend the audio process ran,
its final stats and the verdict. Exits 0 when the session ran and
stopped without an error, 1 otherwise.

Environment: PROBE_SECONDS (default 6), PROBE_MODEL (default
deepfilternet3), POISE_BACKEND (the app's own: auto, wasapi, portaudio).
"""
import os

# As run_poise_gui.py, before numpy loads.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    import json
    import sys
    import time
    import traceback

    here = os.path.dirname(os.path.abspath(sys.executable))
    seconds = float(os.environ.get("PROBE_SECONDS", "6"))
    model = os.environ.get("PROBE_MODEL", "deepfilternet3")
    t0 = time.perf_counter()
    result = {"frozen": bool(getattr(sys, "frozen", False)),
              "stderr_is_none": sys.stderr is None,
              "backend_env": os.environ.get("POISE_BACKEND"),
              "model": model,
              "events": []}

    def event(kind, value=""):
        result["events"].append({"t": round(time.perf_counter() - t0, 3),
                                 "kind": kind, "value": str(value)})

    try:
        from PyQt6.QtCore import QCoreApplication, QTimer
        from stream_denoiser.logging_config import ensure_file_logging
        from stream_denoiser.gui.worker import AudioWorker

        result["log"] = ensure_file_logging(
            log_file=os.path.join(here, "probe.log"), level="INFO")
        app = QCoreApplication(sys.argv)
        # The output the GUI's selector starts on: the WASAPI default
        # playback device (CI makes it a non-CABLE one).
        import sounddevice as sd
        wasapi = next(a for a in sd.query_hostapis()
                      if "wasapi" in a["name"].lower())
        output = wasapi["default_output_device"]
        result["output"] = sd.query_devices(output)["name"]
        worker = AudioWorker()
        worker.configure(model=model, atten_lim_db=-40.0,
                         output_device=output, vb_cable_enabled=False)

        # The audio process's own events, the backend it ran among them
        # (AudioHost calls whatever the worker holds at that name).
        forward = worker._on_host_event

        def on_host_event(msg):
            if msg.get("event") == "running":
                result["backend"] = msg.get("backend")
            forward(msg)

        worker._on_host_event = on_host_event

        def on_status(text):
            event("status", text)
            if text == "Processing" and "child_pid" not in result:
                result["child_pid"] = worker._host.pid
                QTimer.singleShot(int(seconds * 1000), worker.stop)

        def on_stopped():
            event("stopped")
            host = worker._host
            if host is not None:
                result["final_stats"] = host.final_stats
            worker.shutdown()
            app.quit()

        worker.status_changed.connect(on_status)
        worker.error_occurred.connect(lambda m: event("error", m))
        worker.started_processing.connect(lambda: event("started"))
        worker.stopped_processing.connect(on_stopped)
        QTimer.singleShot(int((seconds + 60) * 1000),
                          lambda: (event("error", "watchdog"), app.quit()))
        worker.start()
        app.exec()
        worker.wait(10000)
    except Exception:
        result["exception"] = traceback.format_exc()

    # No frame count check: nothing plays into the cable in CI, so
    # silence skipping keeps every frame from the model.
    result["ok"] = bool(
        result.get("child_pid")
        and result.get("backend")
        and not any(e["kind"] == "error" for e in result["events"])
        and "exception" not in result)
    with open(os.path.join(here, "probe.json"), "w") as f:
        json.dump(result, f, indent=1, default=str)
    sys.exit(0 if result["ok"] else 1)
