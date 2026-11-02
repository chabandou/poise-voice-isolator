"""
macOS Platform Audio Utilities

macOS-specific audio functionality:
- Core Audio device discovery through the HAL (ctypes, no extra install):
  every device with its UID, transport, nominal rate and whether it can
  play, which is what ``--list-devices`` prints and what the native node
  is named with.
- Name/UID resolution: the native node matches an output device on a
  name or UID *substring* (native/poise_coreaudio/poise_coreaudio.m,
  find_output_device); resolving here first turns a typo into a list of
  the devices that exist instead of the node's own message.
- The runtime floor: Core Audio process taps arrived in macOS 14.2, so an
  older Mac gets a sentence rather than a dlopen failure.

There is no loopback here and no capture device to pick: the tap carries
every app's audio (plan C2b), so only the output device is a choice.
PortAudio is not used on macOS — sounddevice is not a macOS dependency and
the HAL answers natively. This module is unused on other platforms.
"""
import ctypes
import platform
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ...logging_config import get_logger

_logger = get_logger(__name__)

# First macOS with Core Audio process taps (CATapDescription and its mute
# behaviour). Versions are (major, minor).
CORE_AUDIO_TAP_FLOOR = (14, 2)


class MacOSUnsupported(RuntimeError):
    """This Mac cannot run Poise's audio path; the message says why."""


# ---------------------------------------------------------------------------
# Runtime floor
# ---------------------------------------------------------------------------

def macos_version() -> str:
    """The running macOS version as a string ("14.2.1"), or "" if unreadable."""
    return platform.mac_ver()[0] or ""


def _version_tuple(version: str) -> Optional[Tuple[int, int]]:
    try:
        parts = version.split(".")
        return int(parts[0]), int(parts[1] if len(parts) > 1 else 0)
    except (TypeError, ValueError, IndexError):
        return None


def require_core_audio_tap_support() -> None:
    """Raise unless this Mac has Core Audio process taps.

    The native library cannot report this: on an older Mac it simply fails
    to load (the whole tap API is missing) or the node fails with a
    property error, and neither names the real cause. Asked before the
    library is touched, the answer is one sentence.
    """
    version = macos_version()
    running = _version_tuple(version) if version else None
    if running is None:
        raise MacOSUnsupported(
            f"Poise needs macOS {CORE_AUDIO_TAP_FLOOR[0]}."
            f"{CORE_AUDIO_TAP_FLOOR[1]} or newer: Core Audio process taps "
            "arrived in "
            f"{CORE_AUDIO_TAP_FLOOR[0]}.{CORE_AUDIO_TAP_FLOOR[1]}; this is "
            f"{version or 'a macOS whose version cannot be read'}")
    if running < CORE_AUDIO_TAP_FLOOR:
        raise MacOSUnsupported(
            f"Poise needs macOS {CORE_AUDIO_TAP_FLOOR[0]}."
            f"{CORE_AUDIO_TAP_FLOOR[1]} or newer: Core Audio process taps "
            "arrived in "
            f"{CORE_AUDIO_TAP_FLOOR[0]}.{CORE_AUDIO_TAP_FLOOR[1]}; this is "
            f"{version}")


# ---------------------------------------------------------------------------
# Core Audio HAL binding
# ---------------------------------------------------------------------------

_CORE_AUDIO = "/System/Library/Frameworks/CoreAudio.framework/CoreAudio"
_CORE_FOUNDATION = ("/System/Library/Frameworks/CoreFoundation.framework/"
                    "CoreFoundation")

_SYSTEM_OBJECT = 1                      # kAudioObjectSystemObject
_ELEMENT_MAIN = 0                       # kAudioObjectPropertyElementMain
_UTF8 = 0x08000100                      # kCFStringEncodingUTF8


def _fourcc(code: str) -> int:
    """A Core Audio property selector or scope ('dev#', 'glob') as UInt32."""
    return int.from_bytes(code.encode("ascii"), "big")


_SCOPE_GLOBAL = _fourcc("glob")
_SCOPE_INPUT = _fourcc("inpt")
_SCOPE_OUTPUT = _fourcc("outp")
_SELECTOR_DEVICES = _fourcc("dev#")               # kAudioHardwarePropertyDevices
_SELECTOR_DEFAULT_OUTPUT = _fourcc("dOut")        # kAudioHardwarePropertyDefaultOutputDevice
_SELECTOR_NAME = _fourcc("lnam")                  # kAudioObjectPropertyName
_SELECTOR_UID = _fourcc("uid ")                   # kAudioDevicePropertyDeviceUID
_SELECTOR_TRANSPORT = _fourcc("tran")             # kAudioDevicePropertyTransportType
_SELECTOR_NOMINAL_RATE = _fourcc("nsrt")          # kAudioDevicePropertyNominalSampleRate
_SELECTOR_STREAMS = _fourcc("strm")               # kAudioDevicePropertyStreams
_SELECTOR_STREAM_CONFIG = _fourcc("slay")         # kAudioDevicePropertyStreamConfiguration

# The same words native/poise_coreaudio's transport_name() uses for the
# same hardware, plus the bus types it leaves as four characters, so the
# node's log lines and --list-devices agree.
_TRANSPORTS: Dict[int, str] = {
    _fourcc("bltn"): "built-in",
    _fourcc("usb "): "usb",
    _fourcc("blue"): "bluetooth",
    _fourcc("blea"): "bluetooth-le",
    _fourcc("hdmi"): "hdmi",
    _fourcc("dprt"): "displayport",
    _fourcc("airp"): "airplay",
    _fourcc("avb "): "avb",
    _fourcc("aggr"): "aggregate",
    _fourcc("virt"): "virtual",
    _fourcc("pci "): "pci",
    _fourcc("1394"): "firewire",
    _fourcc("thun"): "thunderbolt",
    _fourcc("cont"): "continuity",
}


class _PropertyAddress(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32),
                ("mScope", ctypes.c_uint32),
                ("mElement", ctypes.c_uint32)]


class _AudioBuffer(ctypes.Structure):
    _fields_ = [("mNumberChannels", ctypes.c_uint32),
                ("mDataByteSize", ctypes.c_uint32),
                ("mData", ctypes.c_void_p)]


_frameworks = None


def _core_audio():
    """(CoreAudio, CoreFoundation) bound on first use (macOS only)."""
    global _frameworks
    if _frameworks is not None:
        return _frameworks
    ca = ctypes.CDLL(_CORE_AUDIO)
    cf = ctypes.CDLL(_CORE_FOUNDATION)
    address = ctypes.POINTER(_PropertyAddress)
    u32 = ctypes.c_uint32
    ca.AudioObjectGetPropertyDataSize.argtypes = [
        u32, address, u32, ctypes.c_void_p, ctypes.POINTER(u32)]
    ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
    ca.AudioObjectGetPropertyData.argtypes = [
        u32, address, u32, ctypes.c_void_p, ctypes.POINTER(u32),
        ctypes.c_void_p]
    ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
    cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
    cf.CFStringGetLength.restype = ctypes.c_long
    cf.CFStringGetMaximumSizeForEncoding.argtypes = [ctypes.c_long, u32]
    cf.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                      ctypes.c_long, u32]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    _frameworks = (ca, cf)
    return _frameworks


def _address(selector: int, scope: int = _SCOPE_GLOBAL) -> _PropertyAddress:
    return _PropertyAddress(selector, scope, _ELEMENT_MAIN)


def _data_size(ca, object_id: int, selector: int,
               scope: int = _SCOPE_GLOBAL) -> int:
    """Bytes the property would write, or 0 when it has no value."""
    size = ctypes.c_uint32(0)
    status = ca.AudioObjectGetPropertyDataSize(
        object_id, ctypes.byref(_address(selector, scope)), 0, None,
        ctypes.byref(size))
    return int(size.value) if status == 0 else 0


def _raw(ca, object_id: int, selector: int,
         scope: int = _SCOPE_GLOBAL) -> Optional[bytes]:
    """The property's bytes, or None when the HAL refuses or has no value."""
    size = _data_size(ca, object_id, selector, scope)
    if size <= 0:
        return None
    buf = ctypes.create_string_buffer(size)
    io_size = ctypes.c_uint32(size)
    status = ca.AudioObjectGetPropertyData(
        object_id, ctypes.byref(_address(selector, scope)), 0, None,
        ctypes.byref(io_size), buf)
    if status != 0:
        return None
    return buf.raw[:int(io_size.value)]


def _u32(ca, object_id: int, selector: int, scope: int = _SCOPE_GLOBAL) -> int:
    raw = _raw(ca, object_id, selector, scope)
    if not raw or len(raw) < 4:
        return 0
    return struct.unpack("<I", raw[:4])[0]


def _f64(ca, object_id: int, selector: int, scope: int = _SCOPE_GLOBAL) -> float:
    raw = _raw(ca, object_id, selector, scope)
    if not raw or len(raw) < 8:
        return 0.0
    return struct.unpack("<d", raw[:8])[0]


def _cfstring(cf, raw: Optional[bytes]) -> str:
    """A CFStringRef property as str (the HAL hands back a retained one)."""
    if not raw:
        return ""
    width = ctypes.sizeof(ctypes.c_void_p)
    if len(raw) < width:
        return ""
    ref = ctypes.c_void_p(struct.unpack("<Q", raw[:width])[0])
    if not ref.value:
        return ""
    try:
        length = int(cf.CFStringGetLength(ref))
        needed = int(cf.CFStringGetMaximumSizeForEncoding(length, _UTF8)) + 1
        buf = ctypes.create_string_buffer(max(needed, 4))
        if not cf.CFStringGetCString(ref, buf, len(buf), _UTF8):
            return ""
        return buf.value.decode("utf-8", "replace")
    finally:
        cf.CFRelease(ref)


def _channels(ca, device_id: int, scope: int) -> int:
    """Channel count of the device's streams in ``scope`` (0: none there)."""
    raw = _raw(ca, device_id, _SELECTOR_STREAM_CONFIG, scope)
    if not raw or len(raw) < 4:
        return 0
    buffers = struct.unpack("<I", raw[:4])[0]
    # AudioBufferList pads mBuffers to AudioBuffer's pointer alignment, so
    # the array starts at 8 on a 64-bit Mac, not at 4.
    start_of_buffers = ctypes.sizeof(ctypes.c_void_p)
    stride = ctypes.sizeof(_AudioBuffer)
    total = 0
    for i in range(buffers):
        start = start_of_buffers + i * stride
        if start + 4 > len(raw):
            break
        total += struct.unpack("<I", raw[start:start + 4])[0]
    return total


@dataclass
class CoreAudioDevice:
    """One Core Audio device, as the HAL describes it."""

    id: int
    name: str
    uid: str
    transport: str
    nominal_rate: int
    input_channels: int
    output_channels: int
    is_default_output: bool

    @property
    def can_play(self) -> bool:
        """Whether Poise can play to it (an output stream exists)."""
        return self.output_channels > 0


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

def list_core_audio_devices() -> List[CoreAudioDevice]:
    """Every device the HAL knows, in its own order.

    Includes devices that cannot play (microphones, and the aggregate the
    native node creates while it runs): ``--list-devices`` shows them so a
    user can see what exists, and ``out=no`` says Poise cannot use them.
    """
    ca, cf = _core_audio()
    raw = _raw(ca, _SYSTEM_OBJECT, _SELECTOR_DEVICES)
    if not raw:
        return []
    ids = struct.unpack("<" + "I" * (len(raw) // 4), raw[:len(raw) // 4 * 4])
    default_id = _u32(ca, _SYSTEM_OBJECT, _SELECTOR_DEFAULT_OUTPUT)
    devices = []
    for device_id in ids:
        transport = _TRANSPORTS.get(
            _u32(ca, device_id, _SELECTOR_TRANSPORT), "")
        devices.append(CoreAudioDevice(
            id=device_id,
            name=_cfstring(cf, _raw(ca, device_id, _SELECTOR_NAME)),
            uid=_cfstring(cf, _raw(ca, device_id, _SELECTOR_UID)),
            transport=transport,
            nominal_rate=int(round(_f64(ca, device_id,
                                        _SELECTOR_NOMINAL_RATE))),
            input_channels=_channels(ca, device_id, _SCOPE_INPUT),
            output_channels=_channels(ca, device_id, _SCOPE_OUTPUT),
            is_default_output=bool(default_id) and device_id == default_id,
        ))
    return devices


def default_output_device() -> Optional[CoreAudioDevice]:
    """The device the Mac plays to, or None when the HAL has none."""
    for device in list_core_audio_devices():
        if device.is_default_output:
            return device
    return None


def find_output_device(name_or_uid: str) -> CoreAudioDevice:
    """The output device ``name_or_uid`` names.

    Exact UID, then exact name, then a unique case-insensitive substring —
    the last being what the native node itself matches on, so anything
    this accepts, the node finds too.

    Raises:
        ValueError: nothing matches, or the substring names several
            devices (the message lists them).
    """
    wanted = (name_or_uid or "").strip()
    if not wanted:
        raise ValueError("No output device named (see --list-devices).")
    devices = [d for d in list_core_audio_devices() if d.can_play]
    if not devices:
        raise ValueError("No Core Audio output device found.")
    for match in (lambda d: d.uid == wanted,
                  lambda d: d.name == wanted,
                  lambda d: wanted.lower() in d.name.lower()
                  or wanted.lower() in d.uid.lower()):
        found = [d for d in devices if match(d)]
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            raise ValueError(
                f"Output device {wanted!r} matches several devices: "
                + ", ".join(f'"{d.name}" ({d.uid})' for d in found)
                + ". Use the UID.")
    raise ValueError(
        f"No output device matches {wanted!r}. Output devices: "
        + ", ".join(f'"{d.name}" ({d.uid})' for d in devices))


def resolve_output_device(name_or_uid: str) -> str:
    """The UID of the output device ``name_or_uid`` names.

    A UID, not a name: the native node matches on a name or UID substring,
    and a UID is unique on the machine and does not change with the
    system language. Raises ValueError like find_output_device.
    """
    return find_output_device(name_or_uid).uid


def devices_report() -> str:
    """``--list-devices`` on macOS: one line per device, as the node's own
    device listing prints them."""
    devices = list_core_audio_devices()
    if not devices:
        return "No Core Audio devices found."
    lines = [
        "Core Audio devices (--sink takes a name or UID; Poise taps all "
        "system audio, so there is no capture device to choose):",
        "=" * 80,
    ]
    for device in devices:
        transport = device.transport or "?"
        lines.append(
            f"{device.name:40.40} {transport:12.12} "
            f"{device.nominal_rate:6d} Hz  "
            f"out={'yes' if device.can_play else 'no'} "
            f"uid={device.uid}"
            + ("  [default output]" if device.is_default_output else ""))
    lines.append("-" * 80)
    default = default_output_device()
    if default is None:
        lines.append("No default output device: name one with --sink.")
    else:
        lines.append(
            f'Default output: "{default.name}" ({default.uid}), nominal '
            f"{default.nominal_rate} Hz. Poise plays to it unless --sink "
            "names another.")
    return "\n".join(lines)
