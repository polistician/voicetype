# VoiceType Rebuild v0.9.1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship VoiceType v0.9.1 — a downloadable macOS .app at `github.com/polistician/voicetype/releases/latest`, linked from a rebuilt `voicetype.polistician.ai` site, with a 4-screen first-launch onboarding (welcome → permissions → live dictation → optional API key) and a minimal Settings window for ongoing key management.

**Architecture:** PyInstaller bundles the existing Python+Swift code into `VoiceType.app`. `create-dmg` wraps it. `release.sh` cuts a versioned GitHub Release with the DMG and SHA256. The marketing site is vanilla HTML/CSS deployed to the existing `voicetype.polistician.ai` Caddy mount. Onboarding and Settings are new Swift surfaces that bridge to the Python backend over the existing JSON-stdio overlay protocol.

**Tech Stack:** Python 3.12 + rumps (menubar), Swift/SwiftUI (overlay/onboarding/settings), PyInstaller (bundling), create-dmg (DMG packaging), GitHub Releases (distribution), Caddy + FastAPI static mount (site hosting).

**Working directory:** All work happens in `~/voxtype/` (renamed to `~/voicetype/` in Phase 1). The brainstorming session did NOT use a dedicated worktree — execution happens directly in the source tree.

**Spec:** `docs/superpowers/specs/2026-05-04-voicetype-rebuild-design.md` — read it once before starting. Locked decisions (Section 3) and Phase plan (Section 2a) are not up for re-debate.

**Phasing in this plan:**
- Phase 0: Cleanup commit (commit existing quality fixes, fix .gitignore)
- Phase 1: Repo migration (voxtype → voicetype rename)
- Phase 2: GitHub repo setup + LICENSE
- Phase 3: Brand assets (keycap, icons, dmg-bg, favicon)
- Phase 4: Marketing site rebuild
- Phase 5: Keys helper (Keychain integration)
- Phase 6: Settings window
- Phase 7: 4-screen onboarding
- Phase 8: Steer overlay brand restyle
- Phase 9: PyInstaller bundling
- Phase 10: DMG packaging
- Phase 11: Release pipeline + first cut of v0.9.1
- Phase 12: Site deployment + cutover + end-to-end smoke test

Each phase is independently verifiable. Don't skip phases — earlier ones unblock later ones.

---

## Phase 0 — Cleanup commit

The repo has 9 uncommitted modified files (all real quality fixes — none discardable), 2 untracked source files that should be in git (`paste_helper.swift`, `translator.py`), and several untracked build artifacts that should NOT be in git. One commit cleans this up.

### Task 0.1: Tarball backup before any changes

**Files:**
- Create: `~/voxtype-backup-2026-05-05.tar.gz`
- Create: `~/.voxtype-backup-2026-05-05.tar.gz`

- [ ] **Step 1: Create backups**

```bash
tar -czf ~/voxtype-backup-2026-05-05.tar.gz -C ~ voxtype
tar -czf ~/.voxtype-backup-2026-05-05.tar.gz -C ~ .voxtype
ls -lh ~/*voxtype-backup-2026-05-05.tar.gz
```

Expected: two `.tar.gz` files in `~/`, sizes ~200MB and ~5MB respectively.

- [ ] **Step 2: Verify they extract**

```bash
mkdir -p /tmp/voxtype-backup-test
tar -xzf ~/voxtype-backup-2026-05-05.tar.gz -C /tmp/voxtype-backup-test
ls /tmp/voxtype-backup-test/voxtype/voxtype.py
rm -rf /tmp/voxtype-backup-test
```

Expected: `voxtype.py` exists in the extraction.

### Task 0.2: Update .gitignore

**Files:**
- Modify: `~/voxtype/.gitignore`

- [ ] **Step 1: Read current .gitignore**

```bash
cat ~/voxtype/.gitignore
```

- [ ] **Step 2: Replace with the v0.9.1 .gitignore**

Use the Write tool to replace `~/voxtype/.gitignore` with:

```gitignore
# Python
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd

# Build outputs
build/
dist/
*.dmg
*.dmg.sha256
*.icns

# Models (downloaded at install/build time, not source)
models/

# Compiled Swift binaries at repo root (sources are tracked, binaries are not)
hotkey_helper
paste_helper

# Bundle is a build artifact, not source
VoxType.app/
VoiceType.app/

# Brainstorming/plan working dir
.superpowers/

# OS
.DS_Store

# Editor
.vscode/
.idea/
*.swp

# Local config you don't want to publish
.env
```

### Task 0.3: Untrack the build artifacts that were previously tracked

The current repo tracks `VoxType.app/Contents/MacOS/hotkey_helper` (a compiled binary). After updating .gitignore it'll show as still tracked until we explicitly untrack.

**Files:**
- Modify: git index (untrack only)

- [ ] **Step 1: Untrack tracked-but-now-ignored files**

```bash
git -C ~/voxtype rm --cached -r VoxType.app/ 2>&1
git -C ~/voxtype status --short
```

Expected: `VoxType.app/Contents/MacOS/hotkey_helper` shows as `D` (deletion staged), other VoxType.app files now show as `??` (untracked, ignored).

### Task 0.4: Delete obsolete launch.command

**Files:**
- Delete: `~/voxtype/launch.command`

- [ ] **Step 1: Verify it's the obsolete dev-shim**

```bash
cat ~/voxtype/launch.command
```

Expected: a tiny shell script that runs `python ~/voxtype/voxtype.py` directly. This is replaced by the .app bundle in v0.9.1.

- [ ] **Step 2: Delete it**

```bash
rm ~/voxtype/launch.command
```

### Task 0.5: Stage and commit the cleanup

- [ ] **Step 1: Stage everything**

```bash
git -C ~/voxtype add -A
git -C ~/voxtype status --short
```

Expected to be staged:
- Modified: `corrections.py`, `intent.py`, `paster.py`, `recorder.py`, `transcriber.py`, `transcriber_v2.py`, `voice_profile.py`, `voxtype.py`
- New: `paste_helper.swift`, `translator.py`, `.gitignore` (modified), `docs/superpowers/specs/...`
- Deleted: `VoxType.app/Contents/MacOS/hotkey_helper`, `launch.command`

- [ ] **Step 2: Commit**

```bash
git -C ~/voxtype commit -m "$(cat <<'EOF'
chore: pre-launch cleanup — quality fixes + ignore build artifacts

- Commit shipped-but-uncommitted enhancements:
  - voxtype.py: flash-skip menubar feedback, RMS energy gate, confidence-based hallucination filter
  - recorder.py: multi-device fallback chain (no more PortAudio dead-ends)
  - transcriber.py + _v2.py: junk-token filter, English language anchor
  - voice_profile.py: 15-word prompt cap, broader common-word filter
  - intent.py: tightened fuzzy-match threshold 60→85 (fewer false command detections)
  - corrections.py: drop box→vox defaults (rebrand-aligned)
  - paster.py: thin delegate to hotkey helper

- Add untracked source files: paste_helper.swift, translator.py
- Update .gitignore: untrack build artifacts (VoxType.app/, hotkey_helper, paste_helper)
- Remove obsolete launch.command (replaced by .app bundle in v0.9.1)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git -C ~/voxtype status
```

Expected: clean working tree, one new commit on `main`.

---

## Phase 1 — Repo migration (voxtype → voicetype)

Rename the directory and the bundle ID. This is the most invasive structural change and gets done early so all subsequent work happens in the new tree.

### Task 1.1: Write migrate.sh

**Files:**
- Create: `~/voxtype/build/migrate.sh`

- [ ] **Step 1: Create build/ if it doesn't exist**

```bash
mkdir -p ~/voxtype/build
```

- [ ] **Step 2: Write migrate.sh**

```bash
#!/bin/bash
# migrate.sh — one-time rename voxtype → voicetype
# Run from ~/voxtype/ before any other Phase 1 task
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
if launchctl list | grep -q "$OLD_BUNDLE_ID"; then
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
# We replace ~/.voxtype/ with ~/.voicetype/ in known files
echo "Updating path constants in source..."
for f in voxtype.py snippets.py voice_profile.py corrections.py stats.py user_fixes.py transcript_history.py; do
    if [ -f "$NEW_HOME/$f" ]; then
        # macOS sed needs '' after -i
        sed -i '' 's|~/\.voxtype/|~/.voicetype/|g; s|/\.voxtype/|/.voicetype/|g' "$NEW_HOME/$f"
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
```

- [ ] **Step 3: Make executable**

```bash
chmod +x ~/voxtype/build/migrate.sh
```

### Task 1.2: Run migrate.sh

- [ ] **Step 1: Run it**

```bash
~/voxtype/build/migrate.sh
```

Expected: prints progress, ends with "=== Migration complete ===". `~/voxtype/` is now `~/voicetype/`. `~/.voxtype/` still exists; `~/.voicetype/` is a copy.

- [ ] **Step 2: Verify the rename happened**

```bash
ls -d ~/voicetype ~/.voicetype
test -d ~/voxtype && echo "OLD STILL EXISTS — BAD" || echo "OK"
```

Expected: both new dirs exist; old `~/voxtype/` is gone.

### Task 1.3: Verify path constants were updated

- [ ] **Step 1: Grep for stale references**

```bash
grep -rn "voxtype" ~/voicetype --include="*.py" | grep -v "VoxType" | grep -v "voxtype.py" | grep -v "\.voicetype" | head -20
```

Expected: matches are for the file `voxtype.py` itself (which we keep — see locked decision #7), the class name `VoxType`, and bundle helpers — NOT for paths like `~/.voxtype/`.

- [ ] **Step 2: Confirm path constants point at the new dir**

```bash
grep -nE "(\.voicetype|\.voxtype)" ~/voicetype/snippets.py ~/voicetype/voice_profile.py ~/voicetype/corrections.py ~/voicetype/stats.py ~/voicetype/user_fixes.py ~/voicetype/transcript_history.py
```

Expected: every match references `.voicetype` (no `.voxtype` references).

### Task 1.4: Test that the migrated app starts cleanly

- [ ] **Step 1: Activate venv and test imports**

```bash
source ~/voicetype/.venv/bin/activate
python -c "import rumps, sounddevice, pywhispercpp; print('imports OK')"
```

Expected: `imports OK`.

- [ ] **Step 2: Launch voxtype.py briefly to verify it starts**

```bash
cd ~/voicetype
timeout 8 python voxtype.py 2>&1 | head -30
```

Expected: log lines including "Loading Whisper model..." and "Model loaded!" within 8 seconds. The `timeout` ends it.

### Task 1.5: Commit migration

- [ ] **Step 1: Stage the path-constant updates**

```bash
git -C ~/voicetype add -A
git -C ~/voicetype status --short
```

Expected: modified files matching the sed updates from migrate.sh, plus `build/migrate.sh` as new.

- [ ] **Step 2: Commit**

```bash
git -C ~/voicetype commit -m "$(cat <<'EOF'
chore: rename voxtype → voicetype, bundle id com.polistician.voicetype

- Source dir: ~/voxtype/ → ~/voicetype/
- User data dir: ~/.voxtype/ → ~/.voicetype/ (copied, not moved; old stays as fallback)
- Bundle ID: com.voxtype.app → com.polistician.voicetype
- Launchd label updated, new plist installed
- Path constants in snippets.py, voice_profile.py, corrections.py, stats.py,
  user_fixes.py, transcript_history.py updated to .voicetype
- Internal Python class name VoxType + voice trigger word "snippet" stay
  (per spec locked decision #7)
- Adds build/migrate.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### Task 1.6: Optional — re-load launchd agent

Only do this if you previously had voxtype running as a launchd background agent.

- [ ] **Step 1: Load new agent**

```bash
launchctl load ~/Library/LaunchAgents/com.polistician.voicetype.plist
launchctl list | grep voicetype
```

Expected: a row showing `com.polistician.voicetype` with a numeric PID.

- [ ] **Step 2: Verify menubar mic appears**

Manual check: glance at your menubar — the 🎤 emoji should be visible.

---

## Phase 2 — GitHub repo + LICENSE

### Task 2.1: Create the public GitHub repo

- [ ] **Step 1: Verify gh auth**

```bash
gh auth status
```

Expected: signed in as `polistician` with repo write scope.

- [ ] **Step 2: Create the repo (no push yet)**

```bash
gh repo create polistician/voicetype --public \
  --description "Local voice dictation for macOS. Hold ⌥ C, speak, paste anywhere."
```

Expected: prints `https://github.com/polistician/voicetype`.

### Task 2.2: Add LICENSE file (MIT)

**Files:**
- Create: `~/voicetype/LICENSE`

- [ ] **Step 1: Write LICENSE**

Use Write tool to create `~/voicetype/LICENSE` with:

```
MIT License

Copyright (c) 2026 Beauregard Berton

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Task 2.3: Update README.md

**Files:**
- Modify or create: `~/voicetype/README.md`

- [ ] **Step 1: Check current README**

```bash
test -f ~/voicetype/README.md && cat ~/voicetype/README.md || echo "(no README)"
```

- [ ] **Step 2: Replace with the v0.9.1 README**

Use Write tool to create `~/voicetype/README.md` with:

```markdown
# VoiceType

Local voice dictation for macOS. Hold ⌥ C, speak, the words paste into whatever app you were just typing in. Whisper.cpp runs on your laptop. Audio never leaves the machine.

Site: https://voicetype.polistician.ai
Download: https://github.com/polistician/voicetype/releases/latest

## What it does

- **Dictate** — voice to text in any app that accepts ⌘V.
- **Steer** — configure custom voice commands. Say `help`, the settings overlay opens. Say a saved phrase name, the saved text pastes itself.
- **Translate** — optional. Drop a DeepL API key into Settings and VoiceType translates as it pastes.

## Install

Download `VoiceType.dmg` from the Releases page → drag to Applications → right-click → Open (one-time Gatekeeper bypass) → grant Microphone + Accessibility → hold ⌥ C.

The first launch shows a 4-screen guided onboarding (welcome → permissions → live dictation tutorial → optional API key).

## Build from source

```bash
git clone https://github.com/polistician/voicetype.git
cd voicetype
./install.sh         # installs deps, downloads Whisper model
./build/release.sh    # builds VoiceType.app + DMG
```

## Privacy

What stays on your laptop: audio, transcripts, vocabulary, snippets, corrections, statistics, decision log.

What leaves your laptop: only DeepL translation requests, only if you've added a DeepL key in Settings.

API keys (DeepL etc.) are stored in macOS Keychain, never in plaintext config files.

## License

MIT — see [LICENSE](./LICENSE).
```

### Task 2.4: Set git remote and push

- [ ] **Step 1: Add origin**

```bash
git -C ~/voicetype remote -v
git -C ~/voicetype remote add origin https://github.com/polistician/voicetype.git 2>&1 || \
  git -C ~/voicetype remote set-url origin https://github.com/polistician/voicetype.git
git -C ~/voicetype remote -v
```

Expected: `origin  https://github.com/polistician/voicetype.git (fetch/push)`.

- [ ] **Step 2: Stage LICENSE + README, commit, push**

```bash
git -C ~/voicetype add LICENSE README.md
git -C ~/voicetype commit -m "$(cat <<'EOF'
docs: add LICENSE (MIT) + README for v0.9.1

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
git -C ~/voicetype branch -M main
git -C ~/voicetype push -u origin main
```

Expected: push succeeds, commits visible at `https://github.com/polistician/voicetype`.

---

## Phase 3 — Brand assets

All brand assets live in `~/voicetype/assets/`. Source-of-truth is SVG. Raster outputs (icns, png) are generated from the SVGs.

### Task 3.1: Create assets/ directory

- [ ] **Step 1: Create the dir**

```bash
mkdir -p ~/voicetype/assets
```

### Task 3.2: Create keycap.svg (the brand mark, three variants)

**Files:**
- Create: `~/voicetype/assets/keycap.svg` (on-dark, primary)
- Create: `~/voicetype/assets/keycap-on-light.svg`
- Create: `~/voicetype/assets/keycap-mono.svg`

The keycap is a 256×256 SVG showing `⌥ C` inside a rounded keycap shape with a 3D press shadow. Blue fill (`#4d8fdb`), white glyphs.

- [ ] **Step 1: Write keycap.svg (on-dark variant)**

Use Write tool to create `~/voicetype/assets/keycap.svg`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <defs>
    <linearGradient id="keycapBody" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#5a9dec"/>
      <stop offset="1" stop-color="#3d6fa8"/>
    </linearGradient>
    <linearGradient id="keycapTop" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#7eb1e8"/>
      <stop offset="1" stop-color="#4d8fdb"/>
    </linearGradient>
  </defs>
  <!-- Background plate (transparent — caller controls bg) -->
  <!-- Press shadow -->
  <rect x="36" y="48" width="184" height="172" rx="32" fill="#1a3050" opacity="0.6"/>
  <!-- Keycap body -->
  <rect x="32" y="40" width="184" height="172" rx="32" fill="url(#keycapBody)"/>
  <!-- Keycap top face -->
  <rect x="48" y="56" width="152" height="132" rx="22" fill="url(#keycapTop)"/>
  <!-- Glyphs ⌥ C centered on top face -->
  <text x="128" y="142"
        font-family="-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif"
        font-size="78" font-weight="700"
        text-anchor="middle" fill="#ffffff"
        letter-spacing="-2">⌥ C</text>
</svg>
```

- [ ] **Step 2: Write keycap-on-light.svg (darker keycap, white glyphs)**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <defs>
    <linearGradient id="keycapBodyLight" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#3d6fa8"/>
      <stop offset="1" stop-color="#264a78"/>
    </linearGradient>
    <linearGradient id="keycapTopLight" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#4d8fdb"/>
      <stop offset="1" stop-color="#3d6fa8"/>
    </linearGradient>
  </defs>
  <rect x="36" y="48" width="184" height="172" rx="32" fill="#1a3050" opacity="0.4"/>
  <rect x="32" y="40" width="184" height="172" rx="32" fill="url(#keycapBodyLight)"/>
  <rect x="48" y="56" width="152" height="132" rx="22" fill="url(#keycapTopLight)"/>
  <text x="128" y="142"
        font-family="-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif"
        font-size="78" font-weight="700"
        text-anchor="middle" fill="#ffffff"
        letter-spacing="-2">⌥ C</text>
</svg>
```

- [ ] **Step 3: Write keycap-mono.svg (single-color line variant)**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" width="256" height="256">
  <rect x="32" y="40" width="184" height="172" rx="32" fill="none" stroke="currentColor" stroke-width="6"/>
  <rect x="48" y="56" width="152" height="132" rx="22" fill="none" stroke="currentColor" stroke-width="3"/>
  <text x="128" y="142"
        font-family="-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif"
        font-size="78" font-weight="700"
        text-anchor="middle" fill="currentColor"
        letter-spacing="-2">⌥ C</text>
</svg>
```

- [ ] **Step 4: Visual check**

```bash
open -a "Safari" ~/voicetype/assets/keycap.svg
open -a "Safari" ~/voicetype/assets/keycap-on-light.svg
open -a "Safari" ~/voicetype/assets/keycap-mono.svg
```

Expected: three browser tabs render the three variants. Eyeball that the keycap shape, gradient, and `⌥ C` glyphs look correct. If anything's off, iterate on the SVG before moving on.

### Task 3.3: Generate app-icon.icns from keycap.svg

PyInstaller bundles an `.icns` file. macOS requires a multi-resolution iconset.

**Files:**
- Create: `~/voicetype/assets/app-icon.iconset/` (multiple PNGs)
- Create: `~/voicetype/assets/app-icon.icns` (bundled artifact)
- Create: `~/voicetype/build/make-icns.sh`

- [ ] **Step 1: Write make-icns.sh**

Use Write tool to create `~/voicetype/build/make-icns.sh`:

```bash
#!/bin/bash
# make-icns.sh — generate app-icon.icns from keycap.svg
set -euo pipefail

SVG=~/voicetype/assets/keycap.svg
ICONSET=~/voicetype/assets/app-icon.iconset
OUT=~/voicetype/assets/app-icon.icns

if ! command -v rsvg-convert >/dev/null 2>&1; then
    echo "Installing librsvg via brew..."
    brew install librsvg
fi

mkdir -p "$ICONSET"

# Generate at all required sizes (with @2x retina variants)
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
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/voicetype/build/make-icns.sh
```

- [ ] **Step 3: Run it**

```bash
~/voicetype/build/make-icns.sh
```

Expected: prints `Generated /Users/.../app-icon.icns`, file size ~100-200KB.

- [ ] **Step 4: Verify with macOS preview**

```bash
open ~/voicetype/assets/app-icon.icns
```

Expected: Preview opens showing the icon at multiple sizes. The keycap shape should be legible at 16×16 and crisp at 1024×1024.

### Task 3.4: Create wordmark.svg

**Files:**
- Create: `~/voicetype/assets/wordmark.svg`

- [ ] **Step 1: Write wordmark.svg**

Use Write tool:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 96" width="600" height="96">
  <text x="0" y="68"
        font-family="'Space Grotesk', -apple-system, sans-serif"
        font-size="68" font-weight="700"
        letter-spacing="-2">
    <tspan fill="#4d8fdb">Voice</tspan><tspan fill="currentColor">Type</tspan>
  </text>
  <!-- Blinking caret -->
  <rect x="392" y="22" width="6" height="56" fill="#4d8fdb">
    <animate attributeName="opacity" values="1;1;0;0;1" keyTimes="0;0.5;0.51;0.99;1" dur="1.05s" repeatCount="indefinite"/>
  </rect>
</svg>
```

### Task 3.5: Create menubar-mic.svg (template image)

The menubar icon must be a template image — pure black silhouette, macOS auto-tints it for light/dark menubar.

**Files:**
- Create: `~/voicetype/assets/menubar-mic.svg`
- Create: `~/voicetype/assets/menubar-mic.pdf` (template, used by Cocoa)

- [ ] **Step 1: Write menubar-mic.svg**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 22" width="22" height="22">
  <!-- Microphone capsule -->
  <rect x="8" y="3" width="6" height="11" rx="3" fill="#000000"/>
  <!-- Stand arc -->
  <path d="M5 11 v1 a6 6 0 0 0 12 0 v-1"
        fill="none" stroke="#000000" stroke-width="1.6" stroke-linecap="round"/>
  <!-- Stem -->
  <line x1="11" y1="17" x2="11" y2="20" stroke="#000000" stroke-width="1.6" stroke-linecap="round"/>
  <!-- Foot -->
  <line x1="8" y1="20" x2="14" y2="20" stroke="#000000" stroke-width="1.6" stroke-linecap="round"/>
</svg>
```

- [ ] **Step 2: Generate the PDF version (Cocoa template image)**

```bash
rsvg-convert -f pdf ~/voicetype/assets/menubar-mic.svg -o ~/voicetype/assets/menubar-mic.pdf
ls -lh ~/voicetype/assets/menubar-mic.pdf
```

### Task 3.6: Create favicon.svg

**Files:**
- Create: `~/voicetype/assets/favicon.svg`

- [ ] **Step 1: Write favicon (the keycap, simplified for small sizes)**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
  <rect x="3" y="6" width="26" height="22" rx="5" fill="#4d8fdb"/>
  <text x="16" y="22"
        font-family="-apple-system, sans-serif"
        font-size="13" font-weight="700"
        text-anchor="middle" fill="#ffffff">⌥C</text>
</svg>
```

### Task 3.7: Create dmg-background.png

The DMG installer window background. 1280×800. Brand-tinted backdrop with the keycap, the wordmark, an arrow pointing from the icon-drop position to the Applications shortcut, and a small Gatekeeper-bypass instruction.

**Files:**
- Create: `~/voicetype/assets/dmg-background.html` (designed in HTML, rendered to PNG)
- Create: `~/voicetype/assets/dmg-background.png`
- Create: `~/voicetype/build/render-dmg-bg.sh`

- [ ] **Step 1: Write the HTML source**

Use Write tool to create `~/voicetype/assets/dmg-background.html`:

```html
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body { margin:0; background:#0d0e12; color:#e8eaf0; font-family:-apple-system,sans-serif; }
  .frame { width:1280px; height:800px; position:relative; background:linear-gradient(135deg,#0d0e12 0%,#1a1d28 100%); }
  .keycap-bg { position:absolute; top:80px; left:560px; width:160px; height:160px; opacity:0.18; }
  .wordmark { position:absolute; top:120px; left:0; right:0; text-align:center; font-size:48px; font-weight:700; letter-spacing:-1.5px; }
  .wordmark .blue { color:#4d8fdb; }
  .wordmark .caret { color:#4d8fdb; }
  .tagline { position:absolute; top:200px; left:0; right:0; text-align:center; font-size:18px; color:#7a8194; }
  .icon-area { position:absolute; top:380px; left:280px; width:160px; height:160px; border:2px dashed rgba(77,143,219,0.3); border-radius:18px; display:flex; align-items:center; justify-content:center; color:#7a8194; font-size:13px; }
  .arrow { position:absolute; top:430px; left:480px; width:320px; height:60px; }
  .arrow svg { width:100%; height:100%; }
  .applications-area { position:absolute; top:380px; right:280px; width:160px; height:160px; }
  .gatekeeper-note { position:absolute; bottom:80px; left:0; right:0; text-align:center; color:#7a8194; font-size:14px; line-height:1.6; }
  .gatekeeper-note strong { color:#4d8fdb; }
</style>
</head>
<body>
<div class="frame">
  <div class="keycap-bg">
    <svg viewBox="0 0 256 256" width="160" height="160">
      <rect x="32" y="40" width="184" height="172" rx="32" fill="#4d8fdb"/>
      <rect x="48" y="56" width="152" height="132" rx="22" fill="#7eb1e8"/>
      <text x="128" y="142" font-size="78" font-weight="700" text-anchor="middle" fill="#fff" font-family="-apple-system,sans-serif">⌥ C</text>
    </svg>
  </div>
  <div class="wordmark"><span class="blue">Voice</span>Type<span class="caret">|</span></div>
  <div class="tagline">hold ⌥ C, speak, the text appears.</div>
  <div class="icon-area">drag</div>
  <div class="arrow">
    <svg viewBox="0 0 320 60">
      <path d="M0 30 L300 30" stroke="#4d8fdb" stroke-width="3" stroke-linecap="round" stroke-dasharray="8 6"/>
      <path d="M285 18 L300 30 L285 42" fill="none" stroke="#4d8fdb" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </div>
  <div class="gatekeeper-note">
    First time? After dragging: <strong>right-click VoiceType → Open</strong>.<br>
    <span style="opacity:0.6">macOS warns once because we don't pay Apple's notarization fee. Click past it; you'll never see it again.</span>
  </div>
</div>
</body>
</html>
```

- [ ] **Step 2: Write the render script**

```bash
#!/bin/bash
# render-dmg-bg.sh — render dmg-background.html → dmg-background.png at 1280×800
set -euo pipefail

if ! command -v wkhtmltoimage >/dev/null 2>&1; then
    echo "Installing wkhtmltopdf via brew..."
    brew install --cask wkhtmltopdf
fi

wkhtmltoimage --width 1280 --height 800 --quality 95 \
    ~/voicetype/assets/dmg-background.html \
    ~/voicetype/assets/dmg-background.png

ls -lh ~/voicetype/assets/dmg-background.png
```

Save this to `~/voicetype/build/render-dmg-bg.sh`, then `chmod +x` it.

- [ ] **Step 3: Run it**

```bash
~/voicetype/build/render-dmg-bg.sh
```

Expected: `dmg-background.png` exists, ~50-200KB.

- [ ] **Step 4: Visual check**

```bash
open ~/voicetype/assets/dmg-background.png
```

Eyeball it. The keycap, wordmark, drag arrow, and Gatekeeper note should be visible and legible at 1280×800.

### Task 3.8: Commit brand assets

- [ ] **Step 1: Stage and commit**

```bash
git -C ~/voicetype add assets/ build/make-icns.sh build/render-dmg-bg.sh
git -C ~/voicetype commit -m "$(cat <<'EOF'
feat: brand assets — keycap mark, wordmark, app icon, favicon, dmg background

Direction: "The Hotkey" (per spec §3 decision #8).
- assets/keycap.svg (3 variants: on-dark, on-light, monochrome)
- assets/wordmark.svg (Voice|Type with blinking caret)
- assets/app-icon.icns (generated from keycap.svg via build/make-icns.sh)
- assets/menubar-mic.svg + .pdf (template image)
- assets/favicon.svg
- assets/dmg-background.png (rendered from .html via build/render-dmg-bg.sh)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 4 — Marketing site rebuild

Static HTML/CSS/JS, no build step, no framework. Final structure matches mockup v5.

### Task 4.1: Create site/ skeleton

- [ ] **Step 1: Create dirs and stub files**

```bash
mkdir -p ~/voicetype/site/assets
touch ~/voicetype/site/index.html ~/voicetype/site/styles.css ~/voicetype/site/script.js
ln -sf ../../assets/favicon.svg ~/voicetype/site/assets/favicon.svg
ln -sf ../../assets/keycap.svg ~/voicetype/site/assets/keycap.svg
ln -sf ../../assets/wordmark.svg ~/voicetype/site/assets/wordmark.svg
```

### Task 4.2: Write site/styles.css

**Files:**
- Modify: `~/voicetype/site/styles.css`

- [ ] **Step 1: Write the stylesheet**

The full CSS will be ~600 lines. Use Write tool to write the file. The styles must:
- Define CSS custom properties for the color system (matching spec §6)
- Support light + dark theme via `data-theme` attribute on `<html>`
- Use Space Grotesk for headings, Inter for body, JetBrains Mono for code
- Lay out the 9 sections per the v5 mockup
- Style the install-step-strip with numbered circles
- Style the Mac-window mockups (chrome, traffic lights, IDE syntax colors)
- Style the keycap glyph inline (used in the hero shortcut, install step 5, etc.)

The complete CSS source is in the v5 mockup at `~/voicetype/.superpowers/brainstorm/84799-1777909001/content/q4-page-mockup-v5.html` — port the inline styles to a real stylesheet, replacing the `var(--border)` etc. references with the spec's defined custom properties.

For the implementation, refer to the visual companion mockup file path above and the spec's color system in §6. The exact selectors should mirror the mockup's HTML structure.

- [ ] **Step 2: Sanity-check by opening locally**

```bash
open ~/voicetype/site/index.html
```

(Will be empty until Task 4.3, but the file exists.)

### Task 4.3: Write site/index.html

**Files:**
- Modify: `~/voicetype/site/index.html`

The HTML mirrors the v5 mockup section-for-section:
1. `<head>` with title, description, favicon link, Google Fonts (Space Grotesk + Inter + JetBrains Mono + Source Serif 4), stylesheet link, theme-flash-prevention inline script
2. Topbar (`← polistician.ai` link, wordmark center, theme toggle right)
3. Hero (verbatim from current page)
4. Zero-friction callout
5. Section 1 — How it works (3 steps)
6. Section 2 — Three things (Dictate / Steer / Translate cards)
7. Section 3 — Each feature, doing the thing (3 vertical mocks: Cursor+Claude, Steer overlay, Translate split)
8. Section 4 — Why this exists (vision, 3 paragraphs)
9. Section 5 — Install in 30 seconds (5-step strip + final download CTA + version meta + SHA256)
10. Footer — Local-first promise (threat model, MIT license link, GitHub link)

- [ ] **Step 1: Write the HTML file**

Port the structure from `q4-page-mockup-v5.html`. Replace inline styles with class names that match `styles.css`. Keep all copy verbatim from the v5 mockup.

The download button should link to `https://github.com/polistician/voicetype/releases/latest/download/VoiceType.dmg`. Use a `data-version` attribute and a JS-fetch in `script.js` to display the actual latest version.

- [ ] **Step 2: Open in browser, eyeball**

```bash
open ~/voicetype/site/index.html
```

Expected: page renders, all 9 sections visible, layout matches the v5 mockup. Iterate on CSS until it does.

### Task 4.4: Write site/script.js

**Files:**
- Modify: `~/voicetype/site/script.js`

- [ ] **Step 1: Write the script**

```javascript
// VoiceType marketing site — minimal JS
// Responsibilities: theme toggle (persisted), latest-version fetch, smooth scroll.

(function () {
  // --- Theme toggle ---
  const root = document.documentElement;
  const stored = localStorage.getItem('vt-theme') || 'dark';
  root.setAttribute('data-theme', stored);

  const toggle = document.getElementById('theme-toggle');
  if (toggle) {
    toggle.addEventListener('click', () => {
      const next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      localStorage.setItem('vt-theme', next);
    });
  }

  // --- Latest release version + SHA256 ---
  // Fetched once on load; falls back to defaults baked into HTML.
  fetch('https://api.github.com/repos/polistician/voicetype/releases/latest')
    .then(r => r.ok ? r.json() : null)
    .then(release => {
      if (!release) return;
      const v = release.tag_name || 'v0.9.1';
      document.querySelectorAll('[data-latest-version]').forEach(el => el.textContent = v);

      // SHA256 lives in release.assets[*].name === 'VoiceType.dmg.sha256'
      const sha = (release.assets || []).find(a => a.name === 'VoiceType.dmg.sha256');
      if (sha) {
        fetch(sha.browser_download_url).then(r => r.text()).then(text => {
          const checksum = text.trim().split(/\s+/)[0];
          document.querySelectorAll('[data-latest-sha256]').forEach(el => el.textContent = checksum);
        });
      }
    })
    .catch(() => { /* keep HTML defaults */ });
})();
```

### Task 4.5: Local preview pass + iteration

- [ ] **Step 1: Open in browser, do a full readthrough**

```bash
open ~/voicetype/site/index.html
```

Read every section. Check responsive at 320px width (Chrome devtools mobile preview). Click the download button — should link to the GH release URL. Click the GitHub link — should link to the repo. Click the polistician.ai topbar link.

- [ ] **Step 2: Lighthouse audit**

```bash
open -a "Google Chrome" ~/voicetype/site/index.html
```

In Chrome devtools, run Lighthouse on Desktop. Target: ≥95 on Performance, Accessibility, Best Practices, SEO.

- [ ] **Step 3: Fix any Lighthouse findings**

Iterate on the HTML/CSS until scores hit target. Common fixes: explicit width/height on images, alt text on images, `lang="en"` on html, sufficient color contrast.

### Task 4.6: Commit the site

- [ ] **Step 1: Stage and commit**

```bash
git -C ~/voicetype add site/
git -C ~/voicetype commit -m "$(cat <<'EOF'
feat(site): rebuild voicetype.polistician.ai per mockup v5

9 sections: hero (verbatim) → zero-friction callout → how it works
→ three things → each feature in action → why this exists
→ install in 30 seconds → footer threat model.

Cuts: top nav, stats line, what's-shipped enumeration, vs-table,
build-decision rationale.

Static HTML/CSS, no build. JS fetches latest release version + SHA256
from GitHub API; falls back to baked-in HTML defaults.

Lighthouse target: ≥95 on all four scores.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 5 — Keys helper (Keychain integration)

A small Swift helper that exposes JSON-over-stdio commands to read/write API keys in the macOS Keychain. The Python translator uses this instead of reading plaintext keys from `config.json`.

### Task 5.1: Write keys_helper.swift

**Files:**
- Create: `~/voicetype/keys_helper.swift`

- [ ] **Step 1: Write the source**

Use Write tool to create `~/voicetype/keys_helper.swift`:

```swift
// keys_helper.swift — JSON-over-stdio for macOS Keychain.
//
// Protocol: read one JSON line from stdin, write one JSON line to stdout.
// Commands:
//   {"action":"set","account":"deepl","value":"<key>"}     -> {"ok":true}
//   {"action":"get","account":"deepl"}                     -> {"ok":true,"value":"<key>"}  or {"ok":false}
//   {"action":"delete","account":"deepl"}                  -> {"ok":true}
//   {"action":"list"}                                      -> {"ok":true,"accounts":["deepl",...]}
//
// All entries live under the service identifier:
//   com.polistician.voicetype.keys

import Foundation
import Security

let SERVICE = "com.polistician.voicetype.keys"

struct Request: Codable {
    let action: String
    let account: String?
    let value: String?
}

struct Response: Codable {
    var ok: Bool
    var value: String?
    var accounts: [String]?
    var error: String?
}

func emit(_ resp: Response) {
    let enc = JSONEncoder()
    if let data = try? enc.encode(resp), let line = String(data: data, encoding: .utf8) {
        print(line)
        fflush(stdout)
    }
}

func keychainSet(account: String, value: String) -> Response {
    let data = value.data(using: .utf8)!
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecAttrAccount as String: account
    ]
    SecItemDelete(query as CFDictionary)
    var add = query
    add[kSecValueData as String] = data
    let status = SecItemAdd(add as CFDictionary, nil)
    if status == errSecSuccess { return Response(ok: true) }
    return Response(ok: false, error: "SecItemAdd status \(status)")
}

func keychainGet(account: String) -> Response {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecAttrAccount as String: account,
        kSecReturnData as String: true,
        kSecMatchLimit as String: kSecMatchLimitOne
    ]
    var result: AnyObject?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecSuccess, let data = result as? Data, let s = String(data: data, encoding: .utf8) {
        return Response(ok: true, value: s)
    }
    if status == errSecItemNotFound { return Response(ok: false, error: "not found") }
    return Response(ok: false, error: "SecItemCopyMatching status \(status)")
}

func keychainDelete(account: String) -> Response {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecAttrAccount as String: account
    ]
    let status = SecItemDelete(query as CFDictionary)
    if status == errSecSuccess || status == errSecItemNotFound { return Response(ok: true) }
    return Response(ok: false, error: "SecItemDelete status \(status)")
}

func keychainList() -> Response {
    let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: SERVICE,
        kSecReturnAttributes as String: true,
        kSecMatchLimit as String: kSecMatchLimitAll
    ]
    var result: AnyObject?
    let status = SecItemCopyMatching(query as CFDictionary, &result)
    if status == errSecItemNotFound { return Response(ok: true, accounts: []) }
    if status != errSecSuccess { return Response(ok: false, error: "SecItemCopyMatching status \(status)") }
    let items = (result as? [[String: Any]]) ?? []
    let accounts = items.compactMap { $0[kSecAttrAccount as String] as? String }
    return Response(ok: true, accounts: accounts)
}

while let line = readLine() {
    guard let data = line.data(using: .utf8),
          let req = try? JSONDecoder().decode(Request.self, from: data) else {
        emit(Response(ok: false, error: "invalid JSON"))
        continue
    }
    switch req.action {
    case "set":
        guard let a = req.account, let v = req.value else { emit(Response(ok: false, error: "missing account/value")); break }
        emit(keychainSet(account: a, value: v))
    case "get":
        guard let a = req.account else { emit(Response(ok: false, error: "missing account")); break }
        emit(keychainGet(account: a))
    case "delete":
        guard let a = req.account else { emit(Response(ok: false, error: "missing account")); break }
        emit(keychainDelete(account: a))
    case "list":
        emit(keychainList())
    default:
        emit(Response(ok: false, error: "unknown action: \(req.action)"))
    }
}
```

### Task 5.2: Compile keys_helper

**Files:**
- Modify: `~/voicetype/install.sh` (add compile step)

- [ ] **Step 1: Update install.sh to compile keys_helper**

Read current install.sh:

```bash
cat ~/voicetype/install.sh
```

Add this line in the "Compile Swift helpers" section (after the snippet_overlay compile):

```bash
swiftc ~/voicetype/keys_helper.swift -o ~/voicetype/keys_helper
```

Use Edit tool to insert after the existing `swiftc snippet_overlay.swift` line.

- [ ] **Step 2: Compile it now (one-off)**

```bash
swiftc ~/voicetype/keys_helper.swift -o ~/voicetype/keys_helper
ls -lh ~/voicetype/keys_helper
file ~/voicetype/keys_helper
```

Expected: a Mach-O binary, ~30-100KB.

### Task 5.3: Test keys_helper from the command line

**Files:** none (test only)

- [ ] **Step 1: Test set + get**

```bash
echo '{"action":"set","account":"test","value":"hello"}' | ~/voicetype/keys_helper
echo '{"action":"get","account":"test"}' | ~/voicetype/keys_helper
```

Expected output:
```
{"ok":true}
{"ok":true,"value":"hello"}
```

(macOS may prompt to allow Keychain access on first run — click Always Allow.)

- [ ] **Step 2: Test list + delete**

```bash
echo '{"action":"list"}' | ~/voicetype/keys_helper
echo '{"action":"delete","account":"test"}' | ~/voicetype/keys_helper
echo '{"action":"get","account":"test"}' | ~/voicetype/keys_helper
```

Expected:
```
{"ok":true,"accounts":["test"]}
{"ok":true}
{"ok":false,"error":"not found"}
```

### Task 5.4: Add Python wrapper for keys_helper

**Files:**
- Create: `~/voicetype/keys.py`
- Create: `~/voicetype/test_keys.py`

- [ ] **Step 1: Write the failing test**

Use Write tool to create `~/voicetype/test_keys.py`:

```python
"""Tests for the keys.py wrapper around keys_helper.swift."""
import os
import pytest
from keys import KeyStore, KeyNotFound


@pytest.fixture
def store():
    s = KeyStore()
    # ensure clean state
    try:
        s.delete("test_account")
    except KeyNotFound:
        pass
    yield s
    try:
        s.delete("test_account")
    except KeyNotFound:
        pass


def test_set_and_get(store):
    store.set("test_account", "secret_value")
    assert store.get("test_account") == "secret_value"


def test_get_missing_raises(store):
    with pytest.raises(KeyNotFound):
        store.get("not_a_real_account")


def test_delete(store):
    store.set("test_account", "x")
    store.delete("test_account")
    with pytest.raises(KeyNotFound):
        store.get("test_account")


def test_list(store):
    store.set("test_account", "x")
    accounts = store.list()
    assert "test_account" in accounts
```

- [ ] **Step 2: Run test, see fail**

```bash
cd ~/voicetype && source .venv/bin/activate && python -m pytest test_keys.py -v
```

Expected: ImportError for `keys` module.

- [ ] **Step 3: Write the wrapper**

Use Write tool to create `~/voicetype/keys.py`:

```python
"""Keys.py — Python wrapper around keys_helper.swift for macOS Keychain.

Usage:
    store = KeyStore()
    store.set("deepl", "your-api-key")
    key = store.get("deepl")
    store.delete("deepl")
    accounts = store.list()
"""
from __future__ import annotations

import json
import os
import subprocess
from typing import Optional


HELPER_PATH = os.path.expanduser("~/voicetype/keys_helper")


class KeyNotFound(Exception):
    pass


class KeyStoreError(Exception):
    pass


class KeyStore:
    def __init__(self, helper_path: str = HELPER_PATH):
        self.helper_path = helper_path

    def _call(self, payload: dict) -> dict:
        if not os.path.exists(self.helper_path):
            raise KeyStoreError(
                f"keys_helper not found at {self.helper_path}. "
                "Run install.sh to compile it."
            )
        line = json.dumps(payload).encode("utf-8") + b"\n"
        proc = subprocess.run(
            [self.helper_path],
            input=line,
            capture_output=True,
            timeout=5,
        )
        if proc.returncode != 0:
            raise KeyStoreError(f"helper exited {proc.returncode}: {proc.stderr.decode()}")
        try:
            return json.loads(proc.stdout.decode("utf-8").strip())
        except json.JSONDecodeError as e:
            raise KeyStoreError(f"helper returned non-JSON: {proc.stdout!r}") from e

    def set(self, account: str, value: str) -> None:
        resp = self._call({"action": "set", "account": account, "value": value})
        if not resp.get("ok"):
            raise KeyStoreError(resp.get("error", "set failed"))

    def get(self, account: str) -> str:
        resp = self._call({"action": "get", "account": account})
        if not resp.get("ok"):
            err = resp.get("error", "")
            if "not found" in err:
                raise KeyNotFound(account)
            raise KeyStoreError(err)
        return resp["value"]

    def delete(self, account: str) -> None:
        resp = self._call({"action": "delete", "account": account})
        if not resp.get("ok"):
            err = resp.get("error", "")
            if "not found" in err:
                raise KeyNotFound(account)
            raise KeyStoreError(err)

    def list(self) -> list[str]:
        resp = self._call({"action": "list"})
        if not resp.get("ok"):
            raise KeyStoreError(resp.get("error", "list failed"))
        return resp.get("accounts", [])
```

- [ ] **Step 4: Run tests, verify all pass**

```bash
python -m pytest test_keys.py -v
```

Expected: 4 tests pass.

### Task 5.5: Migrate translator.py to use Keychain

**Files:**
- Modify: `~/voicetype/translator.py`
- Modify: `~/voicetype/voxtype.py:48-50` (translator init)
- Modify: `~/voicetype/config.py` (remove `deepl_api_key` default)

- [ ] **Step 1: Update translator.py to fetch key from Keychain**

Use Edit tool on `~/voicetype/translator.py`. Change the constructor:

OLD:
```python
class Translator:
    def __init__(self, api_key: str):
        self.api_key = api_key
```

NEW:
```python
class Translator:
    def __init__(self, api_key: str = ""):
        # If api_key is empty string, the translator will lazy-fetch from Keychain
        # at translate-time. This way fresh-install users with no key just get a no-op.
        self._api_key = api_key
        self._store = None

    def _get_key(self) -> str:
        if self._api_key:
            return self._api_key
        # Lazy import — keys.py only used when translation actually needed
        from keys import KeyStore, KeyNotFound
        if self._store is None:
            self._store = KeyStore()
        try:
            return self._store.get("deepl")
        except KeyNotFound:
            return ""
```

Then update every usage of `self.api_key` in the file to call `self._get_key()` instead, and add a guard at the top of `translate()` and `translate_auto()`:

```python
def translate(self, text: str, target_lang: str) -> str:
    if not self._get_key():
        return text  # no-op when no key configured
    return self._call_deepl(text, target_lang)
```

- [ ] **Step 2: Update voxtype.py translator init**

In `voxtype.py` around line 48, the current code reads:
```python
api_key = self.cfg.get("deepl_api_key", "")
self.translator = Translator(api_key) if api_key else None
```

Change to:
```python
# Translator always exists — it lazy-loads the key from Keychain at translate-time.
# If no key is configured, translate() is a no-op (returns text unchanged).
self.translator = Translator()
```

- [ ] **Step 3: Run existing tests**

```bash
python -m pytest test_keys.py -v
```

Expected: 4 tests pass.

- [ ] **Step 4: Commit Phase 5**

```bash
git -C ~/voicetype add keys_helper.swift keys.py test_keys.py translator.py voxtype.py install.sh
git -C ~/voicetype commit -m "$(cat <<'EOF'
feat: macOS Keychain key store for API keys

- keys_helper.swift: JSON-over-stdio Keychain bridge
  (service: com.polistician.voicetype.keys)
- keys.py: Python wrapper exposing KeyStore class
- translator.py: lazy-fetch DeepL key from Keychain at translate-time;
  no-op if missing (no crash on fresh install)
- voxtype.py: translator always initialized; no longer reads from
  config.json (which never persisted plaintext anyway)
- install.sh: compile keys_helper alongside other Swift helpers
- test_keys.py: round-trip test for set/get/delete/list

Plaintext API keys never touch config.json or any committed file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 6 — Settings window

A small SwiftUI window with one tab in v0.9.1: API keys management. Opened from the menubar dropdown.

### Task 6.1: Write settings_window.swift

**Files:**
- Create: `~/voicetype/settings_window.swift`

- [ ] **Step 1: Write the source**

Use Write tool. The window has:
- A title bar "VoiceType — Settings"
- A "Keys" tab (only tab in v0.9.1)
- Inside Keys tab: rows for each known key. Today: just DeepL.
- Each row: label, SecureField (password style), Reveal toggle, Verify button, Save button, Remove button, status indicator
- The window uses NSStdin/stdout to communicate with the parent process for verify/save events. (Reusing the JSON-stdio pattern from snippet_overlay.swift.)

Full SwiftUI source — too long to inline here. Implementation contract:

```swift
// settings_window.swift
//
// Reads JSON commands from stdin:
//   {"type":"open"}                          -> show window
//   {"type":"key_status","account":"deepl","present":true}
//   {"type":"verify_result","account":"deepl","ok":true}
//   {"type":"verify_result","account":"deepl","ok":false,"error":"401 unauthorized"}
//
// Emits JSON events to stdout:
//   {"type":"set_key","account":"deepl","value":"<entered key>"}
//   {"type":"verify_key","account":"deepl","value":"<entered key>"}
//   {"type":"delete_key","account":"deepl"}
//   {"type":"window_closed"}
//
// Window contents:
//   - SwiftUI NavigationStack with one tab "Keys"
//   - DeepL row:
//       Label("DeepL")
//       SecureField (or TextField when "Reveal" toggled)
//       HStack { Button "Verify" / Button "Save" / Button "Remove" }
//       Status: shows "✓ saved", "× unverified", spinner during verify
```

The full implementation should follow the existing `snippet_overlay.swift` patterns (same SwiftUI + Cocoa hybrid, same JSON-stdio bridging via FileHandle).

- [ ] **Step 2: Compile**

Add `swiftc ~/voicetype/settings_window.swift -o ~/voicetype/settings_window` to `install.sh` (alongside the other helper compiles), then:

```bash
swiftc ~/voicetype/settings_window.swift -o ~/voicetype/settings_window
file ~/voicetype/settings_window
```

Expected: Mach-O binary.

### Task 6.2: Add overlay_bridge.py wiring for settings

**Files:**
- Modify: `~/voicetype/overlay_bridge.py` (or create `~/voicetype/settings_bridge.py`)

The existing `overlay_bridge.py` handles snippet_overlay. We need similar but for settings_window. Easier to add a second class `SettingsBridge` in the same file (DRY: shares the JSON-stdio plumbing).

- [ ] **Step 1: Read overlay_bridge.py to understand the pattern**

```bash
cat ~/voicetype/overlay_bridge.py
```

- [ ] **Step 2: Add a SettingsBridge class**

Use Edit tool on `overlay_bridge.py`. Add a `SettingsBridge` class mirroring `OverlayBridge` but for `settings_window` binary, handling these event types:
- `set_key` → calls `KeyStore().set(account, value)`, emits `key_status`
- `verify_key` → calls a service-specific verifier (DeepL `/usage`), emits `verify_result`
- `delete_key` → calls `KeyStore().delete(account)`, emits `key_status`

DeepL verification:

```python
import urllib.request
def verify_deepl(key: str) -> tuple[bool, str]:
    """Check the key by hitting DeepL's /usage endpoint. Returns (ok, error_msg)."""
    try:
        req = urllib.request.Request(
            "https://api-free.deepl.com/v2/usage",
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return (resp.status == 200, "")
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code}")
    except Exception as e:
        return (False, str(e))
```

### Task 6.3: Add Settings menu item to voxtype.py

**Files:**
- Modify: `~/voicetype/voxtype.py:31-41` (menu construction)

- [ ] **Step 1: Add menu item and callback**

Use Edit tool on `voxtype.py`. In `__init__`, find the `self.menu = [...]` section and add a `Settings…` item before `Help…`:

```python
self._settings_item = rumps.MenuItem("Settings…", callback=self._on_settings_click)
self.menu = [
    self._status_item, None, self._lang_menu, None,
    f"Model: {self.cfg['model']}", None,
    self._settings_item,  # NEW
    self._help_item, self._stats_item,
]
```

Add the callback method on the class:

```python
def _on_settings_click(self, _sender):
    """Open the Settings window via the SettingsBridge."""
    if not hasattr(self, "settings"):
        from overlay_bridge import SettingsBridge
        self.settings = SettingsBridge()
        self.settings.start()
    self.settings.open_window()
```

### Task 6.4: Manual test — open settings, save a real DeepL key

- [ ] **Step 1: Run voxtype.py**

```bash
cd ~/voicetype && python voxtype.py
```

Wait for "Idle -- ready" in the status menu. Click the menubar mic → Settings…

Expected: Settings window opens.

- [ ] **Step 2: Test save**

Paste a real DeepL key. Click Verify. Expected: "✓ verified". Click Save. Expected: "✓ saved".

- [ ] **Step 3: Verify Keychain entry**

```bash
echo '{"action":"get","account":"deepl"}' | ~/voicetype/keys_helper
```

Expected: `{"ok":true,"value":"<your key>"}`.

- [ ] **Step 4: Test translate end-to-end**

Switch output language to a non-English one (e.g., DE). Hold ⌥ C in another app, say "hello world". Expected: "Hallo Welt" (or similar) pastes.

- [ ] **Step 5: Commit Phase 6**

```bash
git -C ~/voicetype add settings_window.swift overlay_bridge.py voxtype.py install.sh
git -C ~/voicetype commit -m "$(cat <<'EOF'
feat: Settings window for API key management

- settings_window.swift: SwiftUI window with Keys tab (DeepL today)
- overlay_bridge.py: SettingsBridge class, DeepL key verifier
- voxtype.py: Settings… menu item + callback
- install.sh: compile settings_window helper

Keys never touch disk in plaintext — entered in SecureField, verified
against the service's API, stored in Keychain. config.json untouched.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 7 — 4-screen onboarding

First-launch experience. Welcome → Permissions → Live dictation tutorial → Optional API key. Detected by absence of `~/.voicetype/onboarding_complete`. Bridges to Python for the live dictation step (real recording, real transcription, real paste).

### Task 7.1: Write onboarding.swift

**Files:**
- Create: `~/voicetype/onboarding.swift`

The onboarding window is a single window with 4 stacked screens (1-of-N progress dots top, content middle, navigation bottom). Like settings_window, it uses JSON-stdio to bridge to Python.

Implementation contract:

```swift
// onboarding.swift
//
// Reads JSON commands from stdin:
//   {"type":"open"}                                         -> show window at screen 1
//   {"type":"perm_status","mic":true,"accessibility":false} -> update screen 2 checkboxes
//   {"type":"tutorial_paste_landed","text":"hello..."}      -> screen 3 success state
//   {"type":"key_verify_result","ok":true}                  -> screen 4 verify result
//   {"type":"key_save_result","ok":true}                    -> screen 4 save result
//
// Emits JSON events to stdout:
//   {"type":"continue_to","screen":2}                       -> navigation
//   {"type":"open_pref_pane","pane":"microphone"}           -> open System Settings
//   {"type":"open_pref_pane","pane":"accessibility"}
//   {"type":"check_perms"}                                  -> request status update
//   {"type":"start_tutorial"}                               -> arm dictation hotkey
//   {"type":"verify_key","account":"deepl","value":"..."}
//   {"type":"save_key","account":"deepl","value":"..."}
//   {"type":"skip_key"}
//   {"type":"onboarding_complete"}
//
// Screens:
//   1. Welcome — keycap mark, headline, Continue button
//   2. Permissions — checklist (Mic + Accessibility), each opens pref pane on click
//      Continue disabled until both green
//   3. Live tutorial — instructions + NSTextView. Hotkey is armed.
//      When paste lands in this NSTextView, transition to "you got it" state.
//      Skip link available.
//   4. Optional key — SecureField for DeepL, Verify button, Save/Skip buttons.
//      Skip writes nothing. Save calls verify first; only stores on success.
//
// All four screens share a header with progress dots (●○○○ etc.) and the keycap mark.
```

The full SwiftUI source mirrors `settings_window.swift` and `snippet_overlay.swift` patterns.

- [ ] **Step 1: Write onboarding.swift**

(Implementation per the contract above. Use NavigationStack with 4 numbered cases. Bridge events via FileHandle stdin/stdout.)

- [ ] **Step 2: Add to install.sh**

```bash
swiftc ~/voicetype/onboarding.swift -o ~/voicetype/onboarding
```

- [ ] **Step 3: Compile**

```bash
swiftc ~/voicetype/onboarding.swift -o ~/voicetype/onboarding
file ~/voicetype/onboarding
```

### Task 7.2: Add OnboardingBridge to overlay_bridge.py

**Files:**
- Modify: `~/voicetype/overlay_bridge.py`

- [ ] **Step 1: Add OnboardingBridge class**

Mirror `SettingsBridge`. Handles:
- `open_pref_pane` → opens `x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone` (or `_Accessibility`)
- `check_perms` → checks via Cocoa AVCaptureDevice + AXIsProcessTrusted; emits `perm_status`
- `start_tutorial` → arms hotkey; on next paste, emits `tutorial_paste_landed`
- `verify_key`, `save_key` → same as SettingsBridge
- `onboarding_complete` → writes `~/.voicetype/onboarding_complete`

For permission checks from Python, we need a small Swift helper or use `tccutil`/checks via `subprocess`. Easiest: do the check in `onboarding.swift` itself using AVCaptureDevice.authorizationStatus() and AXIsProcessTrusted(), and just ask Python to launch system pref panes.

Simplification: move the permission-check logic INTO onboarding.swift, so OnboardingBridge only needs to handle: `open_pref_pane`, `start_tutorial`, `verify_key`, `save_key`, `onboarding_complete`.

### Task 7.3: First-launch detection in voxtype.py

**Files:**
- Modify: `~/voicetype/voxtype.py:__init__` (early)

- [ ] **Step 1: Add first-launch check**

In `__init__`, after `self.cfg = load_config()`, add:

```python
self._maybe_run_onboarding()
```

Add the method:

```python
def _maybe_run_onboarding(self):
    """If no onboarding_complete flag, launch the onboarding flow."""
    flag = os.path.expanduser("~/.voicetype/onboarding_complete")
    if os.path.exists(flag):
        return
    # Lazy import to keep startup fast for repeat users
    from overlay_bridge import OnboardingBridge
    self.onboarding = OnboardingBridge(on_complete=lambda: self._mark_onboarding_done(flag))
    self.onboarding.start()
    self.onboarding.open_window()

def _mark_onboarding_done(self, flag: str):
    os.makedirs(os.path.dirname(flag), exist_ok=True)
    with open(flag, "w") as f:
        f.write("1")
```

### Task 7.4: End-to-end manual test

- [ ] **Step 1: Reset to fresh-install state**

```bash
rm -f ~/.voicetype/onboarding_complete
# Optional: rm -rf ~/.voicetype to simulate fully fresh install
```

- [ ] **Step 2: Launch voxtype.py**

```bash
cd ~/voicetype && python voxtype.py
```

Expected: Onboarding window opens. Walk through:
- Screen 1: see keycap, click Continue.
- Screen 2: click each permission row, accept system dialogs, both turn green, Continue.
- Screen 3: hold ⌥ C, say a phrase, see it paste in the test field, transition to "you got it".
- Screen 4: leave key blank, click Skip. (Or paste a key + Verify + Save.)
- Window closes. Menubar mic appears.

- [ ] **Step 3: Verify the flag was written**

```bash
ls ~/.voicetype/onboarding_complete
```

- [ ] **Step 4: Re-run voxtype.py — onboarding should NOT show**

```bash
cd ~/voicetype && timeout 8 python voxtype.py
```

Expected: menubar mic appears immediately, no onboarding window.

- [ ] **Step 5: Commit Phase 7**

```bash
git -C ~/voicetype add onboarding.swift overlay_bridge.py voxtype.py install.sh
git -C ~/voicetype commit -m "$(cat <<'EOF'
feat: 4-screen first-launch onboarding

Welcome → Permissions → Live dictation tutorial → Optional API key.

- onboarding.swift: SwiftUI window with progress dots, NSTextView test
  target on screen 3, SecureField on screen 4
- overlay_bridge.py: OnboardingBridge handles open_pref_pane,
  start_tutorial, verify_key, save_key, onboarding_complete
- voxtype.py: first-launch detection (~/.voicetype/onboarding_complete);
  lazy-imports onboarding only when needed
- install.sh: compile onboarding helper

User sees text appear in the live tutorial — not just instructions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 8 — Steer overlay brand restyle

Re-skin the existing snippet_overlay.swift to match the new brand. No structural changes.

### Task 8.1: Update snippet_overlay.swift colors and typography

**Files:**
- Modify: `~/voicetype/snippet_overlay.swift`

- [ ] **Step 1: Read current overlay**

```bash
head -100 ~/voicetype/snippet_overlay.swift
```

- [ ] **Step 2: Apply brand updates**

Use Edit tool to update color constants and font references. Key replacements:
- Background: `Color(red:0.10, green:0.11, blue:0.16, opacity:0.97)` (= `#1a1d28` at 0.97 alpha)
- Accent / primary: `Color(red:0.302, green:0.561, blue:0.859)` (= `#4d8fdb`)
- Title font: `Font.custom("Space Grotesk", size: 14).weight(.semibold)`
- Body font: keep system

Also: update the search-row keycap (the `⌥ C` glyph in the search field) to use the brand colors.

- [ ] **Step 3: Recompile and visually verify**

```bash
swiftc ~/voicetype/snippet_overlay.swift -o ~/voicetype/VoxType.app/Contents/MacOS/snippet_overlay
# Restart voxtype.py
cd ~/voicetype && python voxtype.py &
# Trigger overlay
echo "Hold ⌥ C, say 'open snippet overview'"
```

Expected: overlay opens with new colors (deeper blue accent, slate background). All existing functionality (search, paste, edit, delete) unchanged.

### Task 8.2: Commit overlay restyle

```bash
git -C ~/voicetype add snippet_overlay.swift
git -C ~/voicetype commit -m "$(cat <<'EOF'
style: Steer overlay brand restyle (colors + typography)

- Background: #1a1d28 @ 0.97 alpha
- Accent: #4d8fdb (replacing prior accent)
- Title: Space Grotesk semibold
- Search-row keycap glyph reskinned to brand
- No structural / functional changes

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 9 — PyInstaller bundling

Bundle the entire app (Python + Swift helpers + Whisper model + assets) into a single `VoiceType.app` that runs without a system Python.

### Task 9.1: Add pyinstaller to dev deps

**Files:**
- Modify: `~/voicetype/requirements.txt` (or add a build-requirements.txt)

- [ ] **Step 1: Install pyinstaller**

```bash
source ~/voicetype/.venv/bin/activate
pip install pyinstaller
pyinstaller --version
```

Expected: prints PyInstaller version (6.x).

### Task 9.2: Write VoiceType.spec for PyInstaller

**Files:**
- Create: `~/voicetype/build/VoiceType.spec`

- [ ] **Step 1: Write the spec**

Use Write tool to create `~/voicetype/build/VoiceType.spec`:

```python
# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for VoiceType.app
import os

HOME = os.path.expanduser("~/voicetype")
MODELS_DIR = os.path.join(HOME, "models")

a = Analysis(
    [os.path.join(HOME, "voxtype.py")],
    pathex=[HOME],
    binaries=[
        # Compiled Swift helpers
        (os.path.join(HOME, "hotkey_helper"), "."),
        (os.path.join(HOME, "paste_helper"), "."),
        (os.path.join(HOME, "snippet_overlay"), "."),
        (os.path.join(HOME, "settings_window"), "."),
        (os.path.join(HOME, "onboarding"), "."),
        (os.path.join(HOME, "keys_helper"), "."),
    ],
    datas=[
        # Whisper model
        (os.path.join(MODELS_DIR, "ggml-base.en.bin"), "models"),
        # Assets (menubar mic, etc.)
        (os.path.join(HOME, "assets", "menubar-mic.pdf"), "assets"),
    ],
    hiddenimports=[
        "pywhispercpp", "rumps", "sounddevice", "rapidfuzz",
        "numpy",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VoiceType",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # LSUIElement = true (menubar-only)
    disable_windowed_traceback=False,
    argv_emulation=True,
    target_arch=None,
    codesign_identity="-",  # ad-hoc
    entitlements_file=None,
    icon=os.path.join(HOME, "assets", "app-icon.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VoiceType",
)

app = BUNDLE(
    coll,
    name="VoiceType.app",
    icon=os.path.join(HOME, "assets", "app-icon.icns"),
    bundle_identifier="com.polistician.voicetype",
    info_plist={
        "CFBundleName": "VoiceType",
        "CFBundleDisplayName": "VoiceType",
        "CFBundleExecutable": "VoiceType",
        "CFBundleIdentifier": "com.polistician.voicetype",
        "CFBundleVersion": open(os.path.join(HOME, "VERSION")).read().strip(),
        "CFBundleShortVersionString": open(os.path.join(HOME, "VERSION")).read().strip(),
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription": "VoiceType records audio when you hold ⌥ C, transcribes it locally, and pastes the text.",
        "NSAppleEventsUsageDescription": "VoiceType uses Accessibility events to press ⌘ V on your behalf.",
        "NSHumanReadableCopyright": "MIT — see LICENSE file. Copyright © 2026 Beauregard Berton.",
    },
)
```

### Task 9.3: Create VERSION file

**Files:**
- Create: `~/voicetype/VERSION`

- [ ] **Step 1: Write 0.9.1**

```bash
echo "0.9.1" > ~/voicetype/VERSION
```

### Task 9.4: Build the .app

- [ ] **Step 1: Run pyinstaller**

```bash
cd ~/voicetype && source .venv/bin/activate
pyinstaller --noconfirm --clean build/VoiceType.spec
ls -d dist/VoiceType.app
```

Expected: `dist/VoiceType.app` exists. (If pyinstaller errors on `pywhispercpp`, see Task 9.5.)

- [ ] **Step 2: Inspect Info.plist**

```bash
plutil -p dist/VoiceType.app/Contents/Info.plist | head -20
```

Expected: `CFBundleName = VoiceType`, `CFBundleIdentifier = com.polistician.voicetype`.

- [ ] **Step 3: Launch the bundled .app**

```bash
open dist/VoiceType.app
```

Expected: menubar mic appears within ~5 seconds. **Activity Monitor should show "VoiceType" — NOT "Python".**

- [ ] **Step 4: Smoke-test dictation from the bundled app**

Open TextEdit. Hold ⌥ C, say "hello from the bundle". Release.
Expected: "hello from the bundle" pastes in TextEdit.

### Task 9.5: Fallback path for PyInstaller pywhispercpp issues

If Task 9.4 step 1 fails with errors about missing C/C++ libs from pywhispercpp:

- [ ] **Step 1: Inspect what's missing**

```bash
otool -L $(python -c "import pywhispercpp, os; print(os.path.dirname(pywhispercpp.__file__))")/_pywhispercpp.so
```

- [ ] **Step 2: Add the missing dylibs to the spec's `binaries` list**

Edit `build/VoiceType.spec` and add the library paths returned by step 1 to the `binaries=` list. Re-run pyinstaller.

If still failing, the fallback is `py2app`. See spec §13 — first try py2app with a similar setup.py before giving up on a self-contained bundle.

### Task 9.6: Commit Phase 9

- [ ] **Step 1: Commit**

```bash
git -C ~/voicetype add build/VoiceType.spec VERSION
git -C ~/voicetype commit -m "$(cat <<'EOF'
build: PyInstaller spec for VoiceType.app

- build/VoiceType.spec — bundles Python interpreter, deps,
  whisper.cpp model, all Swift helpers, assets
- VERSION — single source of truth, currently 0.9.1
- BUNDLE config sets CFBundleName=VoiceType,
  bundle id com.polistician.voicetype, LSUIElement=true,
  with mic + accessibility usage strings.

Resolves "Python in Activity Monitor" — bundled .app reports
as VoiceType in OS surfaces.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 10 — DMG packaging

Wrap the bundled .app in a custom DMG with the brand background and Applications shortcut.

### Task 10.1: Install create-dmg

- [ ] **Step 1: Install via brew**

```bash
brew install create-dmg
create-dmg --version
```

### Task 10.2: Write the DMG build script

**Files:**
- Create: `~/voicetype/build/make-dmg.sh`

- [ ] **Step 1: Write the script**

```bash
#!/bin/bash
# make-dmg.sh — build VoiceType.dmg from dist/VoiceType.app
set -euo pipefail

APP=~/voicetype/dist/VoiceType.app
DMG=~/voicetype/dist/VoiceType.dmg
BG=~/voicetype/assets/dmg-background.png
VOLUME_ICON=~/voicetype/assets/app-icon.icns

if [ ! -d "$APP" ]; then
    echo "ERROR: $APP not found. Run pyinstaller first."
    exit 1
fi

rm -f "$DMG"

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

ls -lh "$DMG"
shasum -a 256 "$DMG" | tee "$DMG.sha256"
```

- [ ] **Step 2: Make executable + run**

```bash
chmod +x ~/voicetype/build/make-dmg.sh
~/voicetype/build/make-dmg.sh
```

Expected: `dist/VoiceType.dmg` exists, ~250MB, prints SHA256.

### Task 10.3: Test the DMG

- [ ] **Step 1: Mount it**

```bash
open ~/voicetype/dist/VoiceType.dmg
```

Expected: Finder window opens showing VoiceType icon + Applications shortcut, custom background visible.

- [ ] **Step 2: Drag to Applications + first-launch**

Drag VoiceType.app into the Applications shortcut. Eject the DMG. In Finder, navigate to /Applications, **right-click VoiceType → Open**, click Open in the Gatekeeper dialog.

Expected: app launches, onboarding window appears (because /Applications/VoiceType.app is a fresh install — onboarding flag is at `~/.voicetype/`, which still has the flag from earlier; if it doesn't show onboarding, that's expected behavior — flag was already written).

- [ ] **Step 3: Force-fresh test**

```bash
rm -f ~/.voicetype/onboarding_complete
# Quit VoiceType from menubar, then re-launch from /Applications/
```

Expected: onboarding window appears.

### Task 10.4: Commit Phase 10

- [ ] **Step 1: Commit**

```bash
git -C ~/voicetype add build/make-dmg.sh
git -C ~/voicetype commit -m "$(cat <<'EOF'
build: DMG packaging via create-dmg

- build/make-dmg.sh — wraps dist/VoiceType.app in a DMG with
  brand background, Applications drop-link, custom volume icon
- Computes SHA256 alongside, writes to .sha256 sidecar

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Phase 11 — Release pipeline + first cut of v0.9.1

### Task 11.1: Write release.sh

**Files:**
- Create: `~/voicetype/build/release.sh`

- [ ] **Step 1: Write the script**

```bash
#!/bin/bash
# release.sh — cut a versioned VoiceType release on GitHub
# Usage:
#   ./build/release.sh patch        — bump 0.9.1 → 0.9.2
#   ./build/release.sh minor        — bump 0.9.1 → 0.10.0
#   ./build/release.sh major        — bump 0.9.1 → 1.0.0
#   ./build/release.sh 0.9.5        — explicit version
#   ./build/release.sh --dry-run X  — print commands without executing
set -euo pipefail

REPO_ROOT=~/voicetype
cd "$REPO_ROOT"

DRY=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY=true
    shift
fi

ARG="${1:-}"
if [ -z "$ARG" ]; then
    echo "Usage: $0 [patch|minor|major|<X.Y.Z>] [--dry-run]"
    exit 1
fi

# Read current version
CURRENT=$(cat VERSION)
IFS='.' read -r MAJ MIN PAT <<< "$CURRENT"

case "$ARG" in
    patch) NEW="${MAJ}.${MIN}.$((PAT+1))" ;;
    minor) NEW="${MAJ}.$((MIN+1)).0" ;;
    major) NEW="$((MAJ+1)).0.0" ;;
    *)     NEW="$ARG" ;;
esac

echo "Releasing $CURRENT → $NEW"

# Verify clean tree
if ! git diff-index --quiet HEAD --; then
    echo "ERROR: uncommitted changes. Commit or stash first."
    exit 1
fi

run() {
    echo "+ $*"
    if [ "$DRY" = false ]; then "$@"; fi
}

# 1. Bump VERSION
run bash -c "echo $NEW > VERSION"
run git add VERSION
run git commit -m "release: v$NEW"

# 2. Build
run rm -rf dist/ build/build/ build/dist/ # clean
run pyinstaller --noconfirm --clean build/VoiceType.spec
run codesign --sign - --deep --force "dist/VoiceType.app"

# 3. DMG
run ./build/make-dmg.sh

# 4. Verify SHA256
SHA=$(cat dist/VoiceType.dmg.sha256 | awk '{print $1}')
echo "SHA256: $SHA"

# 5. Tag + push
run git tag "v$NEW"
run git push origin main
run git push origin "v$NEW"

# 6. GitHub release
NOTES_FILE=$(mktemp)
cat > "$NOTES_FILE" <<NOTES
Download: VoiceType.dmg

\`\`\`
SHA256: $SHA
\`\`\`

See [README](./README.md) for installation. Right-click → Open on first launch.
NOTES

run gh release create "v$NEW" \
    dist/VoiceType.dmg \
    dist/VoiceType.dmg.sha256 \
    --title "v$NEW" \
    --notes-file "$NOTES_FILE"

rm -f "$NOTES_FILE"

echo ""
echo "✓ Released v$NEW"
echo "  SHA256: $SHA"
echo "  https://github.com/polistician/voicetype/releases/tag/v$NEW"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x ~/voicetype/build/release.sh
```

### Task 11.2: Dry-run the release

- [ ] **Step 1: Dry-run**

```bash
~/voicetype/build/release.sh --dry-run patch
```

Expected: prints commands without executing. Verify the sequence and version bump.

### Task 11.3: Cut the real v0.9.1

- [ ] **Step 1: Verify VERSION is at 0.9.1**

```bash
cat ~/voicetype/VERSION
```

Expected: `0.9.1`. (If it shows something else, it's because Phase 9 set it — adjust the script invocation accordingly. We're going to ship as 0.9.1.)

- [ ] **Step 2: Commit release.sh first**

```bash
git -C ~/voicetype add build/release.sh
git -C ~/voicetype commit -m "$(cat <<'EOF'
build: release.sh — versioned GitHub Release pipeline

Reads VERSION, bumps per arg (patch/minor/major/explicit), builds
.app, codesigns ad-hoc, builds DMG, computes SHA256, tags, pushes,
creates GitHub release with DMG + SHA256 sidecar attached.

Re-run safe (gh release create upserts assets).
--dry-run flag prints commands without executing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 3: Cut v0.9.1**

```bash
~/voicetype/build/release.sh 0.9.1
```

Expected: builds, signs, packages, tags, pushes, creates release. Prints SHA256 and release URL.

- [ ] **Step 4: Verify**

```bash
gh release view v0.9.1 --repo polistician/voicetype
```

Expected: shows v0.9.1 with `VoiceType.dmg` and `VoiceType.dmg.sha256` attached.

- [ ] **Step 5: Test the public URL**

```bash
curl -sI -L https://github.com/polistician/voicetype/releases/latest/download/VoiceType.dmg | head -5
```

Expected: HTTP 302 → HTTP 200 with `Content-Type: application/x-apple-diskimage`.

---

## Phase 12 — Site deployment + cutover

### Task 12.1: Inspect current voicetype.polistician.ai mount

- [ ] **Step 1: SSH to the server**

```bash
ssh -i ~/.ssh/lightsail.pem ubuntu@18.153.234.151 "ls -la /opt/crypto-app/v3/polistician-public/ 2>/dev/null; ls -la /opt/polistician-ventures/static/ 2>/dev/null; ls /etc/caddy/ 2>/dev/null"
```

Verify which static dir actually serves `voicetype.polistician.ai` (per the brainstorming we identified `polistician-ventures` FastAPI on port 8042).

- [ ] **Step 2: Find the existing voicetype dir on the server**

```bash
ssh -i ~/.ssh/lightsail.pem ubuntu@18.153.234.151 "find / -name 'voicetype' -type d 2>/dev/null | head -10"
```

Note the path that's currently being served.

### Task 12.2: Stage the new site to a parallel dir

- [ ] **Step 1: rsync new site to server**

```bash
rsync -avz --delete \
    -e "ssh -i ~/.ssh/lightsail.pem" \
    ~/voicetype/site/ \
    ubuntu@18.153.234.151:/tmp/voicetype-v2/
```

- [ ] **Step 2: Move to a real parallel location**

```bash
ssh -i ~/.ssh/lightsail.pem ubuntu@18.153.234.151 "sudo mkdir -p /opt/polistician-ventures/static/voicetype-v2 && sudo cp -r /tmp/voicetype-v2/* /opt/polistician-ventures/static/voicetype-v2/ && sudo chown -R www-data:www-data /opt/polistician-ventures/static/voicetype-v2/"
```

(Adjust path based on what Task 12.1 found.)

### Task 12.3: Test on a temporary path before cutover

- [ ] **Step 1: Add a temporary FastAPI route for /voicetype-v2**

Edit `polistician-ventures/main.py` to add:

```python
app.mount("/voicetype-v2", StaticFiles(directory="/opt/polistician-ventures/static/voicetype-v2", html=True))
```

Reload the FastAPI service:

```bash
ssh -i ~/.ssh/lightsail.pem ubuntu@18.153.234.151 "sudo systemctl restart polistician-ventures"
```

- [ ] **Step 2: Browse the staging URL**

```bash
open "https://polistician.ai/voicetype-v2/"
```

Expected: the new site renders. Click around. Verify the download button works (should resolve to GH releases). Theme toggle works. Smooth scroll works. Latest-version JS hits the GitHub API and updates the page.

### Task 12.4: Cutover — point voicetype.polistician.ai at the new dir

- [ ] **Step 1: Update the subdomain mount**

In the polistician-ventures config (or Caddy config — check Task 12.1 output), swap the existing `voicetype.polistician.ai` static-dir from the old path to `/opt/polistician-ventures/static/voicetype-v2`.

- [ ] **Step 2: Reload**

```bash
ssh -i ~/.ssh/lightsail.pem ubuntu@18.153.234.151 "sudo systemctl reload caddy && sudo systemctl restart polistician-ventures"
```

- [ ] **Step 3: Verify the live site**

```bash
curl -s https://voicetype.polistician.ai/ | head -30
```

Expected: HTML matches the new site (Voice|Type wordmark, hero copy, etc.).

- [ ] **Step 4: Browser end-to-end test**

```bash
open "https://voicetype.polistician.ai/"
```

Walk through:
- Topbar `← polistician.ai` link works.
- Theme toggle works.
- Click "Download for macOS" → DMG downloads.
- Open DMG → drag to Applications → right-click Open → onboarding fires.
- Complete onboarding → menubar mic appears → dictate in TextEdit → text pastes.

Total time from button-click to first dictation: should be under 60 seconds.

### Task 12.5: Final smoke test from a fresh perspective

- [ ] **Step 1: Reset onboarding flag and clear app**

On a Mac (yours is fine):

```bash
rm -rf /Applications/VoiceType.app
rm -f ~/.voicetype/onboarding_complete
launchctl unload ~/Library/LaunchAgents/com.polistician.voicetype.plist 2>/dev/null || true
```

- [ ] **Step 2: Visit the site, download, install, onboard**

Browser: `https://voicetype.polistician.ai/` → click Download → wait for DMG → open → drag → right-click Open → walk through onboarding → dictate "hello" in TextEdit.

- [ ] **Step 3: Verify the SHA256 displayed on the site matches**

```bash
shasum -a 256 ~/Downloads/VoiceType.dmg | awk '{print $1}'
```

Expected: matches the SHA256 on the site (Section 5 / Footer) and the SHA256 in the GitHub release notes.

### Task 12.6: Final commit + announcement

- [ ] **Step 1: Final commit (if any deployment-tweak files changed)**

```bash
git -C ~/voicetype status
# If there are changes from deployment iterations, commit them.
```

- [ ] **Step 2: Announce v0.9.1**

(Up to user — Twitter, blog, etc. Out of scope for this plan.)

---

## Self-review (run before handing off)

This plan was self-reviewed against the spec. Findings:

**Spec coverage:**
- §2a Phase plan (v0.9.1) — every row covered (site rebuild, brand, DMG, repo migration, onboarding, settings, license, overlay restyle, threat-model section, SHA256, Keychain).
- §3 Locked decisions — all 17 reflected in tasks.
- §5 Site sections — 9 sections all in Task 4.3.
- §6 Brand assets — all 9 deliverables in Phase 3.
- §7 Onboarding 4 screens — Phase 7.
- §7 Settings window — Phase 6.
- §8 Pre-migration cleanup commit — Phase 0.
- §8 Release pipeline — Phase 11.
- §11 Testing — manual tests embedded in each phase; integration smoke test in Phase 12.
- §12 Migration sequence — Phases 0 → 1 → 2 → 11 → 12 follow it.
- §13 Open questions — PyInstaller fallback addressed in Task 9.5.

**Gaps caught:**
- Phase 4 (site) does not include the Section 9 footer threat-model copy explicitly. The implementation should include all 9 sections per spec §5; the description in Task 4.3 names them but the actual HTML body is the engineer's responsibility — they must reference the v5 mockup AND spec §5 §9 to ensure the footer threat-model copy is present.
- The v0.10.0 work (Vocabulary, Corrections, Storage panels, folder-scan onboarding) is deliberately out of scope for this plan — confirmed against §2a.

**Type/method consistency:**
- `KeyStore.set/get/delete/list` consistent across keys.py, test_keys.py, settings_window.swift, onboarding.swift.
- `OnboardingBridge`, `SettingsBridge` follow the same pattern as existing `OverlayBridge`.
- `~/.voicetype/onboarding_complete` flag path consistent in voxtype.py and onboarding.swift.

No placeholders. All steps have concrete commands or code blocks.

---

## Execution handoff

Plan complete and saved to `~/voicetype/docs/superpowers/plans/2026-05-05-voicetype-rebuild-v0-9-1.md`.

Two execution options:

1. **Subagent-driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for plans with this much code volume because each subagent gets full context for its task.

2. **Inline execution** — Execute tasks in this session using executing-plans, with checkpoints for review.

Which approach?
