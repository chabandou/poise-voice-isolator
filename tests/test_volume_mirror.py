"""CABLE Input's volume control mirrored onto the output device.

The switcher's part runs anywhere (the mirror faked). The native mirror
needs a second device it can move independently, and VB-Cable's other
playback device (CABLE In 16ch) shares CABLE Input's level, so the test
of it moves the default output device: by one volume-key step and a
moment's mute, all put back afterwards. It runs only with
POISE_VOLUME_TESTS=1.
"""
import os
import sys
import time

import pytest

from stream_denoiser.backends.platform import windows as win

CABLE = "CABLE Input (VB-Audio Virtual Cable)"


class FakeMirror:
    made = []

    def __init__(self, cable, output):
        self.cable, self.output, self.closed = cable, output, False
        FakeMirror.made.append(self)

    def close(self):
        self.closed = True


@pytest.fixture
def switcher(monkeypatch):
    monkeypatch.setattr(win.VBCableSwitcher, "_check_powershell_available",
                        lambda self: False)
    FakeMirror.made = []
    return win.VBCableSwitcher(vb_cable_name=CABLE, auto_switch=False)


def test_mirror_follows_the_output_device_until_restore(switcher, monkeypatch):
    from stream_denoiser.backends import wasapi_node
    monkeypatch.setattr(wasapi_node, "VolumeMirror", FakeMirror)

    assert switcher.mirror_volume("Speaker (Realtek(R) Audio)")
    first = FakeMirror.made[0]
    assert (first.cable, first.output) == (CABLE, "Speaker (Realtek(R) Audio)")

    # Another output: the first mirror ends before the next starts.
    assert switcher.mirror_volume("Headphone (Realtek(R) Audio)")
    assert first.closed and not FakeMirror.made[1].closed

    # Restoring stops it, even when there is nothing to restore.
    assert switcher.restore_original_device() is False
    assert FakeMirror.made[1].closed
    switcher.stop_volume_mirror()


def test_a_mirror_that_cannot_start_is_no_error(switcher, monkeypatch):
    from stream_denoiser.backends import wasapi_node

    def broken(cable, output):
        raise wasapi_node.WasapiUnavailable("poise_wasapi.dll not found")

    monkeypatch.setattr(wasapi_node, "VolumeMirror", broken)
    assert switcher.mirror_volume("Speaker (Realtek(R) Audio)") is False
    assert switcher.restore_original_device() is False


# ---- native mirror ---------------------------------------------------------

def _default_output():
    """The default output device's name (WASAPI), or the reason the
    native tests cannot run."""
    if sys.platform != "win32":
        return None, "Windows only"
    try:
        import sounddevice as sd
        from stream_denoiser.backends.wasapi_node import endpoint_volume
        endpoint_volume(CABLE)
        wasapi = next(a for a in sd.query_hostapis()
                      if a["name"] == "Windows WASAPI")
        name = sd.query_devices(wasapi["default_output_device"])["name"]
    except Exception as e:
        return None, f"needs poise_wasapi.dll and CABLE Input ({e})"
    # A running Poise mirrors CABLE Input onto its output: changing it
    # here would reach that device too.
    if name.upper().startswith("CABLE"):
        return None, "CABLE Input is the default device (is Poise running?)"
    return name, None


OUTPUT, WHY_NOT = _default_output()


def native(test):
    return pytest.mark.integration(pytest.mark.skipif(
        OUTPUT is None, reason=WHY_NOT or "")(test))


@pytest.fixture
def levels_kept():
    """CABLE Input's and the output's level and mute, put back after."""
    from stream_denoiser.backends.wasapi_node import (
        endpoint_volume, set_endpoint_volume)
    saved = {name: endpoint_volume(name) for name in (CABLE, OUTPUT)}
    try:
        yield saved[OUTPUT]
    finally:
        for name, (level, muted) in saved.items():
            set_endpoint_volume(name, level, muted)


def _settles(name, level=None, muted=None, timeout=2.0):
    """True once `name` has that level/mute (the mirror copies from its
    own thread)."""
    from stream_denoiser.backends.wasapi_node import endpoint_volume
    deadline = time.monotonic() + timeout
    while True:
        have_level, have_muted = endpoint_volume(name)
        if ((level is None or abs(have_level - level) < 0.005)
                and (muted is None or have_muted == muted)):
            return True
        if time.monotonic() > deadline:
            return False
        time.sleep(0.02)


@native
@pytest.mark.skipif(os.environ.get("POISE_VOLUME_TESTS") != "1",
                    reason="moves the default output device's volume "
                           "(set POISE_VOLUME_TESTS=1)")
def test_native_mirror_copies_both_ways(levels_kept):
    from stream_denoiser.backends.wasapi_node import (
        VolumeMirror, endpoint_volume, set_endpoint_volume)
    level, muted = levels_kept
    if muted:
        pytest.skip("the output device is muted")
    # One volume-key step, down unless that would go below 0.
    step = 0.02 if level >= 0.02 else -0.02
    set_endpoint_volume(CABLE, 0.9 if level < 0.5 else 0.1, False)

    with VolumeMirror(CABLE, OUTPUT):
        # Starts from the output device's: what is heard does not jump.
        assert endpoint_volume(CABLE) == (pytest.approx(level, abs=0.005),
                                          False)
        assert endpoint_volume(OUTPUT)[0] == pytest.approx(level, abs=0.005)

        # The volume keys move CABLE Input: the output follows.
        set_endpoint_volume(CABLE, level - step)
        assert _settles(OUTPUT, level - step)
        set_endpoint_volume(CABLE, muted=True)
        assert _settles(OUTPUT, muted=True)

        # The output's own slider and mute: CABLE Input shows them.
        set_endpoint_volume(OUTPUT, level, False)
        assert _settles(CABLE, level, muted=False)

        # Nothing echoes back and forth once a change is copied.
        time.sleep(0.3)
        assert endpoint_volume(CABLE) == (pytest.approx(level, abs=0.005),
                                          False)
        assert endpoint_volume(OUTPUT) == (pytest.approx(level, abs=0.005),
                                           False)

    # Closed: CABLE Input moves alone again.
    set_endpoint_volume(CABLE, level - step)
    time.sleep(0.3)
    assert endpoint_volume(OUTPUT)[0] == pytest.approx(level, abs=0.005)


@native
def test_native_mirror_refuses_bad_devices():
    """Both fail before anything is written."""
    from stream_denoiser.backends.wasapi_node import VolumeMirror, WasapiError
    with pytest.raises(WasapiError, match="same device"):
        VolumeMirror(CABLE, CABLE)
    with pytest.raises(WasapiError, match="output device: device not found"):
        VolumeMirror(CABLE, "No Such Device (Nowhere)")
