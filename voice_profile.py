# voice_profile.py
"""Local voice profile — learns how YOU speak, improves Whisper over time.

Stored at ~/.voicetype/profile.json. Updated after every transcription.
Read on every transcription to feed vocabulary into Whisper's initial_prompt.

No server, no API, no SOMA dependency. Pure local self-improvement.

SOMA can optionally read this file for cross-system voice intelligence,
but VoxType works entirely independently.
"""
import json
import os
from collections import Counter

PROFILE_PATH = os.path.expanduser("~/.voicetype/profile.json")


def _load() -> dict:
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "total_captures": 0,
        "avg_confidence": 0.0,
        "avg_wpm": 0,
        "low_confidence_words": {},   # word -> count
        "vocabulary": {},             # word -> count (all words seen 3+ times)
        "corrections": [],            # manual corrections (future: if user retypes)
        "per_app": {},                # bundle_id -> {word: count}
    }


def _sanitize(obj):
    """Make any object JSON-safe: convert numpy types, replace NaN/Inf."""
    import math
    # numpy scalars → Python native
    if hasattr(obj, 'item'):
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return 0.0
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _save(profile: dict):
    os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)
    clean = _sanitize(profile)
    # Write to temp file then rename — atomic, prevents truncation on crash
    tmp = PROFILE_PATH + ".tmp"
    try:
        serialized = json.dumps(clean, indent=2)  # serialize to string first
    except (ValueError, TypeError) as e:
        print(f"[voice_profile] JSON serialize failed: {e}", flush=True)
        return
    with open(tmp, "w") as f:
        f.write(serialized)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PROFILE_PATH)  # atomic on POSIX


def update(rich_result: dict, app: str | None = None):
    """Update the local profile after a transcription.

    rich_result is from TranscriberV2.transcribe_rich():
    {text, segments, avg_confidence, low_confidence_words, duration_ms, words_per_minute}

    app: optional bundle ID of the frontmost app during recording (e.g.
    "com.todesktop.230313mzl4w4u92" for Cursor). When provided, words are
    also accumulated in the per-app counter so get_whisper_prompt_for_app()
    can return app-specific vocabulary biasing.
    """
    import math
    profile = _load()
    n = profile["total_captures"]

    # Rolling average confidence
    conf = rich_result.get("avg_confidence", 0) or 0
    if isinstance(conf, float) and math.isnan(conf):
        conf = 0
    if conf > 0:
        old = profile["avg_confidence"]
        profile["avg_confidence"] = round((old * n + conf) / (n + 1), 4)

    # Rolling average WPM
    wpm = rich_result.get("words_per_minute", 0)
    if wpm > 0:
        old = profile["avg_wpm"]
        profile["avg_wpm"] = round((old * n + wpm) / (n + 1))

    profile["total_captures"] = n + 1

    # Accumulate low-confidence words
    lc = profile.get("low_confidence_words", {})
    for word in rich_result.get("low_confidence_words", []):
        lc[word] = lc.get(word, 0) + 1
    # Keep top 100
    profile["low_confidence_words"] = dict(
        sorted(lc.items(), key=lambda x: -x[1])[:100]
    )

    # Accumulate vocabulary (all words seen)
    text = rich_result.get("text", "")
    vocab = profile.get("vocabulary", {})
    words_clean = []
    for word in text.split():
        clean = word.strip(".,!?;:'\"()[]{}").lower()
        if len(clean) > 2:
            vocab[clean] = vocab.get(clean, 0) + 1
            words_clean.append(clean)
    # Keep top 200
    profile["vocabulary"] = dict(
        sorted(vocab.items(), key=lambda x: -x[1])[:200]
    )

    # Per-app vocabulary: accumulate words against the bundle ID
    if app and words_clean:
        per_app = profile.get("per_app", {})
        app_vocab = per_app.get(app, {})
        for w in words_clean:
            app_vocab[w] = app_vocab.get(w, 0) + 1
        # Keep top 100 per app
        per_app[app] = dict(sorted(app_vocab.items(), key=lambda x: -x[1])[:100])
        profile["per_app"] = per_app

    _save(profile)


def get_whisper_prompt() -> str:
    """Get vocabulary formatted as Whisper initial_prompt.

    Returns the user's most frequent words (seen 3+ times),
    which dramatically improves Whisper's recognition for
    these specific terms.
    """
    profile = _load()
    vocab = profile.get("vocabulary", {})

    # Only include words seen 3+ times (established vocabulary)
    frequent = [w for w, c in sorted(vocab.items(), key=lambda x: -x[1]) if c >= 3]

    # Filter out common English — Whisper already knows these.
    # Only feed domain-specific terms that Whisper would otherwise miss.
    # An over-long initial_prompt causes Whisper to drift its output toward the
    # prompt's style, hurting general transcription. Keep it short and focused.
    _COMMON = {
        "the", "and", "you", "have", "that", "but", "not", "for", "would",
        "it's", "like", "should", "this", "what", "are", "when", "then",
        "can", "actually", "there", "they", "don't", "first", "see", "all",
        "that's", "want", "with", "also", "your", "example", "about",
        "i'm", "just", "why", "still", "how", "one", "something", "there's",
        "because", "already", "has", "new", "look", "where", "get", "some",
        "way", "know", "which", "think", "them", "make", "say", "out",
        "however", "find", "does", "show", "didn't", "based", "from",
        "only", "give", "two", "three", "was", "well", "back", "right",
        "call", "same", "work", "add", "open", "start", "done", "take",
        "most", "tell", "between", "before", "able", "everything", "etc",
        "if", "is", "it", "to", "of", "in", "on", "or", "be", "so",
        "do", "at", "by", "an", "no", "up", "my", "we", "he", "she",
        "idea", "more", "log", "page", "different", "create", "through",
        "did", "will", "note", "hello", "says", "too", "menu", "record",
        "feedback", "even", "similar", "other", "thing", "addition", "fix",
        "their", "type", "good", "actions", "day", "been", "interface",
        "settings", "click", "could", "chat", "quick", "home", "research",
        "user", "users", "agent", "agents", "page", "pages", "use", "used",
        "uses", "using", "now", "here", "very", "really", "much", "many",
        "any", "into", "both", "each", "had", "her", "him", "his", "its",
        "let", "lets", "may", "might", "need", "needs", "next", "off", "our",
        "over", "people", "send", "sent", "should", "since", "such", "than",
        "their", "these", "those", "told", "try", "trying", "until", "us",
        "we're", "weren't", "while", "who", "whom", "whose", "with", "within",
    }
    domain_words = [
        w for w in frequent
        if w.lower() not in _COMMON and len(w) >= 4
    ]

    if not domain_words:
        return ""
    # Cap at 15: long prompts cause Whisper to bias output toward the prompt's
    # style and hallucinate phantom words from the list during silence.
    return "Words I use: " + " ".join(domain_words[:15])


def get_whisper_prompt_for_app(app: str | None) -> str:
    """Same as get_whisper_prompt() but boosts words frequent for the given app.

    Combines global frequent (top 10) + app-frequent (top 10), deduped,
    capped at 15 total. Long prompts hurt Whisper by biasing its output
    toward the prompt's style and hallucinating phantom words.
    """
    if not app:
        return get_whisper_prompt()

    profile = _load()
    vocab = profile.get("vocabulary", {})
    per_app = profile.get("per_app", {})
    app_vocab = per_app.get(app, {})

    _COMMON = {
        "the", "and", "you", "have", "that", "but", "not", "for", "would",
        "it's", "like", "should", "this", "what", "are", "when", "then",
        "can", "actually", "there", "they", "don't", "first", "see", "all",
        "that's", "want", "with", "also", "your", "example", "about",
        "i'm", "just", "why", "still", "how", "one", "something", "there's",
        "because", "already", "has", "new", "look", "where", "get", "some",
        "way", "know", "which", "think", "them", "make", "say", "out",
        "however", "find", "does", "show", "didn't", "based", "from",
        "only", "give", "two", "three", "was", "well", "back", "right",
        "call", "same", "work", "add", "open", "start", "done", "take",
        "most", "tell", "between", "before", "able", "everything", "etc",
        "if", "is", "it", "to", "of", "in", "on", "or", "be", "so",
        "do", "at", "by", "an", "no", "up", "my", "we", "he", "she",
        "idea", "more", "log", "page", "different", "create", "through",
        "did", "will", "note", "hello", "says", "too", "menu", "record",
        "feedback", "even", "similar", "other", "thing", "addition", "fix",
        "their", "type", "good", "actions", "day", "been", "interface",
        "settings", "click", "could", "chat", "quick", "home", "research",
        "user", "users", "agent", "agents", "page", "pages", "use", "used",
        "uses", "using", "now", "here", "very", "really", "much", "many",
        "any", "into", "both", "each", "had", "her", "him", "his", "its",
        "let", "lets", "may", "might", "need", "needs", "next", "off", "our",
        "over", "people", "send", "sent", "should", "since", "such", "than",
        "their", "these", "those", "told", "try", "trying", "until", "us",
        "we're", "weren't", "while", "who", "whom", "whose", "with", "within",
    }

    def _domain_words(source: dict, n: int) -> list[str]:
        frequent = [w for w, c in sorted(source.items(), key=lambda x: -x[1]) if c >= 3]
        return [w for w in frequent if w.lower() not in _COMMON and len(w) >= 4][:n]

    global_top = _domain_words(vocab, 10)
    app_top = _domain_words(app_vocab, 10)

    # Merge: app words first (higher signal), then global, dedup, cap at 15
    seen: set[str] = set()
    merged: list[str] = []
    for w in app_top + global_top:
        if w not in seen:
            seen.add(w)
            merged.append(w)
        if len(merged) >= 15:
            break

    if not merged:
        return ""
    return "Words I use: " + " ".join(merged)


def get_low_confidence_words() -> list[str]:
    """Words Whisper consistently struggles with for this user."""
    profile = _load()
    lc = profile.get("low_confidence_words", {})
    return [w for w, c in sorted(lc.items(), key=lambda x: -x[1]) if c >= 3]


def get_stats() -> dict:
    """Summary stats for display."""
    profile = _load()
    vocab = profile.get("vocabulary", {})
    lc = profile.get("low_confidence_words", {})
    return {
        "total_captures": profile.get("total_captures", 0),
        "avg_confidence": profile.get("avg_confidence", 0),
        "avg_wpm": profile.get("avg_wpm", 0),
        "vocabulary_size": len([w for w, c in vocab.items() if c >= 3]),
        "problem_words": len([w for w, c in lc.items() if c >= 3]),
    }
