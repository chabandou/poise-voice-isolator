"""
GUI Utilities

Shared utility functions for the GUI package.
"""
import os
from typing import Optional

#: Theme ids with a dedicated icon variant. All other themes (including
#: Mono) use the signature cyan icon; the light-gray gradient tip is
#: identical in every variant.
THEME_ICON_VARIANTS = {
    "ultraviolet": "icon-ultraviolet.svg",
    "ember": "icon-ember.svg",
}


def get_icon_path(theme: Optional[str] = None) -> Optional[str]:
    """
    Get the absolute path to the application icon.

    Prefers the vector icon (crisp at any size), picking the variant
    matching the given theme (defaults to the active theme); falls back
    to the raster PNG. Both are understood by QIcon/QPixmap.

    Returns:
        Path to icon file if it exists, None otherwise.
    """
    from .themes import current_id
    theme_id = theme or current_id()
    assets = os.path.join(os.path.dirname(__file__), "assets")
    candidates = []
    variant = THEME_ICON_VARIANTS.get(theme_id)
    if variant:
        candidates.append(variant)
    candidates.extend(("icon.svg", "icon.png"))
    for name in candidates:
        icon_path = os.path.join(assets, name)
        if os.path.exists(icon_path):
            return icon_path

    # Fallback or development path check could go here
    return None
