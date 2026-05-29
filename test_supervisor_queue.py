"""Tests for supervisor_queue (training-pair pending/processed state machine)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np

import supervisor_queue


def _seed_pair(training_dir: Path, ts: str, audio_seconds: int = 2) -> Path:
    """Drop a stub (audio.npy, meta.json) pair into the training dir."""
    audio = np.zeros(16000 * audio_seconds, dtype=np.float32)
    audio_path = training_dir / f"{ts}.npy"
    meta_path = training_dir / f"{ts}.json"
    np.save(audio_path, audio)
    meta_path.write_text(json.dumps({
        "timestamp": ts, "transcript": "hello world",
        "corrected": "hello world", "confidence": 0.9,
        "sample_rate": 16000, "duration_seconds": float(audio_seconds),
        "is_correction": False,
    }))
    return audio_path


def test_pending_returns_unprocessed_pairs_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        training = tmp_path / "training"
        state = tmp_path / "state.json"
        training.mkdir()
        a = _seed_pair(training, "20260520_120000")
        b = _seed_pair(training, "20260521_140000")

        with mock.patch.object(supervisor_queue, "TRAINING_DIR", training), \
             mock.patch.object(supervisor_queue, "STATE_PATH", state):
            got = supervisor_queue.pending()
        # chronological by filename stem (which is the timestamp)
        assert [p.name for p in got] == [a.name, b.name]


def test_pending_skips_orphan_audio_without_meta():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        training = tmp_path / "training"
        state = tmp_path / "state.json"
        training.mkdir()
        # Audio with NO meta sidecar
        np.save(training / "20260520_120000.npy", np.zeros(16000, dtype=np.float32))
        with mock.patch.object(supervisor_queue, "TRAINING_DIR", training), \
             mock.patch.object(supervisor_queue, "STATE_PATH", state):
            assert supervisor_queue.pending() == []


def test_mark_processed_excludes_from_pending():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        training = tmp_path / "training"
        state = tmp_path / "state.json"
        training.mkdir()
        a = _seed_pair(training, "20260520_120000")
        b = _seed_pair(training, "20260521_140000")
        with mock.patch.object(supervisor_queue, "TRAINING_DIR", training), \
             mock.patch.object(supervisor_queue, "STATE_PATH", state):
            supervisor_queue.mark_processed(a, result="ok")
            remaining = supervisor_queue.pending()
        assert [p.name for p in remaining] == [b.name]


def test_mark_failed_retries_twice_then_gives_up():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        training = tmp_path / "training"
        state = tmp_path / "state.json"
        training.mkdir()
        a = _seed_pair(training, "20260520_120000")
        with mock.patch.object(supervisor_queue, "TRAINING_DIR", training), \
             mock.patch.object(supervisor_queue, "STATE_PATH", state):
            # First two failures keep the pair in the queue.
            supervisor_queue.mark_failed(a, "transient error")
            assert supervisor_queue.pending() == [a]
            supervisor_queue.mark_failed(a, "transient error")
            assert supervisor_queue.pending() == [a]
            # Third strike → permanently marked failed, removed from pending.
            supervisor_queue.mark_failed(a, "transient error")
            assert supervisor_queue.pending() == []
            s = supervisor_queue.stats()
            assert s["by_result"]["failed"] == 1
            assert s["in_flight_failures"] == 0


def test_atomic_save_survives_concurrent_corruption():
    """If the JSON on disk is garbage, _load_state returns a clean default
    rather than crashing the supervisor."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        training = tmp_path / "training"
        state = tmp_path / "state.json"
        training.mkdir()
        state.write_text("{not really json")
        with mock.patch.object(supervisor_queue, "TRAINING_DIR", training), \
             mock.patch.object(supervisor_queue, "STATE_PATH", state):
            # Should not raise.
            assert supervisor_queue.processed_count() == 0


def test_prune_state_drops_orphan_processed_entries_after_grace():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        training = tmp_path / "training"
        state = tmp_path / "state.json"
        training.mkdir()
        # Simulate an entry whose audio has been retention-deleted.
        state.write_text(json.dumps({
            "processed": {
                "old_orphan": {"result": "ok", "ts": "2020-01-01T00:00:00+00:00"},
                "recent_orphan": {"result": "ok", "ts": "2099-01-01T00:00:00+00:00"},
            },
            "schema_version": 1,
        }))
        with mock.patch.object(supervisor_queue, "TRAINING_DIR", training), \
             mock.patch.object(supervisor_queue, "STATE_PATH", state):
            pruned = supervisor_queue.prune_state_for_missing_audio(grace_days=90)
        assert pruned == 1  # only the 2020 one
