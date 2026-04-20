# test_user_fixes.py
import json
import os
import tempfile
import pytest

import user_fixes


@pytest.fixture(autouse=True)
def tmp_fixes_path(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    monkeypatch.setattr(user_fixes, "FIXES_PATH", path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def test_load_default_when_missing():
    data = user_fixes.load()
    assert data["help_variants"] == []
    assert data["corrections"] == {}


def test_add_variant_persists():
    user_fixes.add_variant("help", "HAVE")
    data = user_fixes.load()
    assert "have" in data["help_variants"]


def test_add_variant_dedupes():
    user_fixes.add_variant("help", "have")
    user_fixes.add_variant("help", "HAVE")
    data = user_fixes.load()
    assert data["help_variants"].count("have") == 1


def test_add_correction_persists():
    user_fixes.add_correction("clip-bot", "clipboard")
    data = user_fixes.load()
    assert data["corrections"]["clip-bot"] == "clipboard"


def test_parse_when_i_say():
    fix = user_fixes.parse_heuristic("when I say have treat as help")
    assert fix == {"action": "add_variant", "intent_key": "help", "word": "have"}


def test_parse_should_be_intent_keyword():
    fix = user_fixes.parse_heuristic("have should be help")
    assert fix["action"] == "add_variant"
    assert fix["intent_key"] == "help"
    assert fix["word"] == "have"


def test_parse_x_to_y_intent():
    fix = user_fixes.parse_heuristic("fix have to help")
    assert fix["action"] == "add_variant"
    assert fix["word"] == "have"


def test_parse_word_correction():
    fix = user_fixes.parse_heuristic("clip-bot should be clipboard")
    assert fix["action"] == "add_correction"
    assert fix["wrong"] == "clip-bot"
    assert fix["right"] == "clipboard"


def test_parse_unrecognizable_returns_none():
    fix = user_fixes.parse_heuristic("please just make it work")
    assert fix is None


def test_apply_add_variant():
    msg = user_fixes.apply({"action": "add_variant", "intent_key": "help", "word": "hep"})
    assert "hep" in msg
    assert "hep" in user_fixes.load()["help_variants"]


def test_apply_add_correction():
    msg = user_fixes.apply({"action": "add_correction", "wrong": "vox tape", "right": "VoxType"})
    assert "VoxType" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
