"""Re-analyze the runs in build/latency and write windows-latency-runs.csv.

The recordings stay on the machine that made them; RUNS labels each with
what it measured (the run metadata does not record all of it).
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from win_latency import analyze  # noqa: E402

# run: (path, process, margin_ms, priority, onnx_threads, note)
RUNS = {
    "A-wasapi": ("native", "ui", 21.3, "HIGHEST", 2, "as committed (1e16023)"),
    "A2-wasapi": ("native", "ui", 21.3, "HIGHEST", 2, "as committed; with CABLE Output tap"),
    "B-portaudio": ("portaudio", "ui", None, "normal", 2, "master's loop"),
    "X0-wasapi": ("native", "ui", 21.3, "HIGHEST", 2, "priority A/B: normal class"),
    "X1-wasapi": ("native", "ui", 21.3, "HIGHEST+ABOVE_NORMAL class", 2, "priority A/B: rejected"),
    "Y1-wasapi": ("native", "ui", 21.3, "MMCSS", 1, "de42b90"),
    "M21-wasapi": ("native", "ui", 21.3, "MMCSS", 1, "margin A/B"),
    "M11-wasapi": ("native", "ui", 10.7, "MMCSS", 1, "margin A/B"),
    "D1-wasapi": ("native", "ui", 21.3, "MMCSS", 1, "render_queue diagnostics"),
    "D2-wasapi": ("native", "ui", 21.3, "MMCSS", 1, "20 min; latmeter stall at 476 s"),
    "D3-wasapi": ("native", "ui", 21.3, "MMCSS", 1, "20 min; staircase step caught at 37.5 s"),
    "H1b-wasapi": ("native", "ui", 21.3, "MMCSS", 1, "head-to-head"),
    "H2-proc-rt": ("portaudio", "audio process", None, "MMCSS", 1, "head-to-head; bad start"),
    "H2b-proc-rt": ("portaudio", "audio process", None, "MMCSS", 1, "head-to-head; good start"),
    "H3b-proc-plain": ("portaudio", "audio process", None, "normal", 2, "head-to-head; no fixes"),
    "H4-inproc-rt": ("portaudio", "ui", None, "MMCSS", 1, "head-to-head; bad start"),
    "I-shadow": ("portaudio", "ui", None, "normal", 2, "start spread check"),
    "I-df3": ("portaudio", "ui", None, "normal", 2, "start spread check"),
    "S1-proc-rt": ("portaudio", "audio process", None, "MMCSS", 1, "start spread"),
    "S2-proc-rt": ("portaudio", "audio process", None, "MMCSS", 1, "start spread"),
    "S3-proc-rt": ("portaudio", "audio process", None, "MMCSS", 1, "start spread"),
    "M5-wasapi": ("native", "ui", 5.3, "MMCSS", 1, "small margin, no UI load"),
    "W1-wasapi-proc": ("native", "audio process", 5.3, "MMCSS", 1, "AudioHost"),
    "W2-wasapi-proc": ("native", "audio process", 5.3, "MMCSS", 1, "AudioHost"),
}

FIELDS = ["run", "date", "path", "process", "margin_ms", "priority",
          "onnx_threads", "engine", "note", "phase", "phase_start_s",
          "windows", "bad_windows", "dropouts", "dropout_ms",
          "av_median_ms", "av_first_ms", "av_last_ms", "av_p99_minus_p1_ms",
          "cable_median_ms", "poise_median_ms", "drift_ms_per_min",
          "dry_frames"]

rows = []
for run, (path, process, margin, prio, threads, note) in RUNS.items():
    out = ROOT / "build" / "latency" / run
    t0 = time.time()
    report = analyze(out)
    meta = json.loads((out / "meta.json").read_text())
    date = time.strftime("%Y-%m-%d %H:%M",
                         time.localtime((out / "meta.json").stat().st_mtime))
    engine = meta.get("engine")
    if engine == "df3":
        engine = f"df3 ({meta.get('atten_lim_db', -1)} dB)"
    for p in report["phases"]:
        av = p.get("av_ms", {})
        rows.append({
            "run": run, "date": date, "path": path, "process": process,
            "margin_ms": margin if margin is not None else "",
            "priority": prio, "onnx_threads": threads, "engine": engine,
            "note": note, "phase": p["phase"],
            "phase_start_s": p.get("start_s", ""),
            "windows": p.get("windows", ""),
            "bad_windows": p.get("bad_windows", ""),
            "dropouts": p.get("speaker_gaps", ""),
            "dropout_ms": p.get("speaker_gap_ms", ""),
            "av_median_ms": av.get("median", ""),
            "av_first_ms": av.get("first", ""),
            "av_last_ms": av.get("last", ""),
            "av_p99_minus_p1_ms": av.get("p99_minus_p1", ""),
            "cable_median_ms": p.get("cable_ms", {}).get("median", ""),
            "poise_median_ms": p.get("poise_ms", {}).get("median", ""),
            "drift_ms_per_min": p.get("drift_ms_per_min", ""),
            "dry_frames": p.get("frames_dry", ""),
        })
    print(f"{run}: {len(report['phases'])} phases ({time.time() - t0:.0f} s)",
          flush=True)

dest = ROOT / "measurements" / "windows-latency-runs.csv"
with open(dest, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)} rows -> {dest}")
