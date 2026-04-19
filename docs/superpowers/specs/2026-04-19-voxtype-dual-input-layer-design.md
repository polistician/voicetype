# VoxType Dual-Input Layer — Design

**Status:** Draft
**Date:** 2026-04-19
**Scope:** Snippet manager as the first implementation of voice + keyboard as peer input channels in VoxType.

## 1. Motivation

VoxType today is a dictation tool: hold Option+C, speak, transcription gets pasted. The next step is a general realization — AI-era tools need **two first-class input layers**:

- **Keyboard layer**: precise, fast, deterministic, good for muscle memory and small-N browsing.
- **Voice layer**: semantic, fuzzy, good for scale (hundreds or thousands of items where you remember the concept, not the name).

Neither replaces the other. The snippet manager is the first VoxType surface where both inputs are peers. The same patterns — intent routing, embedding match, gated fallback, unified manager surface — will generalize to future surfaces (clipboard history, saved prompts, etc.). Those are explicitly out of scope for this spec.

## 2. Scope

**In scope (v1):**

- Intent router that classifies every Option+C transcription into an action.
- Snippet store (SQLite) supporting hundreds to low thousands of snippets.
- Local semantic matcher with confidence-gated fallback.
- A manager overlay (Option A palette style) usable by both keyboard and voice.
- A mini picker for ambiguous matches.
- Capture-from-clipboard and capture-from-last-transcriptions flows.

**Out of scope (explicit non-goals for v1):**

- Template variables (`{{date}}`, `{{clipboard}}`, cursor positioning).
- Folders or nested organization (tags only).
- Cross-device sync.
- Cloud LLM fallback — local embeddings only.
- Clipboard history browser, notes, other surfaces that the dual-input pattern would later generalize to.

## 3. User flows

### 3.1 Insert a snippet by voice

1. Hold Option+C; say "snippet deploy the crypto app" (or any natural description); release.
2. Whisper transcribes. Intent router sees the "snippet" trigger → parses description → semantic match.
3. Depending on confidence: paste immediately (top > 0.75), show mini picker (0.55–0.75), or open full overlay in search mode with the query pre-filled (< 0.55).

### 3.2 Insert a snippet by keyboard

1. Press Option+Shift+S → overlay opens.
2. Type to filter (FTS + prefix); ↑↓ to navigate; ⏎ to paste into the previous frontmost app.
3. Esc dismisses.

### 3.3 Open the manager by voice

1. Hold Option+C; say "open snippet overview" (or "show snippets", "snippet manager"); release.
2. Intent router routes to OPEN_OVERVIEW → overlay opens.

### 3.4 Capture a new snippet from something you just wrote

1. Select text, copy it (Cmd+C). Or: finish a dictation and realize it's reusable.
2. Open the overlay (Option+Shift+S or "open snippet overview").
3. The capture strip at the top shows the clipboard preview and the last 5 transcriptions.
4. ⌘S from the strip → creates a draft snippet with the clipboard body prefilled; you name it and tag it.

### 3.5 Edit / delete

1. In overlay, select a snippet. ⌘E to edit, ⌘⌫ to delete (with confirm).

## 4. Architecture

```
Option+C pressed → Recorder → Whisper transcription ("rich": text + conf + timing)
                                      │
                                      ▼
                           ┌──────────────────────┐
                           │ Intent Router        │  ← 4-layer reliability stack
                           │ intent.py            │
                           └──────────┬───────────┘
                                      ▼
             ┌────────────────────────┼────────────────────────────┐
             │                        │                            │
             ▼                        ▼                            ▼
     action: dictate         action: paste_snippet       action: open_overview
     (existing behavior)     (with description)          (no payload)
                                      │                            │
                                      ▼                            ▼
                             ┌─────────────────┐           ┌───────────────┐
                             │ Semantic Match  │           │ Overlay App   │
                             │ embedder.py     │           │ (SwiftUI)     │
                             └────────┬────────┘           └───────┬───────┘
                                      ▼                            │
                             ┌─────────────────┐                   │
                             │ Confidence gate │                   │
                             └────────┬────────┘                   │
                          ┌───────────┼───────────┐                │
                          ▼           ▼           ▼                │
                     direct paste   picker      overlay ──────────┘
                     (>0.75)        (0.55-      (with query
                                     0.75)       pre-filled)
```

### 4.1 Process model

- Existing Python process (`voxtype.py`) hosts intent router, store, embedder. No change to how it starts.
- A new Swift helper `snippet_overlay` (built alongside `hotkey_helper`) owns the overlay UI and mini picker. Communicates with Python over stdin/stdout, same pattern as `hotkey_helper.swift`.
- Python posts events to the overlay process on demand (OPEN, SHOW_PICKER, HIDE). Overlay posts back user actions (PASTE id, SAVE payload, EDIT id, DELETE id, SEARCH query).

### 4.2 Why SwiftUI, not Tkinter/PyObjC-from-Python

- Matches existing `hotkey_helper.swift` paradigm (one Swift helper per native surface).
- Native window chrome, vibrancy, responsive type-to-filter.
- Keeps heavy UI work off the Python main thread.
- The overlay also needs to capture keystrokes (including Option+C inside its own search field for "speak to search") — Cocoa event taps do this cleanly.

## 5. Components

### 5.1 `intent.py` (new)

```python
class Intent:
    action: Literal["dictate", "paste_snippet", "open_overview", "save_snippet"]
    payload: dict  # {"description": "..."} for paste_snippet; empty otherwise
    confidence: float  # 0..1 for how sure we are it wasn't just dictation

def route(transcription: str) -> Intent: ...
```

Four-layer reliability stack:

1. **Whisper vocabulary bias** (existing). Extend `get_whisper_prompt()` to include: `"snippet", "snippets", "overview", "insert", "paste"` + all snippet names.
2. **Fuzzy trigger detection**. First 1–3 tokens matched against `{"snippet", "snippets", "insert snippet", "paste snippet", "open snippet", "show snippet", "save snippet", "new snippet"}` via `rapidfuzz.fuzz.partial_ratio >= 85`. Handles "snip it", "snipped", "senate", etc.
3. **Rule-based action parsing**. Given trigger detected:
   - contains `open|show|launch|bring up` + `overview|overlay|manager|list|snippets` → `open_overview` (all three phrasings "open snippet overview", "show snippet manager", "open snippets" route to the same action)
   - contains "save|new|create" (with optional "from clipboard") → `save_snippet`
   - everything else after the trigger → `paste_snippet` with `description = rest of transcription`
4. **No-trigger fallback**. If no trigger detected → `dictate` (existing behavior).

### 5.1.1 Transcription history buffer

Maintained in `voxtype.py` as an in-memory ring buffer (size 10) of recent transcriptions (text + timestamp). Not persisted across restarts. Drives the "Last dictated" rows in the overlay's capture strip. No additional storage.

### 5.2 `snippets.py` (new)

SQLite at `~/.voxtype/snippets.db`.

```sql
CREATE TABLE snippets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  body TEXT NOT NULL,
  tags TEXT DEFAULT '',  -- comma-separated, low-churn
  created_at INTEGER NOT NULL,
  used_count INTEGER DEFAULT 0,
  last_used_at INTEGER,
  embedding BLOB  -- float32 array, dim = model dim
);
CREATE VIRTUAL TABLE snippets_fts USING fts5(name, description, body, tags, content='snippets', content_rowid='id');
-- triggers to keep FTS in sync
```

Public API:

```python
def list_all() -> list[Snippet]
def search_text(query: str, limit: int = 20) -> list[Snippet]  # FTS
def match_semantic(query: str, k: int = 5) -> list[tuple[Snippet, float]]  # cosine
def create(name, body, description='', tags='') -> Snippet  # embeds on create
def update(id, **fields) -> Snippet  # re-embeds if name/description/tags changed
def delete(id) -> None
def record_use(id) -> None  # increments used_count, updates last_used_at
```

### 5.3 `embedder.py` (new)

- Model: `mxbai-embed-xsmall-v1` via `sentence-transformers`.
- One-time download to `~/.voxtype/models/mxbai-embed-xsmall-v1/` on first use; lazy-loaded.
- Encoding target string for each snippet: `f"{name}. {description}. Tags: {tags}"`.
- In-memory cache: dict `{id: vector}` rebuilt at startup from the `embedding` column; kept hot so queries avoid SQLite reads. Invalidated on update/create/delete.
- `match(query: str, k: int) -> list[(id, score)]`: encodes query, cosine vs cache, returns top-k sorted.

### 5.4 Overlay app (`snippet_overlay/` — SwiftUI)

Single-window floating panel, centered on active display, dismissable with Esc.

Layout (mirrors mockup A, refined for speech-input):

```
┌────────────────────────────────────────────────────────┐
│  🔍 [search field, also accepts voice: Option+C]       │
│                                                         │
│  📋 Clipboard: "…"       ⌘S save    ← capture strip    │
│  🎤 Last dictated: "…"   ⌘D save                       │
│                                                         │
│  ► deploy v3       42×   ./v3/jobs/sync_from_server… │
│    deploy soma     17×   cd ~/soma && git push…       │
│    deploy super…    8×   scp dashboard.html…          │
│                                                         │
│  ↑↓ · ⏎ paste · ⌘N new · ⌘E edit · ⌘⌫ delete           │
└────────────────────────────────────────────────────────┘
```

Input modes:
- Keyboard: type to filter (FTS → matching snippets live).
- Voice: press-and-hold Option+C with overlay focused → Whisper transcribes into the search field. Hitting ⏎ right after transcription pastes the top match (same confidence gating as voice invocation). This makes voice a peer input *inside* the overlay, not just to open it.
- Arrow keys + Enter to select; ⌘1/⌘2/⌘3 as quick-select for top 3.
- ⌘N: creates a new snippet, opens edit pane.
- ⌘E: edits selected.
- ⌘⌫: deletes with one-step undo (5s toast, ⌘Z to undo).
- Esc: dismiss. Overlay never steals focus from the previously-frontmost app on paste.

### 5.5 Mini picker (SwiftUI, same target)

Small floating HUD at the cursor / center of screen when semantic match is ambiguous (0.55–0.75):

```
┌──────────────────────────────────────┐
│ Did you mean:                        │
│  1. deploy v3           (0.71)       │
│  2. deploy soma         (0.68)       │
│  3. deploy superhuman   (0.64)       │
│  Esc to cancel                       │
└──────────────────────────────────────┘
```

- Press 1/2/3 → paste.
- ↑↓ + Enter also works.
- Esc → cancel, no paste.
- Auto-dismisses after 4s of no input (safer than auto-paste on timeout).

## 6. Hotkeys (updated)

| Hotkey | Action | Status |
|---|---|---|
| Option+C (hold) | Dictate → intent-route | Existing, new behavior |
| Option+T | Translate clipboard | Existing, unchanged |
| Option+Shift+S | Open snippet overlay | New |

Inside overlay: Option+C (hold) dictates into the search field.

## 7. Reliability stack (summary)

| Layer | What it does | Fires when |
|---|---|---|
| 1. Whisper vocab bias | Primes recognition toward trigger words + snippet names | Every transcription |
| 2. Fuzzy trigger detection | Catches `snip it`, `sniped`, `snippets`, `senate` → treat as trigger | First 1–3 tokens |
| 3. Rule-based action parse | Split into `paste_snippet` / `open_overview` / `save_snippet` | When trigger present |
| 4. Confidence gate | Top > 0.75 paste, 0.55–0.75 picker, < 0.55 full overlay with query | paste_snippet only |

No silent failures: any ambiguous match drops into a picker. Every voice action has a keyboard equivalent. Every mis-routed transcription is logged to `~/.voxtype/logs/intent.jsonl` (with consent) for future tuning.

## 8. Storage & migration

- New file: `~/.voxtype/snippets.db`.
- No existing snippet data to migrate.
- Embedding regenerated if `~/.voxtype/config.json` records a different `embedding_model` than what's stored — handled lazily at startup.

## 9. Dependencies added

- `sentence-transformers` (PyTorch-based). Simplest path; VoxType already has a heavy-dep profile via Whisper. If footprint becomes a problem later, swap to `mlx-embeddings` — the `embedder.py` interface hides the choice.
- `rapidfuzz` (small, pure-C fuzzy matching).
- Swift overlay app needs no extra deps beyond Cocoa/SwiftUI.

## 10. Testing approach

- Unit tests for `intent.py`: table-driven cases covering 30+ transcription variants (clean, Whisper-garbled, mixed-case, with/without trigger words, edge cases like "this is a snippet of code I wrote").
- Unit tests for `snippets.py`: CRUD, FTS search behavior, embedding regeneration.
- Integration test for the match → paste flow with a fixed corpus.
- Manual test plan for the overlay (keyboard + voice paths).

## 11. Open questions

None blocking v1. Deferred:
- Whether to log intent decisions by default or require opt-in (lean toward opt-in, default off).
- Whether mini picker appears at cursor or screen center (default: center of active display; revisit after use).
- Whether to fingerprint snippet *body* into the embedding too (default: no — names/descriptions/tags are what the user will speak).

## 12. Future extensions (not designed here)

- Generalize the dual-input pattern to other surfaces (clipboard history, saved prompts, notes).
- Plugin API so other macOS apps can expose their own "voice-addressable" surfaces via VoxType.
- Template variables.
- Sync to iOS or iCloud.
