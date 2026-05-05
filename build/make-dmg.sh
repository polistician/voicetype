#!/bin/bash
# make-dmg.sh — build VoiceType.dmg from dist/VoiceType.app + Install.command
set -euo pipefail

REPO=/Users/beauregard/voicetype
APP="$REPO/dist/VoiceType.app"
DMG="$REPO/dist/VoiceType.dmg"
BG="$REPO/assets/dmg-background.png"
VOLUME_ICON="$REPO/assets/app-icon.icns"
INSTALL_CMD="$REPO/build/Install.command"
STAGE="$REPO/dist/dmg-stage"

if [ ! -d "$APP" ]; then
    echo "ERROR: $APP not found. Run pyinstaller first."
    exit 1
fi

# Generate icons + bg if missing
[ -f "$VOLUME_ICON" ] || "$REPO/build/make-icns.sh"
[ -f "$BG" ] || "$REPO/build/render-dmg-bg.sh"

# Stage the contents the DMG should hold
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/VoiceType.app"
cp "$INSTALL_CMD" "$STAGE/Install.command"
chmod +x "$STAGE/Install.command"
cp "$REPO/INSTALL.md" "$STAGE/INSTALL.md"

# Remove old DMG
rm -f "$DMG" "$DMG.sha256"

# Build
create-dmg \
    --volname "VoiceType" \
    --volicon "$VOLUME_ICON" \
    --background "$BG" \
    --window-pos 200 100 \
    --window-size 1280 800 \
    --icon-size 96 \
    --icon "VoiceType.app" 350 340 \
    --icon "Install.command" 640 600 \
    --icon "INSTALL.md" 640 690 \
    --hide-extension "VoiceType.app" \
    --app-drop-link 930 340 \
    --hdiutil-quiet \
    "$DMG" \
    "$STAGE"

# Cleanup stage
rm -rf "$STAGE"

# Compute SHA256 sidecar
shasum -a 256 "$DMG" | tee "$DMG.sha256"

ls -lh "$DMG"
