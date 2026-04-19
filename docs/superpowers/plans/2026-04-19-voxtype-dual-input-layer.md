# VoxType Dual-Input Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship voice + keyboard as peer input channels in VoxType, with a snippet manager as the first surface: voice invocation ("snippet deploy v3" / "open snippet overview"), keyboard overlay (Option+Shift+S), semantic local matching, confidence-gated paste / mini picker / full overlay.

**Architecture:** Post-Whisper intent router routes every transcription to `dictate` / `paste_snippet` / `open_overview` / `save_snippet`. SQLite store with FTS + cached embeddings (mxbai-embed-xsmall-v1). SwiftUI overlay helper mirrors the existing `hotkey_helper.swift` pattern — communicates with Python via stdin/stdout.

**Tech Stack:** Python 3.11, rumps, sentence-transformers, rapidfuzz, SQLite (stdlib), SwiftUI/Cocoa (overlay helper), Carbon (hotkeys).

**Spec:** `docs/superpowers/specs/2026-04-19-voxtype-dual-input-layer-design.md`

**Working directory for all tasks:** `/Users/beauregard/voxtype`

---

## File map

**New Python modules (repo root):**
- `snippets.py` — SQLite store + FTS + embedding BLOB, CRUD + search API
- `embedder.py` — sentence-transformers wrapper + in-memory vector cache + cosine match
- `intent.py` — 4-layer intent router (vocab → fuzzy trigger → rule parse → dictate fallback)
- `transcript_history.py` — in-memory ring buffer of last N transcriptions
- `overlay_bridge.py` — spawns Swift overlay helper, emits events, reads user actions

**New tests (repo root, matching existing pattern):**
- `test_snippets.py`, `test_embedder.py`, `test_intent.py`, `test_transcript_history.py`

**New Swift helper:**
- `snippet_overlay.swift` — SwiftUI overlay window (list + search + detail + capture strip) and mini picker mode
- Compiled into `VoxType.app/Contents/MacOS/snippet_overlay` (next to `hotkey_helper`)

**Modified files:**
- `requirements.txt` — add `sentence-transformers`, `rapidfuzz`
- `voxtype.py` — call intent router after transcription; dispatch actions; feed history buffer; forward events to overlay
- `hotkey_helper.swift` — register Option+Shift+S; emit `OPEN_OVERLAY` event
- `hotkey.py` — surface new `on_open_overlay` callback
- `install.sh` — compile `snippet_overlay.swift` during install

---

## Conventions this plan follows

- Tests are runnable by `python test_<module>.py` (matches existing VoxType style) and also via `pytest` if preferred.
- All new Python files start with a module docstring, same style as `corrections.py`.
- Storage under `~/.voxtype/` matches existing pattern (`config.json`, `corrections.json`, `profile.json`).
- Commits are small, frequent, and use the project's short-prefix style (`feat:`, `fix:`, `test:`).
- **Before committing any task, run the task's tests and verify they pass.** Do not commit on a red test.

---

### Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Edit requirements.txt**

Add two lines so it reads:

```
pywhispercpp
sounddevice
pynput
rumps
numpy
sentence-transformers
rapidfuzz
```

- [ ] **Step 2: Install into the project venv**

Run: `/Users/beauregard/voxtype/.venv/bin/pip install sentence-transformers rapidfuzz`
Expected: both install successfully. `sentence-transformers` will pull in `torch` and `transformers` (large, but VoxType already has them implicitly via `pywhispercpp`-adjacent tooling).

- [ ] **Step 3: Smoke test imports**

Run: `/Users/beauregard/voxtype/.venv/bin/python -c "import sentence_transformers, rapidfuzz; print('OK')"`
Expected output: `OK`

- [ ] **Step 4: Commit**

```bash
git add requirements.txt
git commit -m "feat: add sentence-transformers + rapidfuzz for snippet matching"
```

---

### Task 2: `snippets.py` — SQLite store + FTS

**Files:**
- Create: `snippets.py`
- Create: `test_snippets.py`

- [ ] **Step 1: Write the failing test — CRUD + FTS**

Create `test_snippets.py`:

```python
# test_snippets.py
import os
import tempfile
import pytest

from snippets import Store


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = Store(path=path)
    yield s
    s.close()
    os.unlink(path)


def test_create_and_list(store):
    s = store.create(name="deploy v3", body="./deploy.sh", description="push crypto app")
    assert s.id is not None
    assert s.name == "deploy v3"
    all_ = store.list_all()
    assert len(all_) == 1
    assert all_[0].id == s.id


def test_update(store):
    s = store.create(name="orig", body="x")
    store.update(s.id, name="renamed", body="y")
    loaded = store.get(s.id)
    assert loaded.name == "renamed"
    assert loaded.body == "y"


def test_delete(store):
    s = store.create(name="trash", body="x")
    store.delete(s.id)
    assert store.get(s.id) is None
    assert store.list_all() == []


def test_search_text_fts(store):
    store.create(name="deploy v3", body="./deploy.sh", description="push crypto app")
    store.create(name="pytest watch", body="pytest -q --looponfail", tags="testing")
    store.create(name="brew cleanup", body="brew cleanup -s")

    hits = store.search_text("deploy")
    assert len(hits) == 1
    assert hits[0].name == "deploy v3"

    hits = store.search_text("crypto")
    assert len(hits) == 1  # found via description

    hits = store.search_text("testing")
    assert len(hits) == 1  # found via tags


def test_record_use(store):
    s = store.create(name="a", body="x")
    assert s.used_count == 0
    store.record_use(s.id)
    store.record_use(s.id)
    loaded = store.get(s.id)
    assert loaded.used_count == 2
    assert loaded.last_used_at is not None


def test_default_db_path_configurable(store):
    # Store accepts custom path (already used above); confirms we don't hardcode
    assert store.path.endswith(".db")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_snippets.py -v`
Expected: `ModuleNotFoundError: No module named 'snippets'`

- [ ] **Step 3: Implement `snippets.py`**

Create `snippets.py`:

```python
# snippets.py
"""SQLite-backed snippet store with FTS5 text search and embedding BLOB column.

One snippet is one reusable text fragment. The store handles persistence,
text search (via FTS5), and holds the cached embedding for semantic match.
Embedding generation itself lives in embedder.py — this module only persists.
"""
from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional


DEFAULT_DB_PATH = os.path.expanduser("~/.voxtype/snippets.db")


@dataclass
class Snippet:
    id: int
    name: str
    description: str
    body: str
    tags: str
    created_at: int
    used_count: int
    last_used_at: Optional[int]
    embedding: Optional[bytes]


class Store:
    def __init__(self, path: str = DEFAULT_DB_PATH):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS snippets (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL,
          tags TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          used_count INTEGER NOT NULL DEFAULT 0,
          last_used_at INTEGER,
          embedding BLOB
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS snippets_fts USING fts5(
          name, description, body, tags,
          content='snippets', content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS snippets_ai AFTER INSERT ON snippets BEGIN
          INSERT INTO snippets_fts(rowid, name, description, body, tags)
          VALUES (new.id, new.name, new.description, new.body, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS snippets_ad AFTER DELETE ON snippets BEGIN
          INSERT INTO snippets_fts(snippets_fts, rowid, name, description, body, tags)
          VALUES ('delete', old.id, old.name, old.description, old.body, old.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS snippets_au AFTER UPDATE ON snippets BEGIN
          INSERT INTO snippets_fts(snippets_fts, rowid, name, description, body, tags)
          VALUES ('delete', old.id, old.name, old.description, old.body, old.tags);
          INSERT INTO snippets_fts(rowid, name, description, body, tags)
          VALUES (new.id, new.name, new.description, new.body, new.tags);
        END;
        """)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ---- CRUD ----
    def create(self, name: str, body: str, description: str = "", tags: str = "") -> Snippet:
        now = int(time.time())
        cur = self.conn.execute(
            "INSERT INTO snippets (name, description, body, tags, created_at) VALUES (?, ?, ?, ?, ?)",
            (name, description, body, tags, now),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def update(self, id: int, **fields) -> Snippet:
        allowed = {"name", "description", "body", "tags", "embedding"}
        cols = [k for k in fields if k in allowed]
        if not cols:
            return self.get(id)
        values = [fields[k] for k in cols] + [id]
        sql = f"UPDATE snippets SET {', '.join(f'{c}=?' for c in cols)} WHERE id=?"
        self.conn.execute(sql, values)
        self.conn.commit()
        return self.get(id)

    def delete(self, id: int) -> None:
        self.conn.execute("DELETE FROM snippets WHERE id=?", (id,))
        self.conn.commit()

    def get(self, id: int) -> Optional[Snippet]:
        row = self.conn.execute("SELECT * FROM snippets WHERE id=?", (id,)).fetchone()
        return self._row_to_snippet(row) if row else None

    def list_all(self) -> list[Snippet]:
        rows = self.conn.execute("SELECT * FROM snippets ORDER BY used_count DESC, name ASC").fetchall()
        return [self._row_to_snippet(r) for r in rows]

    def search_text(self, query: str, limit: int = 20) -> list[Snippet]:
        # FTS5 query — escape double quotes in the user query
        q = query.replace('"', '""')
        fts_query = f'"{q}"*'  # prefix match
        rows = self.conn.execute(
            """SELECT s.* FROM snippets s
               JOIN snippets_fts f ON s.id = f.rowid
               WHERE snippets_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (fts_query, limit),
        ).fetchall()
        return [self._row_to_snippet(r) for r in rows]

    def record_use(self, id: int) -> None:
        now = int(time.time())
        self.conn.execute(
            "UPDATE snippets SET used_count = used_count + 1, last_used_at = ? WHERE id = ?",
            (now, id),
        )
        self.conn.commit()

    def _row_to_snippet(self, row) -> Snippet:
        return Snippet(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            body=row["body"],
            tags=row["tags"],
            created_at=row["created_at"],
            used_count=row["used_count"],
            last_used_at=row["last_used_at"],
            embedding=row["embedding"],
        )
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_snippets.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add snippets.py test_snippets.py
git commit -m "feat: SQLite snippet store with FTS5 text search"
```

---

### Task 3: `embedder.py` — local embedding model + cache

**Files:**
- Create: `embedder.py`
- Create: `test_embedder.py`

- [ ] **Step 1: Write the failing test**

Create `test_embedder.py`:

```python
# test_embedder.py
import numpy as np
import pytest

from embedder import Embedder


@pytest.fixture(scope="module")
def embedder():
    # Using a tiny model so tests stay under a minute
    return Embedder(model_name="sentence-transformers/all-MiniLM-L6-v2")


def test_encode_returns_vector(embedder):
    vec = embedder.encode("hello world")
    assert isinstance(vec, np.ndarray)
    assert vec.dtype == np.float32
    assert vec.ndim == 1
    assert vec.shape[0] > 0


def test_encode_batch(embedder):
    vecs = embedder.encode_batch(["foo", "bar", "baz"])
    assert vecs.shape[0] == 3
    assert vecs.shape[1] == embedder.dim


def test_cosine_similarity_self(embedder):
    v = embedder.encode("deploy the v3 production system")
    sim = embedder.cosine(v, v)
    assert abs(sim - 1.0) < 1e-5


def test_semantic_match_ranks_related_higher(embedder):
    queries_close = ("deploy production", "ship the app to prod")
    queries_far = ("deploy production", "make a sandwich")
    v_a = embedder.encode(queries_close[0])
    v_b = embedder.encode(queries_close[1])
    v_far = embedder.encode(queries_far[1])
    sim_close = embedder.cosine(v_a, v_b)
    sim_far = embedder.cosine(v_a, v_far)
    assert sim_close > sim_far


def test_match_ranks(embedder):
    # Build a mini cache and search
    cache = {
        1: embedder.encode("deploy v3 production to server"),
        2: embedder.encode("brew cleanup the machine"),
        3: embedder.encode("run pytest in watch mode"),
    }
    hits = embedder.match("push v3 to prod", cache, k=3)
    # Top hit should be id=1
    assert hits[0][0] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_embedder.py -v`
Expected: `ModuleNotFoundError: No module named 'embedder'`

- [ ] **Step 3: Implement `embedder.py`**

Create `embedder.py`:

```python
# embedder.py
"""Local sentence embedding model + cosine matcher.

The first model load downloads weights (cached under ~/.cache/huggingface/).
For production use we pin mxbai-embed-xsmall-v1 (Apache 2.0, ~22M params,
MiniLM-successor quality). Tests use all-MiniLM-L6-v2 because it's ubiquitous.
"""
from __future__ import annotations

import numpy as np
from typing import Iterable


DEFAULT_MODEL = "mixedbread-ai/mxbai-embed-xsmall-v1"


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        # Lazy import so `import embedder` stays fast and testable
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, text: str) -> np.ndarray:
        vec = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vec.astype(np.float32)

    def encode_batch(self, texts: Iterable[str]) -> np.ndarray:
        vecs = self._model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=True)
        return vecs.astype(np.float32)

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        # Inputs are expected to be normalized — dot product is cosine similarity
        return float(np.dot(a, b))

    def match(self, query: str, cache: dict[int, np.ndarray], k: int = 5) -> list[tuple[int, float]]:
        """Rank cache entries against the query by cosine similarity. Returns top k."""
        if not cache:
            return []
        qvec = self.encode(query)
        scored = [(sid, self.cosine(qvec, vec)) for sid, vec in cache.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    @staticmethod
    def blob_to_array(blob: bytes, dim: int) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32, count=dim)

    @staticmethod
    def array_to_blob(arr: np.ndarray) -> bytes:
        return arr.astype(np.float32).tobytes()
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_embedder.py -v`
Expected: all 5 tests pass. First run may take 30–60s to download `all-MiniLM-L6-v2` weights.

- [ ] **Step 5: Commit**

```bash
git add embedder.py test_embedder.py
git commit -m "feat: local embedding matcher (mxbai-embed-xsmall-v1 default)"
```

---

### Task 4: `intent.py` — 4-layer intent router

**Files:**
- Create: `intent.py`
- Create: `test_intent.py`

- [ ] **Step 1: Write the failing test (table-driven, comprehensive)**

Create `test_intent.py`:

```python
# test_intent.py
import pytest

from intent import route, Intent


# Table: (transcription, expected_action, expected_payload_desc or None)
CASES = [
    # --- dictate: no trigger ---
    ("let me send you an email about the meeting", "dictate", None),
    ("this is a snippet of code I wrote", "dictate", None),  # "snippet" mid-sentence should NOT trigger
    ("", "dictate", None),

    # --- paste_snippet: clean trigger ---
    ("snippet deploy v3", "paste_snippet", "deploy v3"),
    ("snippet the one for crypto app deployment", "paste_snippet", "the one for crypto app deployment"),
    ("insert snippet pytest watch", "paste_snippet", "pytest watch"),
    ("paste snippet brew cleanup", "paste_snippet", "brew cleanup"),
    ("use snippet deploy soma", "paste_snippet", "deploy soma"),

    # --- paste_snippet: fuzzy trigger (Whisper misrecognitions) ---
    ("snipped deploy v3", "paste_snippet", "deploy v3"),
    ("snip it deploy v3", "paste_snippet", "deploy v3"),
    ("senate deploy v3", "paste_snippet", "deploy v3"),   # Whisper sometimes mishears
    ("snippets deploy v3", "paste_snippet", "deploy v3"),  # plural

    # --- open_overview variants ---
    ("open snippet overview", "open_overview", None),
    ("open snippets", "open_overview", None),
    ("show snippet manager", "open_overview", None),
    ("show snippets", "open_overview", None),
    ("launch snippet overlay", "open_overview", None),
    ("bring up the snippet list", "open_overview", None),

    # --- save_snippet ---
    ("save snippet", "save_snippet", None),
    ("save snippet from clipboard", "save_snippet", None),
    ("new snippet", "save_snippet", None),
    ("create snippet from clipboard", "save_snippet", None),

    # --- case + punctuation robustness ---
    ("Snippet Deploy v3", "paste_snippet", "Deploy v3"),
    ("Snippet, deploy v3.", "paste_snippet", "deploy v3"),
    ("SNIPPET DEPLOY V3", "paste_snippet", "DEPLOY V3"),
]


@pytest.mark.parametrize("text,expected_action,expected_desc", CASES)
def test_route(text, expected_action, expected_desc):
    r = route(text)
    assert r.action == expected_action, f"{text!r} → got {r.action}, expected {expected_action}"
    if expected_desc is not None:
        assert r.payload.get("description", "").strip() == expected_desc.strip()


def test_route_returns_intent_dataclass():
    r = route("snippet x")
    assert isinstance(r, Intent)
    assert hasattr(r, "action")
    assert hasattr(r, "payload")
    assert hasattr(r, "confidence")


def test_dictate_has_full_text_in_payload():
    r = route("let me explain the plan")
    assert r.action == "dictate"
    assert r.payload.get("text") == "let me explain the plan"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_intent.py -v`
Expected: `ModuleNotFoundError: No module named 'intent'`

- [ ] **Step 3: Implement `intent.py`**

Create `intent.py`:

```python
# intent.py
"""Post-transcription intent router for VoxType.

Classifies every transcription into one of:
  - dictate: paste the transcription as-is (legacy behavior)
  - paste_snippet: semantic-match the description to a snippet
  - open_overview: open the snippet manager overlay
  - save_snippet: open overlay with a draft prefilled from clipboard

Reliability layers (see spec §5.1 and §7):
  1. Whisper vocabulary prompt bias (lives in voxtype.py / voice_profile.py)
  2. Fuzzy trigger detection (rapidfuzz on first 1–3 tokens)
  3. Rule-based action parse
  4. Default to 'dictate' if nothing trips
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz


Action = Literal["dictate", "paste_snippet", "open_overview", "save_snippet"]


@dataclass
class Intent:
    action: Action
    payload: dict = field(default_factory=dict)
    confidence: float = 1.0


# Tokens that count as "the snippet trigger"; fuzzy-matched (partial_ratio >= 85)
_TRIGGER_TOKENS = {"snippet", "snippets", "snipped", "snip it", "senate"}

# Single-token trigger words (first word of transcription)
_SINGLE_TRIGGERS = {"snippet", "snippets", "snipped", "senate"}

# Two-token trigger prefixes
_TWO_TOKEN_TRIGGERS = {
    ("insert", "snippet"),
    ("paste", "snippet"),
    ("use", "snippet"),
    ("open", "snippet"),
    ("show", "snippet"),
    ("launch", "snippet"),
    ("save", "snippet"),
    ("new", "snippet"),
    ("create", "snippet"),
    ("snip", "it"),
}

# Three-token trigger prefixes (for "bring up the snippet …")
_THREE_TOKEN_TRIGGERS = {
    ("bring", "up", "the"),
    ("bring", "up", "snippet"),
}

# Action keywords (second-layer parse, after trigger detected)
_OPEN_VERBS = {"open", "show", "launch", "bring"}
_OPEN_NOUNS = {"overview", "overlay", "manager", "list", "snippets"}
_SAVE_VERBS = {"save", "new", "create"}


def route(text: str) -> Intent:
    """Route a transcription to an action."""
    raw = text
    cleaned = _clean(text)
    if not cleaned:
        return Intent(action="dictate", payload={"text": raw}, confidence=1.0)

    tokens = cleaned.split()
    trigger_span = _detect_trigger(tokens)

    if trigger_span is None:
        return Intent(action="dictate", payload={"text": raw}, confidence=1.0)

    # tokens consumed by the trigger; everything after is the payload / action verb
    after = tokens[trigger_span:]

    # -- open_overview --
    first = (after[0] if after else "")
    second = (after[1] if len(after) > 1 else "")
    third = (after[2] if len(after) > 2 else "")

    # bring up + the + snippet list/manager
    words_after_cleaned = [w for w in after if w not in {"the", "a", "an", "my"}]
    if tokens[0:3] == ["bring", "up", "the"]:
        # trigger already consumed bring/up/the — "after" starts with "snippet …"
        pass

    joined = " ".join(after).lower()
    if _mentions_open(joined) and _mentions_overview_noun(joined):
        return Intent(action="open_overview", confidence=0.95)
    if joined in {"", "snippets", "snippet list", "snippet manager", "snippet overview", "snippet overlay"} and _starts_with_open_verb(tokens):
        return Intent(action="open_overview", confidence=0.9)

    # -- save_snippet --
    if _starts_with_save_verb(tokens):
        return Intent(action="save_snippet", payload={"from_clipboard": "clipboard" in joined}, confidence=0.95)

    # -- paste_snippet --
    # Everything after the trigger span, reassembled from the ORIGINAL text, not the cleaned one —
    # we want to preserve user's casing in the description.
    desc = _extract_payload_preserve_case(raw, trigger_span)
    return Intent(action="paste_snippet", payload={"description": desc}, confidence=0.9)


def _clean(text: str) -> str:
    # lowercase, strip trailing punctuation, collapse whitespace. Keep internal periods for things like "v3".
    t = text.strip().lower()
    t = re.sub(r"[.,!?;:]+$", "", t)
    t = re.sub(r"^[.,!?;:]+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _detect_trigger(tokens: list[str]) -> int | None:
    """Return the number of tokens consumed by the trigger, or None if no trigger."""
    if not tokens:
        return None
    # 3-token
    if tuple(tokens[:3]) in _THREE_TOKEN_TRIGGERS:
        return 3
    # 2-token
    if len(tokens) >= 2 and tuple(tokens[:2]) in _TWO_TOKEN_TRIGGERS:
        return 2
    # 1-token direct match
    if tokens[0] in _SINGLE_TRIGGERS:
        return 1
    # 1-token fuzzy (handles "snippets"/"snipped"/"senate"/mild misspellings)
    score = max(fuzz.ratio(tokens[0], t) for t in ("snippet", "snippets"))
    if score >= 85:
        return 1
    return None


def _mentions_open(s: str) -> bool:
    return any(v in s.split() for v in _OPEN_VERBS)


def _mentions_overview_noun(s: str) -> bool:
    return any(n in s.split() for n in _OPEN_NOUNS)


def _starts_with_open_verb(tokens: list[str]) -> bool:
    return bool(tokens) and tokens[0] in _OPEN_VERBS


def _starts_with_save_verb(tokens: list[str]) -> bool:
    return bool(tokens) and tokens[0] in _SAVE_VERBS


def _extract_payload_preserve_case(raw: str, tokens_consumed: int) -> str:
    """Re-extract the part of `raw` that comes AFTER the first N tokens, preserving original casing."""
    # Walk through raw, skipping over tokens_consumed whitespace-separated runs
    stripped = raw.strip()
    stripped = re.sub(r"^[.,!?;:]+", "", stripped)
    parts = stripped.split(None, tokens_consumed)
    if len(parts) <= tokens_consumed:
        return ""
    payload = parts[tokens_consumed]
    # Strip trailing sentence punctuation
    payload = re.sub(r"[.,!?;:]+$", "", payload).strip()
    return payload
```

- [ ] **Step 4: Run the test and fix until green**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_intent.py -v`
Expected: all 25+ cases pass. If any fail, read the failing case and adjust `intent.py` (common: a phrase that should route to `open_overview` is landing in `paste_snippet` because `mentions_open`/`mentions_overview_noun` logic misses — extend the keyword sets).

- [ ] **Step 5: Commit**

```bash
git add intent.py test_intent.py
git commit -m "feat: 4-layer intent router — voice snippet commands vs dictation"
```

---

### Task 5: `transcript_history.py` — in-memory ring buffer

**Files:**
- Create: `transcript_history.py`
- Create: `test_transcript_history.py`

- [ ] **Step 1: Write the failing test**

Create `test_transcript_history.py`:

```python
# test_transcript_history.py
from transcript_history import History


def test_empty():
    h = History(size=5)
    assert h.recent() == []


def test_push_and_recent():
    h = History(size=3)
    h.push("one")
    h.push("two")
    h.push("three")
    items = h.recent()
    assert [e.text for e in items] == ["three", "two", "one"]


def test_ring_buffer_drops_oldest():
    h = History(size=3)
    for t in ["a", "b", "c", "d", "e"]:
        h.push(t)
    items = [e.text for e in h.recent()]
    assert items == ["e", "d", "c"]


def test_entries_have_timestamps():
    h = History(size=3)
    h.push("hello")
    entries = h.recent()
    assert entries[0].timestamp > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
```

- [ ] **Step 2: Run the test to confirm it fails**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_transcript_history.py -v`
Expected: `ModuleNotFoundError: No module named 'transcript_history'`

- [ ] **Step 3: Implement `transcript_history.py`**

Create `transcript_history.py`:

```python
# transcript_history.py
"""In-memory ring buffer of recent transcriptions.

Not persisted. Feeds the overlay's "Last dictated" capture strip so you can
turn a thing you just said into a snippet without typing it again.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Entry:
    text: str
    timestamp: float


class History:
    def __init__(self, size: int = 10):
        self._buf: deque[Entry] = deque(maxlen=size)

    def push(self, text: str) -> None:
        if text:
            self._buf.append(Entry(text=text, timestamp=time.time()))

    def recent(self) -> list[Entry]:
        """Most-recent-first list of entries."""
        return list(reversed(self._buf))

    def clear(self) -> None:
        self._buf.clear()
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `/Users/beauregard/voxtype/.venv/bin/python -m pytest test_transcript_history.py -v`
Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add transcript_history.py test_transcript_history.py
git commit -m "feat: transcript history ring buffer for overlay capture strip"
```

---

### Task 6: Integrate intent router into `voxtype.py` (dictate + paste_snippet direct-paste path)

In this task we wire the router for TWO of four actions. The overlay doesn't exist yet, so `open_overview` and `save_snippet` just log for now; `paste_snippet` works end-to-end via direct paste (no picker yet — that comes with the overlay).

**Files:**
- Modify: `voxtype.py`

- [ ] **Step 1: Add imports and init new modules**

In `voxtype.py`, add after existing imports:

```python
from intent import route as route_intent
from snippets import Store as SnippetStore
from embedder import Embedder
from transcript_history import History as TranscriptHistory
import numpy as np
```

- [ ] **Step 2: Initialize store + embedder + history in `VoxType.__init__`**

After `self.paster.set_hotkey(self.hotkey)` (end of `__init__`), add:

```python
        # Snippet infrastructure — lazy init embedder to avoid blocking startup
        self.snippet_store = SnippetStore()
        self.embedder = None
        self._embedder_ready = threading.Event()
        self.snippet_cache: dict[int, np.ndarray] = {}
        self.transcript_history = TranscriptHistory(size=10)
        threading.Thread(target=self._load_embedder, daemon=True).start()
```

And add the embedder-loader method inside the `VoxType` class:

```python
    def _load_embedder(self):
        try:
            self.embedder = Embedder()
            self._rebuild_snippet_cache()
            self._embedder_ready.set()
            print("Embedder loaded", flush=True)
        except Exception as e:
            print(f"Embedder failed to load: {e}", flush=True)

    def _rebuild_snippet_cache(self):
        self.snippet_cache.clear()
        for s in self.snippet_store.list_all():
            if s.embedding:
                self.snippet_cache[s.id] = Embedder.blob_to_array(s.embedding, self.embedder.dim)
            else:
                # Missing embedding — compute and persist now
                vec = self.embedder.encode(f"{s.name}. {s.description}. Tags: {s.tags}")
                self.snippet_store.update(s.id, embedding=Embedder.array_to_blob(vec))
                self.snippet_cache[s.id] = vec
```

- [ ] **Step 3: Replace `_transcribe_and_paste` body to route through intent**

Find the method in `voxtype.py`. Replace the `if text:` block (starting at line 125 in the current file — confirm by `grep -n "if text:"` before editing) with:

```python
        if text:
            # 1. Apply known corrections (fox→vox, etc.)
            corrected = apply_corrections(text)
            if corrected != text:
                print(f"  [corrected] {text} → {corrected}", flush=True)
                text = corrected

            # 2. Update local voice profile (background-safe)
            try:
                update_profile(rich)
                conf = rich.get("avg_confidence", 0)
                lc = rich.get("low_confidence_words", [])
                if lc:
                    print(f"  [profile] conf={conf:.2f}, unclear: {', '.join(lc[:3])}", flush=True)
                prompt = get_whisper_prompt()
                if prompt:
                    words = prompt.replace("Words I use: ", "").split()
                    self.transcriber.set_vocabulary(words)
                auto_learn_corrections()
            except Exception:
                pass

            # 3. Pronunciation / training data — off the critical path
            audio_copy = audio.copy()
            raw_text = rich["text"]
            corrected_text = text if text != raw_text else None
            conf = rich.get("avg_confidence", 0)
            threading.Thread(target=self._background_analysis,
                             args=(audio_copy, raw_text, corrected_text, conf),
                             daemon=True).start()

            # 4. Intent routing — decide whether to dictate or invoke a command
            intent = route_intent(text)
            print(f"  [intent] {intent.action} payload={intent.payload}", flush=True)

            if intent.action == "dictate":
                self.transcript_history.push(text)
                self._dictate_paste(text)
            elif intent.action == "paste_snippet":
                self._handle_paste_snippet(intent.payload.get("description", ""))
            elif intent.action == "open_overview":
                self._open_overlay()
            elif intent.action == "save_snippet":
                self._open_overlay(mode="save", from_clipboard=intent.payload.get("from_clipboard", False))

        self.title = "\U0001f3a4"
        self._update_status("Idle -- ready")
```

- [ ] **Step 4: Add the helper methods to `VoxType`**

```python
    def _dictate_paste(self, text: str):
        if self.output_language != "EN" and self.translator:
            self._update_status("Translating...")
            text = self.translator.translate(text, self.output_language)
        self.paster.paste(text)
        print(f"Pasted: {text}", flush=True)

    def _handle_paste_snippet(self, description: str):
        if not self._embedder_ready.is_set():
            print("Embedder not ready — falling back to dictate", flush=True)
            self._dictate_paste(description)
            return
        if not self.snippet_cache:
            print("No snippets saved — nothing to match", flush=True)
            return
        hits = self.embedder.match(description, self.snippet_cache, k=3)
        if not hits:
            return
        top_id, top_score = hits[0]
        second_score = hits[1][1] if len(hits) > 1 else 0.0
        print(f"  [match] top={top_id} score={top_score:.3f} 2nd={second_score:.3f}", flush=True)

        # Direct-paste threshold: top > 0.75 AND margin > 0.1
        if top_score >= 0.75 and (top_score - second_score) >= 0.1:
            s = self.snippet_store.get(top_id)
            if s:
                self.paster.paste(s.body)
                self.snippet_store.record_use(top_id)
                print(f"  Pasted snippet: {s.name}", flush=True)
                return

        # Ambiguous or low confidence: in this task, fall back to printing —
        # the mini picker / overlay arrives in Task 14.
        print(f"  Ambiguous match — overlay/picker not implemented yet (coming in Task 14)", flush=True)

    def _open_overlay(self, mode: str = "list", from_clipboard: bool = False):
        # Wired up in Task 11. For now: log.
        print(f"  [overlay] requested mode={mode} from_clipboard={from_clipboard}", flush=True)
```

- [ ] **Step 5: Smoke test — run VoxType, speak dictation (should still work), then "snippet anything"**

Run: `/Users/beauregard/voxtype/.venv/bin/python voxtype.py` (from `/Users/beauregard/voxtype/`)
Test matrix:
- Hold Option+C, say "hello world" → should paste "hello world" (dictate path unchanged)
- Hold Option+C, say "snippet deploy v3" → console should log `[intent] paste_snippet` and `No snippets saved`
- Hold Option+C, say "open snippet overview" → console should log `[intent] open_overview` and `[overlay] requested mode=list`

Cmd+C in the VoxType terminal to quit.

- [ ] **Step 6: Commit**

```bash
git add voxtype.py
git commit -m "feat: intent-route transcriptions; dictate + paste_snippet direct path"
```

---

### Task 7: Seed embeddings when snippets are created/updated

We want embeddings to exist for every snippet so matching works. The cache rebuild already handles backfill; here we wire `create`/`update` to compute the embedding inline (so newly-created snippets are matchable immediately).

**Files:**
- Modify: `voxtype.py` (add helper), and later the overlay bridge will call it

- [ ] **Step 1: Add a helper in `VoxType` that creates-with-embedding**

Add to the `VoxType` class:

```python
    def create_snippet(self, name: str, body: str, description: str = "", tags: str = ""):
        """Create a snippet and compute its embedding inline so it's matchable right away."""
        s = self.snippet_store.create(name=name, body=body, description=description, tags=tags)
        if self._embedder_ready.is_set() and self.embedder:
            vec = self.embedder.encode(f"{name}. {description}. Tags: {tags}")
            self.snippet_store.update(s.id, embedding=Embedder.array_to_blob(vec))
            self.snippet_cache[s.id] = vec
        return s

    def update_snippet(self, id: int, **fields):
        text_fields = {"name", "description", "tags"}
        self.snippet_store.update(id, **fields)
        if self._embedder_ready.is_set() and any(k in fields for k in text_fields):
            s = self.snippet_store.get(id)
            vec = self.embedder.encode(f"{s.name}. {s.description}. Tags: {s.tags}")
            self.snippet_store.update(id, embedding=Embedder.array_to_blob(vec))
            self.snippet_cache[id] = vec
        return self.snippet_store.get(id)

    def delete_snippet(self, id: int):
        self.snippet_store.delete(id)
        self.snippet_cache.pop(id, None)
```

- [ ] **Step 2: Seed a couple snippets by hand to test the direct-paste path**

Add a throwaway script `seed_test_snippets.py` (do NOT commit):

```python
# seed_test_snippets.py
from snippets import Store
from embedder import Embedder

store = Store()
emb = Embedder()

samples = [
    ("deploy v3", "./v3/jobs/sync_from_server.sh && git push origin v3", "push crypto app to lightsail", "crypto-app,deploy"),
    ("pytest watch", "pytest -q --looponfail tests/", "run pytest in watch mode", "testing"),
    ("brew cleanup", "brew cleanup -s && brew autoremove", "free disk space", "mac,maintenance"),
]
for name, body, desc, tags in samples:
    s = store.create(name=name, body=body, description=desc, tags=tags)
    vec = emb.encode(f"{name}. {desc}. Tags: {tags}")
    store.update(s.id, embedding=Embedder.array_to_blob(vec))
    print(f"seeded: {s.name}")
store.close()
```

Run: `/Users/beauregard/voxtype/.venv/bin/python seed_test_snippets.py`
Expected: 3 `seeded:` lines.

- [ ] **Step 3: Re-run VoxType and confirm direct-paste works**

Run: `/Users/beauregard/voxtype/.venv/bin/python voxtype.py`
Hold Option+C, say "snippet push the crypto app to production".
Expected: the body `./v3/jobs/sync_from_server.sh && git push origin v3` gets pasted; console logs the match score.

If the top score is below 0.75, the ambiguous-match log prints. Try a more direct phrase like "snippet deploy v3" — that should match cleanly.

- [ ] **Step 4: Delete the throwaway script and commit helpers only**

```bash
rm seed_test_snippets.py
git add voxtype.py
git commit -m "feat: snippet create/update inline embedding"
```

---

### Task 8: Bump Python overlay bridge (stub) — `overlay_bridge.py`

We scaffold the Python side of the bridge now so the rest of `voxtype.py` can depend on it. The Swift helper ships in Task 10; until then the bridge just logs.

**Files:**
- Create: `overlay_bridge.py`

- [ ] **Step 1: Create the bridge stub**

```python
# overlay_bridge.py
"""Python side of the Swift snippet-overlay helper bridge.

Spawns the Swift helper as a subprocess, sends events on stdin, reads user
actions from stdout. Protocol is line-oriented JSON.

Protocol (Python → Swift):
  {"type":"OPEN","mode":"list"|"save"|"search","query":"optional","draft_body":"optional"}
  {"type":"PICKER","candidates":[{"id":1,"name":"...","score":0.71},...]}
  {"type":"SNIPPETS","items":[{"id":1,"name":"...","description":"...","body":"...","tags":"...","used_count":42}, ...]}
  {"type":"CLIPBOARD","text":"..."}
  {"type":"HISTORY","items":[{"text":"...","ts":1706000000}, ...]}
  {"type":"HIDE"}

Protocol (Swift → Python):
  {"type":"PASTE","id":1}
  {"type":"CREATE","name":"...","body":"...","description":"...","tags":"..."}
  {"type":"UPDATE","id":1,"name":"...","body":"...","description":"...","tags":"..."}
  {"type":"DELETE","id":1}
  {"type":"SEARCH","query":"..."}  # requests fresh filtered list
  {"type":"DISMISSED"}
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Callable, Optional


HELPER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "VoxType.app", "Contents", "MacOS", "snippet_overlay",
)


class OverlayBridge:
    def __init__(self, on_event: Callable[[dict], None]):
        self.on_event = on_event
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Start the helper. Returns True if it spawned; False if binary missing."""
        if not os.path.exists(HELPER_PATH):
            print(f"[overlay] helper not built yet at {HELPER_PATH}", flush=True)
            return False
        self._proc = subprocess.Popen(
            [HELPER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def send(self, msg: dict) -> None:
        if not self._proc or not self._proc.stdin:
            return
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    def _read_loop(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[overlay] non-JSON line: {line}", flush=True)
                continue
            try:
                self.on_event(msg)
            except Exception as e:
                print(f"[overlay] handler error: {e}", flush=True)
```

- [ ] **Step 2: Wire it into `VoxType.__init__`**

After the embedder init block:

```python
        # Overlay bridge — helper may not exist yet (built in Task 10)
        from overlay_bridge import OverlayBridge
        self.overlay = OverlayBridge(on_event=self._on_overlay_event)
        self.overlay.start()
```

And add the event handler:

```python
    def _on_overlay_event(self, msg: dict):
        t = msg.get("type")
        if t == "PASTE":
            s = self.snippet_store.get(msg["id"])
            if s:
                self.paster.paste(s.body)
                self.snippet_store.record_use(s.id)
        elif t == "CREATE":
            self.create_snippet(
                name=msg.get("name", "Untitled"),
                body=msg.get("body", ""),
                description=msg.get("description", ""),
                tags=msg.get("tags", ""),
            )
            self._push_snippet_list()
        elif t == "UPDATE":
            self.update_snippet(
                id=msg["id"],
                name=msg.get("name"),
                body=msg.get("body"),
                description=msg.get("description"),
                tags=msg.get("tags"),
            )
            self._push_snippet_list()
        elif t == "DELETE":
            self.delete_snippet(msg["id"])
            self._push_snippet_list()
        elif t == "SEARCH":
            hits = self.snippet_store.search_text(msg["query"])
            self.overlay.send({"type": "SNIPPETS", "items": [self._snippet_dict(s) for s in hits]})
        elif t == "DISMISSED":
            pass

    def _push_snippet_list(self):
        items = [self._snippet_dict(s) for s in self.snippet_store.list_all()]
        self.overlay.send({"type": "SNIPPETS", "items": items})

    @staticmethod
    def _snippet_dict(s):
        return {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "body": s.body,
            "tags": s.tags,
            "used_count": s.used_count,
        }
```

- [ ] **Step 3: Replace `_open_overlay` stub with real bridge call**

```python
    def _open_overlay(self, mode: str = "list", query: str = "", from_clipboard: bool = False):
        draft_body = ""
        if from_clipboard:
            import subprocess as _sp
            draft_body = _sp.run(["pbpaste"], capture_output=True, text=True).stdout
        self._push_snippet_list()
        self.overlay.send({
            "type": "OPEN",
            "mode": mode,
            "query": query,
            "draft_body": draft_body,
        })
```

- [ ] **Step 4: Smoke test — launch VoxType, should start without overlay helper**

Run: `/Users/beauregard/voxtype/.venv/bin/python voxtype.py`
Expected console: `[overlay] helper not built yet at .../snippet_overlay` — no crash. Dictation still works.

- [ ] **Step 5: Commit**

```bash
git add overlay_bridge.py voxtype.py
git commit -m "feat: overlay bridge (Python side) + event handlers"
```

---

### Task 9: Add Option+Shift+S hotkey in Swift helper

**Files:**
- Modify: `hotkey_helper.swift`
- Modify: `hotkey.py`

- [ ] **Step 1: Register a third hotkey in `hotkey_helper.swift`**

Find the block registering Option+T (around line 52). After it, add:

```swift
        // Register Option+Shift+S hotkey (kVK_ANSI_S = 1) — open snippet overlay
        var overlayKeyRef: EventHotKeyRef?
        let overlayKeyID = EventHotKeyID(signature: OSType(0x564F5854), id: 3)

        let status3 = RegisterEventHotKey(
            UInt32(kVK_ANSI_S),
            UInt32(optionKey | shiftKey),
            overlayKeyID,
            GetApplicationEventTarget(),
            0,
            &overlayKeyRef
        )

        if status3 != noErr {
            fputs("ERROR: Could not register Option+Shift+S hotkey (status: \(status3))\n", stderr)
            exit(1)
        }
```

Then in the event handler switch — where `hotKeyID.id == 2` is handled — add:

```swift
                } else if hotKeyID.id == 3 {
                    // Option+Shift+S — open snippet overlay (fire on press only)
                    if kind == UInt32(kEventHotKeyPressed) {
                        fputs("OPEN_OVERLAY\n", stdout)
                        fflush(stdout)
                    }
```

- [ ] **Step 2: Rebuild the Swift helper**

Run:

```bash
cd /Users/beauregard/voxtype
swiftc hotkey_helper.swift -o VoxType.app/Contents/MacOS/hotkey_helper
```

Expected: compiles with no errors.

- [ ] **Step 3: Surface the new callback in `hotkey.py`**

Replace the `HotkeyListener.__init__` signature and add the new branch in `_run`:

```python
    def __init__(self, on_start, on_stop, on_translate=None, on_open_overlay=None):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_translate = on_translate
        self.on_open_overlay = on_open_overlay
        self._proc = None
```

In `_run`, after the `elif line == "TRANSLATE":` branch:

```python
            elif line == "OPEN_OVERLAY":
                if self.on_open_overlay:
                    self.on_open_overlay()
```

- [ ] **Step 4: Wire it in `voxtype.py`**

In `VoxType.__init__`, change the `HotkeyListener(...)` call to pass the new callback:

```python
        self.hotkey = HotkeyListener(
            on_start=self._start_recording,
            on_stop=self._stop_recording,
            on_translate=self._translate_clipboard,
            on_open_overlay=self._open_overlay,
        )
```

- [ ] **Step 5: Smoke test — press Option+Shift+S**

Run: `/Users/beauregard/voxtype/.venv/bin/python voxtype.py`
Press Option+Shift+S.
Expected console: `[overlay] requested mode=list from_clipboard=False` (followed by the "helper not built yet" message).

- [ ] **Step 6: Commit**

```bash
git add hotkey_helper.swift hotkey.py voxtype.py VoxType.app/Contents/MacOS/hotkey_helper
git commit -m "feat: Option+Shift+S hotkey to open snippet overlay"
```

---

### Task 10: Scaffolding `snippet_overlay.swift` — window + stdin reader + smoke test

This is the first cut of the Swift helper. It opens a borderless panel, reads JSON on stdin, echoes events to stdout. The UI is placeholder — real views come in Task 11.

**Files:**
- Create: `snippet_overlay.swift`
- Modify: `install.sh`

- [ ] **Step 1: Create `snippet_overlay.swift` (scaffold)**

```swift
// snippet_overlay.swift
// Snippet overlay + mini picker helper. Reads JSON events on stdin,
// emits JSON events on stdout. Window is a floating panel that never
// steals focus on paste (so Cmd+V targets the previously-frontmost app).

import Cocoa
import SwiftUI

// MARK: - Protocol types

struct OverlayMessage: Codable {
    let type: String
    var mode: String?
    var query: String?
    var draft_body: String?
    var items: [SnippetItem]?
    var candidates: [PickerCandidate]?
    var text: String?
}

struct SnippetItem: Codable, Identifiable {
    let id: Int
    let name: String
    let description: String
    let body: String
    let tags: String
    let used_count: Int
}

struct PickerCandidate: Codable, Identifiable {
    let id: Int
    let name: String
    let score: Double
}

// MARK: - Shared state

final class OverlayState: ObservableObject {
    @Published var snippets: [SnippetItem] = []
    @Published var visible: Bool = false
    @Published var mode: String = "list"
    @Published var query: String = ""
    @Published var draftBody: String = ""
}

// MARK: - stdin reader

func startStdinReader(state: OverlayState, panel: NSPanel) {
    Thread {
        while let line = readLine() {
            guard let data = line.data(using: .utf8),
                  let msg = try? JSONDecoder().decode(OverlayMessage.self, from: data) else {
                continue
            }
            DispatchQueue.main.async {
                switch msg.type {
                case "OPEN":
                    state.mode = msg.mode ?? "list"
                    state.query = msg.query ?? ""
                    state.draftBody = msg.draft_body ?? ""
                    panel.orderFrontRegardless()
                    panel.makeKey()
                case "HIDE":
                    panel.orderOut(nil)
                case "SNIPPETS":
                    state.snippets = msg.items ?? []
                default:
                    break
                }
            }
        }
    }.start()
}

// MARK: - Emit helpers

func emit(_ obj: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: obj) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

// MARK: - Placeholder view (replaced in Task 11)

struct PlaceholderView: View {
    @EnvironmentObject var state: OverlayState
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("VoxType snippets — mode: \(state.mode)")
                .font(.headline)
            Text("\(state.snippets.count) snippets loaded")
                .foregroundColor(.secondary)
            Divider()
            ForEach(state.snippets.prefix(5)) { s in
                HStack {
                    Text(s.name).fontWeight(.medium)
                    Spacer()
                    Text("\(s.used_count)×").foregroundColor(.secondary)
                }
            }
        }
        .padding(16)
        .frame(minWidth: 480, minHeight: 200)
    }
}

// MARK: - App delegate

class AppDelegate: NSObject, NSApplicationDelegate {
    var panel: NSPanel!
    let state = OverlayState()

    func applicationDidFinishLaunching(_ notification: Notification) {
        let rect = NSRect(x: 0, y: 0, width: 540, height: 420)
        panel = NSPanel(
            contentRect: rect,
            styleMask: [.titled, .fullSizeContentView, .nonactivatingPanel, .hudWindow],
            backing: .buffered,
            defer: false
        )
        panel.level = .floating
        panel.isMovableByWindowBackground = true
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.center()
        panel.hidesOnDeactivate = false
        panel.orderOut(nil)

        let content = NSHostingView(rootView: PlaceholderView().environmentObject(state))
        panel.contentView = content

        // Escape key dismiss
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if event.keyCode == 53 { // Esc
                self?.panel.orderOut(nil)
                emit(["type": "DISMISSED"])
                return nil
            }
            return event
        }

        startStdinReader(state: state, panel: panel)

        fputs("READY\n", stdout)
        fflush(stdout)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)
let delegate = AppDelegate()
app.delegate = delegate
app.run()
```

- [ ] **Step 2: Compile it**

Run:

```bash
cd /Users/beauregard/voxtype
swiftc snippet_overlay.swift -o VoxType.app/Contents/MacOS/snippet_overlay
```

Expected: compiles with no errors.

- [ ] **Step 3: Update `install.sh` to compile the new helper during install**

Open `install.sh`; find the existing `swiftc hotkey_helper.swift` line. Add right after it:

```bash
swiftc snippet_overlay.swift -o VoxType.app/Contents/MacOS/snippet_overlay
```

- [ ] **Step 4: Smoke test — run VoxType and trigger the overlay**

Run: `/Users/beauregard/voxtype/.venv/bin/python voxtype.py`
Press Option+Shift+S.
Expected: a floating placeholder panel appears; it shows how many test snippets are loaded; pressing Esc closes it; console logs `[overlay] requested mode=list…` and no "helper not built" message.

- [ ] **Step 5: Commit**

```bash
git add snippet_overlay.swift install.sh VoxType.app/Contents/MacOS/snippet_overlay
git commit -m "feat: SwiftUI overlay helper scaffold — panel + stdin bridge"
```

---

### Task 11: Overlay UI — search + list + capture strip

Replace `PlaceholderView` with the real overlay layout from the spec §5.4.

**Files:**
- Modify: `snippet_overlay.swift`

- [ ] **Step 1: Replace `PlaceholderView` with `OverlayView`**

Delete the `PlaceholderView` struct. Add:

```swift
struct OverlayView: View {
    @EnvironmentObject var state: OverlayState
    @State private var selectedID: Int? = nil
    @State private var localQuery: String = ""

    var filtered: [SnippetItem] {
        if localQuery.isEmpty { return state.snippets }
        let q = localQuery.lowercased()
        return state.snippets.filter {
            $0.name.lowercased().contains(q)
            || $0.description.lowercased().contains(q)
            || $0.tags.lowercased().contains(q)
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            searchField
            captureStrip
            Divider()
            snippetList
            footer
        }
        .padding(14)
        .frame(width: 540, height: 420)
        .background(VisualEffectView(material: .hudWindow, blending: .behindWindow))
    }

    private var searchField: some View {
        TextField("Search snippets…", text: $localQuery, onCommit: {
            if let id = filtered.first?.id {
                emit(["type": "PASTE", "id": id])
                state.visible = false
                NSApp.windows.first?.orderOut(nil)
            }
        })
        .textFieldStyle(PlainTextFieldStyle())
        .font(.system(size: 14))
        .padding(10)
        .background(Color.black.opacity(0.25))
        .cornerRadius(6)
    }

    @ViewBuilder private var captureStrip: some View {
        if !state.draftBody.isEmpty {
            HStack {
                Image(systemName: "doc.on.clipboard")
                Text("Clipboard: ")
                    .foregroundColor(.secondary)
                Text(state.draftBody.prefix(60) + (state.draftBody.count > 60 ? "…" : ""))
                    .lineLimit(1)
                Spacer()
                Button("⌘S save") {
                    emit([
                        "type": "CREATE",
                        "name": "From clipboard",
                        "body": state.draftBody,
                        "description": "",
                        "tags": "",
                    ])
                }
                .buttonStyle(LinkButtonStyle())
            }
            .font(.system(size: 11))
            .padding(8)
            .background(Color.blue.opacity(0.15))
            .cornerRadius(6)
        }
    }

    private var snippetList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 2) {
                ForEach(filtered) { s in
                    SnippetRow(snippet: s, selected: s.id == selectedID)
                        .onTapGesture(count: 2) {
                            emit(["type": "PASTE", "id": s.id])
                            NSApp.windows.first?.orderOut(nil)
                        }
                        .onTapGesture { selectedID = s.id }
                }
            }
        }
    }

    private var footer: some View {
        HStack {
            Text("↑↓ navigate · ⏎ paste · ⌘N new · ⌘E edit · ⌘⌫ delete")
                .font(.system(size: 10))
                .foregroundColor(.secondary)
            Spacer()
            Text("\(filtered.count) of \(state.snippets.count)")
                .font(.system(size: 10))
                .foregroundColor(.secondary)
        }
    }
}

struct SnippetRow: View {
    let snippet: SnippetItem
    let selected: Bool

    var body: some View {
        HStack {
            Text(snippet.name).fontWeight(.medium)
            Text(snippet.body.prefix(50) + (snippet.body.count > 50 ? "…" : ""))
                .foregroundColor(.secondary)
                .lineLimit(1)
                .font(.system(size: 11))
            Spacer()
            Text("\(snippet.used_count)×")
                .foregroundColor(.secondary)
                .font(.system(size: 10))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(selected ? Color.accentColor.opacity(0.3) : Color.clear)
        .cornerRadius(4)
    }
}

struct VisualEffectView: NSViewRepresentable {
    let material: NSVisualEffectView.Material
    let blending: NSVisualEffectView.BlendingMode
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = material
        v.blendingMode = blending
        v.state = .active
        return v
    }
    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}
```

In `applicationDidFinishLaunching`, change:

```swift
        let content = NSHostingView(rootView: PlaceholderView().environmentObject(state))
```

to:

```swift
        let content = NSHostingView(rootView: OverlayView().environmentObject(state))
```

- [ ] **Step 2: Recompile**

```bash
cd /Users/beauregard/voxtype
swiftc snippet_overlay.swift -o VoxType.app/Contents/MacOS/snippet_overlay
```

- [ ] **Step 3: Manual test matrix**

Launch VoxType, trigger overlay with Option+Shift+S. Verify:
- Overlay opens centered with blur/HUD look
- Search field filters the list live (type "dep" → only "deploy v3" shown if you seeded it in Task 7)
- Double-clicking a row pastes it into the previously-frontmost app
- ⏎ in the search field pastes the top match
- Esc closes the panel
- Console shows `PASTE` events arriving at Python

- [ ] **Step 4: Commit**

```bash
git add snippet_overlay.swift VoxType.app/Contents/MacOS/snippet_overlay
git commit -m "feat: overlay UI — search, list, capture strip"
```

---

### Task 12: Overlay editing — create / edit / delete with modal

**Files:**
- Modify: `snippet_overlay.swift`

- [ ] **Step 1: Add an editor sheet state + view**

At the top of `OverlayState`:

```swift
    @Published var editingSnippet: SnippetItem? = nil
    @Published var showingEditor: Bool = false
```

Add a new view:

```swift
struct EditorView: View {
    @EnvironmentObject var state: OverlayState
    @State var name: String = ""
    @State var body: String = ""
    @State var description: String = ""
    @State var tags: String = ""
    var editingID: Int? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField("Name", text: $name).padding(8).background(Color.black.opacity(0.2)).cornerRadius(4)
            TextField("Description (helps voice match)", text: $description).padding(8).background(Color.black.opacity(0.2)).cornerRadius(4)
            TextField("Tags (comma separated)", text: $tags).padding(8).background(Color.black.opacity(0.2)).cornerRadius(4)
            TextEditor(text: $body).frame(minHeight: 120).padding(6).background(Color.black.opacity(0.2)).cornerRadius(4)
            HStack {
                Button("Cancel") { state.showingEditor = false }
                Spacer()
                if let id = editingID {
                    Button("Delete", role: .destructive) {
                        emit(["type": "DELETE", "id": id])
                        state.showingEditor = false
                    }
                }
                Button("Save") {
                    if let id = editingID {
                        emit(["type": "UPDATE", "id": id, "name": name, "body": body, "description": description, "tags": tags])
                    } else {
                        emit(["type": "CREATE", "name": name, "body": body, "description": description, "tags": tags])
                    }
                    state.showingEditor = false
                }
                .keyboardShortcut(.defaultAction)
            }
        }
        .padding(14)
        .frame(width: 500, height: 360)
    }
}
```

- [ ] **Step 2: Add ⌘N / ⌘E / ⌘⌫ handlers in `OverlayView`**

In `OverlayView.body`, attach key equivalents at the top:

```swift
        .onReceive(NotificationCenter.default.publisher(for: NSNotification.Name("voxtype.new"))) { _ in
            state.editingSnippet = nil
            state.showingEditor = true
        }
```

Actually, SwiftUI on macOS handles this more cleanly via menu commands. Skip `NotificationCenter` and use `CommandGroup` later. For now (simpler): add an invisible button with `.keyboardShortcut`:

```swift
Button("") {
    state.editingSnippet = nil
    state.showingEditor = true
}.keyboardShortcut("n", modifiers: .command).frame(width: 0, height: 0).opacity(0)

Button("") {
    if let id = selectedID, let s = state.snippets.first(where: { $0.id == id }) {
        state.editingSnippet = s
        state.showingEditor = true
    }
}.keyboardShortcut("e", modifiers: .command).frame(width: 0, height: 0).opacity(0)

Button("") {
    if let id = selectedID {
        emit(["type": "DELETE", "id": id])
    }
}.keyboardShortcut(.delete, modifiers: .command).frame(width: 0, height: 0).opacity(0)
```

Place those in the `VStack` body above `searchField`.

Also add a sheet presentation:

```swift
.sheet(isPresented: $state.showingEditor) {
    if let s = state.editingSnippet {
        EditorView(name: s.name, body: s.body, description: s.description, tags: s.tags, editingID: s.id)
            .environmentObject(state)
    } else {
        EditorView().environmentObject(state)
    }
}
```

- [ ] **Step 3: Recompile and manual test**

```bash
swiftc snippet_overlay.swift -o VoxType.app/Contents/MacOS/snippet_overlay
```

Launch VoxType. Option+Shift+S. Press ⌘N — editor sheet opens. Fill in name/body, click Save. List refreshes with new snippet. Select a snippet, press ⌘E — editor opens pre-filled. Make a change, Save. ⌘⌫ deletes selected snippet.

- [ ] **Step 4: Commit**

```bash
git add snippet_overlay.swift VoxType.app/Contents/MacOS/snippet_overlay
git commit -m "feat: overlay editor — create, edit, delete"
```

---

### Task 13: Option+C inside overlay dictates into search

The "voice as peer input inside the overlay" behavior.

**Files:**
- Modify: `voxtype.py`

- [ ] **Step 1: Track overlay visibility in `voxtype.py`**

Add to `VoxType.__init__`:

```python
        self.overlay_visible = False
```

In `_open_overlay`:

```python
        self.overlay_visible = True
```

Handle `DISMISSED`:

```python
        elif t == "DISMISSED":
            self.overlay_visible = False
```

- [ ] **Step 2: In `_transcribe_and_paste`, if overlay is visible, route the transcription as a search query**

At the top of `_transcribe_and_paste`, after computing `text`, before intent routing, add:

```python
            if self.overlay_visible:
                # Overlay is focused — route transcription as a search query
                self.overlay.send({"type": "SEARCH", "query": text})
                print(f"  [overlay-search] {text}", flush=True)
                self.title = "\U0001f3a4"
                self._update_status("Idle -- ready")
                return
```

- [ ] **Step 3: In `snippet_overlay.swift`, handle `SEARCH` by setting local query**

Add to the stdin reader `switch`:

```swift
                case "SEARCH":
                    state.query = msg.query ?? ""
```

And in `OverlayView`, bind `localQuery` to `state.query` one-way on change:

```swift
.onChange(of: state.query) { newValue in localQuery = newValue }
```

Recompile.

- [ ] **Step 4: Manual test**

Open overlay with Option+Shift+S. Hold Option+C, say "deploy". Release.
Expected: the search field fills with "deploy", the list filters. Press ⏎ to paste.

- [ ] **Step 5: Commit**

```bash
git add voxtype.py snippet_overlay.swift VoxType.app/Contents/MacOS/snippet_overlay
git commit -m "feat: voice-into-search inside overlay — dual input surface"
```

---

### Task 14: Mini picker for ambiguous matches

**Files:**
- Modify: `snippet_overlay.swift`
- Modify: `voxtype.py`

- [ ] **Step 1: Add a picker mode in `snippet_overlay.swift`**

Add to `OverlayState`:

```swift
    @Published var pickerCandidates: [PickerCandidate] = []
```

Handle the `PICKER` message in the stdin reader:

```swift
                case "PICKER":
                    state.pickerCandidates = msg.candidates ?? []
                    state.mode = "picker"
                    panel.orderFrontRegardless()
                    panel.makeKey()
```

Add a `PickerView`:

```swift
struct PickerView: View {
    @EnvironmentObject var state: OverlayState

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Did you mean:").font(.system(size: 11)).foregroundColor(.secondary)
            ForEach(Array(state.pickerCandidates.prefix(3).enumerated()), id: \.element.id) { idx, c in
                HStack {
                    Text("\(idx + 1).").monospacedDigit().frame(width: 16, alignment: .leading)
                    Text(c.name).fontWeight(.medium)
                    Spacer()
                    Text(String(format: "%.2f", c.score))
                        .foregroundColor(.secondary)
                        .font(.system(size: 10))
                }
                .padding(.vertical, 2)
            }
            Text("Press 1/2/3 · Esc to cancel").font(.system(size: 10)).foregroundColor(.secondary).padding(.top, 4)
        }
        .padding(12)
        .frame(width: 340)
        .background(VisualEffectView(material: .hudWindow, blending: .behindWindow))
    }
}
```

In `applicationDidFinishLaunching`, pick the view based on mode:

```swift
        let rootView = AnyView(
            Group {
                if state.mode == "picker" {
                    PickerView().environmentObject(state)
                } else {
                    OverlayView().environmentObject(state)
                }
            }
        )
        let content = NSHostingView(rootView: rootView)
```

Add picker key equivalents in the key-down monitor:

```swift
        NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            if self?.state.mode == "picker" {
                switch event.keyCode {
                case 18, 83: // 1
                    if let c = self?.state.pickerCandidates.first { emit(["type": "PASTE", "id": c.id]) }
                    self?.panel.orderOut(nil)
                    return nil
                case 19, 84: // 2
                    if let c = self?.state.pickerCandidates.dropFirst().first { emit(["type": "PASTE", "id": c.id]) }
                    self?.panel.orderOut(nil)
                    return nil
                case 20, 85: // 3
                    if let c = self?.state.pickerCandidates.dropFirst(2).first { emit(["type": "PASTE", "id": c.id]) }
                    self?.panel.orderOut(nil)
                    return nil
                default: break
                }
            }
            if event.keyCode == 53 { // Esc
                self?.panel.orderOut(nil)
                emit(["type": "DISMISSED"])
                return nil
            }
            return event
        }
```

- [ ] **Step 2: In `voxtype.py`, replace the "ambiguous" print with a picker call**

In `_handle_paste_snippet`, replace:

```python
        # Ambiguous or low confidence: ...
        print(f"  Ambiguous match — overlay/picker not implemented yet (coming in Task 14)", flush=True)
```

with:

```python
        # Medium confidence — show mini picker
        if top_score >= 0.55:
            candidates = []
            for sid, score in hits[:3]:
                s = self.snippet_store.get(sid)
                if s:
                    candidates.append({"id": sid, "name": s.name, "score": round(float(score), 3)})
            self.overlay.send({"type": "PICKER", "candidates": candidates})
            self.overlay_visible = True
            return

        # Low confidence — open full overlay with query
        self._open_overlay(mode="search", query=description)
```

- [ ] **Step 3: Recompile + manual test matrix**

```bash
swiftc snippet_overlay.swift -o VoxType.app/Contents/MacOS/snippet_overlay
```

With 3 seeded snippets (deploy v3, pytest watch, brew cleanup):
- Say "snippet deploy" — should direct-paste "deploy v3" (high score)
- Say "snippet run something" — should show 3-option picker (medium score)
- Say "snippet quantum hamiltonian eigenstate" — should open overlay with that query pre-filled (low score, nothing matches)

Press 1/2/3 in picker to select. Press Esc to dismiss.

- [ ] **Step 4: Commit**

```bash
git add snippet_overlay.swift voxtype.py VoxType.app/Contents/MacOS/snippet_overlay
git commit -m "feat: mini picker for ambiguous semantic matches"
```

---

### Task 15: Add snippet names to Whisper vocabulary prompt

**Files:**
- Modify: `voxtype.py`

- [ ] **Step 1: Extend the vocabulary feed with snippet names + trigger words**

In `_load_model` (after the existing `prompt = get_whisper_prompt()` block), add:

```python
        # Bias Whisper toward snippet trigger words + snippet names
        bias_words = {"snippet", "snippets", "overview", "manager", "insert", "paste", "save"}
        for s in self.snippet_store.list_all():
            # Only add short, alphabetic name tokens
            for tok in s.name.split():
                if tok.isalpha() and len(tok) > 2:
                    bias_words.add(tok.lower())
        existing = set(words) if prompt else set()
        merged = sorted(existing | bias_words)
        self.transcriber.set_vocabulary(merged)
```

Also hook it to re-run whenever a snippet is created/updated/deleted — at the end of `create_snippet` / `update_snippet` / `delete_snippet`:

```python
        self._refresh_whisper_vocab()
```

And implement:

```python
    def _refresh_whisper_vocab(self):
        if not self.transcriber:
            return
        bias_words = {"snippet", "snippets", "overview", "manager", "insert", "paste", "save"}
        for s in self.snippet_store.list_all():
            for tok in s.name.split():
                if tok.isalpha() and len(tok) > 2:
                    bias_words.add(tok.lower())
        prompt = get_whisper_prompt()
        existing = set(prompt.replace("Words I use: ", "").split()) if prompt else set()
        self.transcriber.set_vocabulary(sorted(existing | bias_words))
```

- [ ] **Step 2: Smoke test**

Launch VoxType. Confirm console: `Loaded N vocabulary words` includes trigger words + your snippet names.

- [ ] **Step 3: Commit**

```bash
git add voxtype.py
git commit -m "feat: bias Whisper toward snippet triggers + snippet names"
```

---

### Task 16: README + hotkey cheat sheet

**Files:**
- Create/Modify: `README.md` (create if missing)

- [ ] **Step 1: Write the README section**

Append (or create) a "Snippets" section:

```markdown
## Snippets

VoxType includes a voice + keyboard snippet manager.

### Invocation

**Voice (hold Option+C):**
- `snippet <description>` → paste the snippet matching that description (e.g. "snippet deploy the crypto app")
- `open snippet overview` → opens the manager
- `save snippet from clipboard` → creates a new snippet with the clipboard body

**Keyboard:**
- `Option+Shift+S` — open the manager
- Inside the manager:
  - `↑↓` navigate, `⏎` paste, `Esc` close
  - `⌘N` new, `⌘E` edit, `⌘⌫` delete
  - Hold `Option+C` inside the manager to dictate a search query

### How reliable matching works

1. Whisper is primed with trigger words + snippet names as vocabulary.
2. `rapidfuzz` catches Whisper misrecognitions like "snipped", "senate", "snippets".
3. A rule-based router picks the action (paste / open / save).
4. `mxbai-embed-xsmall-v1` embeddings rank candidates by meaning.
5. Confidence gate: >0.75 pastes directly, 0.55–0.75 shows a 3-option picker, <0.55 opens the manager with the query pre-filled.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: snippet manager hotkeys + invocation cheatsheet"
```

---

### Task 17: End-to-end acceptance test (manual checklist)

**Files:**
- Create: `SNIPPET_ACCEPTANCE.md` (a living checklist; can be removed later)

- [ ] **Step 1: Run the full matrix against a fresh empty snippet DB**

```bash
rm -f ~/.voxtype/snippets.db
/Users/beauregard/voxtype/.venv/bin/python voxtype.py
```

Then, in order, verify:

- [ ] Option+C, say "hello world" → pastes "hello world" (dictate unchanged)
- [ ] Option+Shift+S → empty overlay opens; Esc closes it
- [ ] Option+Shift+S → ⌘N → create snippet `deploy v3` / body `./deploy.sh v3` / desc `push crypto app` → Save → list shows it
- [ ] ⌘N again → `brew cleanup` / `brew cleanup -s` / `free disk space` → Save
- [ ] Option+C say "snippet deploy v3" → pastes `./deploy.sh v3`
- [ ] Option+C say "snippet push the crypto app to production" → likely picker; pick 1; pastes correctly
- [ ] Option+C say "snippet quantum hamiltonian" → overlay opens in search mode with "quantum hamiltonian" in search field
- [ ] Option+C say "open snippets" → overlay opens
- [ ] Copy some text to clipboard; Option+C say "save snippet from clipboard" → overlay opens, capture strip shows clipboard content
- [ ] Option+Shift+S → select deploy v3 → ⌘E → rename to `deploy v3 prod` → Save → list reflects rename
- [ ] Option+C say "snippet deploy v3 prod" → pastes correctly (embedding regenerated on update)
- [ ] Option+Shift+S → select `brew cleanup` → ⌘⌫ → snippet removed
- [ ] Restart VoxType (Cmd+Q the rumps menu, re-launch). Repeat "snippet deploy v3 prod" — still works (persistence confirmed)

- [ ] **Step 2: Capture any failures**

If anything fails, return to the relevant task and fix. Do not commit this acceptance doc to main until every row passes.

- [ ] **Step 3: Commit the checklist (and any final fixes)**

```bash
git add SNIPPET_ACCEPTANCE.md
git commit -m "test: snippet manager acceptance checklist (green on N/N rows)"
```

---

## Self-review coverage map

| Spec requirement | Task(s) |
|---|---|
| §5.1 Intent router (4-layer) | 4 |
| §5.1.1 Transcript history buffer | 5 |
| §5.2 SQLite + FTS store | 2 |
| §5.3 Embedder + cache | 3 |
| §5.4 Overlay UI (list/search/detail/capture) | 10, 11, 12 |
| §5.5 Mini picker | 14 |
| §6 Hotkeys (Option+Shift+S) | 9 |
| §7 Reliability stack (Whisper bias) | 15 |
| §3 User flows end-to-end | 6, 7, 8, 13, 14, 17 |
| §9 Dependencies | 1 |
| §10 Test approach | 2, 3, 4, 5, 17 |

## Known deferrals (per spec §12, not implemented in this plan)

- Variable substitution (`{{date}}`, `{{clipboard}}`)
- Folders / nesting
- Sync across devices
- Clipboard history, notes, other voice-addressable surfaces
