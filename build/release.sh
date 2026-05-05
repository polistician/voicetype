#!/bin/bash
# release.sh — cut a versioned VoiceType release on GitHub
# Usage:
#   ./build/release.sh patch        — bump 0.9.1 → 0.9.2
#   ./build/release.sh minor        — bump 0.9.1 → 0.10.0
#   ./build/release.sh major        — bump 0.9.1 → 1.0.0
#   ./build/release.sh 0.9.5        — explicit version
#   ./build/release.sh --dry-run X  — print without executing
set -euo pipefail

REPO_ROOT=/Users/beauregard/voicetype
cd "$REPO_ROOT"

# Always unset GITHUB_TOKEN so the OAuth keychain entry is used for gh
unset GITHUB_TOKEN

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

CURRENT=$(cat VERSION)
IFS='.' read -r MAJ MIN PAT <<< "$CURRENT"

case "$ARG" in
    patch) NEW="${MAJ}.${MIN}.$((PAT+1))" ;;
    minor) NEW="${MAJ}.$((MIN+1)).0" ;;
    major) NEW="$((MAJ+1)).0.0" ;;
    *)     NEW="$ARG" ;;
esac

echo "Releasing $CURRENT → $NEW"

# Verify clean tree (warn but don't abort if dirty in dry-run)
if ! git diff-index --quiet HEAD --; then
    if [ "$DRY" = false ]; then
        echo "ERROR: uncommitted changes. Commit or stash first."
        git status --short
        exit 1
    fi
    echo "WARNING: uncommitted changes (continuing in dry-run)"
fi

# Verify tag doesn't already exist
if git rev-parse "v$NEW" >/dev/null 2>&1; then
    echo "ERROR: tag v$NEW already exists. Pick a different version."
    exit 1
fi

run() {
    echo "+ $*"
    if [ "$DRY" = false ]; then "$@"; fi
}

# 1. Bump VERSION + commit (only if changing)
if [ "$CURRENT" != "$NEW" ]; then
    run bash -c "echo $NEW > VERSION"
    run git add VERSION
    run git commit -m "release: v$NEW"
fi

# 2. Build the .app
# Prefer build-app.sh if it exists (handles code-signing fix for Python.framework)
if [ -f build/build-app.sh ]; then
    run /bin/bash build/build-app.sh
else
    run rm -rf dist/ build/VoiceType build/dist
    run pyinstaller --noconfirm --clean build/VoiceType.spec
    run codesign --sign - --deep --force "dist/VoiceType.app"
fi

# 3. DMG + SHA256
run /bin/bash build/make-dmg.sh

# 4. Read SHA256
SHA=$(awk '{print $1}' dist/VoiceType.dmg.sha256)
echo "SHA256: $SHA"

# 5. Tag + push
run git tag "v$NEW"
run git push origin main
run git push origin "v$NEW"

# 6. GitHub release
NOTES_FILE=$(mktemp)
cat > "$NOTES_FILE" <<NOTES
Download: \`VoiceType.dmg\`

\`\`\`
SHA256: $SHA
\`\`\`

See [README](https://github.com/polistician/voicetype/blob/main/README.md) for installation. Right-click → Open on first launch (Gatekeeper bypass).
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
