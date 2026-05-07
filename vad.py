"""vad.py — Silero VAD wrapper for VoiceType.

Replaces the RMS energy gate with a real neural VAD. Silero is the
de-facto open-source speech VAD: ~2 MB ONNX, 1ms inference per chunk,
much better than RMS at distinguishing speech from noise/silence.

Usage:
    vad = SileroVAD()
    has_speech = vad.contains_speech(audio_np_float32, sample_rate=16000)

Notes:
- Auto-detects API version: newer Silero (v5) uses a single combined
  `state` tensor of shape (2, 1, 128); older Silero (v4) uses separate
  `h` and `c` LSTM tensors of shape (2, 1, 64) each.
"""
from __future__ import annotations

import os
import numpy as np


class SileroVAD:
    def __init__(self, model_path: str | None = None, threshold: float = 0.5):
        """threshold: speech-probability above this counts as speech."""
        if model_path is None:
            candidates = [
                os.path.expanduser("~/voicetype/models/silero_vad.onnx"),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "silero_vad.onnx"),
            ]
            import sys
            if hasattr(sys, "_MEIPASS"):
                candidates.insert(0, os.path.join(sys._MEIPASS, "models", "silero_vad.onnx"))
            for c in candidates:
                if os.path.isfile(c):
                    model_path = c
                    break
        if not model_path or not os.path.isfile(model_path):
            raise FileNotFoundError("silero_vad.onnx not found")

        import onnxruntime as ort
        self.sess = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.threshold = threshold

        # Detect API version by inspecting input names
        input_names = {i.name for i in self.sess.get_inputs()}
        self._api = "v5" if "state" in input_names else "v4"

        if self._api == "v5":
            # Combined state tensor (2, 1, 128)
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            # Separate h, c LSTM tensors (2, 1, 64) each
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def reset_state(self):
        if self._api == "v5":
            self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            self._h = np.zeros((2, 1, 64), dtype=np.float32)
            self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def contains_speech(self, audio: np.ndarray, sample_rate: int = 16000) -> bool:
        """Returns True if audio contains any segment classified as speech."""
        if len(audio) == 0:
            return False
        chunk_size = 512 if sample_rate == 16000 else 256
        self.reset_state()
        sr = np.array(sample_rate, dtype=np.int64)
        for i in range(0, len(audio) - chunk_size + 1, chunk_size):
            chunk = audio[i:i + chunk_size].astype(np.float32)
            if self._api == "v5":
                outputs = self.sess.run(None, {
                    "input": chunk[np.newaxis, :],
                    "sr": sr,
                    "state": self._state,
                })
                prob, self._state = outputs
            else:
                outputs = self.sess.run(None, {
                    "input": chunk[np.newaxis, :],
                    "sr": sr,
                    "h": self._h,
                    "c": self._c,
                })
                prob, self._h, self._c = outputs
            if float(prob[0, 0]) > self.threshold:
                return True
        return False
