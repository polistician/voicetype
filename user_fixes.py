# user_fixes.py
"""User-editable intent variants & corrections, loaded at runtime.

Stored at ~/.voxtype/user_intent_fixes.json. Merged with hardcoded
variants in intent.py. Lets the user grow VoxType's tolerance to
Whisper misrecognitions without code changes.
"""
from __future__ import annotations

import json
import os
import re
import threading
from typing import Optional


FIXES_PATH = os.path.expanduser("~/.voxtype/user_intent_fixes.json")

_DEFAULT = {
    "help_variants": [],
    "snippet_variants": [],
    "save_variants": [],
    "clipboard_variants": [],
    "corrections": {},
}

_lock = threading.Lock()


def load() -> dict:
    if not os.path.exists(FIXES_PATH):
        return {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in _DEFAULT.items()}
    try:
        with open(FIXES_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in _DEFAULT.items()}
    # Fill in any missing keys with defaults
    for k, v in _DEFAULT.items():
        data.setdefault(k, v.copy() if isinstance(v, (list, dict)) else v)
    return data


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(FIXES_PATH), exist_ok=True)
    tmp = FIXES_PATH + ".tmp"
    with _lock:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, FIXES_PATH)


def add_variant(intent_key: str, word: str) -> dict:
    """intent_key is one of: help, snippet, save, clipboard.
    Adds `word` to the matching variant list, dedupes, persists, returns full state.
    """
    key = f"{intent_key}_variants"
    data = load()
    if key not in data:
        raise ValueError(f"unknown intent_key: {intent_key}")
    word = word.strip().lower()
    if word and word not in data[key]:
        data[key].append(word)
        save(data)
    return data


def add_correction(wrong: str, right: str) -> dict:
    data = load()
    data["corrections"][wrong.strip().lower()] = right.strip()
    save(data)
    return data


# --- Heuristic parser ---

_INTENT_KEYWORDS = {
    "help": "help",
    "snippet": "snippet",
    "snippets": "snippet",
    "save": "save",
    # "clipboard" is intentionally excluded: "X should be clipboard" means a
    # word-level correction (the user wants clip-bot→clipboard substitution),
    # not an intent routing change. Use add_variant("clipboard", ...) explicitly
    # only when X is already a known Whisper misrecognition of the clipboard action.
}

_PATTERNS = [
    # "when I say X treat as Y" / "when I say X you should do Y"
    re.compile(
        r"when i say\s+(?P<x>.+?)\s+(treat\s+(?:as|it\s+as)|route\s+to|do|open|mean[s]?)\s+(?P<y>\w+)",
        re.IGNORECASE,
    ),
    # "X should be Y" / "X means Y" / "X is Y"
    re.compile(
        r"(?P<x>[\w\-' ]+?)\s+(should\s+be|means|is)\s+(?P<y>\w+)",
        re.IGNORECASE,
    ),
    # "treat X as Y"
    re.compile(
        r"treat\s+(?P<x>[\w\-' ]+?)\s+(?:as|like)\s+(?P<y>\w+)",
        re.IGNORECASE,
    ),
    # Short form: "fix X to Y" / "X to Y"
    re.compile(
        r"(?:fix\s+)?(?P<x>[\w\-' ]+?)\s+(?:to|->|→)\s+(?P<y>\w+)",
        re.IGNORECASE,
    ),
]


def parse_heuristic(description: str) -> Optional[dict]:
    """Return {"action": "add_variant"|"add_correction", ...} or None if unparseable.

    If Y is a known intent keyword (help/snippet/save/clipboard), emits add_variant.
    Otherwise emits add_correction (word-level substitution).
    """
    text = description.strip()
    if not text:
        return None
    for pat in _PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        x = m.group("x").strip().lower()
        y = m.group("y").strip().lower()
        if not x or not y:
            continue
        intent_key = _INTENT_KEYWORDS.get(y)
        if intent_key:
            # Take just the first token of x (the mis-heard word)
            x_word = x.split()[-1] if " " in x else x
            return {"action": "add_variant", "intent_key": intent_key, "word": x_word}
        # Otherwise: word-level correction
        return {"action": "add_correction", "wrong": x, "right": y}
    return None


def apply(fix: dict) -> str:
    """Apply a parsed fix. Returns a human-readable result string."""
    if fix["action"] == "add_variant":
        add_variant(fix["intent_key"], fix["word"])
        return f"Added {fix['word']!r} as a {fix['intent_key']} variant."
    if fix["action"] == "add_correction":
        add_correction(fix["wrong"], fix["right"])
        return f"Added correction: {fix['wrong']!r} → {fix['right']!r}."
    return "No action taken."


# --- LLM fallback via Claude Code CLI ---

def parse_with_claude(description: str, recent_intents: Optional[list] = None,
                      timeout_seconds: int = 15) -> Optional[dict]:
    """Use `claude -p` to parse a free-text fix description.

    Returns {"action": ..., ...} on success, None on failure (missing CLI,
    timeout, non-JSON output, invalid shape). No API key required — piggybacks
    on the user's existing Claude Code sign-in.
    """
    import shutil
    import subprocess

    claude_bin = shutil.which("claude")
    if not claude_bin:
        return None

    recent_block = ""
    if recent_intents:
        recent_block = "\nRecent VoxType transcriptions and how they were routed:\n" + "\n".join(
            f"- {r.get('text', '')!r} → {r.get('action', '')}"
            for r in recent_intents[-5:]
        )

    prompt = f"""You are parsing a correction request for VoxType (a voice dictation tool).

Available command keys: help, snippet, save, clipboard.
Routing actions seen: dictate, paste_snippet, open_overview, open_help, open_fix, save_snippet.
{recent_block}

User's correction: "{description}"

Return ONE JSON object, no prose, no markdown fences. Pick the shape that fits:
- {{"action": "add_variant", "intent_key": "help"|"snippet"|"save"|"clipboard", "word": "<the_misheard_word>"}}
- {{"action": "add_correction", "wrong": "<what_whisper_wrote>", "right": "<what_it_should_be>"}}

add_variant means: "when Whisper hears WORD, route it as INTENT_KEY".
add_correction means: "when Whisper writes WRONG, replace with RIGHT in the transcription".

Output only the JSON object."""

    try:
        result = subprocess.run(
            [claude_bin, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    # Strip markdown fences if the model included them despite the instruction
    if output.startswith("```"):
        lines = [l for l in output.split("\n") if not l.strip().startswith("```")]
        output = "\n".join(lines).strip()

    try:
        fix = json.loads(output)
    except json.JSONDecodeError:
        return None

    action = fix.get("action")
    if action == "add_variant":
        if fix.get("intent_key") in {"help", "snippet", "save", "clipboard"} and fix.get("word"):
            return {"action": "add_variant",
                    "intent_key": fix["intent_key"],
                    "word": str(fix["word"]).strip().lower()}
    elif action == "add_correction":
        if fix.get("wrong") and fix.get("right"):
            return {"action": "add_correction",
                    "wrong": str(fix["wrong"]).strip().lower(),
                    "right": str(fix["right"]).strip()}

    return None
