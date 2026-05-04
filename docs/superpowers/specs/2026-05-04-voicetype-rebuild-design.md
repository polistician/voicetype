# VoiceType Rebuild — Design

**Date:** 2026-05-04
**Author:** Beauregard Berton (with Claude Code)
**Repo at design time:** `~/voxtype/` (renamed during implementation to `~/voicetype/`)
**Public surface:** `voicetype.polistician.ai` + new `github.com/polistician/voicetype`

---

## 1. Goals

Take VoiceType from "personal-use Python script with a deployed but over-promising marketing page and a broken download link" to "indie macOS app any privacy-curious user can download, install, and start using in 30 seconds, with a marketing site that explains it honestly."

Concretely, this rebuild ships four artifacts:
1. A rewritten `voicetype.polistician.ai` static site.
2. A real macOS `.app` bundle delivered via DMG, with a 4-screen first-launch onboarding flow (welcome → permissions → live dictation tutorial → optional API-key setup) plus a minimal Settings window for ongoing key management.
3. A new public GitHub repo `polistician/voicetype` (MIT-licensed) with a one-command release pipeline.
4. A unified brand identity ("The Hotkey" — `⌥ C` keycap) applied across web, app, DMG, and overlay surfaces.

Phased: v0.9.1 ships everything above; v0.10.0 follows with the in-app context-management UX (vocabulary panel, corrections panel, storage panel, folder-scan onboarding step) — see Section 2a.

## 2. Non-goals

The following are explicitly out of scope and should not be added without a separate spec:

- Apple Developer Program / notarization ($99/yr). The Gatekeeper warning is treated as part of the brand story ("we don't pay Apple's tax").
- Native Swift rewrite of the Python core. Python stays.
- Replacement for the `rumps` menubar dropdown. System styling stays.
- iOS / mobile / browser-extension companion.
- Auto-update inside the app (users re-download from GitHub Releases for now).
- Code-level rename of `snippets.py`, the voice trigger word "snippet", or the `VoxType` Python class. "Steer" is a *user-facing capability name*, not an internal code rename.
- Encrypted-at-rest databases. FileVault covers user data; adding our own crypto is over-engineering for a personal-machine app.
- Cloud sync between user devices. Breaks the local-first promise.

## 2a. Phase plan

The work splits into two releases. v0.9.1 is the next public release; v0.10.0 follows.

| | v0.9.1 — public download | v0.10.0 — context UX |
|---|---|---|
| Site rebuild (mockup v5) | ✓ | — |
| Brand identity assets | ✓ | — |
| DMG bundle + GitHub release pipeline | ✓ | — |
| Repo migration + cleanup commit | ✓ | — |
| 4-screen onboarding (welcome → perms → live tutorial → optional key) | ✓ | — |
| Minimal Settings window (DeepL key, Keychain-backed) | ✓ | — |
| MIT license + LICENSE file + threat-model section on site | ✓ | — |
| Steer overlay brand restyle | ✓ | — |
| **Site copy on "learns your vocabulary"** | honest about current invisible behavior ("primes Whisper from your dictation history") | upgraded to "see and manage what VoiceType knows about you" |
| **Vocabulary panel** in overlay (read+edit) | — | ✓ |
| **Corrections panel** in overlay (read+edit) | — | ✓ |
| **Storage panel** in overlay (paths + sizes + decision-log toggle) | — | ✓ |
| **Folder-scan onboarding step** (point at a folder, harvest project terms) | — | ✓ |

The split protects v0.9.1 from scope creep — it's already a multi-track lift (site, bundle, brand, repo, onboarding, settings, license). v0.10.0 ships the context-management UX that turns the "learns your vocabulary" claim from invisible to demonstrable.

## 3. Locked decisions

The brainstorming session settled the following — all locked, not up for re-debate during implementation:

| # | Decision | Why |
|---|----------|-----|
| 1 | DMG distribution, ad-hoc signed | No Apple Developer fee; one-time Gatekeeper bypass framed as a feature |
| 2 | Local release script (not GitHub Actions) | One-person shop, builds on the same Mac that runs the app |
| 3 | Repo name `polistician/voicetype` | Matches the public brand and URL |
| 4 | Local dir rename `~/voxtype/` → `~/voicetype/` | Match the brand publicly; minor migration cost is one-time |
| 5 | Bundle ID `com.polistician.voicetype` | Matches new brand; replaces `com.voxtype.app` |
| 6 | User-data dir rename `~/.voxtype/` → `~/.voicetype/` with one-time migration | Consistency; user is the only existing user |
| 7 | Internal code names stay (`snippets.py`, `class VoxType`, voice trigger word "snippet") | Surface-area-of-rename / value ratio is poor |
| 8 | Brand: "The Hotkey" — `⌥ C` keycap, primary blue `#4d8fdb` on dark | Distinctive, ownable, ties brand to the unique gesture |
| 9 | Menubar icon: monochrome microphone (template image), not the keycap | "Mic" is universal shorthand at 16×16; keycap is for larger surfaces |
| 10 | "Steer" is a *capability category name* on the site, not a literal voice trigger | Sits next to Dictate / Translate; voice triggers stay flexible |
| 11 | License: MIT | Permissive, dependency-compatible (Whisper.cpp/pywhispercpp/rumps/mxbai are all MIT/BSD/Apache), no commercial-use restriction |
| 12 | First-launch onboarding includes a **live** dictation tutorial (the user actually records and sees text paste), not just instructions | The "see it work" moment is the conversion event; teaching by reading is a missed handshake |
| 13 | A minimal Settings window ships in v0.9.1 just for API-key entry (DeepL today, framework for more) | Keys can't be edited via flat config files cleanly + must go to Keychain anyway |
| 14 | All API keys stored in macOS Keychain via Security framework, never in `config.json` | Plain-text secrets in dotfiles is the most common indie-app vuln. One Swift helper handles get/set/delete |
| 15 | DMG SHA256 published in GitHub release notes and on site | Lets paranoid users verify download integrity; cheap to add |
| 16 | "What we store / What we send" threat-model section on the site | Honest disclosure reinforces local-first claim and answers the question every privacy-conscious visitor asks |
| 17 | All currently-uncommitted enhancements (`voxtype.py` flash-skip, RMS gate, hallucination filter; `recorder.py` device fallback; `transcriber.py` junk-token filter; `transcriber_v2.py` language anchor; `voice_profile.py` 15-word cap; `intent.py` tightened thresholds; `corrections.py` rebrand cleanup) committed before v0.9.1 | They're real quality fixes; shipping v0.9.1 without them is shipping an inferior product to the public for the first time |

## 4. Architecture overview

The project produces three independent shipping artifacts and one developer artifact, each with its own deployment path:

```
                ┌─────────────────────────────────────────┐
                │  ~/voicetype/  (renamed from ~/voxtype/) │
                │   ├─ voxtype.py + modules (unchanged)    │
                │   ├─ Swift helpers (paste/hotkey/overlay)│
                │   ├─ assets/ (logo, icon, dmg-bg, mic)   │
                │   ├─ onboarding/ (new, Swift)            │
                │   ├─ build/ (release.sh, spec, .pyinstaller)
                │   └─ site/ (static HTML/CSS/SVG)         │
                └────────────┬────────────────────────────┘
                             │
       ┌─────────────────────┼─────────────────────┐
       ▼                     ▼                     ▼
  voicetype.polistician.ai   GitHub Release        Local repo (git push)
  (Caddy → 8042 site dir)    VoiceType.dmg         polistician/voicetype
  static rebuild             via release.sh        public source
       │                     │                     │
       └──── linked from ────┘                     │
       "Download for macOS" button                 │
                                                   │
                              "Source on GitHub" ──┘
```

Each artifact is independently testable and deployable. The site can be redeployed without rebuilding the app. The app can be re-released without changing the site. The repo lives wherever git lives.

## 5. Surface A — Marketing site

**Location:** `site/` in the repo. Deployed to `voicetype.polistician.ai`.

**Structure** (from approved mockup v5):

1. **Topbar.** Left: `← polistician.ai` link. Center: `Voice|Type` wordmark with blinking caret. Right: theme toggle.
2. **Hero.** Verbatim from current page (locked). Meta line, headline `hold ⌥ C, speak, the text appears.`, lede paragraph, two CTAs (`Download for macOS`, `Source on GitHub`), Gatekeeper-as-feature line.
3. **Zero-friction callout** — *"Capture an idea the second it arrives."* Body leads with what the user gets (think out loud, lose nothing, speak in your own jargon, the tool learns), then closes with friction comparison vs other tools.
4. **Section 1 — How it works.** Three numbered steps: Hold ⌥ C → Talk → Paste. Caption explains clipboard + synthetic ⌘V mechanic.
5. **Section 2 — Three things VoiceType does.** Equal-weight cards: Dictate / Steer / Translate.
6. **Section 3 — Each feature, doing the thing.** One mock per feature: Cursor+Claude vibecoding (Dictate), say "help" → overlay opens (Steer), German voice → English in Slack (Translate).
7. **Section 4 — Why this exists.** 3 paragraphs of vision: built for Claude Code / privacy / voice-as-loose-intent for AI agents.
8. **Section 5 — Install in 30 seconds.** 5-step strip (Download · Drag · Right-click → Open · Grant 2 perms · Hold ⌥ C) + final download CTA + version meta + DMG SHA256.
9. **Footer — Local-first promise.** A short threat-model section: *"What stays on your laptop"* (audio, transcripts, vocab, snippets, corrections, stats, decisions log) and *"What leaves your laptop"* (only DeepL translation requests, only if you opted in by adding a key). Plus the MIT license link, the GitHub repo link, and the SHA256 of the current DMG. Reinforces the core brand claim.

**What gets cut from the existing live page:** top nav (how/specs/vs/origin), stats meta line, "what's shipped/broken/disabled" enumeration, `vs Wispr/Superwhisper/MacWhisper` comparison table, Section 06 build-decision rationale. Total page length ~30% of current.

**Mock fidelity for Section 3:** ships day-one as polished HTML stand-ins (Mac window chrome with traffic lights, IDE syntax-highlighted code, app menubar with mic icon visible). Real screenshots from the bundled app replace these in a follow-up pass once the app is shipping.

**Deployment:** static files in `site/` get copied to the polistician-ventures FastAPI static-mount or served directly by Caddy. The site does not require server-side rendering; vanilla HTML/CSS, no build step, no JS framework. Theme toggle uses localStorage.

**Out of scope for the site:** waitlist form, blog, comparison table revival, FAQ section, comments.

## 6. Surface B — Brand assets

One unified visual language across web, app, DMG, GitHub. All deliverables in `assets/`:

- `wordmark.svg` — `Voice|Type` with blinking caret. Editable for color/state variants.
- `keycap.svg` — the `⌥ C` keycap mark. Single source-of-truth from which favicon and app icon are derived. Three variants: **on-dark** (blue keycap fill, white glyphs — primary use, site + app icon), **on-light** (darker blue fill, white glyphs — for light-mode contexts), **monochrome** (single-color stamp for tiny favicons, embossing, places where color isn't possible).
- `onboarding-frames/` — four Figma-or-equivalent screens for the first-launch flow: welcome, permissions, live-tutorial, optional-keys. Each is a `.png` and a Swift-implementable spec.
- `settings-window.svg` — design for the Settings window (single-pane, key-input rows, Keychain-backed). Minimum viable; v0.10.0 expands.
- `app-icon.icns` — generated from `keycap.svg` at sizes 16, 32, 64, 128, 256, 512, 1024 (with @2x retina variants). Replaces the current `🎤` emoji menubar title — but only for *Activity Monitor / Dock*. The menubar title itself uses the mic template (next item).
- `menubar-mic.svg` (template image) — monochrome microphone, system tints to white/dark per appearance. State changes by tinting via Cocoa, not by swapping icons. Keeps the "indie mic" feel intentionally.
- `dmg-background.png` — 1280×800. Brand-tinted backdrop with the keycap mark, the VoiceType wordmark, an arrow from the icon-drop target to the Applications shortcut, and a small "First time? Right-click → Open" instruction.
- `favicon.svg` — keycap mark at favicon scale. Single SVG handles all browser sizes.
- `og-image.png` — 1200×630 social card with wordmark + keycap + tagline.

Color system:
- Primary blue `#4d8fdb` (interactive accents, keycap fill, CTAs)
- Deep charcoal `#0d0e12` (backgrounds, dark surfaces)
- Surface `#1a1d28` (raised surfaces inside dark)
- Foreground `#e8eaf0` (default light-on-dark text)
- Sub-foreground `#7a8194` (secondary text, captions)
- Plus the existing typography stack (Space Grotesk / Inter / JetBrains Mono / Source Serif 4) — kept, not replaced.

## 7. Surface C — App bundle + DMG

**Bundling:** PyInstaller. Output is a single `VoiceType.app` containing:
- Embedded Python 3.12 interpreter
- All Python deps (`pywhispercpp`, `rumps`, `sounddevice`, `numpy`, `rapidfuzz`, embedder model + tokenizer)
- `whisper.cpp` binary built with CoreML support
- `ggml-base.en.bin` model (~142 MB)
- Compiled Swift helpers (`hotkey_helper`, `paste_helper`, `snippet_overlay`, plus new `onboarding`)
- App icon `.icns`
- Updated `Info.plist` — bundle ID `com.polistician.voicetype`, bundle name `VoiceType`, executable `VoiceType`, `LSUIElement=true` (no Dock icon).

**This automatically resolves the "Python in Activity Monitor" bug** — `MacOS/VoiceType` is the executable, so the OS reports it as "VoiceType" everywhere.

**Codesigning:** ad-hoc (`codesign --sign - --deep --force`). No notarization. First launch shows the Gatekeeper warning; user does right-click → Open once.

**DMG:** built with `create-dmg` or equivalent. Custom background (asset above), `Applications` symlink, drag-target layout, 250 MB compressed.

**First-launch onboarding** (new — Swift):

A new module `onboarding.swift` runs on first launch (detected by absence of `~/.voicetype/onboarding_complete`). It opens a single window with **four screens**:

1. **Welcome** — keycap mark centered, headline `hold ⌥ C, speak, the text appears.`, single Continue button.
2. **Permissions** — two-row checklist:
   - 🎤 Microphone — clicking opens System Settings → Privacy → Microphone, then re-checks `AVCaptureDevice.authorizationStatus`.
   - ♿ Accessibility — clicking opens System Settings → Privacy → Accessibility, then re-checks `AXIsProcessTrusted`.
   - Continue is disabled until both are green.
3. **Live dictation tutorial.** Instruction *"Hold ⌥ C and say 'hello from VoiceType'."* A `NSTextView` test target sits below the instruction. The Python backend is bridged: when the user holds ⌥ C, the app actually records, transcribes via Whisper, writes to clipboard, and synthetically presses ⌘ V — exactly as it would in any other app. The user *sees text appear*. As soon as one successful paste lands, the screen transitions to a "you got it" confirmation. A "skip" link is available; the dictation hotkey remains armed regardless.
4. **Optional API key setup.** "Speak in another language and want it auto-translated to English? Drop your DeepL API key. Otherwise skip — you can add it later in Settings." Single `SecureField` for the key, a small "Get a free DeepL key →" link to `https://www.deepl.com/pro-api`, a "Skip" button, and a "Save" button that (a) verifies the key against DeepL's `usage` endpoint, (b) on success stores it in macOS Keychain via the Security framework, (c) on failure shows inline error text. Skipping writes nothing.

On completion, write `~/.voicetype/onboarding_complete` so the flow doesn't repeat.

Failure modes:
- User denies a permission → return-to-screen with explanation, retry path. Never block the app forever — option to "skip and remind me later".
- User skips dictation tutorial → still mark complete; the menubar mic still works.
- DeepL key verification fails → inline error, key not stored, user can retry or skip.

**Settings window** (new — Swift, minimal):

Accessible from the menubar dropdown via a new "Settings…" item (added to `voxtype.py`'s rumps menu). Opens a small Swift window with one tab in v0.9.1:

- **Keys.** Read+write rows for API keys. Today: just DeepL. Each row has a label, a `SecureField`, a "Reveal" toggle, a "Verify" button (calls service-specific check endpoint), and a "Save" button that updates Keychain. A "Remove" button clears the key. The window is the *only* surface that ever touches plaintext key strings — they never enter `config.json`, never get logged, never leave Keychain except when the translator module reads them at use time.

The Keychain integration lives in a small helper `keys_helper.swift` that exposes JSON-over-stdio commands `get/set/delete/list` to the Python side. Service identifier: `com.polistician.voicetype.keys`. Account names: `deepl`, future entries follow the same convention.

**Steer overlay restyle:** existing `snippet_overlay.swift` Swift code reskinned with the brand:
- Background: `#1a1d28` with `0.97` alpha and 8px blur (already there, just confirms color)
- Search row keycap matches brand (`⌥` glyph + monospace `C` in a 1px blue border)
- Header text uses Space Grotesk
- Highlight color: `#4d8fdb` (blue), replacing whatever current accent
- No structural changes — same data flow, same JSON protocol with `voxtype.py`

## 8. Surface D — Repo + release pipeline

**Repo creation:**
```bash
gh repo create polistician/voicetype --public --description "Local voice dictation for macOS. Hold ⌥ C, speak, paste anywhere."
```

**Pre-migration cleanup commit** (one commit before any rename):
1. Stage and commit all current uncommitted enhancements: `voxtype.py` (flash-skip, RMS gate, hallucination filter), `recorder.py` (device fallback), `transcriber.py` + `transcriber_v2.py` (junk-token filter, language anchor), `voice_profile.py` (15-word cap), `intent.py` (tightened thresholds 60→85), `corrections.py` (rebrand cleanup), plus `paster.py` (delegate-to-helper).
2. Add untracked source files that should be in git: `paste_helper.swift`, `translator.py`.
3. Update `.gitignore` to exclude: `.venv/`, `__pycache__/`, `*.pyc`, `build/`, `dist/`, `*.dmg`, `models/`, compiled Swift binaries (`hotkey_helper`, `paste_helper` at repo root), the entire `VoxType.app/Contents/` build artifacts, `_CodeSignature/`, `.superpowers/`.
4. Delete obsolete `launch.command` (replaced by the .app bundle).
5. Untrack the previously-committed `VoxType.app/Contents/MacOS/hotkey_helper` binary (it'll be regenerated by PyInstaller).

This is one commit, message: `chore: pre-launch cleanup — commit quality fixes, untrack build artifacts`.

**Local rename procedure** (one-time, scripted as `migrate.sh`, runs after cleanup commit):
1. `mv ~/voxtype ~/voicetype`
2. `cp -r ~/.voxtype ~/.voicetype` (copy, don't move — old data stays as fallback for one release)
3. Update launchd plist label `com.voxtype.app` → `com.polistician.voicetype`, paths
4. Update `voxtype.py` config defaults to read from `~/.voicetype/`
5. Update `snippets.py` `DEFAULT_DB_PATH`, plus the path constants in `voice_profile.py`, `corrections.py`, `stats.py`, `user_fixes.py`, `transcript_history.py`
6. `git remote set-url origin https://github.com/polistician/voicetype.git`
7. First push: `git push -u origin main`

**`.gitignore` essentials:**
```
.venv/
__pycache__/
*.pyc
build/
dist/
*.dmg
*.icns  # generated artifact, not source
models/  # downloaded at install/build time
hotkey_helper
paste_helper
VoxType.app/  # entire bundle is a build artifact
.superpowers/
```

**Release script** — `build/release.sh`:

```
1. Read current version from VERSION file
2. Bump per arg (./release.sh patch | minor | major | <explicit>)
3. Verify clean working tree
4. Run pyinstaller VoiceType.spec
5. Codesign --sign - --deep --force on the .app
6. Build VoiceType.dmg via create-dmg with brand background
7. Compute SHA256 of the DMG, write to dist/VoiceType.dmg.sha256
8. git tag v0.x.y
9. git push --tags origin main
10. gh release create v0.x.y VoiceType.dmg VoiceType.dmg.sha256 \
       --notes "<from CHANGELOG.md, with SHA256 prepended>"
11. Print release URL + SHA256
```

End-to-end: ~15 seconds plus PyInstaller build time (~30s on M-series). Re-running with an already-published version aborts cleanly; partial-failure recovery (e.g. tag pushed but DMG upload failed) re-runs successfully because `gh release create` upserts assets.

The site's "Download for macOS" button links to `https://github.com/polistician/voicetype/releases/latest/download/VoiceType.dmg` — the URL is stable across versions. The site also displays the latest version's SHA256 (either hard-coded per release or fetched from the Releases API at deploy time).

**LICENSE file** — `LICENSE` at repo root, MIT, copyright `Beauregard Berton`. The site's footer links to it. The `Info.plist` `NSHumanReadableCopyright` field references it.

## 9. Data flow

**For the visitor:**
```
visit voicetype.polistician.ai
  → click "Download for macOS"
  → GitHub serves VoiceType.dmg (latest release)
  → DMG opens, user drags to Applications
  → user right-click → Open (Gatekeeper bypass, one time)
  → app launches → onboarding window
  → grant Microphone + Accessibility
  → live test: hold ⌥ C, "hello from VoiceType", text pastes
  → window closes, mic appears in menubar, ready
```

**For the maintainer (you):**
```
edit code in ~/voicetype/
  → test locally (python voxtype.py or open the .app)
  → git commit
  → ./build/release.sh patch
  → DMG attached to GitHub release
  → site CTA points at /releases/latest/ — no site update needed
```

**Boundary that does NOT cross:** `~/.voicetype/` (user data — config, corrections, snippets DB, profile, stats, decisions log) is never committed, never bundled, never sent anywhere. Source code reads/writes to this dir but the dir's contents stay on the user's machine.

**API key flow (DeepL today, generic for the future):**

```
user opens Settings → enters key in SecureField
  → clicks Verify
  → Python translator hits DeepL /usage with the key, validates HTTP 200
  → on success: keys_helper.swift writes to Keychain
       (service: com.polistician.voicetype.keys, account: deepl)
  → on failure: inline error, key not stored

at translate-time:
  voxtype.py needs to translate
  → translator.py calls keys_helper.swift get deepl
  → key returned in-memory only, never written to disk
  → DeepL request made over HTTPS
  → reply text pasted

at uninstall / reset:
  user clicks "Remove" in Settings → keys_helper.swift deletes the Keychain entry
```

Keys never appear in `config.json`, `~/.voicetype/`, logs, or any committed file.

## 10. Error handling and edge cases

**Site-side**
- GitHub release URL 404 (no release yet): the "Download" button should be disabled or replaced with "Coming soon" until v0.9.1+ is published. After first release, it's stable forever.
- Visitor on Linux/Windows: page should detect non-macOS UA and dim the download button with a "macOS only" caption. (Defer to follow-up if not trivial — current page already says macOS in meta.)

**App-side**
- First-launch detection failure (corrupted onboarding flag): the worst case is the user re-sees onboarding once. Acceptable.
- Mic/Accessibility permission denied: in-app banner with "Open System Settings" deeplink. The dictation hotkey simply doesn't fire until granted.
- Live tutorial step never produces a paste (e.g., user never holds the key, or audio device fails): "Skip" is always available; tutorial completion not gated on success.
- DeepL key verification fails (wrong key, network down, DeepL rate-limit): inline error in Settings/onboarding, key not stored, retry available.
- DeepL Keychain entry missing at translate-time (user removed it, fresh install): translator silently no-ops; menubar status briefly flashes "translation key missing".
- whisper.cpp model file missing/corrupted: app shows a fatal error overlay with a "Re-download model" button (calls a local endpoint that re-fetches `ggml-base.en.bin` from Hugging Face).
- DMG download interrupted: user redownloads — no state to corrupt.
- Existing user upgrading from `~/voxtype/`: the `migrate.sh` runs once at first launch of a new bundle if it detects `~/.voxtype/` and not `~/.voicetype/`. Copies, doesn't move (safety).
- DMG SHA256 mismatch (paranoid user verifies and finds drift): never silently OK; the published checksum is canonical, any mismatch indicates either a tampered download or a release-script bug — investigate before accepting.

**Release-side**
- `release.sh` fails after tag push but before DMG upload: re-run with same version — `gh release create` is idempotent for asset upload.
- Working tree dirty: script aborts. Force flag exists for explicit override.

## 11. Testing

**Site:**
- Visual review on staging URL.
- Cross-browser smoke (Safari, Chrome, Firefox on macOS; Chrome on Windows for non-Mac visitor handling).
- Lighthouse: target ≥95 on all four scores. Page is static, this is achievable.

**App bundle:**
- Clean-Mac install test: on a fresh user account (or after `rm -rf ~/.voicetype ~/Applications/VoiceType.app`), download DMG → verify SHA256 → drag → right-click Open → onboarding → live tutorial paste lands → completes onboarding. Must complete in under 60 seconds wall-clock.
- Permissions denial path: deny Mic and Accessibility on the system pane, return to onboarding — must not crash, must surface a clear retry.
- Live tutorial path: hold ⌥ C, say a phrase during onboarding screen 3, confirm the text appears in the test field.
- Skip-tutorial path: click skip on screen 3, confirm onboarding completes and menubar mic still functions.
- DeepL key path: in onboarding screen 4, paste a known-good key, click Verify, confirm Keychain entry exists; restart app, confirm translator can read the key without re-entering.
- DeepL key wrong: paste a fake key, click Verify, confirm inline error and no Keychain write.
- Settings re-entry: open Settings post-install, change the DeepL key, confirm Keychain updates without leaking plaintext to logs.
- Existing-user upgrade: simulate a `~/.voxtype/` setup (copy from real user dir), launch new bundle, confirm migration runs and old data is preserved at `~/.voicetype/`.
- Whisper inference smoke test: hold ⌥ C, say "hello world", confirm paste in TextEdit.

**Release script:**
- Dry-run mode (`--dry-run`) prints what would happen without writing tags or uploading.
- After v0.9.1 ships: download the GitHub Release DMG on a different Mac, run through the full install path. The button link → DMG → install → onboarding → first dictation must work end to end without me touching it.

**Steer overlay:**
- Existing functional behavior (search, paste, edit, delete, navigate) must be unchanged after the restyle.

## 12. Migration sequence (top-to-bottom)

The repo at design time is `~/voxtype/` with a launchd plist running `python ~/voxtype/voxtype.py`. The transition is one-time:

1. **Tarball backup** of `~/voxtype/` and `~/.voxtype/` (safety net before any moves).
2. **Cleanup commit** (per Section 8): commit current uncommitted enhancements + add untracked source files + new `.gitignore` + delete `launch.command` + untrack the bundle binaries. One commit, message `chore: pre-launch cleanup …`.
3. **Run `./migrate.sh`** (new script, written as part of implementation):
   - Renames `~/voxtype/` → `~/voicetype/` and copies `~/.voxtype/` → `~/.voicetype/`.
   - Updates path references in code (`~/.voxtype/` → `~/.voicetype/` in `snippets.py`, `voice_profile.py`, `corrections.py`, `stats.py`, `voxtype.py`, `user_fixes.py`, `transcript_history.py`).
   - Updates `Info.plist` bundle ID + bundle name, regenerates a clean .app shell.
   - Unloads old launchd plist (`com.voxtype.app`), loads new plist (`com.polistician.voicetype`).
   - Confirms the app starts cleanly under the new dir.
4. **Commit the migrated source** (second commit). Message: `chore: rename voxtype → voicetype, bundle ID com.polistician.voicetype`.
5. **Set up GitHub remote and push.** `gh repo create polistician/voicetype --public`, `git remote set-url`, `git push -u origin main`.
6. **Add LICENSE + README + brand assets + onboarding + Settings + new site**. Multiple commits as work progresses.
7. **First release.** `./build/release.sh 0.9.1` — builds DMG, signs, computes SHA256, tags, pushes, attaches to GH release.
8. **Site cutover** (per Section 13): deploy new `site/` dir to server, swap the Caddy/FastAPI mount for `voicetype.polistician.ai`, keep old dir as rollback insurance for one release cycle.

After v0.9.1 ships, every code change is a normal commit + optional `./release.sh patch|minor|major`.

## 13. Open questions / known unknowns

These are flagged for the implementation phase but should not gate spec sign-off:

- **PyInstaller and `pywhispercpp`** — bundling the C++ Whisper backend cleanly through PyInstaller is the riskiest technical step. Fallback: `py2app` (slower bundle, more native macOS conventions). If both fail, fall back to a `.app` shell that wraps a venv (uglier but reliable). Implementation plan should test PyInstaller first and have a budget to switch.
- **DMG branding tooling** — `create-dmg` works on Apple Silicon but DMG layouts are notoriously finicky. Acceptable fallback: generic DMG without custom background art for v0.9.1, polished version for v0.10.0.
- **Onboarding window-vs-menubar coordination** — the rumps app starts in menubar mode immediately; the onboarding window needs to take focus on first launch without breaking the existing background-thread Whisper model load. Implementation should validate this on a clean install before integrating.
- **Site cutover** — the `voicetype.polistician.ai` subdomain already serves a live page from the polistician-ventures FastAPI app. Cutover plan: build the new site in `~/voicetype/site/`, deploy alongside the existing static dir on the server (e.g., `voicetype-v2/`), test on a temporary path, then swap the subdomain mount to the new dir. Atomic switch; no DNS changes; old dir stays for one release as rollback insurance.

---

## Approval

Spec captures all decisions from the brainstorming session. If approved, the next step is `superpowers:writing-plans` skill to break this into a sequenced implementation plan with concrete tasks, file paths, and verification gates.
