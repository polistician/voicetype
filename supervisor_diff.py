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

# Minimum word length to be considered for new-vocab promotion. Below this,
# we're almost always staring at a stopword the supervisor mis-spelled, OR
# a domain abbreviation already well-handled by initial_prompt biasing.
# v0.15.0.1: raised from 4 → 6 after early auto-promotion poisoning showed
# words like "still", "cheap", "yeah" landing in the user's vocabulary file.
MIN_VOCAB_WORD_LEN = 6

# Words that we never promote as new vocab AND never emit as a
# substitution side (because "the" ↔ "a" oscillation poisons every
# dictation). v0.15.0.1: expanded from ~80 to ~700 entries covering the
# top-500 English words + top-200 German words plus contractions and the
# common Whisper-misrecognition synonyms ("yeah", "okay", etc.).
_STOPWORDS: set[str] = {
    # English — top-500 most-frequent. Sourced from the OEC + COCA top lists,
    # deduped and lowercased. Includes all the function words AND the most
    # common content words that show up in EVERY dictation regardless of
    # topic — those are the ones that poison the substitution layer because
    # the fast vs slow models routinely disagree on tense/article/casing.
    "a", "able", "about", "above", "across", "act", "actually", "add", "after",
    "again", "against", "ago", "all", "almost", "alone", "along", "already",
    "also", "although", "always", "am", "among", "an", "and", "another",
    "answer", "any", "anyone", "anything", "anyway", "appear", "are", "area",
    "around", "as", "ask", "at", "available", "away", "back", "bad", "be",
    "became", "because", "become", "becomes", "been", "before", "began",
    "begin", "behind", "being", "believe", "below", "best", "better",
    "between", "big", "both", "bring", "but", "by", "call", "called", "came",
    "can", "cannot", "care", "case", "cause", "certain", "change", "check",
    "child", "children", "close", "come", "comes", "coming", "common",
    "company", "consider", "continue", "could", "couldn't", "course", "day",
    "days", "deal", "decide", "decision", "did", "didn't", "die", "different",
    "do", "does", "doesn't", "doing", "don't", "done", "down", "during",
    "each", "early", "easy", "either", "else", "end", "enough", "even",
    "ever", "every", "everyone", "everything", "exact", "exactly", "example",
    "except", "fact", "far", "feel", "few", "find", "finds", "fine", "first",
    "five", "follow", "for", "form", "found", "four", "from", "full", "gave",
    "general", "get", "gets", "getting", "give", "given", "gives", "go",
    "goes", "going", "gone", "good", "got", "great", "group", "had", "hadn't",
    "happen", "happened", "happens", "happy", "has", "hasn't", "have",
    "haven't", "having", "he", "he'd", "he'll", "he's", "head", "hear",
    "heard", "held", "help", "her", "here", "here's", "hers", "herself",
    "high", "him", "himself", "his", "hold", "home", "hour", "hours",
    "house", "how", "however", "human", "i", "i'd", "i'll", "i'm", "i've",
    "idea", "if", "important", "in", "indeed", "instead", "interest", "into",
    "is", "isn't", "it", "it's", "its", "itself", "just", "keep", "keeps",
    "kept", "kind", "knew", "know", "known", "knows", "large", "last",
    "later", "lay", "lead", "least", "leave", "left", "less", "let", "let's",
    "level", "lie", "life", "like", "liked", "likes", "list", "little",
    "live", "lived", "lives", "long", "look", "looked", "looking", "looks",
    "lot", "lots", "made", "main", "make", "makes", "making", "man", "many",
    "matter", "may", "maybe", "me", "mean", "means", "meant", "might",
    "mind", "minute", "miss", "money", "month", "more", "most", "move",
    "much", "must", "my", "myself", "name", "near", "need", "needs", "never",
    "new", "next", "no", "none", "nor", "not", "nothing", "now", "of", "off",
    "often", "oh", "okay", "old", "on", "once", "one", "ones", "only",
    "open", "opens", "or", "other", "others", "our", "ours", "out", "over",
    "own", "part", "past", "people", "perhaps", "person", "place", "plan",
    "play", "please", "point", "possible", "power", "pretty", "probably",
    "problem", "program", "put", "puts", "question", "quick", "quite",
    "rather", "reach", "read", "real", "really", "result", "right", "room",
    "round", "run", "said", "same", "saw", "say", "says", "school", "second",
    "see", "seem", "seems", "seen", "self", "send", "sent", "set", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "show", "shown",
    "side", "since", "small", "so", "some", "someone", "something",
    "sometime", "sometimes", "soon", "sort", "speak", "specific", "start",
    "state", "stay", "still", "stop", "study", "such", "sure", "system",
    "take", "takes", "taking", "talk", "talking", "tell", "tells", "ten",
    "than", "thank", "that", "that's", "the", "their", "theirs", "them",
    "themselves", "then", "there", "there's", "therefore", "these", "they",
    "they'd", "they'll", "they're", "they've", "thing", "things", "think",
    "thinking", "thinks", "third", "this", "those", "though", "thought",
    "three", "through", "thus", "till", "time", "times", "to", "today",
    "together", "told", "too", "took", "top", "toward", "town", "true",
    "try", "trying", "turn", "two", "under", "until", "up", "upon", "us",
    "use", "used", "useful", "uses", "using", "usually", "very", "via",
    "view", "wait", "want", "wants", "was", "wasn't", "way", "ways", "we",
    "we'd", "we'll", "we're", "we've", "week", "well", "went", "were",
    "weren't", "what", "what's", "whatever", "when", "where", "whether",
    "which", "while", "white", "who", "who's", "whom", "whose", "why",
    "will", "with", "within", "without", "won't", "word", "words", "work",
    "works", "world", "would", "wouldn't", "write", "year", "years", "yeah",
    "yes", "yet", "you", "you'd", "you'll", "you're", "you've", "young",
    "your", "yours", "yourself",
    # German — top-200 function + frequent content words.
    "aber", "alle", "allen", "aller", "alles", "allgemein", "als", "also",
    "am", "an", "andere", "anderen", "anderes", "auch", "auf", "aus", "bei",
    "beide", "beim", "bekommen", "besonders", "besser", "beste", "bin",
    "bis", "bisher", "bitte", "brauchen", "bringen", "ча", "da", "dabei",
    "dafür", "dagegen", "daher", "damit", "danach", "dank", "danke", "dann",
    "daran", "darauf", "daraus", "darin", "darum", "das", "dass", "davon",
    "davor", "dazu", "dein", "deine", "dem", "den", "denen", "denken",
    "denn", "der", "deren", "des", "dessen", "dich", "die", "diese",
    "dieselbe", "diesem", "diesen", "dieser", "dieses", "dir", "doch",
    "dort", "drei", "du", "durch", "ein", "eine", "einem", "einen", "einer",
    "eines", "einige", "einmal", "elf", "er", "es", "etwa", "etwas", "euch",
    "euer", "eure", "fast", "ferner", "folgende", "für", "ganz", "gar",
    "geht", "geben", "gegen", "gehen", "geht", "gemacht", "genug", "gerade",
    "gewesen", "gewollt", "gewusst", "gibt", "gleich", "gut", "haben",
    "habe", "habt", "hast", "hat", "hatte", "hatten", "her", "heute", "hier",
    "hin", "hinter", "ich", "ihm", "ihn", "ihnen", "ihr", "ihre", "ihrem",
    "ihren", "ihrer", "ihres", "im", "immer", "in", "indem", "ins",
    "irgend", "ist", "ja", "je", "jede", "jedem", "jeden", "jeder", "jedes",
    "jedoch", "jene", "jenem", "jenen", "jener", "jenes", "jetzt", "kann",
    "kannst", "kaum", "kein", "keine", "keinem", "keinen", "keiner",
    "keines", "können", "könnte", "könnten", "machen", "macht", "mal", "man",
    "manche", "manchen", "mancher", "manches", "mehr", "mein", "meine",
    "meinem", "meinen", "meiner", "meines", "mich", "mir", "mit", "müssen",
    "muss", "musste", "musst", "nach", "nachdem", "nein", "neue", "neuen",
    "nicht", "nichts", "noch", "nun", "nur", "ob", "obwohl", "oder",
    "ohne", "schon", "sehr", "sei", "sein", "seine", "seinem", "seinen",
    "seiner", "seines", "seit", "sich", "sie", "sind", "so", "solche",
    "solchem", "solchen", "solcher", "solches", "sollte", "sondern", "und",
    "uns", "unser", "unsere", "unter", "viel", "viele", "vom", "von", "vor",
    "wann", "warum", "was", "weiter", "welche", "welchem", "welchen",
    "welcher", "welches", "wenn", "wer", "werde", "werden", "wie", "wieder",
    "will", "wir", "wird", "wirst", "wo", "wollen", "wollte", "während",
    "würde", "würden", "zu", "zum", "zur", "zwar", "zwischen", "über",
}


def _looks_like_stopword(tok: str) -> bool:
    """True if a token shouldn't appear on either side of a substitution
    candidate. Combines the explicit stopword set with a length gate:
    1-3 character "words" are basically always articles, prepositions,
    contractions, or noise. Includes the contraction-split case ("don't"
    tokenises to one entry; "it's" → also one)."""
    norm = _normalize(tok)
    if not norm:
        return True
    if len(norm) <= 3:
        return True
    return norm in _STOPWORDS


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
            # and not stopwords. v0.15.0.1: tightened length gate to 6.
            for w in slow_span:
                if _looks_like_stopword(w) or len(w) < MIN_VOCAB_WORD_LEN:
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
            # v0.15.0.1: drop substitutions where BOTH spans are entirely
            # stopwords. That catches the↔a, is↔it's, were↔was —
            # oscillating function-word disagreements that poison every
            # dictation. But it leaves useful substitutions like
            # "by ne" → "binary" alone, where one side is short noise
            # (`by`, `ne`) but the target ("binary") is real signal.
            # Contradiction detection in the promoter handles the cases
            # where one side has a useful word but the pair still oscillates
            # (e.g. project ↔ projects).
            if (all(_looks_like_stopword(t) for t in fast_span)
                    and all(_looks_like_stopword(t) for t in slow_span)):
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
                if (not _looks_like_stopword(w)
                        and len(w) >= MIN_VOCAB_WORD_LEN
                        and w not in fast_span):
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
