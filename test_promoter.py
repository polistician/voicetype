"""Tests for the candidate promoter.

The promoter walks unpromoted candidates in the SQLite store and applies
threshold rules. We exercise:

  - new_vocab below threshold ⇒ no promotion
  - new_vocab at/above threshold ⇒ vocabulary.add called once with source=supervisor
  - substitution below threshold ⇒ no promotion
  - substitution at/above threshold ⇒ corrections.add_correction called
  - dry_run mode reports counts but doesn't write
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import supervisor_candidates as sc
import promoter as p


def _patch_db(tmp: str):
    return mock.patch.object(sc, "DB_PATH", Path(tmp) / "candidates.db")


def _seed(audio: str, type_: str, payload: dict, conf: float = 0.9) -> int:
    return sc.add(audio, type_, payload, conf)


# ── new_vocab ──────────────────────────────────────────────────────────────


def test_new_vocab_below_threshold_not_promoted():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        _seed("a.npy", "new_vocab", {"word": "Polistician"})
        # Only 1 distinct audio → below threshold of 2
        with mock.patch("vocabulary.add") as vmock:
            summary = p.run(dry_run=False)
        assert vmock.call_count == 0
        assert summary["new_vocab_promoted"] == 0


def test_new_vocab_at_threshold_promoted():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        _seed("a.npy", "new_vocab", {"word": "Polistician"})
        _seed("b.npy", "new_vocab", {"word": "Polistician"})
        with mock.patch("vocabulary.add") as vmock:
            summary = p.run(dry_run=False)
        assert vmock.call_count == 1
        # promoted with source=supervisor
        _, kwargs = vmock.call_args
        assert kwargs.get("source") == "supervisor"
        assert summary["new_vocab_promoted"] == 1


def test_new_vocab_same_audio_repeated_does_not_count_twice():
    """Threshold counts DISTINCT audio paths — two candidates from one
    recording shouldn't be enough to promote."""
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        _seed("a.npy", "new_vocab", {"word": "Polistician"})
        _seed("a.npy", "new_vocab", {"word": "Polistician"})
        _seed("a.npy", "new_vocab", {"word": "Polistician"})
        with mock.patch("vocabulary.add") as vmock:
            summary = p.run(dry_run=False)
        assert vmock.call_count == 0
        assert summary["new_vocab_promoted"] == 0


def test_new_vocab_promotion_marks_candidates_promoted():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        _seed("a.npy", "new_vocab", {"word": "Polistician"})
        _seed("b.npy", "new_vocab", {"word": "Polistician"})
        with mock.patch("vocabulary.add", return_value=True):
            p.run(dry_run=False)
        # All candidates for this word should be stamped promoted
        remaining = sc.unpromoted(type_="new_vocab")
        assert remaining == []


# ── substitution ────────────────────────────────────────────────────────────


def test_substitution_below_threshold_not_promoted():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        _seed("a.npy", "substitution", {"from": "voice type", "to": "VoiceType"})
        _seed("b.npy", "substitution", {"from": "voice type", "to": "VoiceType"})
        # Need 3 distinct audios
        with mock.patch("corrections.add_correction") as cmock:
            summary = p.run(dry_run=False)
        assert cmock.call_count == 0
        assert summary["substitutions_promoted"] == 0


def test_substitution_at_threshold_promoted_with_source():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        for audio in ("a.npy", "b.npy", "c.npy"):
            _seed(audio, "substitution", {"from": "voice type", "to": "VoiceType"})
        with mock.patch("corrections.add_correction") as cmock:
            summary = p.run(dry_run=False)
        assert cmock.call_count == 1
        args, kwargs = cmock.call_args
        assert kwargs.get("source") == "supervisor"
        assert args[0] == "voice type"
        assert args[1] == "VoiceType"
        assert summary["substitutions_promoted"] == 1


# ── dry-run ──────────────────────────────────────────────────────────────────


def test_dry_run_does_not_write_or_stamp():
    with tempfile.TemporaryDirectory() as tmp, _patch_db(tmp):
        _seed("a.npy", "new_vocab", {"word": "Polistician"})
        _seed("b.npy", "new_vocab", {"word": "Polistician"})
        with mock.patch("vocabulary.add") as vmock:
            summary = p.run(dry_run=True)
        assert vmock.call_count == 0
        assert summary["new_vocab_promoted"] == 1   # reported as a *would*
        # rows must remain unpromoted
        assert sc.unpromoted(type_="new_vocab") != []


# ── language_switch ─────────────────────────────────────────────────────────


def test_language_switch_relaxes_pinned_input_language(tmp_path, monkeypatch):
    """If config.json pins input_language to a non-auto value and the
    supervisor saw a language switch, we should relax to 'auto'."""
    cfg = tmp_path / "config.json"
    cfg.write_text('{"input_language": "en"}')
    monkeypatch.setattr(os.path, "expanduser",
                        lambda s: str(cfg) if s.endswith("config.json") else os.path.expanduser(s))

    with tempfile.TemporaryDirectory() as db_tmp, _patch_db(db_tmp):
        _seed("a.npy", "language_switch", {"detected_lang": "de"})
        summary = p.run(dry_run=False)

    import json
    assert json.loads(cfg.read_text())["input_language"] == "auto"
    assert summary["language_switches"] == 1
