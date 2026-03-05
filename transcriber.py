# transcriber.py
from pywhispercpp.model import Model
import numpy as np


class Transcriber:
    def __init__(self, model_path="models/ggml-base.en.bin"):
        self.model = Model(model_path, n_threads=4)

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe a float32 numpy array (16kHz mono) to text."""
        if len(audio) == 0:
            return ""
        segments = self.model.transcribe(audio)
        return " ".join(seg.text.strip() for seg in segments).strip()
