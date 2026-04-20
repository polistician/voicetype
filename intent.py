# intent.py
"""Post-transcription intent router for VoxType.

Classifies every transcription into one of:
  - dictate: paste the transcription as-is (legacy behavior)
  - paste_snippet: semantic-match the description to a snippet
  - open_overview: open the snippet manager overlay
  - save_snippet: open overlay with a draft prefilled from clipboard

Reliability layers (see spec §5.1 and §7):
  1. Whisper vocabulary prompt bias (lives in voxtype.py / voice_profile.py)
  2. Fuzzy trigger detection (rapidfuzz on first 1–3 tokens)
  3. Rule-based action parse
  4. Default to 'dictate' if nothing trips
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz


Action = Literal["dictate", "paste_snippet", "open_overview", "save_snippet", "open_help", "open_fix"]


@dataclass
class Intent:
    action: Action
    payload: dict = field(default_factory=dict)
    confidence: float = 1.0


# Tokens that count as "the snippet trigger"; fuzzy-matched (partial_ratio >= 85)
_TRIGGER_TOKENS = {"snippet", "snippets", "snipped", "snip it", "senate"}

# Single-token trigger words (first word of transcription)
_SINGLE_TRIGGERS = {"snippet", "snippets", "snipped", "senate"}

# Two-token trigger prefixes
_TWO_TOKEN_TRIGGERS = {
    ("insert", "snippet"),
    ("paste", "snippet"),
    ("use", "snippet"),
    ("open", "snippet"),
    ("show", "snippet"),
    ("launch", "snippet"),
    ("save", "snippet"),
    ("new", "snippet"),
    ("create", "snippet"),
    ("snip", "it"),
    ("show", "help"),
    ("open", "help"),
    # Whisper misrecognitions of "help"
    ("show", "hub"), ("open", "hub"),
    ("show", "halp"), ("open", "halp"),
    ("show", "helps"), ("open", "helps"),
}

# Whisper commonly mishears "help" as one of these when said with a prefix
# ("open hub", "show halp") — these are safe because the prefix disambiguates.
_HELP_VARIANTS = {"help", "hub", "halp", "helps"}

# Bare single-word help — a broader set, because when said alone while
# holding Option+C, acoustic neighbors of "help" are almost certainly
# command intent (user saying "help" quickly).
# Trade-off: someone dictating just "head" or "have" alone will instead
# get the help screen; these are rare one-word dictations.
try:
    import user_fixes as _user_fixes
    _user_data = _user_fixes.load()
except Exception:
    _user_data = {"help_variants": [], "snippet_variants": [], "save_variants": [], "clipboard_variants": []}

_BARE_HELP_VARIANTS = _HELP_VARIANTS | {"head", "held", "have", "hep", "hulp"} | set(_user_data["help_variants"])
_EXTRA_SNIPPET_VARIANTS = set(_user_data["snippet_variants"])
_EXTRA_SAVE_VARIANTS = set(_user_data["save_variants"])
_EXTRA_CLIPBOARD_VARIANTS = set(_user_data["clipboard_variants"])


def reload_user_fixes():
    """Reload user variants from ~/.voxtype/user_intent_fixes.json."""
    global _BARE_HELP_VARIANTS, _EXTRA_SNIPPET_VARIANTS, _EXTRA_SAVE_VARIANTS, _EXTRA_CLIPBOARD_VARIANTS
    try:
        data = _user_fixes.load()
    except Exception:
        return
    _BARE_HELP_VARIANTS = _HELP_VARIANTS | {"head", "held", "have", "hep", "hulp"} | set(data.get("help_variants", []))
    _EXTRA_SNIPPET_VARIANTS = set(data.get("snippet_variants", []))
    _EXTRA_SAVE_VARIANTS = set(data.get("save_variants", []))
    _EXTRA_CLIPBOARD_VARIANTS = set(data.get("clipboard_variants", []))

_BARE_FIX_VARIANTS = {"fix", "fixed", "fixes", "fixing"}

# Three-token trigger prefixes (for "bring up the snippet …")
_THREE_TOKEN_TRIGGERS = {
    ("bring", "up", "the"),
    ("bring", "up", "snippet"),
}

# Action keywords (second-layer parse, after trigger detected)
_OPEN_VERBS = {"open", "show", "launch", "bring"}
_OPEN_NOUNS = {"overview", "overlay", "manager", "list", "snippets"}
# "safe" is a common Whisper misrecognition of "save"
_SAVE_VERBS = {"save", "new", "create", "safe"} | _EXTRA_SAVE_VARIANTS

# Words that count as "the user mentioned the clipboard" — includes common
# Whisper misrecognitions ("clip-bot", "clip bot", "clipped").
_CLIPBOARD_HINTS = tuple(list(("clipboard", "clip-bot", "clip bot", "clipboards", "clipped")) + list(_EXTRA_CLIPBOARD_VARIANTS))


def route(text: str) -> Intent:
    """Route a transcription to an action."""
    raw = text
    cleaned = _clean(text)
    if not cleaned:
        return Intent(action="dictate", payload={"text": raw}, confidence=1.0)

    tokens = cleaned.split()
    trigger_span, is_compound_trigger = _detect_trigger(tokens)

    if trigger_span is None:
        return Intent(action="dictate", payload={"text": raw}, confidence=1.0)

    # tokens consumed by the trigger; everything after is the payload / action verb
    after_tokens = tokens[trigger_span:]
    joined_after = " ".join(after_tokens).lower()

    # -- open_help (check before open_overview) --
    # "show/open <help-or-neighbor>" or bare "help" alone.
    # After an explicit "open"/"show" verb, command mode is active,
    # so accept the wider neighbor set too.
    # Fuzzy threshold for single-word commands — Option+C is command mode,
    # so one-word utterances acoustically near "help" / "fix" are almost
    # certainly commands, not dictation. Catches "hope", "fist", etc.
    if len(tokens) == 2 and tokens[0] in {"show", "open"}:
        if tokens[1] in _BARE_HELP_VARIANTS or fuzz.ratio(tokens[1], "help") >= 60:
            conf = 0.95 if tokens[1] == "help" else 0.7
            return Intent(action="open_help", confidence=conf)
    if len(tokens) == 1:
        word = tokens[0]
        if word in _BARE_HELP_VARIANTS or fuzz.ratio(word, "help") >= 60:
            conf = 0.95 if word == "help" else 0.65
            return Intent(action="open_help", confidence=conf)
        if word in _BARE_FIX_VARIANTS or fuzz.ratio(word, "fix") >= 60:
            return Intent(action="open_fix", confidence=0.95 if word == "fix" else 0.7)

    # -- open_overview --
    # Check if the first token is an open verb (before the trigger)
    first_token = tokens[0]
    if first_token in _OPEN_VERBS:
        # "open snippet overview", "show snippet manager", "open snippets", "show snippets"
        # The after_tokens are what comes after the trigger phrase
        # For "open snippet overview" → trigger_span=2, after=["overview"]
        # For "open snippets" → trigger_span=1 (first token is "open", second is "snippets" trigger)
        #   Wait — "open snippets": tokens=["open","snippets"], _TWO_TOKEN_TRIGGERS has ("open","snippet")
        #   but not ("open","snippets"). However "snippets" as first token is in _SINGLE_TRIGGERS.
        #   Let's re-examine: tokens[0]="open" is not in _SINGLE_TRIGGERS, so single-token path doesn't apply.
        #   Two-token: ("open","snippets") is not in _TWO_TOKEN_TRIGGERS (only "snippet").
        #   So for "open snippets" we need to handle it.
        # The compound trigger check handles the two-token open+snippet cases.
        # For bare "open snippets", we check if it was caught by two-token with fuzzy.
        if is_compound_trigger:
            # Compound trigger: verb + snippet-word. Check if it's an overview intent.
            if not joined_after or joined_after in _OPEN_NOUNS or any(n in after_tokens for n in _OPEN_NOUNS):
                return Intent(action="open_overview", confidence=0.95)
        # Also catch "open snippets" where "snippets" alone triggers
        # In that case trigger_span=1 but first_token="open" is in _OPEN_VERBS
        if trigger_span == 1 and first_token in _OPEN_VERBS:
            # "open" is token[0], trigger is token[1] (snippets) — but wait, if snippets is token[0]
            # and trigger_span=1 that means tokens[0] was the trigger.
            # "open snippets" → tokens=["open","snippets"] → first_token="open" not in _SINGLE_TRIGGERS
            # so this path won't be reached from single-token trigger detection for "open snippets".
            pass

    # Special case: "open snippets" — "open" is first token (open verb), second token "snippets"
    # is in _SINGLE_TRIGGERS but wasn't matched because we only look at tokens[0] for single triggers.
    # We need to detect "OPEN_VERB + SNIPPET_TRIGGER" patterns not covered by _TWO_TOKEN_TRIGGERS.
    # Let's re-examine in _detect_trigger. Actually "open snippet" IS in _TWO_TOKEN_TRIGGERS.
    # "open snippets" is NOT. So we need to handle this case explicitly.

    # -- save_snippet --
    if first_token in _SAVE_VERBS:
        full = " ".join(tokens)
        from_clipboard = (
            any(h in full for h in _CLIPBOARD_HINTS)
            or "clip" in tokens  # bare "clip" = common Whisper dropout of "clipboard"
        )
        return Intent(action="save_snippet", payload={"from_clipboard": from_clipboard}, confidence=0.95)

    # -- open_overview fallback for single-trigger "snippets" preceded by open verb --
    # (handled above via is_compound_trigger)

    # -- paste_snippet --
    desc = _extract_payload_preserve_case(raw, trigger_span)
    return Intent(action="paste_snippet", payload={"description": desc}, confidence=0.9)


def _clean(text: str) -> str:
    # lowercase, strip trailing punctuation, collapse whitespace.
    t = text.strip().lower()
    t = re.sub(r"[.,!?;:]+$", "", t)
    t = re.sub(r"^[.,!?;:]+", "", t)
    t = re.sub(r"\s+", " ", t)
    return t


def _detect_trigger(tokens: list[str]) -> tuple[int | None, bool]:
    """Return (tokens_consumed, is_compound_trigger) or (None, False) if no trigger.

    is_compound_trigger=True means the trigger was verb+snippet (e.g. "open snippet"),
    which is needed downstream to distinguish open_overview from paste_snippet.
    """
    if not tokens:
        return None, False

    # 3-token
    if len(tokens) >= 3 and tuple(tokens[:3]) in _THREE_TOKEN_TRIGGERS:
        return 3, True

    # 2-token
    if len(tokens) >= 2 and tuple(tokens[:2]) in _TWO_TOKEN_TRIGGERS:
        return 2, True

    # Handle "open snippets" (plural not in _TWO_TOKEN_TRIGGERS)
    if len(tokens) >= 2 and tokens[0] in _OPEN_VERBS:
        second = tokens[1]
        if second in _SINGLE_TRIGGERS or fuzz.ratio(second, "snippet") >= 85 or fuzz.ratio(second, "snippets") >= 85:
            return 2, True

    # 1-token bare "help" (or fuzzy-matching acoustic neighbor)
    if len(tokens) == 1 and (tokens[0] in _BARE_HELP_VARIANTS or fuzz.ratio(tokens[0], "help") >= 60):
        return 1, False

    # 1-token bare "fix" (or fuzzy-matching acoustic neighbor)
    if len(tokens) == 1 and (tokens[0] in _BARE_FIX_VARIANTS or fuzz.ratio(tokens[0], "fix") >= 60):
        return 1, False

    # 2-token compound "open/show + help-neighbor" — consume both
    if len(tokens) == 2 and tokens[0] in {"open", "show"} and (tokens[1] in _BARE_HELP_VARIANTS or fuzz.ratio(tokens[1], "help") >= 60):
        return 2, True

    # Flexible save: "save/safe/new/create [anything] snippet"
    # Handles "save my clipboard as a snippet", "safe my clip-bot as snippet", etc.
    if tokens[0] in _SAVE_VERBS and len(tokens) >= 2:
        for t in tokens[1:]:
            clean = re.sub(r"[^a-z]", "", t)
            if clean and (fuzz.ratio(clean, "snippet") >= 80 or fuzz.ratio(clean, "snippets") >= 80):
                return len(tokens), True

    # User-added snippet variants
    if tokens[0] in _EXTRA_SNIPPET_VARIANTS:
        return 1, False

    # 1-token direct match
    if tokens[0] in _SINGLE_TRIGGERS:
        return 1, False

    # 1-token fuzzy (handles "snipped"/"senate"/mild misspellings)
    score = max(fuzz.ratio(tokens[0], t) for t in ("snippet", "snippets"))
    if score >= 85:
        return 1, False

    return None, False


def _mentions_open(s: str) -> bool:
    return any(v in s.split() for v in _OPEN_VERBS)


def _mentions_overview_noun(s: str) -> bool:
    return any(n in s.split() for n in _OPEN_NOUNS)


def _starts_with_open_verb(tokens: list[str]) -> bool:
    return bool(tokens) and tokens[0] in _OPEN_VERBS


def _starts_with_save_verb(tokens: list[str]) -> bool:
    return bool(tokens) and tokens[0] in _SAVE_VERBS


def _extract_payload_preserve_case(raw: str, tokens_consumed: int) -> str:
    """Re-extract the part of `raw` that comes AFTER the first N tokens, preserving original casing."""
    stripped = raw.strip()
    # Strip leading punctuation
    stripped = re.sub(r"^[.,!?;:]+\s*", "", stripped)
    parts = stripped.split(None, tokens_consumed)
    if len(parts) <= tokens_consumed:
        return ""
    payload = parts[tokens_consumed]
    # Strip trailing sentence punctuation
    payload = re.sub(r"[.,!?;:]+$", "", payload).strip()
    return payload
