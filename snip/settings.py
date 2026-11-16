import json
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Snip"
SETTINGS_FILE = APP_DIR / "settings.json"


def _default_folder():
    pics = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation) or str(Path.home() / "Pictures")
    return str(Path(pics) / "Snips")


DEFAULTS = {
    "save_folder": None,          # filled lazily (needs QApplication)
    "auto_save": True,
    "auto_copy": True,
    "after_capture": "thumbnail",  # thumbnail | editor | nothing
    "hotkey_primary": "Print Screen",
    "hotkey_secondary": "Ctrl+Shift+X",
    "hotkey_instant": "Ctrl+Print Screen",
    "asked_printscreen": False,
    "start_with_windows": True,
    "color": "#ff3b30",
    "width": 4,
    "font_size": 28,
    "shadow": True,
    "fill": False,
    "custom_colors": [],
    "first_run": True,
    "folder_rules": {},
    "shortcut_created": False,
    "last_frame": None,
    "auto_redact": False,
    "scroll_mode": "freeze",     # freeze (Glint steps the page under a frozen picture) | manual
    "arrow_head": "tapered",     # tapered | classic | double
    "outline": False,
    "callout": False,
    "accent": "#e8a33d",
    "appearance": "system",
    "library_sort": "newest",
    "sidebar_collapsed": False,
    "last_region": None,         # [x, y, w, h] physical, for "Repeat last area"
    "hotkey_repeat": "None",
    "hide_desktop_icons": False,
    "window_style": "clean",     # plain | clean (Win11 rounded corners made transparent) | shadow    # newest | oldest | app | folder | size | name      # system | light | dark
    "gaming_tip_hidden": False,
    "style_presets": [],         # user-saved presets: {name, color, width, font, fill, shadow, head, outline}
}


class Settings:
    def __init__(self):
        self._d = dict(DEFAULTS)
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                self._d.update(json.load(f))
        except Exception:
            pass
        if not self._d.get("save_folder"):
            self._d["save_folder"] = _default_folder()

    def __getattr__(self, k):
        d = self.__dict__.get("_d")
        if d is not None and k in d:
            return d[k]
        raise AttributeError(k)

    def set(self, **kw):
        self._d.update(kw)
        self.save()

    def save(self):
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            tmp = SETTINGS_FILE.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._d, f, indent=2)
            os.replace(tmp, SETTINGS_FILE)
        except Exception:
            pass
