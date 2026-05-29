"""supervisor_runner.py — background batch worker for the v0.15 pipeline.

Pulls unprocessed `(audio.npy, meta.json)` pairs from `supervisor_queue.pending()`,
re-transcribes each through a slower, more accurate model (default:
WhisperKit large-v3), diffs against the fast transcript already on disk in
the meta, and pushes structured candidates into `supervisor_candidates`.

The promoter is invoked AFTER the batch so any threshold-hitting candidates
get applied to `vocabulary.json` / `corrections.json` immediately. The whole
thing is single-threaded and bounded: a `time_budget_s` hard-stop and a
`max_pairs` cap make it safe to fire from an idle trigger without
runaway-CPU concerns.

A 30-day retention sweep runs at the start of every batch so the disk
footprint stays bounded. Sweeps are conservative: they only delete pairs
whose key already appears in `supervisor_state.processed` (i.e. we DID
look at them) so an unprocessed clip can never be silently dropped.

WhisperKit is lazy-imported. On Intel Macs or systems without the helper
binary, the runner reports `backend_unavailable` and exits cleanly — the
rest of the codebase keeps working with no fine-tuning signal until the
user fixes it.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

import supervisor_candidates as candidates
import supervisor_diff
import supervisor_queue


DEFAULT_BACKEND = "whisperkit"
DEFAULT_MAX_PAIRS = 50
DEFAULT_TIME_BUDGET_S = 300
DEFAULT_RETENTION_DAYS = 30

WHISPERKIT_MODEL_SUBDIR = "whisperkit/openai_whisper-large-v3_turbo"


# ────────────────────────────────────────────────────────────────────────────
# Supervisor backend protocol
# ────────────────────────────────────────────────────────────────────────────


class SupervisorBackend:
    """Minimal interface every supervisor backend must satisfy.

    `transcribe(audio_array, sample_rate)` returns a plain text string (no
    timestamps, no rich segments — the diff only needs the words). Backends
    are free to raise; the runner catches and records a per-pair failure.
    """
    name: str = "abstract"

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:  # pragma: no cover
        raise NotImplementedError


class _WhisperKitSupervisor(SupervisorBackend):
    """WhisperKit large-v3 via the existing `whisperkit_backend.WhisperKitBackend`
    helper. Loads once per runner instance; the helper binary stays alive
    between batches if the caller keeps the instance."""
    name = "whisperkit"

    def __init__(self, model_dir: Optional[str] = None) -> None:
        from whisperkit_backend import WhisperKitBackend  # lazy
        if model_dir is None:
            # Mirror voxtype.py's resolution path.
            model_dir = os.path.expanduser(
                f"~/voicetype/models/{WHISPERKIT_MODEL_SUBDIR}"
            )
        self._backend = WhisperKitBackend(model_path=model_dir)
        self._backend.load()
        # Pin language=auto so the supervisor catches code-switches the fast
        # path missed.
        self._backend.set_language("auto")

    def transcribe(self, audio: np.ndarray, sample_rate: int) -> str:
        rich = self._backend.transcribe(audio)
        return (rich.get("text") if isinstance(rich, dict) else "") or ""


def _build_backend(name: str) -> SupervisorBackend:
    name = (name or DEFAULT_BACKEND).strip().lower()
    if name in ("whisperkit", "wk", "auto"):
        return _WhisperKitSupervisor()
    raise RuntimeError(f"Unknown supervisor backend: {name!r}")


# ────────────────────────────────────────────────────────────────────────────
# Retention sweep
# ────────────────────────────────────────────────────────────────────────────


def _retention_sweep(retention_days: int, log: Callable[[str], None]) -> int:
    """Delete training pairs whose audio file is older than `retention_days`
    AND whose key is already in `supervisor_state.processed`. Also nukes
    matching candidate rows so the DB doesn't keep pointing at deleted
    audio. Returns number of (audio, meta) pair-pairs removed."""
    if retention_days <= 0:
        return 0
    cutoff = time.time() - retention_days * 86400
    removed = 0
    training_dir = supervisor_queue.TRAINING_DIR
    if not training_dir.exists():
        return 0
    state = supervisor_queue._load_state()
    processed = state.get("processed", {})

    for audio_path in sorted(training_dir.glob("*.npy")):
        try:
            mtime = audio_path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue
        key = audio_path.stem
        if key not in processed:
            # Defensive: don't delete pairs we haven't supervised yet, even
            # if they're old — the user may have fired up the supervisor
            # after a long gap and the queue is still working through them.
            continue
        # Remove audio + sidecar + candidate rows
        meta_path = audio_path.with_suffix(".json")
        try:
            audio_path.unlink()
            if meta_path.exists():
                meta_path.unlink()
            n_rows = candidates.delete_for_audio(str(audio_path))
            log(f"[supervisor] retained-out {audio_path.name} ({n_rows} candidate rows)")
            removed += 1
        except OSError as e:
            log(f"[supervisor] retention delete failed for {audio_path.name}: {e}")
    return removed


# ────────────────────────────────────────────────────────────────────────────
# Batch worker
# ────────────────────────────────────────────────────────────────────────────


class SupervisorRunner:
    """Reusable batch worker. Create once and call `run_batch()` repeatedly
    so the heavyweight backend load amortizes across runs."""

    def __init__(self, backend_name: str = DEFAULT_BACKEND,
                 backend: Optional[SupervisorBackend] = None) -> None:
        self.backend_name = backend_name
        self._backend = backend  # explicit injection used by tests
        self._backend_init_error: Optional[str] = None

    def _ensure_backend(self) -> Optional[SupervisorBackend]:
        if self._backend is not None:
            return self._backend
        if self._backend_init_error is not None:
            return None  # already tried, gave up
        try:
            self._backend = _build_backend(self.backend_name)
            return self._backend
        except Exception as e:
            self._backend_init_error = str(e)
            return None

    def run_batch(self,
                  max_pairs: int = DEFAULT_MAX_PAIRS,
                  time_budget_s: int = DEFAULT_TIME_BUDGET_S,
                  retention_days: int = DEFAULT_RETENTION_DAYS,
                  log: Optional[Callable[[str], None]] = None,
                  ) -> dict:
        """Process up to `max_pairs` pending pairs or until `time_budget_s`
        elapses, whichever comes first. Returns a result dict."""
        log_fn = log or (lambda _: None)
        result: dict = {
            "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "processed": 0,
            "candidates": 0,
            "skipped": 0,
            "failed": 0,
            "retention_removed": 0,
            "backend": self.backend_name,
            "promotions": None,
            "error": None,
        }

        # Retention first so a pair we're about to supervise can't be one we'd
        # rather have deleted (would race with the candidates rows).
        result["retention_removed"] = _retention_sweep(retention_days, log_fn)

        backend = self._ensure_backend()
        if backend is None:
            result["error"] = f"backend_unavailable: {self._backend_init_error}"
            return result

        deadline = time.monotonic() + max(1, time_budget_s)
        pending = supervisor_queue.pending()
        log_fn(f"[supervisor] pending: {len(pending)} pair(s)")

        for audio_path in pending[: max(0, max_pairs)]:
            if time.monotonic() >= deadline:
                log_fn("[supervisor] time budget hit; stopping batch early")
                break
            try:
                cand_count = self._process_one(audio_path, backend, log_fn)
            except Exception as e:
                log_fn(f"[supervisor] {audio_path.name} failed: {e}")
                supervisor_queue.mark_failed(audio_path, str(e))
                result["failed"] += 1
                continue
            if cand_count is None:
                result["skipped"] += 1
                continue
            result["processed"] += 1
            result["candidates"] += cand_count

        # Run the promoter once at the end so threshold-hitting candidates
        # land in vocabulary.json / corrections.json before voxtype's next
        # _refresh_whisper_vocab call.
        try:
            import promoter
            result["promotions"] = promoter.run(log=log_fn)
        except Exception as e:
            log_fn(f"[supervisor] promoter step failed: {e}")
            result["promotions"] = {"error": str(e)}

        result["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return result

    def _process_one(self, audio_path: Path, backend: SupervisorBackend,
                     log: Callable[[str], None]) -> Optional[int]:
        """Returns candidate-count if processed, None if skipped."""
        meta_path = audio_path.with_suffix(".json")
        if not meta_path.exists():
            supervisor_queue.mark_processed(audio_path, result="skipped",
                                             reason="meta_missing")
            return None
        try:
            meta = json.loads(meta_path.read_text())
        except Exception as e:
            supervisor_queue.mark_processed(audio_path, result="skipped",
                                             reason=f"meta_invalid: {e}")
            return None

        # The fast transcript is whichever is more interesting: the
        # corrected text (Quick Fix etc.) if it differs, else the raw.
        fast_text: str = meta.get("corrected") or meta.get("transcript") or ""
        sample_rate: int = int(meta.get("sample_rate") or 16000)

        try:
            audio = np.load(audio_path)
        except Exception as e:
            supervisor_queue.mark_processed(audio_path, result="skipped",
                                             reason=f"audio_load_failed: {e}")
            return None

        try:
            slow_text = backend.transcribe(audio, sample_rate)
        except Exception as e:
            # Treat backend transcription failures as transient — bounce to
            # the retry path so a one-off glitch doesn't permanently sideline
            # a pair.
            raise RuntimeError(f"backend.transcribe: {e}") from e

        cands = supervisor_diff.diff(fast_text, slow_text)
        if not cands:
            supervisor_queue.mark_processed(audio_path, result="ok",
                                             reason="no_candidates")
            return 0

        candidates.add_batch(str(audio_path), cands)
        supervisor_queue.mark_processed(audio_path, result="ok",
                                         reason=f"{len(cands)} candidate(s)")
        log(f"[supervisor] {audio_path.name}: {len(cands)} candidate(s) added")
        return len(cands)


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────


def _cli(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m supervisor_runner")
    p.add_argument("--max", type=int, default=DEFAULT_MAX_PAIRS,
                   help="maximum pairs to process this batch (default 50)")
    p.add_argument("--budget", type=int, default=DEFAULT_TIME_BUDGET_S,
                   help="hard time budget in seconds (default 300)")
    p.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS,
                   help="delete training pairs older than this (default 30)")
    p.add_argument("--backend", default=DEFAULT_BACKEND,
                   help="supervisor backend name (default whisperkit)")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    def _log(msg: str) -> None:
        if not args.quiet:
            print(msg, flush=True)

    runner = SupervisorRunner(backend_name=args.backend)
    result = runner.run_batch(
        max_pairs=args.max,
        time_budget_s=args.budget,
        retention_days=args.retention_days,
        log=_log,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("error") is None else 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
