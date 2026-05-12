"""whisper.cpp backend — the v0.12 transcriber repackaged as a TranscriberBackend.

This is the same code that was `TranscriberV2` in v0.12.x, mechanically
adapted to the v0.13 backend protocol:

- Lazy load (was eager in constructor) so `pick_default_backend` can decide
  at runtime without paying the model-load cost twice.
- ``transcribe(audio, *, language=..., initial_prompt=..., beam_size=...)``
  replaces the implicit `self.language` / `self._prompt` reads.
- Public ``transcribe()`` returns a ``RichResult`` dict (same shape as v0.12)
  with a new ``"backend"`` key for telemetry.

Runs on Metal GPU via whisper.cpp (pywhispercpp). Slower than WhisperKit
(no Apple Neural Engine support) but works on every Mac, including Intel,
which is why it's the universal fallback.

See ``docs/SPEC-v0.13-whisperkit.md`` § 6 for context.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from transcriber_backend import RichResult


# Hallucination tokens — whisper's silence-fillers on quiet clips. Same set
# as the old TranscriberV2.JUNK; this backend filters them at segment level.
_JUNK = frozenset({
    "[BLANK_AUDIO]", "[silence]", "(silence)", "[music]", "(music)",
    "[applause]", "[laughter]", "you", "You.",
    "Thank you.", "Thanks for watching!", "Thanks for watching.",
    ". Thank you.", "Bye.", "Bye!", ". Bye.",
    "So.", ". So.", ".",
})


class WhisperCppBackend:
    """``TranscriberBackend`` implementation backed by pywhispercpp + Metal."""

    name = "whispercpp"

    # Exposed for any v0.12-era callers that imported the JUNK set directly.
    # New code should not depend on this — it's an internal detail.
    JUNK = _JUNK

    def __init__(self, model_path: str, n_threads: int = 4):
        self.model_path = model_path
        self._n_threads = n_threads
        self.model = None  # set on load()
        self._vocabulary: list[str] = []
        self._prompt: str = ""
        self.language: str = "auto"
        self._loaded = False

    # ── lifecycle ──────────────────────────────────────────────────────────

    def load(self) -> None:
        if self._loaded:
            return
        from pywhispercpp.model import Model
        self.model = Model(self.model_path, n_threads=self._n_threads)
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded

    def unload(self) -> None:
        # pywhispercpp doesn't expose a destructor; drop the reference and
        # rely on GC + Metal's deallocator to free the backend resources.
        self.model = None
        self._loaded = False

    # ── configuration ─────────────────────────────────────────────────────

    def set_language(self, code: str | None) -> None:
        if not code:
            self.language = "auto"
        else:
            self.language = code.lower()

    def set_vocabulary(
        self, words: list[str], *, prefix_sentence: str = ""
    ) -> None:
        """Set the vocabulary prompt.

        Args:
            words: passive vocab (snippet triggers + voice_profile top-200).
                Joined as a "Words I use: …" bare list.
            prefix_sentence: optional natural-sentence preamble — the user's
                explicit ``vocabulary.json``. Prepended verbatim because
                Whisper biases more reliably toward sentence-form prompts
                than lists.
        """
        self._vocabulary = list(words)[:50]
        clean = [w for w in self._vocabulary if w.strip()]
        parts: list[str] = []
        if prefix_sentence:
            parts.append(prefix_sentence.strip())
        if clean:
            parts.append("Words I use: " + " ".join(clean))
        self._prompt = " ".join(parts)

    @property
    def base_prompt(self) -> str:
        return self._prompt or ""

    # ── inference ─────────────────────────────────────────────────────────

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        if self.model is None:
            self.load()
        try:
            out = self.model.auto_detect_language(audio)
            code = out[0][0]
            prob = float(out[0][1])
            return (code, prob)
        except Exception:
            # Contract: never raise from detect_language.
            return ("en", 0.0)

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
        if self.model is None:
            self.load()

        if len(audio) == 0:
            return RichResult(
                text="", segments=[], avg_confidence=0.0,
                low_confidence_words=[], duration_ms=0, words_per_minute=0,
                detected_language=None, backend=self.name,
            )

        # Resolve language. Argument > instance default > "auto".
        lang = (language or self.language or "auto").lower()
        detected: tuple[str, float] | None = None
        if lang == "auto":
            detected = self.detect_language(audio)
            lang = detected[0]

        params: dict[str, Any] = {
            "token_timestamps": True,
            "extract_probability": True,
            "language": lang,
            "n_threads": self._n_threads,
            "no_speech_thold": no_speech_thold,
            "logprob_thold": logprob_thold,
            # Pin to deterministic greedy decode by default. Without this,
            # whisper.cpp uses its temperature-fallback ladder (0.0 → 1.0
            # at 0.2 steps), which produces *different* outputs each chunk
            # depending on whether the logprob gate is met. v0.12 streaming
            # set temperature=0.0 explicitly; the refactor needs to too,
            # otherwise long-clip WER spikes on chunk-boundary uncertainty.
            "temperature": 0.0,
            "suppress_blank": True,
        }
        if initial_prompt:
            params["initial_prompt"] = initial_prompt
        elif self._prompt:
            # Use the backend's vocab prompt if the caller didn't override.
            params["initial_prompt"] = self._prompt

        if beam_size and beam_size > 1:
            params["beam_search"] = {"beam_size": int(beam_size), "patience": 1.0}

        segments = self.model.transcribe(audio, **params)

        processed: list[dict[str, Any]] = []
        all_probs: list[float] = []
        low_confidence: list[str] = []
        for seg in segments:
            text = seg.text.strip()
            if not text or text in _JUNK:
                continue
            raw_prob = getattr(seg, "probability", None)
            t0 = int(getattr(seg, "t0", 0))
            t1 = int(getattr(seg, "t1", 0))
            prob = float(raw_prob) if raw_prob is not None else None
            seg_dict: dict[str, Any] = {"text": text, "t0": t0, "t1": t1}
            if prob is not None and not math.isnan(prob):
                seg_dict["probability"] = round(prob, 4)
                all_probs.append(prob)
                if prob < 0.7:
                    for word in text.split():
                        clean = word.strip(".,!?;:'\"").lower()
                        if clean and len(clean) > 1:
                            low_confidence.append(clean)
            processed.append(seg_dict)

        full_text = " ".join(s["text"] for s in processed).strip()
        avg_conf = sum(all_probs) / len(all_probs) if all_probs else 0.0
        duration_ms = int(len(audio) / 16000 * 1000)
        word_count = len(full_text.split())
        wpm = int(word_count / (duration_ms / 60000)) if duration_ms > 0 else 0

        return RichResult(
            text=full_text,
            segments=processed,
            avg_confidence=round(avg_conf, 4),
            low_confidence_words=list(set(low_confidence)),
            duration_ms=duration_ms,
            words_per_minute=wpm,
            detected_language=(detected[0] if detected else lang),
            backend=self.name,
        )


# Backwards-compat alias so any straggler import of TranscriberV2 still works.
# Anything new should import WhisperCppBackend directly.
TranscriberV2 = WhisperCppBackend
