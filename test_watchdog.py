"""Tests for the v0.15.3 health watchdog.

We don't spin up a real rumps app; we exercise the two pure helpers
(_check_helper_health and _append_health_event) on a duck-typed stub.
"""
import json
import os
import tempfile
from types import SimpleNamespace
from unittest import mock

import voxtype


def _stub_voxtype_with_helpers(hotkey_poll, overlay_poll):
    """Build a stub matching the shape voxtype expects."""
    s = SimpleNamespace()
    s.hotkey  = SimpleNamespace(_proc=SimpleNamespace(poll=lambda: hotkey_poll,
                                                       returncode=hotkey_poll))
    s.overlay = SimpleNamespace(_proc=SimpleNamespace(poll=lambda: overlay_poll,
                                                       returncode=overlay_poll))
    # Bind the methods so they see our stub `self`
    s._check_helper_health = voxtype.VoxType._check_helper_health.__get__(s)
    return s


def test_healthy_when_all_helpers_alive():
    s = _stub_voxtype_with_helpers(None, None)   # poll()=None means still running
    assert s._check_helper_health() == []


def test_hotkey_helper_death_reported():
    s = _stub_voxtype_with_helpers(139, None)    # SIGSEGV = 139
    problems = s._check_helper_health()
    assert len(problems) == 1
    assert "hotkey_helper" in problems[0]
    assert "139" in problems[0]


def test_overlay_death_reported():
    s = _stub_voxtype_with_helpers(None, 1)
    problems = s._check_helper_health()
    assert len(problems) == 1
    assert "snippet_overlay" in problems[0]


def test_both_dead_both_reported():
    s = _stub_voxtype_with_helpers(139, 1)
    problems = s._check_helper_health()
    assert len(problems) == 2


def test_missing_proc_handle_is_safe():
    """If hotkey listener hasn't started yet, _proc is None — watchdog
    must not crash."""
    s = SimpleNamespace()
    s.hotkey  = SimpleNamespace()   # no _proc attribute at all
    s.overlay = SimpleNamespace()
    s._check_helper_health = voxtype.VoxType._check_helper_health.__get__(s)
    # Just shouldn't raise
    assert s._check_helper_health() == []


def test_append_health_event_writes_jsonl(tmp_path):
    log_path = tmp_path / "health_log.jsonl"
    s = SimpleNamespace(HEALTH_LOG_PATH=str(log_path))
    voxtype.VoxType._append_health_event(s, {"ts": "now", "kind": "manual_restart"})
    voxtype.VoxType._append_health_event(s, {"ts": "later", "kind": "helper_died"})
    lines = log_path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["kind"] == "manual_restart"
    assert json.loads(lines[1])["kind"] == "helper_died"


def test_append_health_event_never_raises():
    """Disk full / permission error must NOT crash the watchdog thread."""
    # Point at a path under a real-world impossible parent (/dev/null/x can't be made)
    s = SimpleNamespace(HEALTH_LOG_PATH="/dev/null/cannot/be/made/log.jsonl")
    # Should silently no-op, not raise
    voxtype.VoxType._append_health_event(s, {"ts": "x", "kind": "y"})
