"""
Poise Voice Isolator - UI Scaling

Single source for resolution-aware sizing. The scale factor derives from
the primary screen's logical DPI (96 DPI == 1.0, e.g. Windows 150% text
scaling == 1.5), clamped to a sane range, and can be forced for testing
or preference via the POISE_UI_SCALE environment variable.

Usage:
    from .scaling import sp, ui_scale, init_scaling

    init_scaling()          # once, after QApplication exists
    width = sp(216)         # scaled pixels for fixed widget sizes
    css = scale_stylesheet(POISE_STYLESHEET)  # scale every NNpx in QSS

This module must not import PyQt6 at top level so the pure helpers
stay importable (and testable) without Qt.
"""
import os
import re

BASE_DPI = 96.0
MIN_SCALE = 0.8
MAX_SCALE = 2.0
#: Extra multiplier for icons on top of the UI scale (tunable via
#: POISE_ICON_SCALE). Icons stay legible one step above body text.
ICON_SCALE_BOOST = 1.25

_scale_factor = None


def _clamp(value: float) -> float:
    return max(MIN_SCALE, min(MAX_SCALE, float(value)))


def set_scale_factor(factor: float) -> float:
    """Force a scale factor (tests / manual override). Returns the clamped value."""
    global _scale_factor
    _scale_factor = _clamp(factor)
    return _scale_factor


def _pick_scale(logical_dpi: float, physical_dpi: float,
                device_pixel_ratio: float) -> float:
    """Choose the UI factor from raw screen metrics (pure, testable).

    When the OS/compositor already scales (devicePixelRatio > 1), Qt
    applies that automatically, so we must stay at 1.0 to avoid
    double-scaling. Otherwise we scale up from the denser of the
    logical/physical DPI so a 144 DPI laptop panel and a 96 DPI
    desktop render at a comparable physical size.
    """
    if device_pixel_ratio > 1.0:
        return 1.0
    candidates = [BASE_DPI]
    if logical_dpi and 60.0 <= logical_dpi <= 600.0:
        candidates.append(logical_dpi)
    if physical_dpi and 60.0 <= physical_dpi <= 600.0:
        candidates.append(physical_dpi)
    return _clamp(max(candidates) / BASE_DPI)


def _detect_scale() -> float:
    """Detect the scale factor from the environment or primary screen."""
    env = os.environ.get("POISE_UI_SCALE")
    if env:
        try:
            return _clamp(float(env))
        except ValueError:
            pass
    try:
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
        if screen is not None:
            return _pick_scale(screen.logicalDotsPerInchX(),
                               screen.physicalDotsPerInchX(),
                               screen.devicePixelRatio())
    except Exception:
        pass
    return 1.0


def init_scaling() -> float:
    """Detect and store the scale factor. Call once after QApplication exists."""
    global _scale_factor
    _scale_factor = _detect_scale()
    return _scale_factor


def ui_scale() -> float:
    """Current scale factor (detects on the fly if init_scaling ran yet)."""
    if _scale_factor is not None:
        return _scale_factor
    return _detect_scale()


def sp(px: float) -> int:
    """Scale a pixel value for fixed widget sizes. Always >= 1."""
    return max(1, int(round(px * ui_scale())))


def icon_boost() -> float:
    """Icon size multiplier on top of the UI scale."""
    env = os.environ.get("POISE_ICON_SCALE")
    if env:
        try:
            return _clamp(float(env))
        except ValueError:
            pass
    return ICON_SCALE_BOOST


def isp(px: float) -> int:
    """Scale a pixel value for icons (UI scale x icon boost). Always >= 1."""
    return max(1, int(round(px * ui_scale() * icon_boost())))


def scale_stylesheet(css: str, scale=None) -> str:
    """Scale every NNpx value in a stylesheet by the UI factor."""
    factor = ui_scale() if scale is None else _clamp(scale)
    if factor == 1.0:
        return css

    def _replace(match: "re.Match") -> str:
        return f"{int(round(float(match.group(1)) * factor))}px"

    return re.sub(r"(\d+(?:\.\d+)?)px", _replace, css)
