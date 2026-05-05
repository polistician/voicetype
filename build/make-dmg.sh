#!/bin/bash
# make-dmg.sh — build VoiceType.dmg from dist/VoiceType.app
# Simple 2-item DMG: VoiceType.app + Applications shortcut. Period.
# (Install.command + INSTALL.md live in the repo for troubleshooting.)
set -euo pipefail

REPO=/Users/beauregard/voicetype
APP="$REPO/dist/VoiceType.app"
DMG="$REPO/dist/VoiceType.dmg"
BG="$REPO/assets/dmg-background.png"
VOLUME_ICON="$REPO/assets/app-icon.icns"
STAGE="$REPO/dist/dmg-stage"

if [ ! -d "$APP" ]; then
    echo "ERROR: $APP not found. Run pyinstaller first."
    exit 1
fi

# Generate icons + bg if missing
[ -f "$VOLUME_ICON" ] || "$REPO/build/make-icns.sh"
[ -f "$BG" ] || "$REPO/build/render-dmg-bg.sh"

# Stage just the .app — keep DMG minimal
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/VoiceType.app"

# Remove old DMG
rm -f "$DMG" "$DMG.sha256"

# Build
create-dmg \
    --volname "VoiceType" \
    --volicon "$VOLUME_ICON" \
    --background "$BG" \
    --window-pos 200 100 \
    --window-size 800 480 \
    --icon-size 128 \
    --icon "VoiceType.app" 220 230 \
    --hide-extension "VoiceType.app" \
    --app-drop-link 580 230 \
    --hdiutil-quiet \
    "$DMG" \
    "$STAGE"

# Cleanup stage
rm -rf "$STAGE"

# Compute SHA256 sidecar
shasum -a 256 "$DMG" | tee "$DMG.sha256"

ls -lh "$DMG"
