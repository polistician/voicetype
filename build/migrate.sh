#!/bin/bash
# migrate.sh — one-time rename voxtype → voicetype
# Run from anywhere; script uses absolute paths
set -euo pipefail

OLD_HOME=~/voxtype
NEW_HOME=~/voicetype
OLD_DATA=~/.voxtype
NEW_DATA=~/.voicetype
OLD_BUNDLE_ID="com.voxtype.app"
NEW_BUNDLE_ID="com.polistician.voicetype"
OLD_PLIST="$HOME/Library/LaunchAgents/com.voxtype.app.plist"
NEW_PLIST="$HOME/Library/LaunchAgents/com.polistician.voicetype.plist"

echo "=== VoiceType migration ==="

if [ ! -d "$OLD_HOME" ]; then
    echo "ERROR: $OLD_HOME doesn't exist. Already migrated?"
    exit 1
fi
if [ -d "$NEW_HOME" ]; then
    echo "ERROR: $NEW_HOME already exists. Manual review required."
    exit 1
fi

# Stop launchd agent if running
if launchctl list 2>/dev/null | grep -q "$OLD_BUNDLE_ID"; then
    echo "Unloading old launchd agent..."
    launchctl unload "$OLD_PLIST" 2>/dev/null || true
fi

# Move source dir
echo "Moving source: $OLD_HOME → $NEW_HOME"
mv "$OLD_HOME" "$NEW_HOME"

# Copy (don't move) user data dir for safety
if [ -d "$OLD_DATA" ] && [ ! -d "$NEW_DATA" ]; then
    echo "Copying user data: $OLD_DATA → $NEW_DATA"
    cp -R "$OLD_DATA" "$NEW_DATA"
fi

# Update path constants in code (uses sed, in-place)
echo "Updating path constants in source..."
for f in voxtype.py snippets.py voice_profile.py corrections.py stats.py user_fixes.py transcript_history.py \
         config.py intent.py pronunciation.py suggestions.py training_data.py; do
    if [ -f "$NEW_HOME/$f" ]; then
        # macOS sed needs '' after -i
        # Handles both dot-prefix (~/.voxtype/) and non-dot (~/voxtype/) patterns
        sed -i '' 's|~/\.voxtype/|~/.voicetype/|g; s|/\.voxtype/|/.voicetype/|g; s|~/voxtype/|~/voicetype/|g; s|/voxtype/|/voicetype/|g' "$NEW_HOME/$f"
        echo "  updated $f"
    fi
done

# Write new launchd plist
echo "Writing new launchd plist..."
cat > "$NEW_PLIST" <<PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$NEW_BUNDLE_ID</string>
    <key>ProgramArguments</key>
    <array>
        <string>$NEW_HOME/.venv/bin/python</string>
        <string>$NEW_HOME/voxtype.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$NEW_HOME</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$NEW_DATA/voicetype.log</string>
    <key>StandardErrorPath</key>
    <string>$NEW_DATA/voicetype.log</string>
</dict>
</plist>
PLISTEOF

# Remove old plist
if [ -f "$OLD_PLIST" ]; then
    echo "Removing old launchd plist..."
    rm "$OLD_PLIST"
fi

echo ""
echo "=== Migration complete ==="
echo ""
echo "Next steps:"
echo "  1. cd $NEW_HOME"
echo "  2. Verify .venv still works: source .venv/bin/activate && python -c 'import rumps'"
echo "  3. Test: python voxtype.py  (Ctrl-C after menubar mic appears)"
echo "  4. If happy, load new launchd agent: launchctl load $NEW_PLIST"
echo ""
