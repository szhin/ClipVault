#!/usr/bin/env bash
# Build bản macOS: PyInstaller (.app) -> dist/ClipVault-<version>-macos.dmg. Chạy trên macOS từ thư mục gốc dự án:
#   bash packaging/build_macos.sh      (cần .venv hoặc python có `pip install -e ".[build]"`)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
VERSION="$("$PY" - <<'PYEOF'
import re
print(re.search(r'__version__\s*=\s*"([^"]+)"', open("src/clipvault/__init__.py", encoding="utf-8").read()).group(1))
PYEOF
)"
echo "ClipVault $VERSION"

# icon.icns từ assets/icon.png (iconutil có sẵn trên macOS)
rm -rf build dist/ClipVault dist/ClipVault.app
mkdir -p build/icon.iconset
for s in 16 32 64 128 256 512; do
  sips -z $s $s assets/icon.png --out "build/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) assets/icon.png --out "build/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns build/icon.iconset -o build/icon.icns

"$PY" -m PyInstaller packaging/clipvault_macos.spec --noconfirm --distpath dist --workpath build/pyi

DMG="dist/ClipVault-$VERSION-macos.dmg"
rm -f "$DMG"
STAGE="build/dmg"
rm -rf "$STAGE" && mkdir -p "$STAGE"
cp -R dist/ClipVault.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "ClipVault $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
echo "Done: $DMG"
