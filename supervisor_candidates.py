"""supervisor_candidates.py — append-only SQLite store for diff candidates.

Each row is one structured observation pulled from a (fast, slow) transcript
diff. The promoter walks unpromoted rows periodically; rows that meet a
minimum-occurrence threshold get applied to vocabulary.json / corrections.json.

Why SQLite instead of JSONL? The hottest promoter query is
"how many independent occurrences of this same (from,to) substitution exist?"
SQLite gives us that with an indexed `SELECT COUNT(*)`; with JSONL we'd be
re-parsing the whole file every batch.

The DB lives at `~/.voicetype/supervisor_candidates.db`. Schema:

    CREATE TABLE candidates (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        ts          TEXT NOT NULL,
        audio_path  TEXT NOT NULL,
        type        TEXT NOT NULL,      -- new_vocab | substitution | punctuation | language_switch
        payload     TEXT NOT NULL,      -- JSON: type-specific structure
        confidence  REAL NOT NULL,
        promoted_at TEXT
    );
    CREATE INDEX idx_type_promoted ON candidates(type, promoted_at);
    CREATE INDEX idx_audio         ON candidates(audio_path);

`payload` is a JSON string instead of separate columns because the schema
varies by `type`: a `new_vocab` candidate is `{"word": "..."}`, a
`substitution` is `{"from": "...", "to": "..."}`, etc. Trading lookup
ergonomics for schema flexibility — we never query on payload contents
directly; the promoter loads + groups in Python.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


DB_PATH = Path(os.path.expanduser("~/.voicetype/supervisor_candidates.db"))


_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    audio_path  TEXT NOT NULL,
    type        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    confidence  REAL NOT NULL,
    promoted_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_type_promoted ON candidates(type, promoted_at);
CREATE INDEX IF NOT EXISTS idx_audio         ON candidates(audio_path);
"""


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(_SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def add(audio_path: str, type_: str, payload: dict, confidence: float) -> int:
    """Insert a candidate. Returns the new row id."""
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO candidates (ts, audio_path, type, payload, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, str(audio_path), type_, json.dumps(payload, ensure_ascii=False), confidence),
        )
        return int(cur.lastrowid)


def add_batch(audio_path: str, candidates: list[dict]) -> int:
    """Insert many candidates from one audio file in a single transaction.

    Each entry in `candidates` is `{"type": str, "payload": dict, "confidence": float}`.
    Returns the count actually inserted.
    """
    if not candidates:
        return 0
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = [
        (ts, str(audio_path), c["type"], json.dumps(c["payload"], ensure_ascii=False),
         float(c.get("confidence", 0.0)))
        for c in candidates
    ]
    with _conn() as conn:
        conn.executemany(
            "INSERT INTO candidates (ts, audio_path, type, payload, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    return len(rows)


def unpromoted(type_: Optional[str] = None) -> list[sqlite3.Row]:
    """Return rows whose `promoted_at` is NULL, optionally filtered by type."""
    sql = "SELECT * FROM candidates WHERE promoted_at IS NULL"
    args: tuple = ()
    if type_ is not None:
        sql += " AND type = ?"
        args = (type_,)
    sql += " ORDER BY id ASC"
    with _conn() as conn:
        return list(conn.execute(sql, args).fetchall())


def mark_promoted(ids: list[int]) -> None:
    """Stamp a set of candidates as promoted so the promoter doesn't re-touch them."""
    if not ids:
        return
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _conn() as conn:
        conn.executemany(
            "UPDATE candidates SET promoted_at = ? WHERE id = ?",
            [(ts, i) for i in ids],
        )


def recent_promoted(limit: int = 50) -> list[sqlite3.Row]:
    """Most recently promoted candidates — feeds the 'View recent learnings' panel.

    Ties on `promoted_at` (sub-second granularity in our ISO strings) break
    by `id DESC` so a newer row inside the same second still sorts ahead of
    an older one promoted in that same call.
    """
    with _conn() as conn:
        return list(conn.execute(
            "SELECT * FROM candidates WHERE promoted_at IS NOT NULL "
            "ORDER BY promoted_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall())


def stats() -> dict:
    """Snapshot for the Settings panel + CLI."""
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM candidates").fetchone()["n"]
        promoted = conn.execute(
            "SELECT COUNT(*) AS n FROM candidates WHERE promoted_at IS NOT NULL"
        ).fetchone()["n"]
        by_type = {
            row["type"]: row["n"]
            for row in conn.execute(
                "SELECT type, COUNT(*) AS n FROM candidates GROUP BY type"
            ).fetchall()
        }
    return {
        "total":    int(total),
        "promoted": int(promoted),
        "by_type":  by_type,
    }


def delete_for_audio(audio_path: str) -> int:
    """Remove rows tied to a specific audio file. Used by retention cleanup so
    pruned-audio candidates don't linger forever. Returns rows deleted."""
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM candidates WHERE audio_path = ?", (str(audio_path),)
        )
        return cur.rowcount
