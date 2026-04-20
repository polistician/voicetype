# suggestions.py
"""Snippet suggestions mined from the user's recent dictations.

Scan ~/.voxtype/decisions.jsonl for phrases dictated repeatedly. If the
same transcription comes up 3+ times and isn't already a saved snippet,
it's a candidate the user will probably want as a snippet.

Pure heuristic, no LLM. Whole-transcription match for now; n-gram
extraction can come later if this proves too crude.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


_STOP_ACTIONS = {"dictate"}  # Only dictations are snippet candidates; commands aren't.
_MIN_LEN_CHARS = 10
_MIN_LEN_WORDS = 3
_MAX_LEN_CHARS = 400


def _normalize(text: str) -> str:
    """Normalize whitespace + casing for dedup, preserving punctuation for display."""
    t = re.sub(r"\s+", " ", text.strip())
    return t


def suggest(
    decisions: Iterable[dict],
    existing_snippet_bodies: Iterable[str],
    min_repeats: int = 3,
    max_suggestions: int = 5,
) -> list[dict]:
    """Return snippet suggestions mined from recent decisions.

    Each suggestion: {"phrase": str, "count": int, "last_seen": int}
    """
    existing_set = {b.strip().lower() for b in existing_snippet_bodies if b}
    counts: Counter = Counter()
    last_seen: dict[str, int] = {}
    display_for_key: dict[str, str] = {}

    for d in decisions:
        if d.get("action") not in _STOP_ACTIONS:
            continue
        raw = d.get("raw", "")
        display = _normalize(raw)
        if len(display) < _MIN_LEN_CHARS or len(display) > _MAX_LEN_CHARS:
            continue
        if len(display.split()) < _MIN_LEN_WORDS:
            continue
        key = display.lower()
        if key in existing_set:
            continue
        counts[key] += 1
        display_for_key[key] = display  # keep original casing
        ts = d.get("ts", 0)
        if ts > last_seen.get(key, 0):
            last_seen[key] = ts

    suggestions: list[dict] = []
    for key, count in counts.most_common(max_suggestions * 3):
        if count < min_repeats:
            break
        suggestions.append({
            "phrase": display_for_key[key],
            "count": count,
            "last_seen": last_seen[key],
        })
        if len(suggestions) >= max_suggestions:
            break
    return suggestions
