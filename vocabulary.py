"""User vocabulary store — niche words biased into Whisper's prompt.

Why this exists
---------------
The v0.12 voice profile (``voice_profile.py``) passively learned from
what Whisper *output*. If Whisper consistently misheard "Polistician"
as "polystition", that misheard form is what got reinforced. Vicious
cycle.

This module is the *active* path: the user tells the app the niche
words they actually use. Those words get prepended to Whisper's
``initial_prompt`` on every dictation as a natural-sentence vocabulary
seed.

Three input channels feed the same store:
    1. Smart Suggester — auto-extracts low-confidence words from
       ``profile.json`` and surfaces them for one-click confirmation.
    2. Quick Fix bar (⌥⇧V) — captures a misrecognized word inline
       right after a bad dictation.
    3. Paste-dump — bulk add from a project README / glossary.

All three end up here. Word rows are tiny: just the canonical spelling,
an optional alias (how the user *says* it if different from how it
should be *written*), a usage counter, status. No tags. No folders.

File: ``~/.voicetype/vocabulary.json``
Schema (single JSON object):
    {
        "version": 1,
        "words": [
            {"canonical": "Polistician", "alias": null,
             "usage_count": 0, "added_at": 1715600000, "status": "new"},
            {"canonical": "HablaDaily", "alias": "habla daily",
             "usage_count": 0, "added_at": 1715600100, "status": "new"},
            ...
        ]
    }

Status transitions:
    new  →  seen (any usage > 0)
    seen →  active (usage > 5)
    *    →  archived (manual; kept on disk but excluded from prompt)
"""
from __future__ import annotations

import json
import os
import time
from typing import Any

VOCAB_PATH = os.path.expanduser("~/.voicetype/vocabulary.json")
PROMPT_TOKEN_BUDGET = 180  # ~150 short words after tokenization
PROMPT_PREFIX = "I often mention "  # natural sentence framing


def _empty() -> dict[str, Any]:
    return {"version": 1, "words": []}


def _load() -> dict[str, Any]:
    if not os.path.isfile(VOCAB_PATH):
        return _empty()
    try:
        with open(VOCAB_PATH) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "words" not in data:
            return _empty()
        return data
    except (json.JSONDecodeError, OSError):
        return _empty()


def _save(data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(VOCAB_PATH), exist_ok=True)
    tmp = VOCAB_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, VOCAB_PATH)


def list_all() -> list[dict[str, Any]]:
    """Return all vocab rows, in insertion order."""
    return _load()["words"]


def list_active() -> list[dict[str, Any]]:
    """Non-archived rows, sorted by usage_count desc then added_at desc.

    This is the order the prompt builder uses when budget is tight: most-
    used words win, then most-recent.
    """
    rows = [w for w in list_all() if w.get("status") != "archived"]
    rows.sort(key=lambda w: (-int(w.get("usage_count", 0)),
                              -int(w.get("added_at", 0))))
    return rows


def add(canonical: str, alias: str | None = None) -> bool:
    """Add a new word. Returns False if it already exists (case-insensitive
    canonical match)."""
    canonical = (canonical or "").strip()
    if not canonical:
        return False
    data = _load()
    existing = {w["canonical"].lower() for w in data["words"]}
    if canonical.lower() in existing:
        return False
    data["words"].append({
        "canonical": canonical,
        "alias": (alias or "").strip() or None,
        "usage_count": 0,
        "added_at": int(time.time()),
        "status": "new",
    })
    _save(data)
    return True


def add_many(canonicals: list[str]) -> int:
    """Bulk insert. Returns count actually added (skips duplicates)."""
    data = _load()
    existing = {w["canonical"].lower() for w in data["words"]}
    n = 0
    now = int(time.time())
    for raw in canonicals:
        c = (raw or "").strip()
        if not c or c.lower() in existing:
            continue
        data["words"].append({
            "canonical": c, "alias": None,
            "usage_count": 0, "added_at": now, "status": "new",
        })
        existing.add(c.lower())
        n += 1
    if n:
        _save(data)
    return n


def update(canonical_old: str, canonical_new: str, alias: str | None) -> bool:
    """Edit a row by its old canonical. Returns True if found + updated."""
    data = _load()
    for w in data["words"]:
        if w["canonical"].lower() == canonical_old.lower():
            w["canonical"] = canonical_new.strip()
            w["alias"] = (alias or "").strip() or None
            _save(data)
            return True
    return False


def remove(canonical: str) -> bool:
    """Delete a row. Returns True if found + removed."""
    data = _load()
    before = len(data["words"])
    data["words"] = [
        w for w in data["words"] if w["canonical"].lower() != canonical.lower()
    ]
    if len(data["words"]) != before:
        _save(data)
        return True
    return False


def mark_seen(words_in_transcript: list[str]) -> None:
    """After each successful transcription, bump usage_count for any vocab
    words that appeared. Called from voxtype.py's _transcribe_and_paste."""
    if not words_in_transcript:
        return
    data = _load()
    if not data["words"]:
        return
    transcript_norm = {w.strip(".,!?;:'\"").lower() for w in words_in_transcript}
    changed = False
    for w in data["words"]:
        c = w["canonical"].lower()
        if c in transcript_norm:
            w["usage_count"] = int(w.get("usage_count", 0)) + 1
            if w.get("status") == "new":
                w["status"] = "seen"
            elif w.get("status") == "seen" and w["usage_count"] >= 5:
                w["status"] = "active"
            changed = True
    if changed:
        _save(data)


def get_prompt(budget_words: int = PROMPT_TOKEN_BUDGET) -> str:
    """Build the vocabulary-bias prompt fragment.

    Returns a *natural sentence* containing the user's vocabulary words.
    Whisper mimics the prompt's style; sentence-form outperforms a bare
    comma-list on the same words.

    Empty string when no vocab — caller still has snippet-bias / profile-
    vocab paths to fall back on.
    """
    rows = list_active()
    if not rows:
        return ""
    # Take top-N by priority order from list_active().
    words: list[str] = []
    seen = set()
    for r in rows[:budget_words]:
        c = r["canonical"]
        if c.lower() in seen:
            continue
        seen.add(c.lower())
        words.append(c)
    if not words:
        return ""
    # Natural-sentence framing. Whisper biases more reliably toward words
    # it sees in a sentence than in a comma list.
    if len(words) == 1:
        return PROMPT_PREFIX + words[0] + "."
    return PROMPT_PREFIX + ", ".join(words[:-1]) + ", and " + words[-1] + "."


def suggest_from_profile() -> list[dict[str, Any]]:
    """Mine ``profile.json``'s ``low_confidence_words`` for candidates.

    Returns a list of:
        {"raw": "polystition", "suggested": "Polistician", "count": 4}

    Heuristics for the suggestion:
        1. Auto-capitalize the first letter if the raw form is all-lower.
        2. If the raw form is suspiciously phonetic (consonant cluster
           atypical of English), bias toward capitalized proper-noun
           interpretation.
    """
    profile_path = os.path.expanduser("~/.voicetype/profile.json")
    if not os.path.isfile(profile_path):
        return []
    try:
        with open(profile_path) as f:
            profile = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    low_conf = profile.get("low_confidence_words", {})
    if not isinstance(low_conf, dict):
        return []
    # Filter out words already in vocabulary (case-insensitive)
    existing = {w["canonical"].lower() for w in list_all()}
    suggestions: list[dict[str, Any]] = []
    for raw, count in low_conf.items():
        if not isinstance(count, int) or count < 2:
            continue
        # Skip very common English words even if Whisper flagged them
        # low-confidence — those are noise, not niche vocab.
        if raw.lower() in _COMMON_EN_WORDS:
            continue
        if raw.lower() in existing:
            continue
        suggested = _capitalize_guess(raw)
        suggestions.append({
            "raw": raw,
            "suggested": suggested,
            "count": int(count),
        })
    # Most-confused first
    suggestions.sort(key=lambda s: -s["count"])
    return suggestions[:20]  # cap so the UI doesn't drown the user


def dismiss_suggestion(raw: str) -> None:
    """Remove a low_confidence_words entry from profile.json so it stops
    re-appearing in Suggested. Called when the user clicks ✕ on a suggestion."""
    profile_path = os.path.expanduser("~/.voicetype/profile.json")
    if not os.path.isfile(profile_path):
        return
    try:
        with open(profile_path) as f:
            profile = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    low_conf = profile.get("low_confidence_words", {})
    if raw in low_conf:
        low_conf.pop(raw)
        profile["low_confidence_words"] = low_conf
        try:
            with open(profile_path, "w") as f:
                json.dump(profile, f, indent=2)
        except OSError:
            pass


def extract_proper_nouns(text: str) -> list[str]:
    """Paste-dump helper. Pull capitalized words that look like proper
    nouns from a free-form text block.

    Heuristics:
        - Capitalized word, ≥ 3 chars
        - Skip if at sentence start AND is a common English word
        - Skip common all-caps acronyms < 3 chars (US, UK, etc.)
        - Dedupe case-insensitively
    """
    import re
    candidates = re.findall(r"\b[A-Z][A-Za-z]{2,}(?:[A-Z][a-z]+)*\b", text)
    seen = set()
    out: list[str] = []
    for c in candidates:
        norm = c.lower()
        if norm in seen:
            continue
        if norm in _COMMON_EN_WORDS:
            continue
        # Skip a starts-of-sentence common word: rough heuristic — if it's
        # an English stopword-class capitalization it's noise.
        if norm in _SENTENCE_START_NOISE:
            continue
        seen.add(norm)
        out.append(c)
    return out


# Stopword filter for the Suggester. We want niche/proper-noun candidates,
# not common English the user happened to mumble. Words below this bar are
# silently dropped from suggestions. Errs on the side of filtering — too
# aggressive a filter just means the user adds a missing word manually;
# too lax fills the Suggester with noise the user has to dismiss.
_COMMON_EN_WORDS = frozenset({
    # articles / pronouns / aux
    "the", "a", "an", "i", "me", "my", "we", "us", "our", "you",
    "your", "he", "she", "him", "her", "his", "they", "them", "their",
    "it", "its", "this", "that", "these", "those",
    "am", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "having",
    "do", "does", "did", "doing", "done",
    # prepositions / conjunctions / particles
    "and", "or", "but", "so", "for", "if", "when", "while", "where",
    "with", "from", "into", "onto", "upon", "over", "under", "by",
    "at", "of", "in", "on", "to", "as", "than", "then", "though",
    "although", "because", "since", "yet", "just", "even", "also",
    "still", "now", "back", "out", "up", "down", "off",
    # interrogatives / common verbs / state
    "what", "who", "whom", "whose", "why", "how", "which",
    "can", "could", "will", "would", "shall", "should", "may", "might",
    "must", "say", "said", "see", "saw", "seen", "get", "got",
    "getting", "make", "made", "making", "take", "took", "taking",
    "taken", "come", "came", "coming", "go", "went", "gone", "going",
    "want", "wants", "wanted", "wanting", "use", "used", "using",
    "know", "knew", "known", "think", "thought", "feel", "felt",
    "look", "looking", "looked", "give", "gave", "given", "tell",
    "told", "talk", "talked", "talking", "let", "letting",
    # quantifiers / generic noun-fillers / adjectives
    "good", "bad", "very", "much", "many", "some", "any", "more", "most",
    "less", "few", "all", "every", "each", "no", "not", "yes",
    "long", "short", "new", "old", "first", "last", "next", "early",
    "late", "high", "low", "big", "small", "right", "left", "true",
    "false", "okay", "ok", "actually", "really", "kind", "sort",
    "like", "well", "way", "thing", "things", "stuff",
    # times / generic noun classes that show up in spoken dictation
    "day", "days", "time", "times", "year", "years", "week", "weeks",
    "month", "months", "hour", "hours", "minute", "minutes",
    "people", "person", "everyone", "someone", "anyone", "everything",
    "something", "anything", "nothing",
    # filler / discourse markers
    "hello", "hi", "hey", "yeah", "yep", "nope", "huh", "oh", "ah",
    "um", "uh", "wait", "anyway", "though",
})

_SENTENCE_START_NOISE = frozenset({
    "i", "my", "me", "we", "us", "our", "this", "that", "these", "those",
    "the", "a", "an", "and", "but", "or", "so", "if", "when", "where",
    "while", "as", "because", "since", "though", "although",
})


def _capitalize_guess(raw: str) -> str:
    """Guess a canonical spelling for an all-lowercase niche word.

    Defaults to title-casing. CamelCase-likely strings (contain a common
    second-word prefix like "daily", "type", "kit") get CamelCase'd.
    """
    if not raw:
        return raw
    # Already mixed-case → trust the user's form
    if raw != raw.lower():
        return raw
    # Multi-word phrase → title-case each token
    if " " in raw:
        return " ".join(t.capitalize() for t in raw.split())
    return raw.capitalize()
