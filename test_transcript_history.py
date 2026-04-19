# test_transcript_history.py
from transcript_history import History


def test_empty():
    h = History(size=5)
    assert h.recent() == []


def test_push_and_recent():
    h = History(size=3)
    h.push("one")
    h.push("two")
    h.push("three")
    items = h.recent()
    assert [e.text for e in items] == ["three", "two", "one"]


def test_ring_buffer_drops_oldest():
    h = History(size=3)
    for t in ["a", "b", "c", "d", "e"]:
        h.push(t)
    items = [e.text for e in h.recent()]
    assert items == ["e", "d", "c"]


def test_entries_have_timestamps():
    h = History(size=3)
    h.push("hello")
    entries = h.recent()
    assert entries[0].timestamp > 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
