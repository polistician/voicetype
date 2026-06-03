"""Regression tests for the Whisper repetition-collapse deduper.

The original v0.15.0 streaming_transcriber had max_phrase=8, which silently
missed the real user failure mode where Whisper got stuck emitting a
9-word phrase 22 times in a row. v0.15.2 raised the cap to 20 and added
a final post-pass in voxtype.
"""
from streaming_transcriber import _dedupe_phrase_repeats


def test_short_phrase_double_repeat_collapses():
    """The original supported case: 2-word repeat → 1 copy."""
    text = "hello world hello world"
    assert _dedupe_phrase_repeats(text) == "hello world"


def test_8_word_repeat_collapses():
    """At the old 8-word cap — must still work after the raise."""
    text = "this is a sentence with eight word phrase this is a sentence with eight word phrase"
    out = _dedupe_phrase_repeats(text)
    assert out.split().count("eight") == 1


def test_9_word_repeat_collapses():
    """The actual user failure: a 9-word repeating phrase. Pre-v0.15.2 the
    8-word cap let this through; post-v0.15.2 it must collapse."""
    phrase = "have live typing so talk in the text it's"
    text = " ".join([phrase] * 4)
    out = _dedupe_phrase_repeats(text)
    assert out.split().count("typing") == 1, f"got: {out!r}"


def test_extreme_22x_repeat_collapses():
    """The exact user scenario — 22 verbatim repeats of a 9-word phrase."""
    phrase = "have live typing so talk in the text it's"
    text = " ".join([phrase] * 22)
    out = _dedupe_phrase_repeats(text)
    # Should compress all 22 down to a single occurrence (or very few)
    assert out.split().count("typing") <= 2, f"too many repeats survived: {out!r}"


def test_legitimate_repetition_with_intervening_words_preserved():
    """Real speech: 'I really really wanted to' — adjacent dupe only;
    'I want X and I want Y' — same word with stuff between — keep."""
    text = "I really wanted to do this and I really wanted to share it"
    out = _dedupe_phrase_repeats(text)
    # "really wanted to" appears twice but NOT back-to-back → must survive
    assert out.lower().count("really") == 2, f"clobbered legit repeat: {out!r}"


def test_no_op_on_clean_text():
    text = "this is normal speech with no repetition at all"
    assert _dedupe_phrase_repeats(text) == text


def test_empty_and_short_inputs():
    assert _dedupe_phrase_repeats("") == ""
    assert _dedupe_phrase_repeats("hi") == "hi"
    assert _dedupe_phrase_repeats("one two three") == "one two three"


def test_punctuation_drift_tolerated():
    """'this works. this works' (period drift) should still be caught."""
    text = "this works. this works"
    out = _dedupe_phrase_repeats(text)
    assert out.lower().count("works") == 1, f"got: {out!r}"
