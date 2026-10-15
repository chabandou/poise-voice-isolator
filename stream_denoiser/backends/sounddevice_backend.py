"""
Sounddevice Backend

Audio processing using sounddevice for both input and output.

:func:`run_portaudio_loop` is the loop itself, stoppable and with a
stats callback, so it can run in the audio process (audio_host) as well
as from the CLI (both through session.py).
"""
import sys
import time
from contextlib import nullcontext
from typing import Callable, Optional, Tuple

import numpy as np

try:
    import sounddevice as sd
    USE_SOUNDDEVICE = True
except (ImportError, OSError):
    USE_SOUNDDEVICE = False

from ..audio_gc import gc_paused
from ..constants import STATS_PRINT_INTERVAL_SEC
from ..processor import DenoiserAudioProcessor
from ..logging_config import get_logger, get_log_file_path
from ..sync import StallCounter
from ..device_utils import (
    find_loopback_device,
    get_output_device_id,
    validate_output_device,
)
from ._loop_util import SYNC_LOG_INTERVAL_SEC, StopLike, fast_gil_handoff, \
    stop_requested

_logger = get_logger(__name__)


def _realtime_thread(enabled: bool):
    """MMCSS for the loop thread on Windows (see platform.windows)."""
    if not enabled or sys.platform != "win32":
        return nullcontext(False)
    from .platform.windows import mmcss_thread
    return mmcss_thread()


class PortAudioSyncLog:
    """"sync:" log lines for the PortAudio loop (the fallback path).

    PortAudio's blocking WASAPI streams report neither overflows nor
    underflows (measured: a 300 ms stall flagged nothing while the audio
    of it was lost), so losses are inferred from time: StallCounter
    compares the audio the loop got through with the wall time that
    passed. Capture backlog and output queue come from read_available
    and write_available, logged as their range over the interval.
    """

    def __init__(self, input_stream, output_stream, block_ms: float,
                 input_sr: int, output_sr: int):
        self._in, self._out = input_stream, output_stream
        self._in_ms = 1000.0 / input_sr
        self._out_ms = 1000.0 / output_sr
        # Output buffer size: the stream's latency is its length; before
        # the first write (unless primed) it is all free.
        self._out_size = max(
            output_stream.write_available,
            int(round(output_stream.latency * output_sr)))
        self.stalls = StallCounter(block_ms)
        self._logger = get_logger(__name__)
        self._last = None
        self._reset()

    def _reset(self):
        self._backlog = [float("inf"), 0.0]
        self._queue = [float("inf"), 0.0]

    def observe(self, now: float) -> None:
        """Call once per loop iteration (monotonic seconds)."""
        stall = self.stalls.observe(now)
        if stall:
            self._logger.info("sync: loop stalled %.0f ms (audio lost)",
                              stall)
        try:
            backlog = self._in.read_available * self._in_ms
            queue = (self._out_size - self._out.write_available) * self._out_ms
        except Exception:
            return
        for rng, v in ((self._backlog, backlog), (self._queue, queue)):
            rng[0], rng[1] = min(rng[0], v), max(rng[1], v)
        if self._last is None:
            self._last = now
        elif now - self._last >= SYNC_LOG_INTERVAL_SEC:
            self._logger.info(
                "sync: backend=portaudio capture_backlog=%.0f-%.0fms "
                "output_queue=%.0f-%.0fms stalls=%d max_stall=%.0fms "
                "lost=%.0fms", *self._backlog, *self._queue,
                self.stalls.count, self.stalls.max_ms, self.stalls.lost_ms)
            self._last = now
            self._reset()


def select_devices(processor: DenoiserAudioProcessor,
                   input_device: Optional[int] = None,
                   output_device: Optional[int] = None) -> Tuple[int, int]:
    """(input, output) device IDs: CABLE Output (or the given input) and
    an output device on the same host API. Raises ValueError when no
    output device fits."""
    try:
        input_dev_id = find_loopback_device(input_device)
    except (RuntimeError, ValueError) as e:
        _logger.warning("%s", e)
        input_dev_id = sd.default.device[0]

    devices = sd.query_devices()
    # Get input device's host API to ensure output uses the same backend
    input_device_info = sd.query_devices(input_dev_id)
    input_host_api = sd.query_hostapis(input_device_info['hostapi'])['name']
    output_dev_id = get_output_device_id(output_device, devices,
                                         input_host_api=input_host_api)
    if not validate_output_device(output_dev_id, processor.target_sr, devices):
        raise ValueError(f"Output device {output_dev_id} does not support "
                         "required configuration")
    return input_dev_id, output_dev_id


def _open_streams(processor: DenoiserAudioProcessor, input_dev_id: int,
                  output_dev_id: int):
    """Open the capture and playback streams (not started).

    Returns (input_stream, output_stream, input_sr, out_block_size).
    """
    input_device_info = sd.query_devices(input_dev_id)
    output_device_info = sd.query_devices(output_dev_id)
    input_sr = int(input_device_info['default_samplerate'])

    # Setup processor resampler. The input read size is rate-scaled so each
    # read resamples to ~one engine frame; a fixed frame_size read at a
    # non-target input rate lets the resampler backlog grow without bound
    # (A/V desync that becomes visible after a few minutes).
    processor.setup_resampler(input_sr)
    in_block_size = processor.input_block_size

    # NOTE: always capture stereo and downmix in software. Opening a
    # stereo WASAPI endpoint (e.g. VB-Cable Output) with channels=1
    # yields sample-doubled garbage on this driver (every sample
    # repeated twice = effective half rate in a full-rate container:
    # dull, muffled, incomprehensible). Stereo capture is bit-clean.
    try:
        input_stream = sd.InputStream(
            device=input_dev_id,
            samplerate=input_sr,
            channels=2,
            dtype='float32',
            blocksize=in_block_size
        )
    except sd.PortAudioError:
        # Fall back to mono capture for genuinely mono devices.
        input_stream = sd.InputStream(
            device=input_dev_id,
            samplerate=input_sr,
            channels=1,
            dtype='float32',
            blocksize=in_block_size
        )

    try:
        processor.setup_output_resampler(processor.target_sr)
        out_block_size = processor.output_resample_size
        output_stream = sd.OutputStream(
            device=output_dev_id,
            samplerate=processor.target_sr,
            channels=2,
            dtype='float32',
            blocksize=out_block_size
        )
    except sd.PortAudioError as e:
        # Fallback to device default sample rate
        device_default_sr = int(output_device_info.get('default_samplerate', 44100))
        _logger.warning(
            "Failed to open output at %sHz (%s); retrying with device "
            "default %sHz", processor.target_sr, e, device_default_sr)
        try:
            processor.setup_output_resampler(device_default_sr)
            out_block_size = processor.output_resample_size
            output_stream = sd.OutputStream(
                device=output_dev_id,
                samplerate=device_default_sr,
                channels=2,
                dtype='float32',
                blocksize=out_block_size
            )
        except sd.PortAudioError:
            input_stream.close()
            raise
    return input_stream, output_stream, input_sr, out_block_size


def run_portaudio_loop(processor: DenoiserAudioProcessor,
                       input_device: Optional[int] = None,
                       output_device: Optional[int] = None,
                       should_stop: StopLike = None,
                       on_stats: Optional[Callable[[dict, float], None]] = None,
                       stats_interval_sec: float = STATS_PRINT_INTERVAL_SEC,
                       on_started: Optional[Callable[[int, int], None]] = None,
                       pause_gc: bool = False,
                       realtime: bool = True) -> dict:
    """Capture CABLE Output, process, play, until ``should_stop``.

    Args:
        processor: DenoiserAudioProcessor (engine already set).
        input_device, output_device: PortAudio device IDs (None = find).
        should_stop: threading.Event, callable, or None (until Ctrl+C).
        on_stats: Optional callback(stats, elapsed_sec) every interval.
        stats_interval_sec: Stats callback cadence.
        on_started: Called with (input_id, output_id) once both streams
            are open.
        pause_gc: Keep the garbage collector off while the streams are
            open (only in a process that does nothing else; see audio_gc).
        realtime: Run the loop thread under MMCSS (Windows).

    Returns:
        The processor's final stats.
    """
    if not USE_SOUNDDEVICE:
        raise RuntimeError("This mode requires sounddevice library")
    input_dev_id, output_dev_id = select_devices(
        processor, input_device, output_device)
    input_stream, output_stream, input_sr, out_block_size = _open_streams(
        processor, input_dev_id, output_dev_id)

    block_ms = processor.frame_size * 1000.0 / processor.target_sr
    stalls = StallCounter(block_ms)
    overflows = 0
    start_time = time.time()
    last_stats = last_log = last_sync = start_time

    # The collection before the loop runs before the streams start: once
    # capture runs, time spent stays behind as backlog.
    with gc_paused(pause_gc), fast_gil_handoff(), \
            _realtime_thread(realtime) as rt, input_stream, output_stream:
        _logger.info(
            "run start: model=%s frame_size=%s backend=portaudio "
            "input=%r (%s Hz) output=%r (%s Hz) mmcss=%d gc_paused=%d log=%s",
            getattr(getattr(processor, "engine", None), "name", "?"),
            processor.frame_size, sd.query_devices(input_dev_id)['name'],
            input_sr, sd.query_devices(output_dev_id)['name'],
            int(output_stream.samplerate), int(bool(rt)), int(pause_gc),
            get_log_file_path())
        if on_started is not None:
            on_started(input_dev_id, output_dev_id)
        # Reused stereo buffer with one sample of headroom: output takes
        # dither around out_block_size (e.g. 470/471 averaging 470.4).
        stereo_output = np.empty((out_block_size + 1, 2), dtype=np.float32)
        while not stop_requested(should_stop):
            # Read audio chunk. The size is dithered around the
            # rate-scaled block so it resamples to ~one frame on average.
            audio_chunk, overflowed = input_stream.read(
                processor.next_input_block_size())
            if overflowed:
                overflows += 1

            if audio_chunk is None or len(audio_chunk) == 0:
                continue

            # Downmix to mono in software (mean). See the channels=2
            # note at stream open: a mono open corrupts the capture.
            if audio_chunk.ndim == 2:
                if audio_chunk.shape[1] > 1:
                    audio_chunk = audio_chunk.mean(axis=1).astype(np.float32)
                else:
                    audio_chunk = audio_chunk.flatten()
            else:
                audio_chunk = audio_chunk.flatten()

            # Process through unified processor
            audio_output = processor.process_chunk(audio_chunk)

            if audio_output is not None:
                # Duplicate mono to stereo for proper playback on both channels.
                # Write exactly what the pipeline produced: padding with
                # zeros would insert silence and shift A/V sync.
                n = min(len(audio_output), len(stereo_output))
                stereo_output[:n, 0] = audio_output[:n]
                stereo_output[:n, 1] = audio_output[:n]
                output_stream.write(stereo_output[:n])

            stall = stalls.observe(time.monotonic())
            if stall:
                _logger.info("sync: loop stalled %.0f ms (audio lost)", stall)
            now = time.time()
            if on_stats is not None and now - last_stats >= stats_interval_sec:
                try:
                    on_stats(processor.get_stats(), now - start_time)
                except Exception:
                    pass
                last_stats = now
            if now - last_sync >= SYNC_LOG_INTERVAL_SEC:
                _logger.info(
                    "sync: backend=portaudio stalls=%d max_stall=%.0fms "
                    "lost=%.0fms overflows=%d", stalls.count, stalls.max_ms,
                    stalls.lost_ms, overflows)
                last_sync = now
            # Throttled file snapshot for weak-PC diagnosis (~every 5s)
            if now - last_log >= 5.0:
                stats = processor.get_stats()
                diag = processor.get_diagnostics()
                _logger.info(
                    "perf: frames=%s avg_ms=%.2f rtf=%.3f aad_total=%s "
                    "aad_bypassed=%s bypass_ratio=%.2f elapsed=%.1fs "
                    "in_block=%s backlog=%s dropped=%s",
                    stats.get("frame_count"), stats.get("avg_time_ms", 0.0),
                    stats.get("rtf", 0.0), stats.get("aad_total"),
                    stats.get("aad_bypassed"),
                    stats.get("aad_bypass_ratio", 0.0),
                    now - start_time,
                    diag.get("input_block_size"),
                    diag.get("resampler_backlog"),
                    diag.get("resampler_dropped"),
                )
                last_log = now
    _logger.info(
        "run stop: backend=portaudio elapsed=%.1fs stalls=%d max_stall=%.0fms "
        "lost=%.0fms overflows=%d", time.time() - start_time, stalls.count,
        stalls.max_ms, stalls.lost_ms, overflows)
    return processor.get_stats()
