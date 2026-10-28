#!/usr/bin/env sh
# Installs the Goban icon and an application-menu entry for the current user.
# Run from anywhere: packaging/linux/install.sh   (undo with --uninstall)
set -eu

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
DATA=${XDG_DATA_HOME:-$HOME/.local/share}
SIZES="16 24 32 48 64 128 256 512"

if [ "${1:-}" = "--uninstall" ]; then
    for n in $SIZES; do rm -f "$DATA/icons/hicolor/${n}x${n}/apps/goban.png"; done
    rm -f "$DATA/applications/goban.desktop"
    echo "Removed Goban menu entry and icons."
    exit 0
fi

PYTHON="$ROOT/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3

for n in $SIZES; do
    install -Dm644 "$ROOT/assets/icons/goban-$n.png" "$DATA/icons/hicolor/${n}x${n}/apps/goban.png"
done
mkdir -p "$DATA/applications"
sed "s|@EXEC@|\"$PYTHON\" \"$ROOT/main.py\"|" "$ROOT/packaging/linux/goban.desktop" > "$DATA/applications/goban.desktop"
chmod 644 "$DATA/applications/goban.desktop"

command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t "$DATA/icons/hicolor" || true
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q "$DATA/applications" || true
echo "Installed Goban to your application menu."
