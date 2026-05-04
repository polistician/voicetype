# transcriber.py
from pywhispercpp.model import Model
import numpy as np


class Transcriber:
    def __init__(self, model_path="models/ggml-base.en.bin"):
        self.model = Model(model_path, n_threads=4)

    # Whisper hallucination tokens to filter out
    JUNK = {"[BLANK_AUDIO]", "[silence]", "(silence)", "[music]", "(music)",
            "[applause]", "[laughter]", "you", "Thank you.", "Thanks for watching!"}

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 numpy array (16kHz mono) to text."""
        if len(audio) == 0:
            return ""
        segments = self.model.transcribe(audio)
        parts = []
        for seg in segments:
            text = seg.text.strip()
            if text and text not in self.JUNK:
                parts.append(text)
        return " ".join(parts).strip()
