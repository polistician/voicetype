"""Abstract backend protocol for VoiceType transcribers.

Why this exists
---------------
v0.12.x hard-coded ``pywhispercpp.Model`` everywhere. v0.13 abstracts it so
we can swap in:

- ``WhisperKitBackend`` (Apple Neural Engine, ~2.5× faster)
- ``CanaryBackend``    (NVIDIA, code-switching, v0.14)
- ``ParakeetBackend``  (English-only speed mode, v0.15)
- ``MoonshineBackend`` (tiny on-device, v0.15)

All backends produce identical ``RichResult`` shape so the streaming
pipeline, voice profile, and downstream paste/intent logic stay
backend-agnostic.

Concrete backends live in their own files:
    whisper_cpp_backend.py   (was transcriber_v2.py)
    whisperkit_backend.py    (new in v0.13)

See ``docs/SPEC-v0.13-whisperkit.md`` for the full architecture.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable, Any
import platform

import numpy as np


# RichResult is structurally a dict — keeping it as ``dict`` (not a dataclass)
# preserves backward compatibility with the existing v0.12 callers that index
# into the result by string keys. The class exists for documentation / type
# hints only.
class RichResult(dict):
    """Shape returned by every backend's ``transcribe()``.

    Keys (all required unless noted):
        text:                 str          — final transcribed text
        segments:             list[dict]   — per-segment {text, t0, t1, probability?}
        avg_confidence:       float        — mean per-segment probability, 0..1
        low_confidence_words: list[str]    — words flagged < 0.7 confidence
        duration_ms:          int          — audio duration in ms
        words_per_minute:     int          — speech rate
        detected_language:    str | None   — ISO code of language used (or None)
        backend:              str          — name of producing backend (new in v0.13)
    """


@runtime_checkable
class TranscriberBackend(Protocol):
    """The contract every backend must satisfy.

    ``runtime_checkable`` so ``isinstance(b, TranscriberBackend)`` works as a
    duck-type fence at composition sites without inheritance.
    """

    name: str
    """Stable identifier used in telemetry + config selection.
    Conventions: lower-case alphanumeric, no spaces. Examples:
    ``"whispercpp"``, ``"whisperkit"``, ``"canary"``.
    """

    @property
    def base_prompt(self) -> str:
        """The vocab-biased prompt the streamer prefixes to per-chunk
        ``initial_prompt`` for prompt carryover. Built from
        ``set_vocabulary()`` input.
        """
        ...

    # ---- lifecycle ----

    def load(self) -> None:
        """Load the model into memory. Idempotent — calling on an already-
        loaded backend is a no-op. May block for seconds on first call.
        """
        ...

    def is_loaded(self) -> bool:
        """True after a successful ``load()``."""
        ...

    def unload(self) -> None:
        """Release the model. Useful when swapping backends in Settings.
        Calling ``load()`` again works."""
        ...

    # ---- configuration ----

    def set_language(self, code: str | None) -> None:
        """Set the language hint. Accepts ISO codes (``"en"``, ``"de"``,
        ...), ``"auto"`` for per-clip detection, or ``None`` (treated as
        ``"auto"``)."""
        ...

    def set_vocabulary(self, words: list[str]) -> None:
        """Set the user-vocabulary prompt. Subsequent ``transcribe()`` calls
        use the resulting ``base_prompt`` as the prefix of their
        ``initial_prompt``."""
        ...

    # ---- inference ----

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        """Run language ID on a clip. Returns ``(code, probability)``.

        Fallback contract: never raises — returns ``("en", 0.0)`` on any
        internal failure so callers can rely on a usable result.
        """
        ...

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        initial_prompt: str = "",
        beam_size: int = 0,
        no_speech_thold: float = 0.6,
        logprob_thold: float = -1.0,
    ) -> RichResult:
        """Transcribe audio synchronously.

        Args:
            audio: float32 mono PCM at 16 kHz.
            language: ISO code, ``"auto"``, or ``None`` (uses
                ``self.set_language`` value).
            initial_prompt: prompt prefix (vocab + chunk-carryover tokens).
            beam_size: ``0`` = greedy (fastest), ``>1`` = beam search
                (slower, more accurate). Used by the verifier pass.
            no_speech_thold: drop segments with no-speech prob above this.
            logprob_thold: drop segments with avg logprob below this.

        Returns:
            ``RichResult`` dict. Empty ``text`` is a valid result for
            silence/noise clips.
        """
        ...


def pick_default_backend(cfg: dict[str, Any]) -> str:
    """Return the backend name to use given config + system capability.

    Resolution order:
      1. ``cfg["transcriber_backend"]`` if set to a concrete name
         (``"whispercpp"`` / ``"whisperkit"`` / ...) — honor the override.
      2. ``"whisperkit"`` on Apple Silicon (arm64), iff the helper binary
         exists in the bundle.
      3. ``"whispercpp"`` everywhere else.

    The helper-binary existence check is in ``_whisperkit_available()`` so
    voxtype.py doesn't have to reach into the helper layout.
    """
    explicit = (cfg.get("transcriber_backend") or "auto").strip().lower()
    if explicit not in {"auto", ""}:
        return explicit

    # Auto: pick the best available
    if platform.machine() == "arm64" and _whisperkit_available():
        return "whisperkit"
    return "whispercpp"


def _whisperkit_available() -> bool:
    """Check if WhisperKit helper binary + model are present in the bundle.

    Importing whisperkit_backend lazily here avoids loading WhisperKit's
    deps when the user is forced to whisper.cpp.
    """
    try:
        from paths import helper_path
    except ImportError:
        return False
    import os
    helper = helper_path("whisperkit_helper")
    return bool(helper) and os.path.isfile(helper)
