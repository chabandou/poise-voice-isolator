"""``backends/platform/macos.py`` against a fake Core Audio HAL.

No device, no framework and no permission is needed: ``_core_audio()`` is
replaced by a fake answering the two HAL property calls the module makes
from a dict of raw property bytes, and CoreFoundation strings are fake
references into a dict of str. What runs is the module's own parsing
(``_raw``/``_u32``/``_f64``/``_cfstring``/``_channels``), the name/UID
resolution ``--sink`` goes through, and the runtime floor.
"""
import ctypes
import struct

import pytest

from stream_denoiser.backends.platform import macos

# Device ids: anything but _SYSTEM_OBJECT (1), so a property set on a
# device can never be the one read from the system object.
SPEAKERS = 11
USB = 12
MIC = 13
EMPTY = 14


class _FakeHAL:
    """The HAL calls macos.py makes, over a dict of raw property values.

    A property with no entry is one the device does not have: the real
    AudioObjectGetPropertyDataSize answers a non-zero status for it, which
    is what ``_raw`` turns into None.
    """

    def __init__(self):
        self._props = {}        # (object_id, selector, scope) -> raw bytes
        self._strings = {}      # CFStringRef value -> the string it holds

    # --- what a machine has ------------------------------------------------

    def set_raw(self, object_id, selector, raw, scope=macos._SCOPE_GLOBAL):
        self._props[(object_id, selector, scope)] = raw

    def set_u32(self, object_id, selector, value, scope=macos._SCOPE_GLOBAL):
        self.set_raw(object_id, selector, struct.pack("<I", value), scope)

    def set_f64(self, object_id, selector, value, scope=macos._SCOPE_GLOBAL):
        self.set_raw(object_id, selector, struct.pack("<d", value), scope)

    def set_string(self, object_id, selector, text,
                   scope=macos._SCOPE_GLOBAL):
        # A CFString property is the pointer; _cfstring keeps its lifetime.
        ref = len(self._strings) + 1
        self._strings[ref] = text
        self.set_raw(object_id, selector, struct.pack("<Q", ref), scope)

    def set_streams(self, object_id, scope, *channels_per_buffer):
        """An AudioBufferList as the HAL writes it: the buffer count, then
        padding to the 8-byte pointer boundary, then the buffers."""
        raw = struct.pack("<I", len(channels_per_buffer))
        raw += b"\x00" * 4             # mBuffers starts at sizeof(void *)
        for channels in channels_per_buffer:
            raw += struct.pack("<IIQ", channels, 0, 0)
        self.set_raw(object_id, macos._SELECTOR_STREAM_CONFIG, raw, scope)

    def add_device(self, device_id, name, uid, rate=48000, transport="bltn",
                   outputs=(), inputs=()):
        self.set_string(device_id, macos._SELECTOR_NAME, name)
        self.set_string(device_id, macos._SELECTOR_UID, uid)
        self.set_f64(device_id, macos._SELECTOR_NOMINAL_RATE, float(rate))
        self.set_u32(device_id, macos._SELECTOR_TRANSPORT,
                     macos._fourcc(transport))
        self.set_streams(device_id, macos._SCOPE_OUTPUT, *outputs)
        self.set_streams(device_id, macos._SCOPE_INPUT, *inputs)

    def set_devices(self, *device_ids, default=0):
        self.set_raw(macos._SYSTEM_OBJECT, macos._SELECTOR_DEVICES,
                     struct.pack("<" + "I" * len(device_ids), *device_ids))
        if default:
            self.set_u32(macos._SYSTEM_OBJECT,
                         macos._SELECTOR_DEFAULT_OUTPUT, default)

    # --- the two HAL entry points -----------------------------------------

    def _key(self, object_id, address_ptr):
        address = ctypes.cast(
            address_ptr, ctypes.POINTER(macos._PropertyAddress)).contents
        return (object_id, address.mSelector, address.mScope)

    def AudioObjectGetPropertyDataSize(self, object_id, address, qualifier,
                                       qualifier_data, size_ptr):
        raw = self._props.get(self._key(object_id, address))
        if raw is None:
            return -1095579993          # kAudioHardwareUnknownPropertyError
        ctypes.cast(size_ptr, ctypes.POINTER(ctypes.c_uint32))[0] = len(raw)
        return 0

    def AudioObjectGetPropertyData(self, object_id, address, qualifier,
                                   qualifier_data, io_size, buf):
        raw = self._props.get(self._key(object_id, address))
        if raw is None:
            return -1095579993
        size = ctypes.cast(io_size, ctypes.POINTER(ctypes.c_uint32))
        n = min(len(raw), size[0])
        ctypes.memmove(buf, raw, n)
        size[0] = n
        return 0

    # --- the CoreFoundation calls _cfstring makes --------------------------

    def CFStringGetLength(self, ref):
        return len(self._strings[ref.value])

    def CFStringGetMaximumSizeForEncoding(self, length, encoding):
        return length * 4               # UTF-8's worst case per UTF-16 unit

    def CFStringGetCString(self, ref, buf, size, encoding):
        data = self._strings[ref.value].encode("utf-8")
        if len(data) + 1 > size:
            return False
        ctypes.memmove(buf, data + b"\x00", len(data) + 1)
        return True

    def CFRelease(self, ref):
        pass


@pytest.fixture
def hal(monkeypatch):
    """The fake HAL, in place of the real frameworks."""
    fake = _FakeHAL()
    monkeypatch.setattr(macos, "_frameworks", (fake, fake))
    # mac_ver is the process's, not the HAL's: the floor tests set it too.
    return fake


@pytest.fixture
def machine(hal):
    """A Mac with the built-in speakers (the default output) and a USB
    interface, plus a microphone that cannot play."""
    hal.add_device(SPEAKERS, "MacBook Pro Speakers", "BuiltInSpeakerDevice",
                   rate=48000, transport="bltn", outputs=(2,))
    hal.add_device(USB, "Scarlett 2i2 USB", "AppleUSBAudioEngine:Focusrite",
                   rate=44100, transport="usb ", outputs=(2,), inputs=(2,))
    hal.add_device(MIC, "MacBook Pro Microphone", "BuiltInMicrophoneDevice",
                   rate=48000, transport="bltn", inputs=(1,))
    hal.set_devices(SPEAKERS, USB, MIC, default=SPEAKERS)
    return hal


def _by_name(name):
    return next(d for d in macos.list_core_audio_devices() if d.name == name)


# --- the device list -------------------------------------------------------

def test_list_reads_name_uid_rate_transport_and_channels(machine):
    devices = macos.list_core_audio_devices()
    assert [d.id for d in devices] == [SPEAKERS, USB, MIC]  # the HAL's order

    speakers = devices[0]
    assert speakers.name == "MacBook Pro Speakers"
    assert speakers.uid == "BuiltInSpeakerDevice"
    assert speakers.transport == "built-in"        # not the raw 'bltn'
    assert speakers.nominal_rate == 48000
    assert speakers.output_channels == 2
    assert speakers.input_channels == 0
    assert speakers.can_play

    usb = devices[1]
    assert usb.transport == "usb"
    assert usb.nominal_rate == 44100               # 44.1 kHz survives intact
    assert (usb.input_channels, usb.output_channels) == (2, 2)
    assert usb.can_play


def test_channel_count_sums_every_buffer_of_the_stream(machine):
    machine.set_streams(SPEAKERS, macos._SCOPE_OUTPUT, 2, 2)
    assert _by_name("MacBook Pro Speakers").output_channels == 4


def test_only_the_default_output_is_marked(machine):
    by_id = {d.id: d for d in macos.list_core_audio_devices()}
    assert [d.id for d in by_id.values() if d.is_default_output] == [SPEAKERS]
    assert macos.default_output_device().name == "MacBook Pro Speakers"


def test_an_input_only_device_is_listed_but_cannot_play(machine):
    microphone = _by_name("MacBook Pro Microphone")
    assert microphone.input_channels == 1
    assert not microphone.can_play


def test_a_device_with_no_properties_is_empty_not_an_error(hal):
    """A device the HAL lists but answers nothing for: no crash, no lie."""
    hal.set_devices(EMPTY)
    (device,) = macos.list_core_audio_devices()
    assert (device.name, device.uid, device.transport) == ("", "", "")
    assert (device.nominal_rate, device.input_channels,
            device.output_channels) == (0, 0, 0)
    assert not device.can_play and not device.is_default_output


def test_no_device_property_means_no_devices(hal):
    """The HAL has the system object but no device list: an empty list."""
    assert macos.list_core_audio_devices() == []
    assert macos.default_output_device() is None
    assert macos.devices_report() == "No Core Audio devices found."


def test_a_missing_default_output_property_marks_no_device(hal):
    hal.add_device(SPEAKERS, "MacBook Pro Speakers", "BuiltInSpeakerDevice",
                   outputs=(2,))
    hal.set_devices(SPEAKERS)                      # no dOut property
    assert macos.default_output_device() is None
    assert "No default output device" in macos.devices_report()


def test_report_shows_each_device_and_the_default(machine):
    report = macos.devices_report()
    assert 'Default output: "MacBook Pro Speakers"' in report
    assert "uid=AppleUSBAudioEngine:Focusrite" in report
    assert "out=no" in report                      # the microphone
    assert "[default output]" in report


# --- --sink: name and UID resolution --------------------------------------

def test_resolves_an_output_device_by_exact_name(machine):
    assert macos.resolve_output_device("Scarlett 2i2 USB") \
        == "AppleUSBAudioEngine:Focusrite"
    assert macos.find_output_device("Scarlett 2i2 USB").id == USB


def test_resolves_an_output_device_by_uid(machine):
    assert macos.resolve_output_device("AppleUSBAudioEngine:Focusrite") \
        == "AppleUSBAudioEngine:Focusrite"


def test_resolves_a_unique_substring_case_insensitively(machine):
    """What the native node matches on, so --sink accepts it too."""
    assert macos.resolve_output_device("scarlett").startswith("AppleUSB")
    assert macos.resolve_output_device("MACBOOK PRO SPEAKERS") \
        == "BuiltInSpeakerDevice"


def test_an_input_only_device_is_not_an_output(machine):
    with pytest.raises(ValueError, match="No output device matches"):
        macos.resolve_output_device("MacBook Pro Microphone")


def test_an_unknown_name_fails_readably(machine):
    with pytest.raises(ValueError) as err:
        macos.resolve_output_device("Scarlet 2i2")   # one 't' short
    message = str(err.value)
    assert "No output device matches 'Scarlet 2i2'" in message
    # The message is the list of what does exist, with the UIDs --sink takes.
    assert '"MacBook Pro Speakers" (BuiltInSpeakerDevice)' in message
    assert '"Scarlett 2i2 USB" (AppleUSBAudioEngine:Focusrite)' in message


def test_an_ambiguous_name_names_the_matches_and_asks_for_the_uid(hal):
    hal.add_device(SPEAKERS, "Speakers (left)", "LeftSpeakers", outputs=(2,))
    hal.add_device(USB, "Speakers (right)", "RightSpeakers", outputs=(2,))
    hal.set_devices(SPEAKERS, USB)
    with pytest.raises(ValueError) as err:
        macos.resolve_output_device("speakers")
    message = str(err.value)
    assert "matches several devices" in message
    assert "LeftSpeakers" in message and "RightSpeakers" in message
    assert message.endswith("Use the UID.")


def test_no_output_device_at_all_is_said_as_much(hal):
    hal.add_device(MIC, "MacBook Pro Microphone", "BuiltInMicrophoneDevice",
                   inputs=(1,))
    hal.set_devices(MIC)
    with pytest.raises(ValueError, match="No Core Audio output device found"):
        macos.resolve_output_device("MacBook Pro Speakers")


def test_an_empty_name_asks_for_the_device_list(machine):
    with pytest.raises(ValueError, match="No output device named"):
        macos.resolve_output_device("   ")


# --- the >= 14.2 floor -----------------------------------------------------

def _version(monkeypatch, version):
    monkeypatch.setattr(macos, "macos_version", lambda: version)


def _sentence(version):
    return ("Poise needs macOS 14.2 or newer: Core Audio process taps "
            f"arrived in 14.2; this is {version}")


@pytest.mark.parametrize("version", ["13.6", "14.0", "14.1", "14.1.9"])
def test_a_mac_older_than_14_2_gets_the_sentence(monkeypatch, version):
    _version(monkeypatch, version)
    with pytest.raises(macos.MacOSUnsupported) as err:
        macos.require_core_audio_tap_support()
    assert str(err.value) == _sentence(version)


@pytest.mark.parametrize("version", ["14.2", "14.2.1", "15.0", "27.0.1"])
def test_a_mac_with_taps_is_let_through(monkeypatch, version):
    _version(monkeypatch, version)
    assert macos.require_core_audio_tap_support() is None


def test_a_version_that_cannot_be_read_says_so(monkeypatch):
    _version(monkeypatch, "")
    with pytest.raises(macos.MacOSUnsupported) as err:
        macos.require_core_audio_tap_support()
    assert str(err.value) == (
        "Poise needs macOS 14.2 or newer: Core Audio process taps arrived "
        "in 14.2; this is a macOS whose version cannot be read")
