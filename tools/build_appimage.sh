#!/usr/bin/env bash
# Builds Red-Rip-<version>-appimg-<arch>.AppImage (Linux). Needs: Python with requirements.txt +
# pyinstaller installed, and internet access to fetch appimagetool on first use.
#   tools/build_appimage.sh [version-label]      e.g. tools/build_appimage.sh v0.1.6
set -euo pipefail
cd "$(dirname "$0")/.."
LABEL="${1:-dev}"
ARCH="$(uname -m)"
OUT="${OUT_DIR:-dist}"
WORK="${WORK_DIR:-build/appimage}"

rm -rf "$WORK" && mkdir -p "$WORK" "$OUT"

# 1. Folder build (faster startup than --onefile inside an AppImage)
python -m PyInstaller --noconfirm --clean --onedir --windowed --name Red-Rip \
  --add-data "$PWD/assets/icon.ico:assets" --add-data "$PWD/assets/icon.png:assets" \
  --distpath "$WORK/pyi-dist" --workpath "$WORK/pyi-work" --specpath "$WORK" \
  "$PWD/launcher.py"

# 2. AppDir layout
APPDIR="$WORK/Red-Rip.AppDir"
mkdir -p "$APPDIR/usr/lib" "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -a "$WORK/pyi-dist/Red-Rip" "$APPDIR/usr/lib/red-rip"
cp packaging/linux/red-rip.desktop "$APPDIR/red-rip.desktop"
cp packaging/linux/red-rip.desktop "$APPDIR/usr/share/applications/red-rip.desktop"
cp assets/icon.png "$APPDIR/red-rip.png"
cp assets/icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/red-rip.png"
ln -sf red-rip.png "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/red-rip/Red-Rip" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

if [ -n "${SKIP_PACK:-}" ]; then
  echo "AppDir ready (not packed): $APPDIR"; exit 0
fi

# 3. Pack (appimagetool embeds a static runtime: no libfuse2 needed on the target system)
TOOL="$WORK/../appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
  curl -fsSL -o "$TOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage"
  chmod +x "$TOOL"
fi
TARGET="$OUT/Red-Rip-$LABEL-appimg-$ARCH.AppImage"
ARCH="$ARCH" "$TOOL" --appimage-extract-and-run --no-appstream "$APPDIR" "$TARGET"
echo "Built: $TARGET"
