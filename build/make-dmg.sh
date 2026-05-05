#!/bin/bash
# make-dmg.sh — build VoiceType.dmg from dist/VoiceType.app
set -euo pipefail

REPO=/Users/beauregard/voicetype
APP="$REPO/dist/VoiceType.app"
DMG="$REPO/dist/VoiceType.dmg"
BG="$REPO/assets/dmg-background.png"
VOLUME_ICON="$REPO/assets/app-icon.icns"

if [ ! -d "$APP" ]; then
    echo "ERROR: $APP not found. Run pyinstaller first."
    exit 1
fi

# Generate icons + bg if missing
[ -f "$VOLUME_ICON" ] || "$REPO/build/make-icns.sh"
[ -f "$BG" ] || "$REPO/build/render-dmg-bg.sh"

# Remove old DMG
rm -f "$DMG" "$DMG.sha256"

# Build with create-dmg
create-dmg \
    --volname "VoiceType" \
    --volicon "$VOLUME_ICON" \
    --background "$BG" \
    --window-pos 200 100 \
    --window-size 1280 800 \
    --icon-size 128 \
    --icon "VoiceType.app" 360 480 \
    --hide-extension "VoiceType.app" \
    --app-drop-link 920 480 \
    --hdiutil-quiet \
    "$DMG" \
    "$APP"

# Compute SHA256 sidecar
shasum -a 256 "$DMG" | tee "$DMG.sha256"

ls -lh "$DMG"
