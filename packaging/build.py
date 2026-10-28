"""Builds a stand-alone Goban for the platform this runs on.

    python packaging/build.py

Windows -> dist/Goban/Goban.exe      macOS -> dist/Goban.app      Linux -> dist/Goban/Goban

PyInstaller cannot cross-compile, so build each platform on that platform.
Needs the packages in requirements-dev.txt.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "assets" / "icons"


def main():
    args = [
        sys.executable, "-m", "PyInstaller", str(ROOT / "main.py"),
        "--name", "Goban",
        "--windowed",  # no console window on Windows, a proper .app bundle on macOS
        "--noconfirm", "--clean",
        "--add-data", f"{ROOT / 'assets'}{os.pathsep}assets",
        # pyglet picks its window, GL, font and audio backends at runtime, out of
        # sight of PyInstaller's import scan.
        "--collect-submodules", "pyglet",
    ]
    # Large packages that are often installed alongside but never used by the game.
    for module in ("matplotlib", "tkinter", "gi", "onnxruntime", "PIL", "IPython", "pandas", "PyQt5",
                   "PyQt6", "PySide6", "cv2", "torch"):
        args += ["--exclude-module", module]
    args += [
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    if sys.platform == "win32":
        args += ["--icon", str(ICONS / "goban.ico")]
    elif sys.platform == "darwin":
        args += ["--icon", str(ICONS / "goban.icns"), "--osx-bundle-identifier", "io.goban.client"]
    subprocess.run(args, check=True)

    built = {"win32": "dist/Goban/Goban.exe", "darwin": "dist/Goban.app"}.get(sys.platform, "dist/Goban/Goban")
    print(f"\nBuilt {ROOT / built}")


if __name__ == "__main__":
    main()
