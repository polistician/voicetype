"""Tests for SupervisorRunner — plumbing only; never touches WhisperKit.

A `FakeBackend` returns canned slow-transcript strings keyed by the audio
filename so we can simulate the (fast, slow) divergence and verify the
end-to-end loop wires the queue, diff, candidates, and promoter together
correctly.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from unittest import mock

import numpy as np

import supervisor_candidates as sc
import supervisor_queue
import supervisor_runner as sr


class FakeBackend(sr.SupervisorBackend):
    """Returns a canned slow transcript for each audio_path stem."""
    name = "fake"

    def __init__(self, table: dict[str, str], raise_on: set[str] | None = None) -> None:
        self.table = table
        self.raise_on = raise_on or set()

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        # Audio array is just zeros in tests; we identify "which pair"
        # by the caller-provided table. The runner doesn't pass the path
        # into transcribe, so the table is consulted in test setup using
        # the caller's chosen audio_path keys via patch.
        raise RuntimeError("Use _attach for per-pair stubs")


def _make_pair(training_dir: Path, ts: str, fast_text: str,
               audio_seconds: int = 2) -> Path:
    audio = np.zeros(16000 * audio_seconds, dtype=np.float32)
    audio_path = training_dir / f"{ts}.npy"
    meta_path = training_dir / f"{ts}.json"
    np.save(audio_path, audio)
    meta_path.write_text(json.dumps({
        "timestamp": ts,
        "transcript": fast_text,
        "corrected": fast_text,
        "confidence": 0.85,
        "sample_rate": 16000,
        "duration_seconds": float(audio_seconds),
        "is_correction": False,
    }))
    return audio_path


class _Stubs:
    """Patch all the on-disk paths the runner touches into a tmpdir."""
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.training = tmp / "training"
        self.state    = tmp / "supervisor_state.json"
        self.db       = tmp / "candidates.db"
        self.cfg      = tmp / "config.json"
        self.training.mkdir(parents=True, exist_ok=True)

    def patches(self):
        return [
            mock.patch.object(supervisor_queue, "TRAINING_DIR", self.training),
            mock.patch.object(supervisor_queue, "STATE_PATH",   self.state),
            mock.patch.object(sc, "DB_PATH",                    self.db),
        ]

    def __enter__(self):
        self._mgrs = self.patches()
        for m in self._mgrs:
            m.__enter__()
        return self

    def __exit__(self, *exc):
        for m in reversed(self._mgrs):
            m.__exit__(*exc)


def _make_fake_backend(slow_by_stem: dict[str, str]):
    """Build a backend instance whose `.transcribe` returns slow text picked
    by the most-recent audio path the runner is processing. We monkey-patch
    `_process_one` to peek at the audio_path."""
    class _Backend(sr.SupervisorBackend):
        name = "fake"
        def __init__(self): self.current_stem = None
        def transcribe(self, audio, sample_rate):
            return slow_by_stem.get(self.current_stem, "")
    return _Backend()


def _run_with_fake(runner: sr.SupervisorRunner, backend, slow_by_stem):
    """Wrap _process_one to bind current_stem on the fake backend before
    transcribe() runs."""
    original = runner._process_one
    def _wrap(audio_path, b, log):
        backend.current_stem = audio_path.stem
        return original(audio_path, b, log)
    runner._process_one = _wrap


def test_run_batch_processes_pending_and_emits_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Stubs(Path(tmp))
        with s:
            _make_pair(s.training, "20260520_120000", "i love voice type a lot")
            _make_pair(s.training, "20260521_140000", "the by ne file is corrupted")
            backend = _make_fake_backend({
                "20260520_120000": "I love VoiceType a lot.",
                "20260521_140000": "The binary file is corrupted.",
            })
            runner = sr.SupervisorRunner(backend=backend)
            _run_with_fake(runner, backend, {})
            result = runner.run_batch(max_pairs=10, time_budget_s=30,
                                       retention_days=0)
            assert result["error"] is None
            assert result["processed"] == 2
            assert result["candidates"] >= 2  # at least one per pair


def test_run_batch_marks_pairs_processed_so_they_dont_repeat():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Stubs(Path(tmp))
        with s:
            _make_pair(s.training, "20260520_120000", "voice type is great")
            backend = _make_fake_backend({"20260520_120000": "VoiceType is great."})
            runner = sr.SupervisorRunner(backend=backend)
            _run_with_fake(runner, backend, {})
            runner.run_batch(max_pairs=10, time_budget_s=30, retention_days=0)
            assert supervisor_queue.pending() == []


def test_run_batch_with_unavailable_backend_reports_error():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Stubs(Path(tmp))
        with s:
            _make_pair(s.training, "20260520_120000", "fast")
            runner = sr.SupervisorRunner(backend_name="nonexistent_backend")
            # _ensure_backend will raise; should fail cleanly
            result = runner.run_batch(max_pairs=10, time_budget_s=30,
                                       retention_days=0)
            assert result["error"] is not None
            assert result["processed"] == 0


def test_backend_transcribe_failure_marks_pair_failed_and_continues():
    """A bad pair shouldn't poison the whole batch."""
    with tempfile.TemporaryDirectory() as tmp:
        s = _Stubs(Path(tmp))
        with s:
            _make_pair(s.training, "20260520_120000", "bad pair")
            _make_pair(s.training, "20260521_140000", "good pair voice type works")

            class _FlakyBackend(sr.SupervisorBackend):
                name = "flaky"
                def __init__(self): self.current_stem = None
                def transcribe(self, audio, sample_rate):
                    if self.current_stem == "20260520_120000":
                        raise RuntimeError("simulated upstream timeout")
                    return "Good pair VoiceType works."
            backend = _FlakyBackend()
            runner = sr.SupervisorRunner(backend=backend)
            _run_with_fake(runner, backend, {})
            result = runner.run_batch(max_pairs=10, time_budget_s=30,
                                       retention_days=0)
            assert result["failed"] == 1
            assert result["processed"] == 1


def test_retention_sweep_drops_old_processed_pairs():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Stubs(Path(tmp))
        with s:
            # Old pair that was already processed
            old_pair = _make_pair(s.training, "20200101_000000", "old fast text")
            # Make the file mtime ancient
            os.utime(old_pair, (1577836800.0, 1577836800.0))  # 2020-01-01
            os.utime(old_pair.with_suffix(".json"), (1577836800.0, 1577836800.0))
            supervisor_queue.mark_processed(old_pair, result="ok")
            sc.add(str(old_pair), "new_vocab", {"word": "ancient"}, 1.0)
            # Recent unprocessed pair shouldn't be touched
            new_pair = _make_pair(s.training, "20260520_120000", "fresh")

            runner = sr.SupervisorRunner(backend=_make_fake_backend({}))
            result = runner.run_batch(max_pairs=0, time_budget_s=30,
                                       retention_days=1)
            assert result["retention_removed"] == 1
            assert not old_pair.exists()
            assert new_pair.exists()
            # Candidate row for the old pair should be gone
            assert sc.stats()["total"] == 0


def test_retention_skip_when_disabled():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Stubs(Path(tmp))
        with s:
            old = _make_pair(s.training, "20200101_000000", "ancient")
            os.utime(old, (1577836800.0, 1577836800.0))
            supervisor_queue.mark_processed(old, result="ok")
            runner = sr.SupervisorRunner(backend=_make_fake_backend({}))
            result = runner.run_batch(max_pairs=0, time_budget_s=30,
                                       retention_days=0)
            assert result["retention_removed"] == 0
            assert old.exists()


def test_time_budget_short_circuits_batch():
    with tempfile.TemporaryDirectory() as tmp:
        s = _Stubs(Path(tmp))
        with s:
            for i in range(5):
                _make_pair(s.training, f"2026052{i}_120000", f"fast {i}")

            class _SlowBackend(sr.SupervisorBackend):
                name = "slow"
                def __init__(self): self.current_stem = None
                def transcribe(self, audio, sample_rate):
                    time.sleep(0.4)
                    return f"slow output for {self.current_stem}"
            backend = _SlowBackend()
            runner = sr.SupervisorRunner(backend=backend)
            _run_with_fake(runner, backend, {})
            result = runner.run_batch(max_pairs=10, time_budget_s=1,
                                       retention_days=0)
            assert result["processed"] < 5  # budget kicked in
