"""Tests for the candidates SQLite store."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import supervisor_candidates as sc


def _patch_db(tmp: str):
    """Return a mock.patch context redirecting DB_PATH to a temp file."""
    return mock.patch.object(sc, "DB_PATH", Path(tmp) / "candidates.db")


def test_add_and_count():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        sc.add("a.npy", "new_vocab", {"word": "Polistician"}, 0.9)
        sc.add("b.npy", "substitution", {"from": "voice type", "to": "VoiceType"}, 0.7)
        s = sc.stats()
        assert s["total"] == 2
        assert s["promoted"] == 0
        assert s["by_type"] == {"new_vocab": 1, "substitution": 1}


def test_add_batch_inserts_in_one_transaction():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        candidates = [
            {"type": "new_vocab", "payload": {"word": "engram"}, "confidence": 0.95},
            {"type": "new_vocab", "payload": {"word": "soma"},   "confidence": 0.95},
            {"type": "substitution", "payload": {"from": "by ne", "to": "binary"}, "confidence": 0.8},
        ]
        n = sc.add_batch("c.npy", candidates)
        assert n == 3
        assert sc.stats()["total"] == 3


def test_unpromoted_filters_by_type():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        sc.add("a.npy", "new_vocab", {"word": "x"}, 1.0)
        sc.add("a.npy", "substitution", {"from": "y", "to": "z"}, 1.0)
        rows = sc.unpromoted(type_="new_vocab")
        assert len(rows) == 1
        assert rows[0]["type"] == "new_vocab"


def test_mark_promoted_excludes_from_unpromoted():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        i1 = sc.add("a.npy", "new_vocab", {"word": "x"}, 1.0)
        i2 = sc.add("a.npy", "new_vocab", {"word": "y"}, 1.0)
        sc.mark_promoted([i1])
        rows = sc.unpromoted(type_="new_vocab")
        assert [r["id"] for r in rows] == [i2]
        assert sc.stats()["promoted"] == 1


def test_recent_promoted_orders_by_promoted_at_desc():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        i1 = sc.add("a.npy", "new_vocab", {"word": "first"}, 1.0)
        i2 = sc.add("a.npy", "new_vocab", {"word": "second"}, 1.0)
        sc.mark_promoted([i1])
        sc.mark_promoted([i2])  # later promotion timestamp
        rows = sc.recent_promoted(limit=10)
        assert [r["id"] for r in rows][0] == i2  # most recent first


def test_delete_for_audio_returns_row_count():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        sc.add("a.npy", "new_vocab", {"word": "x"}, 1.0)
        sc.add("a.npy", "new_vocab", {"word": "y"}, 1.0)
        sc.add("b.npy", "new_vocab", {"word": "z"}, 1.0)
        deleted = sc.delete_for_audio("a.npy")
        assert deleted == 2
        assert sc.stats()["total"] == 1
