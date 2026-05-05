#!/bin/bash
# render-dmg-bg.sh — render dmg-background.svg → dmg-background.png at 1280×800
set -euo pipefail

if ! command -v rsvg-convert >/dev/null 2>&1; then
    brew install librsvg
fi

rsvg-convert -w 1280 -h 800 \
    /Users/beauregard/voicetype/assets/dmg-background.svg \
    -o /Users/beauregard/voicetype/assets/dmg-background.png

ls -lh /Users/beauregard/voicetype/assets/dmg-background.png
