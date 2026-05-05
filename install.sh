#!/bin/bash
set -e

echo "=== VoxType Installer ==="

# Install whisper-cpp via brew (provides the ggml models download script)
if ! brew list whisper-cpp &>/dev/null; then
    echo "Installing whisper-cpp..."
    brew install whisper-cpp
fi

# Create venv
if [ ! -d ~/voxtype/.venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv ~/voxtype/.venv
fi

source ~/voxtype/.venv/bin/activate

# Install Python deps with CoreML support
echo "Installing Python dependencies..."
WHISPER_COREML=1 pip install -r ~/voxtype/requirements.txt

# Download base.en model
MODEL_DIR=~/voxtype/models
mkdir -p "$MODEL_DIR"
if [ ! -f "$MODEL_DIR/ggml-base.en.bin" ]; then
    echo "Downloading base.en model (~142MB)..."
    curl -L "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin" \
        -o "$MODEL_DIR/ggml-base.en.bin"
fi

# Compile Swift helpers
echo "Compiling Swift helpers..."
swiftc ~/voxtype/snippet_overlay.swift -o ~/voxtype/VoxType.app/Contents/MacOS/snippet_overlay
swiftc ~/voicetype/keys_helper.swift -o ~/voicetype/keys_helper

# Create launchd plist for auto-start
PLIST=~/Library/LaunchAgents/com.voxtype.app.plist
cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.voxtype.app</string>
    <key>ProgramArguments</key>
    <array>
        <string>$HOME/voxtype/.venv/bin/python</string>
        <string>$HOME/voxtype/voxtype.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$HOME/voxtype</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>$HOME/.voxtype/voxtype.log</string>
    <key>StandardErrorPath</key>
    <string>$HOME/.voxtype/voxtype.log</string>
</dict>
</plist>
PLISTEOF

echo "Launch agent created at $PLIST"
echo "To enable auto-start: launchctl load $PLIST"
echo "To disable: launchctl unload $PLIST"

echo ""
echo "=== Setup complete ==="
echo "Run: source ~/voxtype/.venv/bin/activate && python ~/voxtype/voxtype.py"
echo ""
echo "IMPORTANT: Grant these permissions in System Settings > Privacy & Security:"
echo "  - Microphone: allow Terminal / iTerm / VS Code"
echo "  - Accessibility: allow Terminal / iTerm / VS Code"
