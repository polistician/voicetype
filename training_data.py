# training_data.py
"""Training data collector for Whisper LoRA fine-tuning.

Saves audio + corrected transcript pairs. When enough data accumulates
(10+ minutes of corrected audio), LoRA fine-tuning can produce a
personalized Whisper adapter (~10MB) that dramatically improves
recognition accuracy for this specific user.

Data saved to ~/.voicetype/training/
"""
import os
import json
import numpy as np
from datetime import datetime

TRAINING_DIR = os.path.expanduser("~/.voicetype/training")


def save_training_pair(audio: np.ndarray, transcript: str, corrected: str = None,
                       confidence: float = 0.0, sample_rate: int = 16000):
    """Save an audio + transcript pair for future fine-tuning.

    Only saves if:
    - Audio is long enough (> 1 second)
    - Transcript is non-empty
    - If corrected is provided, it differs from transcript (actual correction)

    Args:
        audio: numpy float32 array
        transcript: what Whisper produced
        corrected: what the user corrected it to (optional)
        confidence: Whisper's confidence score
        sample_rate: audio sample rate
    """
    os.makedirs(TRAINING_DIR, exist_ok=True)

    # Only save meaningful audio
    if len(audio) < sample_rate:  # less than 1 second
        return False
    if not transcript or not transcript.strip():
        return False
    # If corrected provided, only save if different (actual correction)
    if corrected and corrected.strip() == transcript.strip():
        return False

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = os.path.join(TRAINING_DIR, timestamp)

    # Save audio
    np.save(f"{base}.npy", audio)

    # Save metadata
    meta = {
        "timestamp": timestamp,
        "transcript": transcript,
        "corrected": corrected or transcript,
        "confidence": confidence,
        "sample_rate": sample_rate,
        "duration_seconds": round(len(audio) / sample_rate, 2),
        "is_correction": corrected is not None and corrected != transcript,
    }
    with open(f"{base}.json", "w") as f:
        json.dump(meta, f, indent=2)

    return True


def get_training_stats():
    """Get statistics about collected training data."""
    if not os.path.exists(TRAINING_DIR):
        return {"pairs": 0, "total_seconds": 0, "corrections": 0, "ready_for_finetuning": False}

    pairs = 0
    total_seconds = 0
    corrections = 0

    for f in os.listdir(TRAINING_DIR):
        if f.endswith(".json"):
            try:
                with open(os.path.join(TRAINING_DIR, f)) as fp:
                    meta = json.load(fp)
                pairs += 1
                total_seconds += meta.get("duration_seconds", 0)
                if meta.get("is_correction"):
                    corrections += 1
            except Exception:
                pass

    return {
        "pairs": pairs,
        "total_seconds": round(total_seconds, 1),
        "total_minutes": round(total_seconds / 60, 1),
        "corrections": corrections,
        "ready_for_finetuning": total_seconds >= 600,  # 10 minutes minimum
    }
