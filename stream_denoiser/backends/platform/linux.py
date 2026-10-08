"""
Linux Platform Audio Utilities

Linux-specific audio functionality:
- PulseAudio/PipeWire device discovery via pulsectl
- Null-sink routing for system-audio capture

Audio I/O itself uses libpulse-simple directly
(see stream_denoiser.backends.pulse_simple); PortAudio is not used
on Linux.

This module is unused on Windows builds.
"""
import time
from typing import Optional, List, Tuple
from dataclasses import dataclass

from ...logging_config import get_logger

_logger = get_logger(__name__)

# Try to import pulsectl for PulseAudio/PipeWire device discovery
try:
    import pulsectl
    USE_PULSECTL = True
except ImportError:
    USE_PULSECTL = False
    _logger.debug("pulsectl not available - PulseAudio routing unavailable")


@dataclass
class PulseAudioSource:
    """Represents a PulseAudio/PipeWire source (input device)."""
    index: int
    name: str  # Internal name (e.g., "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor")
    description: str  # Human-readable (e.g., "Monitor of Built-in Audio Analog Stereo")
    is_monitor: bool
    sample_rate: int
    channels: int


@dataclass
class PulseAudioSink:
    """Represents a PulseAudio/PipeWire sink (output device)."""
    index: int
    name: str
    description: str
    sample_rate: int
    channels: int


def list_pulseaudio_sources() -> List[PulseAudioSource]:
    """
    List all PulseAudio/PipeWire sources using pulsectl.

    Returns:
        List of PulseAudioSource objects
    """
    if not USE_PULSECTL:
        return []

    try:
        with pulsectl.Pulse('stream-denoiser-list') as pulse:
            sources = []
            for source in pulse.source_list():
                is_monitor = source.name.endswith('.monitor')
                sources.append(PulseAudioSource(
                    index=source.index,
                    name=source.name,
                    description=source.description,
                    is_monitor=is_monitor,
                    sample_rate=source.sample_spec.rate,
                    channels=source.sample_spec.channels
                ))
            return sources
    except pulsectl.PulseError as e:
        _logger.warning(f"Failed to list PulseAudio sources: {e}")
        return []


def list_pulseaudio_sinks() -> List[PulseAudioSink]:
    """
    List all PulseAudio/PipeWire sinks using pulsectl.

    Returns:
        List of PulseAudioSink objects
    """
    if not USE_PULSECTL:
        return []

    try:
        with pulsectl.Pulse('stream-denoiser-list') as pulse:
            sinks = []
            for sink in pulse.sink_list():
                sinks.append(PulseAudioSink(
                    index=sink.index,
                    name=sink.name,
                    description=sink.description,
                    sample_rate=sink.sample_spec.rate,
                    channels=sink.sample_spec.channels
                ))
            return sinks
    except pulsectl.PulseError as e:
        _logger.warning(f"Failed to list PulseAudio sinks: {e}")
        return []


def list_pulseaudio_sources_formatted() -> str:
    """
    Get formatted string of PulseAudio sources for CLI display.

    Returns:
        Formatted string for display, or empty string if unavailable
    """
    sources = list_pulseaudio_sources()
    if not sources:
        return ""

    lines = []
    for source in sources:
        monitor_marker = " [MONITOR]" if source.is_monitor else ""
        lines.append(f"{source.name}: {source.description}{monitor_marker}")
        lines.append(f"    Sample rate: {source.sample_rate}Hz, Channels: {source.channels}")
        lines.append("")

    return "\n".join(lines)


def list_pulseaudio_sinks_formatted() -> str:
    """
    Get formatted string of PulseAudio sinks for CLI display.

    Returns:
        Formatted string for display, or empty string if unavailable
    """
    sinks = list_pulseaudio_sinks()
    if not sinks:
        return ""

    lines = []
    for sink in sinks:
        lines.append(f"{sink.name}: {sink.description}")
        lines.append(f"    Sample rate: {sink.sample_rate}Hz, Channels: {sink.channels}")
        lines.append("")

    return "\n".join(lines)


def get_default_sink_name() -> Optional[str]:
    """Return the server's current default sink name, or None."""
    if not USE_PULSECTL:
        return None
    try:
        with pulsectl.Pulse('stream-denoiser-default-sink') as pulse:
            return pulse.server_info().default_sink_name
    except Exception as e:
        _logger.debug(f"Could not query default sink: {e}")
        return None


def get_pulse_server_info() -> Tuple[Optional[str], Optional[str]]:
    """Return (server_name, server_version) from pulsectl, or (None, None)."""
    if not USE_PULSECTL:
        return None, None
    try:
        with pulsectl.Pulse('stream-denoiser-server-info') as pulse:
            info = pulse.server_info()
            return getattr(info, 'server_name', None), getattr(
                info, 'server_version', None)
    except Exception as e:
        _logger.debug(f"Could not query server info: {e}")
        return None, None


def find_monitor_source_pulsectl() -> Optional[PulseAudioSource]:
    """
    Find the best monitor source for system audio capture using pulsectl.

    Priority:
    1. Monitor of the default sink
    2. Any monitor source with "built-in" or "analog" in name
    3. First available monitor source

    Returns:
        PulseAudioSource for the best monitor, or None
    """
    if not USE_PULSECTL:
        return None

    try:
        with pulsectl.Pulse('stream-denoiser-find') as pulse:
            # Get default sink to find its monitor
            server_info = pulse.server_info()
            default_sink_name = server_info.default_sink_name

            sources = pulse.source_list()
            monitor_sources = [s for s in sources if s.name.endswith('.monitor')]

            if not monitor_sources:
                _logger.warning("No monitor sources found in PulseAudio")
                return None

            # Priority 1: Monitor of default sink
            default_monitor_name = f"{default_sink_name}.monitor"
            for source in monitor_sources:
                if source.name == default_monitor_name:
                    _logger.info(f"Found default sink monitor: {source.description}")
                    return PulseAudioSource(
                        index=source.index,
                        name=source.name,
                        description=source.description,
                        is_monitor=True,
                        sample_rate=source.sample_spec.rate,
                        channels=source.sample_spec.channels
                    )

            # Priority 2: Built-in or analog monitor
            for source in monitor_sources:
                name_lower = source.name.lower()
                if 'built-in' in name_lower or 'analog' in name_lower or 'alsa_output' in name_lower:
                    _logger.info(f"Found built-in monitor: {source.description}")
                    return PulseAudioSource(
                        index=source.index,
                        name=source.name,
                        description=source.description,
                        is_monitor=True,
                        sample_rate=source.sample_spec.rate,
                        channels=source.sample_spec.channels
                    )

            # Priority 3: First available monitor
            source = monitor_sources[0]
            _logger.info(f"Using first available monitor: {source.description}")
            return PulseAudioSource(
                index=source.index,
                name=source.name,
                description=source.description,
                is_monitor=True,
                sample_rate=source.sample_spec.rate,
                channels=source.sample_spec.channels
            )

    except pulsectl.PulseError as e:
        _logger.warning(f"Failed to find monitor source: {e}")
        return None


class LinuxAudioRouter:
    """
    Automatic audio routing for Linux using PulseAudio/PipeWire.

    1. Creates a null sink (virtual audio device)
    2. Sets it as the default sink (apps route audio there)
    3. Provides the null sink's monitor source name for capture
    4. Restores original routing on exit

    Capture and playback both use names, never indices: the monitor
    source name (``Poise_Capture.monitor``) and the real hardware sink
    name saved at setup time.
    """

    SINK_NAME = "Poise_Capture"
    SINK_DESCRIPTION = "Poise Audio Capture"

    def __init__(self, auto_switch: bool = True):
        """
        Initialize the Linux audio router.

        Args:
            auto_switch: If True, automatically switch default sink on init
        """
        self._module_id: Optional[int] = None
        self._original_default_sink: Optional[str] = None
        self._sink_name: Optional[str] = None
        self._monitor_source: Optional[str] = None
        self._auto_switch = auto_switch

        if auto_switch:
            self._setup_routing()

    def _setup_routing(self) -> bool:
        """Set up null sink and switch default sink."""
        if not USE_PULSECTL:
            _logger.warning("pulsectl not available - cannot set up automatic routing")
            return False

        try:
            with pulsectl.Pulse('denoiser-router') as pulse:
                # Get current default sink
                server_info = pulse.server_info()
                current_default = server_info.default_sink_name

                # Check if our sink already exists
                existing_null_sink = None
                for sink in pulse.sink_list():
                    if sink.name == self.SINK_NAME:
                        existing_null_sink = sink
                        break

                # If current default IS our null sink, we need to find the real hardware sink
                if current_default == self.SINK_NAME:
                    _logger.warning("Current default is our null sink (from previous crash?)")
                    # Find a real hardware sink to restore to
                    for sink in pulse.sink_list():
                        if sink.name != self.SINK_NAME and 'null' not in sink.name.lower():
                            self._original_default_sink = sink.name
                            _logger.info(f"Found real hardware sink: {sink.name}")
                            break
                    if not self._original_default_sink:
                        _logger.warning("Could not find a hardware sink to restore to")
                else:
                    self._original_default_sink = current_default
                    _logger.info(f"Original default sink: {self._original_default_sink}")

                # Reuse existing null sink if present
                if existing_null_sink:
                    _logger.info(f"Reusing existing null sink: {self.SINK_NAME}")
                    self._sink_name = existing_null_sink.name
                    self._monitor_source = f"{existing_null_sink.name}.monitor"
                    pulse.sink_default_set(existing_null_sink)
                    _logger.info(f"Set default sink to: {self.SINK_NAME}")
                    return True

                # Create null sink using pactl (pulsectl doesn't support module loading directly)
                import subprocess
                result = subprocess.run(
                    ['pactl', 'load-module', 'module-null-sink',
                     f'sink_name={self.SINK_NAME}',
                     f'sink_properties=device.description="{self.SINK_DESCRIPTION}"'],
                    capture_output=True, text=True
                )

                if result.returncode != 0:
                    _logger.error(f"Failed to create null sink: {result.stderr}")
                    return False

                self._module_id = int(result.stdout.strip())
                self._sink_name = self.SINK_NAME
                self._monitor_source = f"{self.SINK_NAME}.monitor"
                _logger.info(f"Created null sink: {self.SINK_NAME} (module ID: {self._module_id})")

                # Set as default sink
                # Need to refresh sink list
                for sink in pulse.sink_list():
                    if sink.name == self.SINK_NAME:
                        pulse.sink_default_set(sink)
                        _logger.info(f"Set default sink to: {self.SINK_NAME}")
                        break

                return True

        except pulsectl.PulseError as e:
            _logger.error(f"PulseAudio error during routing setup: {e}")
            return False
        except Exception as e:
            _logger.error(f"Error setting up routing: {e}")
            return False

    def get_monitor_source_name(self) -> Optional[str]:
        """Get the name of the null sink's monitor source for capture."""
        return self._monitor_source

    @property
    def original_sink_name(self) -> Optional[str]:
        """Name of the real hardware sink saved at setup time.

        Playback targets this sink by name so output keeps going to
        hardware even after the default flips to Poise_Capture.
        """
        return self._original_default_sink

    def wait_for_monitor_source(self, timeout_sec: float = 3.0,
                                poll_interval_sec: float = 0.05) -> Optional[str]:
        """Wait for the null sink's monitor source to appear at Pulse level.

        Polls ``pulsectl.source_list()`` for the exact name
        ``Poise_Capture.monitor``. Returns the source name when found,
        else None after ``timeout_sec``. Fail fast: callers must not fall
        back to the default input (that would capture silence while the
        default sink points at the null sink).
        """
        if not self._monitor_source:
            return None
        if not USE_PULSECTL:
            # Without pulsectl we cannot confirm; trust the expected name
            # so offline tests can proceed, real runs need pulsectl anyway.
            return self._monitor_source
        deadline = time.monotonic() + max(0.0, timeout_sec)
        while True:
            try:
                import pulsectl
                with pulsectl.Pulse('denoiser-router-wait') as pulse:
                    names = {s.name for s in pulse.source_list()}
                if self._monitor_source in names:
                    return self._monitor_source
            except Exception as e:
                _logger.debug(f"Monitor wait poll failed: {e}")
            if time.monotonic() >= deadline:
                break
            time.sleep(max(0.005, poll_interval_sec))
        _logger.warning(
            "Null sink monitor '%s' did not appear at the PulseAudio "
            "level within %.1fs. Not starting: capturing the default input "
            "instead would record silence. Fixes: check pavucontrol/PipeWire "
            "Pulse backend, or use --no-vb-cable to keep default capture.",
            self._monitor_source, timeout_sec,
        )
        return None

    def restore_original_sink(self) -> bool:
        """Restore the original default sink and clean up null sink."""
        success = True

        if not USE_PULSECTL:
            return True

        try:
            with pulsectl.Pulse('denoiser-router-cleanup') as pulse:
                # Restore original default sink
                if self._original_default_sink:
                    try:
                        for sink in pulse.sink_list():
                            if sink.name == self._original_default_sink:
                                pulse.sink_default_set(sink)
                                _logger.info(f"Restored default sink to: {self._original_default_sink}")
                                break
                    except pulsectl.PulseError as e:
                        _logger.warning(f"Could not restore original sink: {e}")
                        success = False

                # Unload null sink module
                if self._module_id is not None:
                    import subprocess
                    result = subprocess.run(
                        ['pactl', 'unload-module', str(self._module_id)],
                        capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        _logger.info(f"Unloaded null sink module: {self._module_id}")
                    else:
                        _logger.warning(f"Could not unload module: {result.stderr}")
                        success = False
                    self._module_id = None

        except pulsectl.PulseError as e:
            _logger.error(f"PulseAudio error during cleanup: {e}")
            success = False

        return success

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - restore original routing."""
        self.restore_original_sink()
        return False

    @staticmethod
    def get_routing_instructions() -> str:
        """Get user-friendly instructions for manual audio routing."""
        return """
Linux Audio Routing (Automatic):
================================

The denoiser automatically creates a virtual audio sink and routes system audio
through it. When you stop the denoiser, original routing is restored.

If automatic routing doesn't work, you can set it up manually:

Option 1: Use PipeWire/PulseAudio GUI tools
  - Install 'pavucontrol' or 'helvum'
  - Redirect application audio to "Poise Audio Capture"
  - The denoiser captures from this sink's monitor

Option 2: Manual command line setup
  # Create null sink
  pactl load-module module-null-sink sink_name=Poise_Capture sink_properties=device.description="Poise_Capture"

  # Set as default (apps will use it automatically)
  pactl set-default-sink Poise_Capture

  # Run denoiser - it will capture from the null sink's monitor
  python -m stream_denoiser
"""
