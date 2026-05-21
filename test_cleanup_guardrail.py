"""Tests for the edit-distance guardrail that rejects LLM hallucinations."""
from integrator_chat import _fallback_if_mangled


def test_guardrail_keeps_close_paraphrase():
    raw = "i need to fix this thing"
    cleaned = "I need to fix this thing."
    assert _fallback_if_mangled(raw, cleaned, threshold=0.5) == cleaned


def test_guardrail_keeps_punctuation_only_change():
    raw = "open the door"
    cleaned = "Open the door."
    assert _fallback_if_mangled(raw, cleaned, threshold=0.5) == cleaned


def test_guardrail_keeps_filler_removal():
    raw = "um so like the the file is here"
    cleaned = "The file is here."
    assert _fallback_if_mangled(raw, cleaned, threshold=0.5) == cleaned


def test_guardrail_rejects_total_hallucination():
    raw = "open the door"
    cleaned = "The mitochondria is the powerhouse of the cell."
    assert _fallback_if_mangled(raw, cleaned, threshold=0.5) == raw


def test_guardrail_rejects_topic_drift():
    raw = "schedule a meeting for tuesday"
    cleaned = "I love eating apples in the park on sunday."
    assert _fallback_if_mangled(raw, cleaned, threshold=0.5) == raw


def test_guardrail_empty_cleaned_returns_raw():
    raw = "test content"
    cleaned = ""
    assert _fallback_if_mangled(raw, cleaned, threshold=0.5) == raw


def test_guardrail_lower_threshold_keeps_more():
    raw = "tuesday meeting at three"
    cleaned = "wednesday lunch at four"
    # Different content but a lower threshold tolerates more drift.
    assert _fallback_if_mangled(raw, cleaned, threshold=0.1) == cleaned
