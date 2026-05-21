"""Tests for the silent migration from legacy boolean cleanup flags to the
unified `cleanup_backend` string. Run after any change to config.py.
"""
import json
import os
import tempfile
from unittest import mock

import config as _config_mod


def _run_load_with(user_cfg: dict) -> dict:
    """Write user_cfg to a temp path, point config.py at it, call load_config."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        with open(path, "w") as f:
            json.dump(user_cfg, f)
        with mock.patch.object(_config_mod, "CONFIG_PATH", path):
            return _config_mod.load_config()


def test_legacy_ai_cleanup_enabled_true_maps_to_integrator():
    cfg = _run_load_with({"ai_cleanup_enabled": True})
    assert cfg["cleanup_backend"] == "integrator"


def test_legacy_use_llm_correction_true_maps_to_local():
    cfg = _run_load_with({"use_llm_correction": True})
    assert cfg["cleanup_backend"] == "local"


def test_legacy_use_llm_correction_wins_over_ai_cleanup():
    cfg = _run_load_with({"use_llm_correction": True, "ai_cleanup_enabled": True})
    # local has higher precedence in the migration order
    assert cfg["cleanup_backend"] == "local"


def test_neither_legacy_set_maps_to_off():
    cfg = _run_load_with({})
    assert cfg["cleanup_backend"] == "off"


def test_explicit_cleanup_backend_wins_over_legacy():
    cfg = _run_load_with({"ai_cleanup_enabled": True, "cleanup_backend": "groq"})
    assert cfg["cleanup_backend"] == "groq"


def test_save_config_strips_legacy_keys():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "config.json")
        with mock.patch.object(_config_mod, "CONFIG_PATH", path):
            _config_mod.save_config({
                "cleanup_backend": "local",
                "ai_cleanup_enabled": True,   # legacy — should be stripped
                "use_llm_correction": True,   # legacy — should be stripped
                "auto_paste": False,
            })
            with open(path) as f:
                written = json.load(f)
    assert written == {"cleanup_backend": "local", "auto_paste": False}
