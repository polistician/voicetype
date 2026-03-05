# test_recorder.py
import numpy as np
import time
from recorder import Recorder

def test_recorder_captures_audio():
    """Record 1 second, verify we get a non-empty numpy array at 16kHz mono."""
    rec = Recorder(sample_rate=16000)
    rec.start()
    time.sleep(1)
    audio = rec.stop()

    assert isinstance(audio, np.ndarray), "Should return numpy array"
    assert audio.dtype == np.float32, "Should be float32"
    assert len(audio) > 0, "Should have captured samples"
    # 1 second at 16kHz should give ~16000 samples (allow some slack)
    assert 14000 < len(audio) < 18000, f"Expected ~16000 samples, got {len(audio)}"

def test_recorder_empty_if_not_started():
    """Stop without start should return empty array."""
    rec = Recorder(sample_rate=16000)
    audio = rec.stop()
    assert len(audio) == 0

if __name__ == "__main__":
    test_recorder_captures_audio()
    print("PASS: test_recorder_captures_audio")
    test_recorder_empty_if_not_started()
    print("PASS: test_recorder_empty_if_not_started")
    print("All tests passed!")
