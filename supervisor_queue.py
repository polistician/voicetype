"""supervisor_queue.py — track which training pairs are pending supervision.

The training_data module already saves (audio.npy, meta.json) pairs into
~/.voicetype/training/ on every dictation. This module adds a tiny
processed-set on top so the supervisor pipeline only re-supervises pairs
it hasn't seen yet.

State lives in `~/.voicetype/supervisor_state.json` and looks like:

    {
      "processed": {
        "20260522_140133": {
          "result":   "ok" | "skipped" | "failed",
          "ts":       "2026-05-22T14:05:32",
          "reason":   "optional explanation"
        },
        ...
      },
      "schema_version": 1
    }

Why a dict keyed on the audio timestamp instead of a sibling marker file?
On 30-day retention sweeps we delete the audio + meta but still want to
remember "we processed this and produced N candidates" — that audit fact
shouldn't disappear with the source media.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


TRAINING_DIR = Path(os.path.expanduser("~/.voicetype/training"))
STATE_PATH = Path(os.path.expanduser("~/.voicetype/supervisor_state.json"))


_SCHEMA_VERSION = 1


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {"processed": {}, "schema_version": _SCHEMA_VERSION}
    try:
        with open(STATE_PATH) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"processed": {}, "schema_version": _SCHEMA_VERSION}
    if "processed" not in data or not isinstance(data["processed"], dict):
        data["processed"] = {}
    data.setdefault("schema_version", _SCHEMA_VERSION)
    return data


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write — write to a sibling then rename so a crash mid-write
    # doesn't truncate the existing state file.
    tmp = STATE_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)
    tmp.replace(STATE_PATH)


def _audio_key(audio_path: Path) -> str:
    """Stable key derived from the audio filename stem (the timestamp)."""
    return audio_path.stem


def pending() -> list[Path]:
    """Return unprocessed `(audio.npy)` paths in chronological order.

    Pairs are skipped if:
      - their meta.json is missing (orphan audio),
      - the audio is too short (< 1 s — same gate as training_data uses),
      - they're already recorded in `supervisor_state.processed`.
    """
    if not TRAINING_DIR.exists():
        return []
    state = _load_state()
    processed = state["processed"]
    out: list[Path] = []
    for audio_path in sorted(TRAINING_DIR.glob("*.npy")):
        key = _audio_key(audio_path)
        if key in processed:
            continue
        meta_path = audio_path.with_suffix(".json")
        if not meta_path.exists():
            continue
        out.append(audio_path)
    return out


def mark_processed(audio_path: Path, result: str = "ok",
                   reason: Optional[str] = None) -> None:
    """Record that `audio_path` has been supervised. Survives 30-day cleanup."""
    state = _load_state()
    entry: dict = {
        "result": result,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if reason:
        entry["reason"] = reason
    state["processed"][_audio_key(audio_path)] = entry
    _save_state(state)


def mark_failed(audio_path: Path, error: str) -> None:
    """Record a transient failure so the pair can be retried next batch."""
    state = _load_state()
    key = _audio_key(audio_path)
    # Keep failures out of `processed` so pending() returns them again,
    # but record the attempt count + last error under a separate failures
    # bucket — three strikes and we give up.
    failures = state.setdefault("failures", {})
    entry = failures.get(key, {"attempts": 0, "first_failure": None, "last_error": None})
    entry["attempts"] = int(entry.get("attempts", 0)) + 1
    if entry["first_failure"] is None:
        entry["first_failure"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entry["last_error"] = error[:500]
    failures[key] = entry
    if entry["attempts"] >= 3:
        # Three failed attempts → give up, mark processed with the failure reason.
        state["processed"][key] = {
            "result": "failed",
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": entry["last_error"],
        }
        failures.pop(key, None)
    _save_state(state)


def processed_count() -> int:
    return len(_load_state()["processed"])


def stats() -> dict:
    """Return a snapshot for the Settings panel + CLI."""
    state = _load_state()
    counts: dict = {"ok": 0, "skipped": 0, "failed": 0}
    for entry in state["processed"].values():
        r = entry.get("result", "ok")
        counts[r] = counts.get(r, 0) + 1
    return {
        "processed_total": len(state["processed"]),
        "by_result": counts,
        "in_flight_failures": len(state.get("failures", {})),
        "pending": len(pending()),
    }


def prune_state_for_missing_audio(grace_days: int = 90) -> int:
    """Remove processed entries whose original audio has been gone for
    longer than `grace_days`. Defensive: in normal use the processed set
    grows monotonically, but this lets a user wipe the whole training/
    directory without leaving the state file with orphaned references.
    Returns the number of entries pruned.
    """
    state = _load_state()
    processed = state["processed"]
    pruned = 0
    cutoff_ts = datetime.now(timezone.utc).timestamp() - grace_days * 86400
    for key in list(processed.keys()):
        audio_path = TRAINING_DIR / f"{key}.npy"
        if audio_path.exists():
            continue
        # Audio missing; only prune entries older than `grace_days` so a
        # fresh dictation right before a sweep isn't dropped.
        ts_str = processed[key].get("ts")
        try:
            ts = datetime.fromisoformat(ts_str).timestamp() if ts_str else 0
        except ValueError:
            ts = 0
        if ts < cutoff_ts:
            processed.pop(key)
            pruned += 1
    if pruned:
        _save_state(state)
    return pruned
