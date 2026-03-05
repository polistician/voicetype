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

echo ""
echo "=== Setup complete ==="
echo "Run: source ~/voxtype/.venv/bin/activate && python ~/voxtype/voxtype.py"
echo ""
echo "IMPORTANT: Grant these permissions in System Settings > Privacy & Security:"
echo "  - Microphone: allow Terminal / iTerm / VS Code"
echo "  - Accessibility: allow Terminal / iTerm / VS Code"
