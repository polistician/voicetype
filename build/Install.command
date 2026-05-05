#!/bin/bash
# Install.command — Manual install fallback for VoiceType
# Run this if the launcher shim's auto-fix didn't work for some reason.
# Removes the macOS quarantine attribute from /Applications/VoiceType.app
# so AppTranslocation doesn't kick in.
set -e

APP=/Applications/VoiceType.app

if [ ! -d "$APP" ]; then
    echo ""
    echo "❌ /Applications/VoiceType.app not found."
    echo ""
    echo "First drag VoiceType from this DMG into the Applications shortcut,"
    echo "THEN run this script."
    echo ""
    read -p "Press Return to close."
    exit 1
fi

echo ""
echo "🔧 Removing macOS quarantine from /Applications/VoiceType.app..."
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
echo "✓ Done."
echo ""
echo "Now launch VoiceType from /Applications normally."
echo "On first run, macOS will ask for Microphone + Accessibility — grant both."
echo ""
read -p "Press Return to close."
