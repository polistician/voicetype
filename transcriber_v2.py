"""Backwards-compatibility shim for the v0.12 module path.

The canonical implementation moved to ``whisper_cpp_backend.py`` in v0.13 as
part of the ``TranscriberBackend`` abstraction. This file re-exports the
symbols at their old names so any straggler imports keep working.

Anything new should import from ``whisper_cpp_backend`` (or pick a backend
via ``transcriber_backend.pick_default_backend``).
"""
from whisper_cpp_backend import WhisperCppBackend, _JUNK

# Old name → new name
TranscriberV2 = WhisperCppBackend

# Some downstream code reached into TranscriberV2.JUNK; keep that path open.
TranscriberV2.JUNK = _JUNK  # type: ignore[attr-defined]

__all__ = ["TranscriberV2"]
