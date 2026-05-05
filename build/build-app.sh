#!/bin/bash
# build-app.sh — Build VoiceType.app and fix code signatures
# Run from the voicetype directory with the venv active.
set -euo pipefail

VOICETYPE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_APP="$VOICETYPE_DIR/dist/VoiceType.app"
PY_FW="$DIST_APP/Contents/Frameworks/Python.framework/Versions/3.14/Python"

echo "==> Building VoiceType.app with PyInstaller..."
cd "$VOICETYPE_DIR"
source .venv/bin/activate
pyinstaller --noconfirm --clean build/VoiceType.spec

# PyInstaller's BUNDLE step re-signs with hardened runtime (flags=0x10002).
# On Python 3.14/Homebrew the Python.framework dylib has a different runtime
# version than the bootloader, which causes macOS to reject it at dlopen time
# with "mapping process and mapped file have different Team IDs".
# Fix: strip hardened runtime from Python.framework, then re-sign the whole
# app bundle plain adhoc (flags=0x2).
echo "==> Re-signing to strip hardened runtime from Python.framework..."
if [ -f "$PY_FW" ]; then
    codesign --force --sign - --timestamp=none "$PY_FW"
    echo "    Framework re-signed."
fi

echo "==> Re-signing entire app bundle (plain adhoc)..."
codesign --force --sign - --timestamp=none --deep "$DIST_APP"
echo "    Bundle re-signed."

echo "==> Build complete."
du -sh "$DIST_APP"
echo "    MacOS binary: $(file "$DIST_APP/Contents/MacOS/VoiceType")"
echo "    Bundle ID: $(plutil -extract CFBundleIdentifier raw "$DIST_APP/Contents/Info.plist")"
