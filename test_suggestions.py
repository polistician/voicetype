# test_suggestions.py
from suggestions import suggest


def _d(raw, action="dictate", ts=0):
    return {"raw": raw, "action": action, "ts": ts, "detail": "", "duration_s": 1.0, "corrected": False}


def test_empty_decisions_returns_empty():
    assert suggest([], []) == []


def test_single_repeat_not_suggested():
    decisions = [_d("kind regards, Beauregard")]
    assert suggest(decisions, []) == []


def test_three_repeats_suggested():
    decisions = [_d("kind regards, Beauregard", ts=i) for i in range(3)]
    out = suggest(decisions, [])
    assert len(out) == 1
    assert out[0]["phrase"] == "kind regards, Beauregard"
    assert out[0]["count"] == 3


def test_too_short_filtered():
    decisions = [_d("hi", ts=i) for i in range(5)]
    assert suggest(decisions, []) == []


def test_existing_snippet_excluded():
    decisions = [_d("deploy the v3 system", ts=i) for i in range(4)]
    out = suggest(decisions, existing_snippet_bodies=["Deploy the V3 system"])
    assert out == []


def test_commands_excluded():
    decisions = [_d("open help", action="open_help", ts=i) for i in range(5)]
    assert suggest(decisions, []) == []


def test_orders_by_frequency():
    decisions = (
        [_d("this phrase is more frequent", ts=i) for i in range(5)]
        + [_d("this one appears three times", ts=i + 100) for i in range(3)]
    )
    out = suggest(decisions, [])
    assert len(out) == 2
    assert out[0]["count"] == 5
    assert out[1]["count"] == 3


def test_case_insensitive_dedup():
    decisions = [
        _d("Kind regards, Beau", ts=1),
        _d("kind regards, beau", ts=2),
        _d("KIND REGARDS, BEAU", ts=3),
    ]
    out = suggest(decisions, [])
    assert len(out) == 1
    assert out[0]["count"] == 3


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
