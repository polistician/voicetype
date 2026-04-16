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
