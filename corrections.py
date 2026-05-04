# corrections.py
"""Post-processing correction layer for VoxType.

Maintains a user-specific substitution dictionary. When Whisper
consistently mistranscribes a word (e.g., "fox" → should be "vox"),
the correction is stored and applied automatically to future transcriptions.

Two sources of corrections:
1. Explicit: user tells us "when I say X you wrote Y, it should be Z"
2. Implicit: accumulated from voice profile low-confidence patterns

The correction runs AFTER Whisper, BEFORE paste. Pure string replacement,
zero latency cost.
"""
import json
import os
import re

CORRECTIONS_PATH = os.path.expanduser("~/.voxtype/corrections.json")


def _load() -> dict:
    """Load corrections dict: {"wrong": "right", ...}"""
    if os.path.exists(CORRECTIONS_PATH):
        try:
            with open(CORRECTIONS_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save(corrections: dict):
    os.makedirs(os.path.dirname(CORRECTIONS_PATH), exist_ok=True)
    with open(CORRECTIONS_PATH, "w") as f:
        json.dump(corrections, f, indent=2)


def add_correction(wrong: str, right: str):
    """Add a correction: wrong → right."""
    corrections = _load()
    corrections[wrong.lower()] = right
    _save(corrections)


def apply_corrections(text: str) -> str:
    """Apply all stored corrections to a transcription.

    Uses word-boundary matching to avoid partial replacements.
    Case-insensitive matching, preserves original case pattern.
    """
    corrections = _load()
    if not corrections:
        return text

    for wrong, right in corrections.items():
        # Word-boundary replacement, case-insensitive
        pattern = r'\b' + re.escape(wrong) + r'\b'
        text = re.sub(pattern, right, text, flags=re.IGNORECASE)

    return text


def get_corrections() -> dict:
    return _load()


def auto_learn_corrections():
    """Infer corrections from voice profile data — zero user effort.

    Logic: if a low-confidence word is within edit distance 1 of a
    known domain/vocabulary word, it's probably a misrecognition.
    Auto-add the correction.
    """
    try:
        from voice_profile import _load as load_profile
    except ImportError:
        return 0

    profile = load_profile()
    lc_words = profile.get("low_confidence_words", {})
    vocab = profile.get("vocabulary", {})
    corrections = _load()
    added = 0

    # Domain words the user actually uses (count >= 3 in vocabulary)
    known = {w for w, c in vocab.items() if c >= 3}
    # Add seeded domain words
    known.update(_DOMAIN_DEFAULTS.values())
    known = {w.lower() for w in known}

    for wrong, count in lc_words.items():
        if count < 2:  # need at least 2 occurrences
            continue
        if len(wrong) < 4:  # short words cause too many false positives
            continue
        if wrong in corrections:  # already have a correction
            continue
        if wrong in known:  # it's a real word the user uses
            continue

        # Check edit distance 1 against known words
        for right in known:
            if len(right) < 4:  # don't correct TO short words either
                continue
            if _edit_distance_1(wrong, right):
                corrections[wrong] = right
                added += 1
                break

    if added:
        _save(corrections)
    return added


def _edit_distance_1(a: str, b: str) -> bool:
    """True if a and b differ by exactly 1 character (substitution, insert, or delete)."""
    if a == b:
        return False
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        # Substitution: exactly one position differs
        return sum(x != y for x, y in zip(a, b)) == 1
    # Insert/delete: the longer string has one extra char
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = j = diffs = 0
    while i < len(short) and j < len(long):
        if short[i] != long[j]:
            diffs += 1
            j += 1
        else:
            i += 1
            j += 1
    return diffs <= 1


# Common known corrections for domain vocabulary
# These are seeded once and can be overridden by user corrections
_DOMAIN_DEFAULTS = {
    "fox": "vox",
    "fox type": "VoxType",
    "soma hook": "SOMA hook",
    "in gram": "engram",
    "n gram": "engram",
}


def seed_defaults():
    """Seed domain-specific corrections if not already present."""
    corrections = _load()
    changed = False
    for wrong, right in _DOMAIN_DEFAULTS.items():
        if wrong not in corrections:
            corrections[wrong] = right
            changed = True
    if changed:
        _save(corrections)
