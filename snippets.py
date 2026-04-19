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
        # check_same_thread=False: accessed from main thread, embedder-loader
        # thread, and hotkey-listener thread. SQLite is thread-safe for our
        # single-writer pattern.
        self.conn = sqlite3.connect(path, check_same_thread=False)
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
