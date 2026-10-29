"""
TUI Settings

The choices a user makes in the TUI (model, output device, AAD threshold,
strength, color theme), kept across sessions in
$XDG_CONFIG_HOME/poise/tui.json, plus colors of their own set there by
hand. The GUI keeps its own through QSettings; the TUI does not depend
on Qt.

Reading never fails: a missing, unreadable or malformed file, or a bad
value in it, gives the default for that setting.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

from ..constants import ALL_MODELS

AAD_MIN_DB = -80.0
AAD_MAX_DB = 0.0
# Strength (the engines' attenuation limit), the GUI dial's range: past
# -50 dB the leftover noise is below the model's own residual.
ATTEN_MIN_DB = -50.0
ATTEN_MAX_DB = -10.0

_logger = logging.getLogger("stream_denoiser")


def settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base) if base else Path.home() / ".config"
    return root / "poise" / "tui.json"


class TuiSettings:
    """Load once, then each setter writes the whole file."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else settings_path()
        self._data: dict = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._data = data
        except FileNotFoundError:
            pass
        except Exception as e:
            _logger.warning("Ignoring unreadable TUI settings %s: %s",
                            self.path, e)

    @property
    def model(self) -> Optional[str]:
        value = self._data.get("model")
        return value if value in ALL_MODELS else None

    @model.setter
    def model(self, value: str) -> None:
        self._set("model", value)

    @property
    def output_device(self) -> Optional[str]:
        """Pulse sink name (stable across reboots, unlike its index)."""
        value = self._data.get("output_device")
        return value if isinstance(value, str) and value else None

    @output_device.setter
    def output_device(self, value: str) -> None:
        self._set("output_device", value)

    @property
    def aad_threshold_db(self) -> Optional[float]:
        value = self._data.get("aad_threshold_db")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return max(AAD_MIN_DB, min(AAD_MAX_DB, float(value)))

    @aad_threshold_db.setter
    def aad_threshold_db(self, value: float) -> None:
        self._set("aad_threshold_db", float(value))

    @property
    def atten_lim_db(self) -> Optional[float]:
        value = self._data.get("atten_lim_db")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return max(ATTEN_MIN_DB, min(ATTEN_MAX_DB, float(value)))

    @atten_lim_db.setter
    def atten_lim_db(self, value: float) -> None:
        self._set("atten_lim_db", float(value))

    @property
    def theme(self) -> Optional[str]:
        """A palette theme name (checked by palette.apply)."""
        value = self._data.get("theme")
        return value if isinstance(value, str) and value else None

    @theme.setter
    def theme(self, value: str) -> None:
        self._set("theme", value)

    @property
    def colors(self) -> dict:
        """The user's own colors, role -> color, over the theme. Only
        ever edited by hand (checked by palette.apply)."""
        value = self._data.get("colors")
        return dict(value) if isinstance(value, dict) else {}

    @property
    def disclaimer_shown(self) -> bool:
        """Whether the first start has said music can pass through."""
        return self._data.get("disclaimer_shown") is True

    @disclaimer_shown.setter
    def disclaimer_shown(self, value: bool) -> None:
        self._set("disclaimer_shown", bool(value))

    def _set(self, key: str, value) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self._data, indent=2) + "\n",
                           encoding="utf-8")
            os.replace(tmp, self.path)  # never leave a half-written file
        except Exception as e:
            _logger.warning("Could not save TUI settings to %s: %s",
                            self.path, e)
