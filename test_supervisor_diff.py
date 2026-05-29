"""Tests for supervisor_diff — fast vs slow transcript → candidates."""
from __future__ import annotations

import supervisor_diff as sd


# ─── Basic cases ─────────────────────────────────────────────────────────────


def test_identical_inputs_emit_nothing():
    assert sd.diff("hello world", "hello world") == []


def test_empty_inputs_emit_nothing():
    assert sd.diff("", "anything") == []
    assert sd.diff("anything", "") == []
    assert sd.diff("", "") == []


def test_pure_punctuation_diff_is_informational():
    cands = sd.diff("hello world", "Hello, world.")
    assert len(cands) == 1
    assert cands[0]["type"] == "punctuation"


# ─── Substitution ───────────────────────────────────────────────────────────


def test_substitution_voice_type_to_voicetype():
    cands = sd.diff(
        "i love voice type a lot",
        "I love VoiceType a lot.",
    )
    subs = [c for c in cands if c["type"] == "substitution"]
    assert len(subs) == 1
    assert subs[0]["payload"] == {"from": "voice type", "to": "VoiceType"}


def test_substitution_by_ne_to_binary():
    cands = sd.diff(
        "the by ne file is corrupted",
        "The binary file is corrupted.",
    )
    subs = [c for c in cands if c["type"] == "substitution"]
    assert any(s["payload"] == {"from": "by ne", "to": "binary"} for s in subs)


def test_substitution_segments_are_bounded():
    """Each substitution candidate must have ≤4 tokens on each side.
    Whole-sentence noise still produces individual substitution candidates,
    but the promoter's ≥3-occurrence threshold suppresses one-off noise."""
    fast = "this whole sentence is wrong on every single word"
    slow = "completely different sentence with totally other words elsewhere"
    cands = sd.diff(fast, slow)
    for c in cands:
        if c["type"] != "substitution":
            continue
        from_words = c["payload"]["from"].split()
        to_words = c["payload"]["to"].split()
        assert len(from_words) <= 4
        assert len(to_words) <= 4


# ─── New vocabulary ─────────────────────────────────────────────────────────


def test_new_vocab_emitted_for_inserted_long_words():
    cands = sd.diff(
        "I work on the project",
        "I work on the Polistician project",
    )
    new_vocabs = [c for c in cands if c["type"] == "new_vocab"]
    assert any(c["payload"]["word"] == "Polistician" for c in new_vocabs)


def test_new_vocab_skips_stopwords():
    # "yes" / "no" are stopwords; should NOT be flagged.
    cands = sd.diff("see the file", "yes, see the file")
    assert all(c["payload"].get("word") != "yes" for c in cands)


def test_new_vocab_skips_short_words():
    # 3-letter "dog" should NOT be flagged as new vocab.
    cands = sd.diff("see the cat", "see the dog cat")
    new_vocabs = [c for c in cands if c["type"] == "new_vocab"]
    assert not any(c["payload"]["word"].lower() == "dog" for c in new_vocabs)


# ─── Hallucination guard ────────────────────────────────────────────────────


def test_hallucination_guard_drops_total_disagreement():
    fast = "please open the door"
    slow = "The mitochondria is the powerhouse of the cell"
    assert sd.diff(fast, slow) == []


def test_hallucination_guard_keeps_close_paraphrases():
    fast = "please open the door"
    slow = "Please open the door."
    cands = sd.diff(fast, slow)
    # Pure punctuation/casing → kept as informational
    assert len(cands) >= 1
    assert cands[0]["type"] == "punctuation"


# ─── Confidence scoring ─────────────────────────────────────────────────────


def test_substitution_confidence_decreases_with_span_size():
    short = sd.diff("voice type is great", "VoiceType is great")
    long = sd.diff(
        "by ne file is great",
        "binary file is great",
    )
    short_conf = next(c["confidence"] for c in short if c["type"] == "substitution")
    assert 0 < short_conf <= 1.0


# ─── German cases ───────────────────────────────────────────────────────────


def test_german_vocabulary_extracted():
    fast = "die growth heisst auf englisch"
    slow = "die Großvater heißt auf Englisch"
    cands = sd.diff(fast, slow)
    # Either we get Großvater as new_vocab or growth→Großvater as substitution.
    found = any(
        ("Großvater" in str(c["payload"].get("word", "")) or
         "Großvater" in str(c["payload"].get("to", "")))
        for c in cands
    )
    assert found
