# transcriber_v2.py
"""Enhanced transcriber with confidence scoring and adaptive vocabulary.

Returns not just text but per-segment confidence, timing, and
low-confidence tokens — the raw material for voice profile learning.
"""
from pywhispercpp.model import Model
import numpy as np


class TranscriberV2:
    """Whisper transcriber with voice profile support."""

    # Hallucination tokens to filter
    JUNK = {
        "[BLANK_AUDIO]", "[silence]", "(silence)", "[music]", "(music)",
        "[applause]", "[laughter]", "you", "Thank you.", "Thanks for watching!",
    }

    def __init__(self, model_path="models/ggml-base.en.bin"):
        self.model = Model(model_path, n_threads=4)
        self._vocabulary: list[str] = []  # learned user vocabulary for initial_prompt

    def set_vocabulary(self, words: list[str]):
        """Set user vocabulary to improve recognition accuracy.

        Whisper uses initial_prompt as context — words the user frequently
        says will be recognized more accurately when prompted.
        """
        self._vocabulary = words[:50]
        # Pre-build the prompt as a natural sentence (NOT comma-separated,
        # because Whisper mimics the punctuation style of the prompt)
        clean = [w for w in self._vocabulary if w.strip()]
        self._prompt = "Words I use: " + " ".join(clean) if clean else ""  # cap to avoid prompt overflow

    def transcribe(self, audio: np.ndarray) -> str:
        """Simple transcription — backward compatible with v1."""
        result = self.transcribe_rich(audio)
        return result["text"]

    def transcribe_rich(self, audio: np.ndarray) -> dict:
        """Rich transcription with confidence, timing, and diagnostics.

        Returns:
            {
                "text": "the full transcription",
                "segments": [
                    {"text": "segment text", "t0": 0, "t1": 1200, "probability": 0.92},
                    ...
                ],
                "avg_confidence": 0.87,
                "low_confidence_words": ["word1", "word2"],
                "duration_ms": 3400,
                "words_per_minute": 142,
            }
        """
        if len(audio) == 0:
            return {"text": "", "segments": [], "avg_confidence": 0.0,
                    "low_confidence_words": [], "duration_ms": 0, "words_per_minute": 0}

        # Build initial prompt from learned vocabulary
        prompt = getattr(self, "_prompt", "")

        # Transcribe with enhanced parameters
        params = {
            "token_timestamps": True,
            "extract_probability": True,
        }
        if prompt:
            params["initial_prompt"] = prompt

        segments = self.model.transcribe(audio, **params)

        # Process segments
        processed = []
        all_probs = []
        low_confidence = []

        for seg in segments:
            text = seg.text.strip()
            if not text or text in self.JUNK:
                continue

            import math
            raw_prob = getattr(seg, "probability", None)
            t0 = int(getattr(seg, "t0", 0))
            t1 = int(getattr(seg, "t1", 0))

            # Convert numpy float32 → Python float
            prob = float(raw_prob) if raw_prob is not None else None

            seg_dict = {
                "text": text,
                "t0": t0,
                "t1": t1,
            }

            if prob is not None and not math.isnan(prob):
                seg_dict["probability"] = round(prob, 4)
                all_probs.append(prob)

                # Flag low-confidence segments (< 0.7 probability)
                if prob < 0.7:
                    for word in text.split():
                        clean = word.strip(".,!?;:'\"").lower()
                        if clean and len(clean) > 1:
                            low_confidence.append(clean)

            processed.append(seg_dict)

        full_text = " ".join(s["text"] for s in processed).strip()
        avg_conf = sum(all_probs) / len(all_probs) if all_probs else 0.0

        # Compute speech rate
        duration_ms = int(len(audio) / 16000 * 1000)  # assuming 16kHz
        word_count = len(full_text.split())
        wpm = int(word_count / (duration_ms / 60000)) if duration_ms > 0 else 0

        return {
            "text": full_text,
            "segments": processed,
            "avg_confidence": round(avg_conf, 4),
            "low_confidence_words": list(set(low_confidence)),
            "duration_ms": duration_ms,
            "words_per_minute": wpm,
        }
