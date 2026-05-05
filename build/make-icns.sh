#!/bin/bash
# make-icns.sh — generate app-icon.icns from keycap.svg
set -euo pipefail

SVG=/Users/beauregard/voicetype/assets/keycap.svg
ICONSET=/Users/beauregard/voicetype/assets/app-icon.iconset
OUT=/Users/beauregard/voicetype/assets/app-icon.icns

if ! command -v rsvg-convert >/dev/null 2>&1; then
    echo "Installing librsvg via brew..."
    brew install librsvg
fi

mkdir -p "$ICONSET"

for entry in "16:icon_16x16.png" "32:icon_16x16@2x.png" \
             "32:icon_32x32.png" "64:icon_32x32@2x.png" \
             "128:icon_128x128.png" "256:icon_128x128@2x.png" \
             "256:icon_256x256.png" "512:icon_256x256@2x.png" \
             "512:icon_512x512.png" "1024:icon_512x512@2x.png"; do
    size="${entry%%:*}"
    name="${entry##*:}"
    rsvg-convert -w "$size" -h "$size" "$SVG" -o "$ICONSET/$name"
done

iconutil -c icns "$ICONSET" -o "$OUT"
echo "Generated $OUT"
ls -lh "$OUT"
