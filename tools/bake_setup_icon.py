"""Bake the setup window's mark into the installer's .ico.

Poise_Setup.exe is the first thing a user sees, so its file-system icon is
the About page's vector mark (assets/icon.svg), not the app's tiled
icon.ico. The .ico is committed because ISCC needs it on disk before
PyInstaller runs; this script regenerates it when icon.svg changes:

    python tools/bake_setup_icon.py

Only PyQt6 (already required) is needed. The SVG is rendered once at high
resolution, scaled down to each icon size, and packed by hand as 32-bit
BGRA DIB entries - the form Windows and PyInstaller both read.
"""
from __future__ import annotations

import os
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "stream_denoiser", "gui", "assets")
SVG = os.path.join(ASSETS, "icon.svg")
OUT = os.path.join(ASSETS, "icon-setup.ico")
SIZES = (256, 128, 64, 48, 32, 24, 16)
#: Rendered once and scaled down, so the glow survives the small sizes.
MASTER = 1024


def render(size: int):
    """The SVG painted onto a transparent square image."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(SVG)
    if not renderer.isValid():
        raise SystemExit(f"not a valid SVG: {SVG}")
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def _dib(image) -> bytes:
    """One 32-bit icon image: BITMAPINFOHEADER, bottom-up BGRA, AND mask."""
    from PyQt6.QtGui import QImage

    side = image.width()
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    rows = []
    for y in range(side - 1, -1, -1):
        row = bytearray()
        for x in range(side):
            colour = image.pixelColor(x, y)
            row += bytes((colour.blue(), colour.green(),
                          colour.red(), colour.alpha()))
        rows.append(bytes(row))
    pixels = b"".join(rows)
    # The mask is unused at 32 bits: the alpha channel decides.
    stride = ((side + 31) // 32) * 4
    mask = bytes(stride * side)
    header = struct.pack("<IiiHHIIiiII", 40, side, side * 2, 1, 32, 0,
                         len(pixels) + len(mask), 0, 0, 0, 0)
    return header + pixels + mask


def build() -> str:
    """Write OUT and return its path."""
    from PyQt6.QtCore import Qt

    master = render(MASTER)
    images = []
    for side in SIZES:
        scaled = master.scaled(side, side,
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        images.append((side, _dib(scaled)))

    directory = struct.pack("<HHH", 0, 1, len(images))
    entries = bytearray()
    blob = bytearray()
    offset = 6 + 16 * len(images)
    for side, data in images:
        entries += struct.pack("<BBBBHHII", side % 256, side % 256, 0, 0,
                               1, 32, len(data), offset)
        blob += data
        offset += len(data)

    with open(OUT, "wb") as fh:
        fh.write(directory + bytes(entries) + bytes(blob))
    return OUT


if __name__ == "__main__":
    print(build())
