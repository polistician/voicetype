"""Cleanup backend selection — mirrors transcriber_backend.py.

A cleanup backend turns raw Whisper text into a polished version, and
optionally applies a free-form editing instruction in Command Mode. The
backend is selected by a single string config key `cleanup_backend`:

    "off"        — paste raw text, no LLM call
    "integrator" — Integrator → ChatGPT (cloud)
    "groq"       — Integrator → Groq Llama 4 Scout (cloud, fast)
    "local"      — Qwen 3 0.6B via MLX (on-device)

All backends MUST return raw input on any failure — dictation latency is
sacred and the user must never see an exception cross this boundary.
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class CleanupBackend(Protocol):
    name: str

    def cleanup(self, text: str) -> str:
        ...

    def edit(self, context: str, instruction: str) -> str:
        ...


_VALID_BACKENDS = {"off", "integrator", "local", "groq"}


def pick_cleanup_backend(cfg: dict) -> str:
    """Return the configured cleanup backend, normalized to a known value."""
    v = (cfg.get("cleanup_backend") or "off").strip().lower()
    return v if v in _VALID_BACKENDS else "off"
