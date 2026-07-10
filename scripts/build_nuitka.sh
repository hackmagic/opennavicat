#!/usr/bin/env bash
set -euo pipefail
# Build OpenNavicat CLI/GUI with Nuitka (AOT compiler).
# Produces standalone single-file executables in dist/nuitka/.

TARGET="${1:-cli}"  # "cli" or "gui"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/open_navicat"
OUT_DIR="$ROOT/dist/nuitka"

if [ "$TARGET" = "gui" ]; then
    ENTRY="gui_main.py"
    OUT_NAME="opennavicat"
    PLUGINS="--enable-plugin=pyside6"
    ICON=""
    [ -f "$SRC/ui/resources/icon.ico" ] && ICON="--windows-icon-from-ico=$SRC/ui/resources/icon.ico"
else
    ENTRY="cli_main.py"
    OUT_NAME="opennavicat-cli"
    PLUGINS=""
    ICON=""
fi

echo "Building OpenNavicat ($TARGET) with Nuitka..."

nuitka --onefile --standalone \
    --python-flag=-m \
    $PLUGINS $ICON \
    --output-dir="$OUT_DIR" \
    --output-name="$OUT_NAME" \
    --include-data-dir="$SRC/i18n=open_navicat/i18n" \
    --include-package=open_navicat \
    --disable-ccache \
    --noinclude-pytest-mode=nofollow \
    --noinclude-setuptools-mode=nofollow \
    "$SRC/$ENTRY"

echo "Done: $OUT_DIR/$OUT_NAME"
