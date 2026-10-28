"""Where things live on each platform, both from source and in a PyInstaller build."""

import os
import sys
from pathlib import Path

APP_NAME = "Goban"
FROZEN = getattr(sys, "frozen", False)

# Bundled, read-only files (assets/...). PyInstaller unpacks them under sys._MEIPASS.
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
ICON_DIR = RESOURCE_ROOT / "assets" / "icons"


def cache_dir():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_NAME / "Cache"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "pyglet-goban"


def data_dir():
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "goban"


def music_dirs():
    """Folders searched for the player's own music, first match wins."""
    beside_app = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
    return [beside_app / "music", data_dir() / "music"]
