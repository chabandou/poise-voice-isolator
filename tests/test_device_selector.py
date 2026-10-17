"""Device selector header guards (needs Qt; skipped without it).

The title label was once added to its header row twice; duplicate
layout items for one widget split its allocation and the title drifted
right (scale/width dependent — only visible with room to spare, hence
the wide + scaled setup here).
"""
import os
import time

import pytest

pytest.importorskip("PyQt6.QtWidgets")


@pytest.fixture(scope="module")
def app():
    # Forced offscreen (not setdefault): deterministic geometry.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _pump(app, secs=0.4):
    end = time.time() + secs
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def _header_layout(selector):
    from PyQt6.QtWidgets import QHBoxLayout
    outer = selector.layout()
    for i in range(outer.count()):
        item = outer.itemAt(i)
        lay = item.layout()
        if isinstance(lay, QHBoxLayout):
            return lay
    raise AssertionError("header row not found")


def _flat_widgets(layout):
    """Widgets of a layout, descending into nested layouts."""
    out = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is not None:
            out.append(item.widget())
        elif item.layout() is not None:
            out.extend(_flat_widgets(item.layout()))
    return out


def test_title_appears_once_and_sits_left(app):
    from stream_denoiser.gui import scaling
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    try:
        scaling.set_scale_factor(1.5)
        selector = DeviceSelector("Input Device", "input", "Caption")
        selector.resize(1055, 90)
        selector.show()
        _pump(app)
        header = _header_layout(selector)
        refs = sum(1 for w in _flat_widgets(header) if w is selector._label)
        assert refs == 1, "title label must be added exactly once"
        # The icon chip leads the row; the title sits one spacing after it.
        chip = selector._chip
        assert header.itemAt(0).widget() is chip
        gap = selector._label.x() - (chip.x() + chip.width())
        assert gap == header.spacing(), (gap, header.spacing())
        assert selector._label.text() == "Input Device"
    finally:
        scaling.init_scaling()
    selector.close()


# -- device list: no "Default" entry, VB-Cable left out ---------------------------
class _FakeSD:
    """Stand-in for sounddevice: index 0 = MME, 1 = WASAPI."""

    APIS = [{"name": "MME", "default_output_device": 2},
            {"name": "Windows WASAPI", "default_output_device": 5}]

    def __init__(self, devices, wasapi_default=5):
        self.devices = devices
        self.APIS = [dict(api) for api in self.APIS]
        self.APIS[1]["default_output_device"] = wasapi_default

    def query_devices(self):
        return self.devices

    def query_hostapis(self, index=None):
        return self.APIS if index is None else self.APIS[index]


def _dev(name, api=1, outs=2, ins=0):
    return {"name": name, "hostapi": api,
            "max_output_channels": outs, "max_input_channels": ins}


DEVICES = [
    _dev("Speakers (Realtek)", api=0),                     # 0: MME, skipped
    _dev("CABLE Output (VB-Audio Virtual Cable)", outs=0, ins=2),  # 1: input
    _dev("Speakers (Realtek)", api=0),                     # 2: MME default
    _dev("CABLE Input (VB-Audio Virtual Cable)"),          # 3: VB-Cable out
    _dev("Headphones (USB Audio)"),                        # 4
    _dev("Speakers (Realtek(R) Audio)"),                   # 5: WASAPI default
]


@pytest.fixture()
def fake_sd(monkeypatch):
    from stream_denoiser.gui.widgets import device_selector
    fake = _FakeSD(list(DEVICES))
    monkeypatch.setattr(device_selector, "sd", fake, raising=False)
    monkeypatch.setattr(device_selector, "USE_SOUNDDEVICE", True)
    return fake


def _items(selector):
    combo = selector._combo
    return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]


def test_output_list_has_no_default_and_no_vb_cable(app, fake_sd):
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    selector = DeviceSelector("Output device", "output")
    assert _items(selector) == [("Headphones (USB Audio)", 4),
                                ("Speakers (Realtek(R) Audio)", 5)]
    selector.close()


def test_output_preselects_the_wasapi_default_not_the_mme_one(app, fake_sd):
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    selector = DeviceSelector("Output device", "output")
    assert selector.selected_device_id == 5
    selector.selected_device_id = None            # nothing saved yet
    assert selector.selected_device_id == 5
    selector.selected_device_id = 4               # saved choice wins
    assert selector.selected_device_id == 4
    selector.selected_device_id = 99              # saved device vanished
    assert selector.selected_device_id == 5
    selector.close()


def test_default_on_vb_cable_falls_back_to_the_first_device(app, monkeypatch):
    from stream_denoiser.gui.widgets import device_selector
    monkeypatch.setattr(device_selector, "sd",
                        _FakeSD(list(DEVICES), wasapi_default=3), raising=False)
    monkeypatch.setattr(device_selector, "USE_SOUNDDEVICE", True)
    selector = device_selector.DeviceSelector("Output device", "output")
    assert selector.selected_device_id == 4
    selector.close()


def test_rescan_announces_a_fallback_when_the_choice_disappears(app, fake_sd):
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    selector = DeviceSelector("Output device", "output")
    selector.selected_device_id = 4
    seen = []
    selector.device_changed.connect(seen.append)
    selector.refresh_devices()                    # unchanged: stays quiet
    assert seen == [] and selector.selected_device_id == 4
    fake_sd.devices[4] = _dev("Headphones (USB Audio)", outs=0)  # unplugged
    selector.refresh_devices()
    assert selector.selected_device_id == 5
    assert seen == [5]
    selector.close()


def test_empty_output_list_says_so(app, fake_sd):
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    fake_sd.devices = [DEVICES[0], DEVICES[3]]    # MME + VB-Cable only
    selector = DeviceSelector("Output device", "output")
    assert _items(selector) == [("No output devices found", None)]
    selector.close()


def test_is_vb_cable_names():
    from stream_denoiser.gui.widgets.device_selector import is_vb_cable
    assert is_vb_cable("CABLE Input (VB-Audio Virtual Cable)")
    assert is_vb_cable("CABLE In 16ch (VB-Audio Virtual Cable)")
    assert is_vb_cable("CABLE Input (VB-Audio Virtual C")   # truncated
    assert not is_vb_cable("Speakers (Realtek(R) Audio)")
    assert not is_vb_cable("Cable Modem Speakers")


def test_lock_swaps_caption_and_disables_picking(app):
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    selector = DeviceSelector("Output device", "output", "Caption")
    selector.set_locked(True)
    assert selector.is_locked
    assert not selector._combo.isEnabled()
    assert not selector._refresh_btn.isEnabled()
    assert selector._refresh_btn.isHidden()
    assert selector._subtitle.text() == "Locked while running"
    selector.set_subtitle("New caption")      # kept for the unlock
    assert selector._subtitle.text() == "Locked while running"
    selector.set_locked(False)
    assert not selector.is_locked and selector._refresh_btn.isEnabled()
    assert selector._subtitle.text() == "New caption"
    selector.close()


def test_card_text_splits_endpoint_from_hardware():
    from stream_denoiser.gui.widgets.device_selector import card_text
    assert card_text("Speakers (Realtek(R) Audio)") == (
        "Speakers", "Realtek(R) Audio")
    # WASAPI truncates long names, losing the closing parenthesis.
    assert card_text("Headphones (WH-1000XM4 Stereo") == (
        "Headphones", "WH-1000XM4 Stereo")
    assert card_text("Digital Output", is_default=True) == (
        "Digital Output", "System default")
    assert card_text("Speakers (USB DAC)", is_default=True) == (
        "Speakers", "USB DAC \u00b7 System default")


def test_refresh_icon_is_centred_in_its_button(app):
    """Fixed 6 px margins once left the boosted icon too little room:
    it overflowed right and down, off-centre in its hover wash."""
    from stream_denoiser.gui.widgets.device_selector import DeviceSelector
    selector = DeviceSelector("Output device", "output", "Caption")
    selector.show()
    _pump(app, 0.1)
    button, glyph = selector._refresh_btn, selector._refresh_icon.geometry()
    assert button.width() == button.height()
    assert glyph.left() == button.width() - glyph.right() - 1
    assert glyph.top() == button.height() - glyph.bottom() - 1
    selector.close()
