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


# ── v0.15.4 — stuck-prefix loops ────────────────────────────────────────────


from streaming_transcriber import _dedupe_prefix_loops


def test_prefix_loop_german_user_failure():
    """Exact German output the user reported in v0.15.4.
    4 sentences share a 7-word prefix but vary at the end. Must collapse
    to at most 1 occurrence of the looping prefix."""
    text = (
        "Ich habe ja auch gemacht, dass wir die Website verbinden und dann "
        "auch nicht verbunden sind. "
        "Ich habe ja auch gemacht, dass wir die Website verbinden sind. "
        "Ich habe ja auch gemacht, dass wir das nicht mehr als auf dem Weg "
        "gehen. "
        "Ich habe ja auch gemacht, dass wir die Website verbinden sind."
    )
    out = _dedupe_prefix_loops(text)
    # The 7-word prefix should appear at most once
    occurrences = out.lower().count("ich habe ja auch gemacht")
    assert occurrences <= 1, f"prefix appeared {occurrences}× in: {out!r}"


def test_prefix_loop_short_text_no_op():
    """Below min_occurrences (3), the function must not alter content."""
    text = "I went to the store. I went to the bank."
    out = _dedupe_prefix_loops(text)
    assert out == text


def test_prefix_loop_preserves_non_looping_content():
    """Looping prefix collapses; surrounding sentences with different
    prefixes survive."""
    text = (
        "I want to tell you something. "
        "Now the thing is broken again. "
        "Now the thing is broken again. "
        "Now the thing is broken again. "
        "But anyway, let's move on."
    )
    out = _dedupe_prefix_loops(text)
    assert "I want to tell you something" in out
    assert "But anyway" in out
    # Looping "Now the thing" should appear at most once
    assert out.lower().count("now the thing") <= 1


def test_prefix_loop_empty_input():
    assert _dedupe_prefix_loops("") == ""
    assert _dedupe_prefix_loops("just one sentence here.") == "just one sentence here."


def test_combined_dedupe_idempotent():
    """Running both passes twice in a row produces the same result as once."""
    text = (
        "Ich habe ja auch gemacht, dass wir die Website verbinden sind. "
        "Ich habe ja auch gemacht, dass wir die Website verbinden sind. "
        "Ich habe ja auch gemacht, dass wir die Website verbinden sind."
    )
    once = _dedupe_prefix_loops(_dedupe_phrase_repeats(text))
    twice = _dedupe_prefix_loops(_dedupe_phrase_repeats(once))
    assert once == twice


# ── v0.15.5 — trailing-silence hallucination ────────────────────────────────


def test_trailing_only_loop_dropped_entirely():
    """v0.15.5: when the loop is the entire trailing tail (no non-looping
    content after), drop ALL occurrences — pure trailing hallucination.

    Real user message — the 4 'Ich habe ja auch gemacht' sentences were
    NEVER spoken; the model hallucinated them after the user fell silent."""
    real = (
        "Ich sehe zwei Sachen. "
        "Erstens, ich würde lieber die Domain nutzen. "
        "Und als zweites, wir haben Integrator und könnten den verbinden, "
        "oder nicht?"
    )
    hallucinated = (
        " Ich habe ja auch gemacht, dass wir die Website verbinden und dann "
        "auch nicht verbunden sind. "
        "Ich habe ja auch gemacht, dass wir die Website verbinden sind. "
        "Ich habe ja auch gemacht, dass wir das nicht mehr als auf dem Weg "
        "gehen. "
        "Ich habe ja auch gemacht, dass wir die Website verbinden sind."
    )
    text = real + hallucinated
    out = _dedupe_prefix_loops(text)
    # The legitimate content survives, the hallucination is gone entirely
    assert "Ich sehe zwei Sachen" in out
    assert "Integrator" in out
    assert "Ich habe ja auch gemacht" not in out, f"hallucination leaked: {out!r}"


def test_interleaved_loop_keeps_first_occurrence():
    """When the looping prefix is mixed with non-looping content (so the
    user genuinely said it once), preserve v0.15.4 behavior: keep first."""
    text = (
        "I think we should ship. "
        "Now the thing is broken again. "
        "Now the thing is broken again. "
        "Now the thing is broken again. "
        "But anyway, let's move on."
    )
    out = _dedupe_prefix_loops(text)
    # First occurrence of the loop survives because there's non-looping
    # content (last sentence) after it.
    assert out.lower().count("now the thing") == 1
    assert "I think we should ship" in out
    assert "But anyway" in out
