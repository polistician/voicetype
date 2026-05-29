"""supervisor_diff.py — extract structured candidates from fast vs slow.

Given the fast model's transcript (whisper.cpp turbo, what the user sees)
and the slow supervisor's transcript (WhisperKit large-v3, generally more
accurate), emit a list of structured candidates. The promoter later turns
≥N occurrences of the same candidate into a deterministic vocabulary /
correction update so the fast model improves over time.

Candidate types:

    new_vocab        — word present in slow, absent in fast, not a common
                       stopword → likely a vocabulary item the fast model
                       missed because it wasn't biased toward it.

    substitution     — token-aligned segments where 1-4 fast tokens map
                       to 1-4 slow tokens. The hot path for "voice type" →
                       "VoiceType" and "by ne" → "binary".

    punctuation      — slow added/changed punctuation or casing only;
                       informational, the cleanup_backend already handles
                       this so we don't promote it.

    language_switch  — slow detected a non-English span that fast rendered
                       as gibberish English. Promoted as a hint to switch
                       input_language=auto if the user has it pinned to en.

Hallucination guard: if `token_set_ratio(fast, slow) < HALLUCINATION_FLOOR`,
we drop the whole diff. That ratio of ~0.4 catches the case where the
supervisor went off the rails (silent audio → "The quick brown fox").
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


HALLUCINATION_FLOOR = 0.4

# Words that we never promote as new vocab — they're too generic to bias
# Whisper usefully on, and including them just dilutes the prompt budget.
# Tuned for English + a handful of German function words that show up in
# the user's profile already.
_STOPWORDS: set[str] = {
    # English
    "the", "a", "an", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "for", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "i", "you", "he",
    "she", "it", "we", "they", "me", "him", "her", "us", "them", "my", "your",
    "his", "its", "our", "their", "this", "that", "these", "those", "so",
    "not", "no", "yes", "as", "than", "then", "there", "here", "when",
    "where", "who", "what", "how", "why", "which", "all", "any", "some",
    "one", "two", "three", "very", "just", "also", "only", "also",
    # German function words common in the user's data
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen", "einem",
    "ich", "du", "er", "sie", "es", "wir", "ihr", "und", "oder", "aber",
    "ist", "war", "sind", "habe", "hat", "haben", "wie", "was", "wer", "wo",
    "warum", "auch", "nicht", "nur", "noch", "schon", "sehr", "hier", "dort",
}


# ────────────────────────────────────────────────────────────────────────────
# Tokenization
# ────────────────────────────────────────────────────────────────────────────


_TOKEN_RE = re.compile(r"[\w'-]+|[^\w\s]", re.UNICODE)


def _normalize(s: str) -> str:
    """NFC + lowercase + collapse whitespace. Used for comparison only —
    we keep originals around for the promotion payload."""
    if not s:
        return ""
    s = unicodedata.normalize("NFC", s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokenize(s: str) -> list[str]:
    """Word + punctuation tokenizer. Apostrophe-hyphen-safe ("don't",
    "self-motivated"). Punctuation is kept as its own token so we can
    detect punctuation-only diffs."""
    return _TOKEN_RE.findall(s or "")


def _is_punct(tok: str) -> bool:
    return bool(tok) and not any(c.isalnum() for c in tok)


def _is_stopword(tok: str) -> bool:
    return _normalize(tok) in _STOPWORDS


# ────────────────────────────────────────────────────────────────────────────
# Hallucination guard
# ────────────────────────────────────────────────────────────────────────────


def _hallucination_score(fast: str, slow: str) -> float:
    """Token-set similarity 0..1. Importing rapidfuzz lazily so the
    diff module stays importable on minimal installs (the test env)."""
    try:
        from rapidfuzz import fuzz
    except Exception:
        return 1.0  # fail open
    return fuzz.token_set_ratio(_normalize(fast), _normalize(slow)) / 100.0


# ────────────────────────────────────────────────────────────────────────────
# Diff
# ────────────────────────────────────────────────────────────────────────────


def diff(fast_text: str, slow_text: str) -> list[dict]:
    """Compare a fast vs slow transcript; return zero or more candidates.

    Each candidate is a dict shaped:

        {"type": str, "payload": dict, "confidence": float}

    Confidence is a heuristic 0..1: closer to 1 means the diff is well-formed
    (small, localized, non-hallucinated); closer to 0 means it's risky.
    """
    fast = fast_text or ""
    slow = slow_text or ""
    if not fast.strip() or not slow.strip():
        return []
    if _normalize(fast) == _normalize(slow):
        return []

    if _hallucination_score(fast, slow) < HALLUCINATION_FLOOR:
        return []  # supervisor disagreed too much — drop entire diff

    fast_toks = _tokenize(fast)
    slow_toks = _tokenize(slow)
    # Lowercase normalized versions used for alignment; originals kept
    # for the payload so the user sees the same casing the supervisor used.
    fast_norm = [_normalize(t) for t in fast_toks]
    slow_norm = [_normalize(t) for t in slow_toks]

    out: list[dict] = []

    # --- Punctuation-only diff -------------------------------------------------
    # If we strip punctuation tokens from both and they match, we'd flag this
    # as "punctuation only" — informational, not promoted by the promoter.
    fast_words = [t for t in fast_norm if not _is_punct(t)]
    slow_words = [t for t in slow_norm if not _is_punct(t)]
    if fast_words == slow_words:
        out.append({
            "type": "punctuation",
            "payload": {"fast": fast.strip(), "slow": slow.strip()},
            "confidence": 0.6,
        })
        return out

    # --- Token alignment via difflib --------------------------------------------
    # We align on the lowercased word streams (no punctuation) and emit
    # substitutions for each "replace" opcode. Insertions are candidate
    # new-vocab.
    import difflib
    matcher = difflib.SequenceMatcher(a=fast_words, b=slow_words, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        fast_span = fast_words[i1:i2]
        slow_span = slow_words[j1:j2]

        if tag == "insert":
            # Words the supervisor added → new vocab if they're long enough
            # and not stopwords.
            for w in slow_span:
                if _is_stopword(w) or len(w) < 4:
                    continue
                out.append({
                    "type": "new_vocab",
                    "payload": {"word": _surface_word(slow_toks, slow_norm, w)},
                    "confidence": 0.85,
                })
            continue

        if tag == "delete":
            # Words the supervisor removed. Probably the fast model
            # hallucinated them. We don't promote anything here — the
            # promoter would have to actively delete vocab, which we don't
            # do automatically.
            continue

        if tag == "replace":
            # A substitution span. Only meaningful for spans of 1-4 tokens
            # each side; longer than that is probably a sentence-level
            # rewrite that's not safely captured by a single substitution
            # rule.
            if len(fast_span) > 4 or len(slow_span) > 4:
                continue
            if len(fast_span) == 0 or len(slow_span) == 0:
                continue
            from_phrase = " ".join(fast_span).strip()
            to_phrase = _surface_phrase(slow_toks, slow_norm, slow_span)
            if not from_phrase or not to_phrase:
                continue
            if from_phrase == to_phrase.lower():
                continue  # casing-only — promoter handles via vocab instead
            # confidence drops with span length and edit distance
            conf = max(0.4, 0.95 - 0.1 * (len(fast_span) + len(slow_span) - 2))
            out.append({
                "type": "substitution",
                "payload": {"from": from_phrase, "to": to_phrase},
                "confidence": conf,
            })
            # If the substitution introduces a long word not in the fast
            # side, also surface it as a vocab candidate (belt + braces).
            for w in slow_span:
                if not _is_stopword(w) and len(w) >= 4 and w not in fast_span:
                    out.append({
                        "type": "new_vocab",
                        "payload": {"word": _surface_word(slow_toks, slow_norm, w)},
                        "confidence": 0.7,
                    })
            continue

    return _dedupe(out)


# ────────────────────────────────────────────────────────────────────────────
# Surface-form helpers — recover the original casing from the slow tokens
# ────────────────────────────────────────────────────────────────────────────


def _surface_word(orig_tokens: list[str], norm_tokens: list[str], norm: str) -> str:
    """First occurrence of `norm` in `norm_tokens` → corresponding original."""
    for o, n in zip(orig_tokens, norm_tokens):
        if n == norm:
            return o
    return norm


def _surface_phrase(orig_tokens: list[str], norm_tokens: list[str],
                    norm_span: list[str]) -> str:
    """Find the first contiguous run of norm_tokens matching norm_span,
    and return the corresponding orig_tokens joined by spaces."""
    n = len(norm_span)
    if n == 0:
        return ""
    # We aligned on word-only tokens, but orig_tokens includes punctuation
    # interleaved. We need to walk orig_tokens skipping punctuation.
    orig_words: list[str] = []
    word_norms: list[str] = []
    for o, no in zip(orig_tokens, [_normalize(t) for t in orig_tokens]):
        if _is_punct(o):
            continue
        orig_words.append(o)
        word_norms.append(no)
    for i in range(len(word_norms) - n + 1):
        if word_norms[i:i + n] == norm_span:
            return " ".join(orig_words[i:i + n])
    return " ".join(norm_span)


def _dedupe(cands: list[dict]) -> list[dict]:
    """Drop exact duplicates within a single diff (same type + same payload)."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for c in cands:
        key = (c["type"], tuple(sorted(c["payload"].items())))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out
