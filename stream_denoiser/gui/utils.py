"""
GUI Utilities

Shared utility functions for the GUI package.
"""
import os
from typing import Optional

def get_icon_path() -> Optional[str]:
    """
    Get the absolute path to the application icon.
    
    Returns:
        Path to icon file if it exists, None otherwise.
    """
    # Look for icon in assets folder relative to this package
    # Prefer .ico on Windows for better scaling
    # icon_path_ico = os.path.join(os.path.dirname(__file__), "assets", "icon.ico")
    # if os.path.exists(icon_path_ico):
    #     return icon_path_ico

    icon_path = os.path.join(os.path.dirname(__file__), "assets", "icon.png")
    if os.path.exists(icon_path):
        return icon_path
    
    # Fallback or development path check could go here
    return None
