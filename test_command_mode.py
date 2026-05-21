"""Tests for the Command Mode pipeline (⌥⇧C → edit → paste).

We don't spin up the real recorder / transcriber / model — those are
covered by the integration verification steps in the v0.14 plan. Instead
we exercise the dispatcher and history-context wiring.
"""
from unittest.mock import MagicMock, patch

from transcript_history import History as TranscriptHistory


def test_apply_voice_edit_dispatches_to_integrator(monkeypatch):
    """When cleanup_backend='integrator', _apply_voice_edit should call
    integrator_chat.edit() with the right args."""
    import integrator_chat

    captured = {}
    def _fake_edit(context, instruction, **kw):
        captured["context"] = context
        captured["instruction"] = instruction
        captured["kw"] = kw
        return "edited!"
    monkeypatch.setattr(integrator_chat, "edit", _fake_edit)

    # Build a minimal VoxType-shaped object with just _apply_voice_edit available.
    from voxtype import VoxType
    inst = MagicMock(spec=VoxType)
    inst.cfg = {"cleanup_backend": "integrator"}
    inst._mlx_cleanup = None
    # Bind the real method to our mock so it uses our cfg.
    inst._apply_voice_edit = VoxType._apply_voice_edit.__get__(inst)

    result = inst._apply_voice_edit("hello world", "make it formal")
    assert result == "edited!"
    assert captured["context"] == "hello world"
    assert captured["instruction"] == "make it formal"


def test_apply_voice_edit_groq_passes_model_prefix(monkeypatch):
    """cleanup_backend='groq' must call edit() with model='groq/default' so
    the Integrator dispatcher routes upstream to Groq."""
    import integrator_chat
    captured = {}
    def _fake_edit(context, instruction, **kw):
        captured["model"] = kw.get("model")
        return "g"
    monkeypatch.setattr(integrator_chat, "edit", _fake_edit)

    from voxtype import VoxType
    inst = MagicMock(spec=VoxType)
    inst.cfg = {"cleanup_backend": "groq"}
    inst._mlx_cleanup = None
    inst._apply_voice_edit = VoxType._apply_voice_edit.__get__(inst)
    inst._apply_voice_edit("x", "y")
    assert captured["model"] == "groq/default"


def test_apply_voice_edit_off_falls_back_to_integrator_when_paired(monkeypatch):
    """With cleanup_backend='off' the user still expects Command Mode to work
    if they have Integrator paired (otherwise voice edits are useless even
    though Command Mode was explicitly enabled)."""
    import integrator_chat
    monkeypatch.setattr(integrator_chat, "is_connected", lambda: True)
    monkeypatch.setattr(integrator_chat, "edit", lambda c, i, **k: "ed")

    from voxtype import VoxType
    inst = MagicMock(spec=VoxType)
    inst.cfg = {"cleanup_backend": "off"}
    inst._mlx_cleanup = None
    inst._apply_voice_edit = VoxType._apply_voice_edit.__get__(inst)
    assert inst._apply_voice_edit("x", "y") == "ed"


def test_apply_voice_edit_off_no_pairing_returns_context(monkeypatch):
    import integrator_chat
    monkeypatch.setattr(integrator_chat, "is_connected", lambda: False)

    from voxtype import VoxType
    inst = MagicMock(spec=VoxType)
    inst.cfg = {"cleanup_backend": "off"}
    inst._mlx_cleanup = None
    inst._apply_voice_edit = VoxType._apply_voice_edit.__get__(inst)
    assert inst._apply_voice_edit("keep me", "anything") == "keep me"


def test_transcript_history_recent_drives_context():
    """The Command Mode context must come from the last paste in
    transcript_history when one exists."""
    h = TranscriptHistory(size=4)
    h.push("first")
    h.push("the latest paste")
    assert h.most_recent() == "the latest paste"
