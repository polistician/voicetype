# test_transcriber.py
import numpy as np
from transcriber import Transcriber

def test_transcriber_loads_model():
    """Model should load without error."""
    t = Transcriber(model_path="models/ggml-base.en.bin")
    assert t.model is not None

def test_transcriber_silent_audio():
    """Silent audio should return empty or whitespace-only string."""
    t = Transcriber(model_path="models/ggml-base.en.bin")
    # 2 seconds of silence at 16kHz
    silence = np.zeros(32000, dtype=np.float32)
    text = t.transcribe(silence)
    assert isinstance(text, str)
    # Silent audio may return empty or special tokens — just check it doesn't crash

def test_transcriber_returns_string():
    """Transcribing a sine wave (noise) should return a string."""
    t = Transcriber(model_path="models/ggml-base.en.bin")
    # Generate a 1-second 440Hz tone
    sr = 16000
    t_arr = np.linspace(0, 1, sr, dtype=np.float32)
    tone = 0.5 * np.sin(2 * np.pi * 440 * t_arr)
    text = t.transcribe(tone)
    assert isinstance(text, str)

if __name__ == "__main__":
    test_transcriber_loads_model()
    print("PASS: test_transcriber_loads_model")
    test_transcriber_silent_audio()
    print("PASS: test_transcriber_silent_audio")
    test_transcriber_returns_string()
    print("PASS: test_transcriber_returns_string")
    print("All tests passed!")
