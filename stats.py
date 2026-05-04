# stats.py
"""Persistent usage stats + recent-decisions log for VoxType.

Two files:
  ~/.voicetype/stats.json        — monotonic counters
  ~/.voicetype/decisions.jsonl   — last 50 transcriptions with raw+final (for Demo)
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from typing import Optional


STATS_PATH = os.path.expanduser("~/.voicetype/stats.json")
DECISIONS_PATH = os.path.expanduser("~/.voicetype/decisions.jsonl")
_DECISIONS_KEEP = 50

_DEFAULT_STATS = {
    "first_used_at": None,          # epoch seconds
    "recordings_total": 0,
    "words_dictated_total": 0,
    "snippet_pastes": 0,
    "help_opens": 0,
    "fix_opens": 0,
    "overview_opens": 0,
    "corrections_applied": 0,       # Whisper errors caught by corrections.py
    "fuzzy_help_saves": 0,          # how often fuzzy ratio saved a help route
    "fuzzy_save_saves": 0,          # same for save_snippet flexible grammar
    "user_variant_saves": 0,        # how often a user-added variant fired
    "autogen_name_used": 0,         # how often autogen filled metadata
}

_lock = threading.Lock()


def load() -> dict:
    if not os.path.exists(STATS_PATH):
        s = _DEFAULT_STATS.copy()
        s["first_used_at"] = int(time.time())
        return s
    try:
        with open(STATS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = _DEFAULT_STATS.copy()
    # Backfill any missing keys
    for k, v in _DEFAULT_STATS.items():
        data.setdefault(k, v)
    if data.get("first_used_at") is None:
        data["first_used_at"] = int(time.time())
    return data


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(STATS_PATH), exist_ok=True)
    tmp = STATS_PATH + ".tmp"
    with _lock:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STATS_PATH)


def increment(key: str, by: int = 1) -> None:
    data = load()
    data[key] = data.get(key, 0) + by
    save(data)


def log_decision(
    raw_text: str,
    final_action: str,
    final_detail: str = "",
    duration_s: float = 0.0,
    was_corrected: bool = False,
) -> None:
    """Append a decision to the ring-buffered JSONL log.

    raw_text:     what Whisper initially transcribed (before corrections/intent)
    final_action: dictate | paste_snippet | open_help | open_overview | save_snippet | open_fix | skip_short | skip_empty
    final_detail: e.g. matched snippet name, "fuzzy: hope→help", corrected text
    duration_s:   length of the audio in seconds
    was_corrected: True if corrections.py modified the text
    """
    entry = {
        "ts": int(time.time()),
        "raw": raw_text[:500],
        "action": final_action,
        "detail": final_detail[:300],
        "duration_s": round(duration_s, 2),
        "corrected": bool(was_corrected),
    }
    os.makedirs(os.path.dirname(DECISIONS_PATH), exist_ok=True)
    with _lock:
        # Read existing, trim, append
        existing: deque = deque(maxlen=_DECISIONS_KEEP)
        if os.path.exists(DECISIONS_PATH):
            try:
                with open(DECISIONS_PATH) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            existing.append(line)
            except OSError:
                pass
        existing.append(json.dumps(entry))
        tmp = DECISIONS_PATH + ".tmp"
        with open(tmp, "w") as f:
            for line in existing:
                f.write(line + "\n")
        os.replace(tmp, DECISIONS_PATH)


def recent_decisions(n: int = 10) -> list[dict]:
    """Most-recent-first list of decision entries."""
    if not os.path.exists(DECISIONS_PATH):
        return []
    out = []
    try:
        with open(DECISIONS_PATH) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return list(reversed(out))[:n]
