"""Themed Windows title bar: colour conversion and platform gating."""
import sys

import pytest

from stream_denoiser.gui import themes, titlebar


def test_colorref_is_bgr():
    assert titlebar.colorref("#112233") == 0x00332211
    assert titlebar.colorref("#E8C468") == 0x0068C4E8
    assert titlebar.colorref("ffffff") == 0x00FFFFFF


def test_every_theme_has_the_frame_colours():
    for theme_id in themes.theme_ids():
        p = themes.get_theme(theme_id)
        for key in (titlebar.CAPTION_KEY, titlebar.TEXT_KEY,
                    titlebar.BORDER_KEY):
            assert 0 <= titlebar.colorref(p[key]) <= 0xFFFFFF


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows behaviour")
def test_noop_off_windows():
    class Fake:
        def winId(self):  # noqa: N802
            raise AssertionError("must not touch the native window")
    assert titlebar.windows_build() == 0
    assert titlebar.apply_titlebar(Fake(), themes.current()) is False


def _fake_windows(monkeypatch, build):
    calls = []
    monkeypatch.setattr(titlebar, "windows_build", lambda: build)
    monkeypatch.setattr(titlebar, "_set_attr",
                        lambda hwnd, attr, value: calls.append(
                            (attr, value)) or True)
    return calls


class _Win:
    def winId(self):  # noqa: N802
        return 1234


def test_windows_11_sets_caption_text_and_border(monkeypatch):
    calls = _fake_windows(monkeypatch, 22631)
    p = themes.get_theme("abyss")
    assert titlebar.apply_titlebar(_Win(), p) is True
    attrs = dict(calls)
    assert attrs[titlebar.DWMWA_USE_IMMERSIVE_DARK_MODE] == 1
    assert attrs[titlebar.DWMWA_CAPTION_COLOR] == titlebar.colorref(
        p[titlebar.CAPTION_KEY])
    assert attrs[titlebar.DWMWA_TEXT_COLOR] == titlebar.colorref(p["text"])
    assert titlebar.DWMWA_BORDER_COLOR in attrs


def test_windows_10_only_goes_dark(monkeypatch):
    calls = _fake_windows(monkeypatch, 19045)
    assert titlebar.apply_titlebar(_Win(), themes.get_theme("ember")) is True
    assert [a for a, _ in calls] == [titlebar.DWMWA_USE_IMMERSIVE_DARK_MODE]


def test_failures_never_raise(monkeypatch):
    monkeypatch.setattr(titlebar, "windows_build", lambda: 22631)

    def boom(*_a):
        raise OSError("no dwmapi")
    monkeypatch.setattr(titlebar, "_set_attr", boom)
    assert titlebar.apply_titlebar(_Win(), themes.current()) is False
