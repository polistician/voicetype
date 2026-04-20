# test_stats.py
import json
import os
import tempfile
import pytest

import stats as stats_mod


@pytest.fixture(autouse=True)
def tmp_stats(monkeypatch, tmp_path):
    monkeypatch.setattr(stats_mod, "STATS_PATH", str(tmp_path / "stats.json"))
    monkeypatch.setattr(stats_mod, "DECISIONS_PATH", str(tmp_path / "decisions.jsonl"))


def test_load_default():
    s = stats_mod.load()
    assert s["recordings_total"] == 0
    assert s["first_used_at"] is not None


def test_increment():
    stats_mod.increment("recordings_total")
    stats_mod.increment("recordings_total", by=2)
    s = stats_mod.load()
    assert s["recordings_total"] == 3


def test_increment_unknown_key_creates_it():
    stats_mod.increment("weird_custom_counter")
    assert stats_mod.load()["weird_custom_counter"] == 1


def test_log_and_recent_decisions():
    stats_mod.log_decision("hello", "dictate", "", 1.2)
    stats_mod.log_decision("open hope", "open_help", "fuzzy: hope→help", 0.5)
    recent = stats_mod.recent_decisions(n=10)
    assert len(recent) == 2
    assert recent[0]["raw"] == "open hope"
    assert recent[0]["action"] == "open_help"
    assert recent[1]["raw"] == "hello"


def test_decisions_ring_buffer_trims_to_50():
    for i in range(60):
        stats_mod.log_decision(f"msg{i}", "dictate", "", 0.5)
    recent = stats_mod.recent_decisions(n=100)
    assert len(recent) == 50
    # Most recent first — msg59 should be first
    assert recent[0]["raw"] == "msg59"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
