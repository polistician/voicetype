# pronunciation.py
"""Phoneme-level pronunciation analysis for non-native speakers.

Uses wav2vec2 for forced alignment + per-phoneme confidence scoring.
German→English specific: flags known L1 transfer problems.

Gracefully degrades if torch is not installed — returns empty results.
"""
import os
import json
import logging

logger = logging.getLogger(__name__)

ANALYSIS_PATH = os.path.expanduser("~/.voxtype/pronunciation.json")

# German→English known problem phonemes
# These are L1 transfer issues for German native speakers
L1_PROBLEMS = {
    "θ": {"description": "th (as in 'think')", "common_substitution": "s or z", "tip": "Place tongue between teeth"},
    "ð": {"description": "th (as in 'this')", "common_substitution": "d or z", "tip": "Place tongue between teeth, voice it"},
    "æ": {"description": "short a (as in 'cat')", "common_substitution": "e sound", "tip": "Open mouth wider, tongue lower"},
    "ɹ": {"description": "r (as in 'red')", "common_substitution": "uvular r", "tip": "Curl tongue tip back, don't vibrate throat"},
    "w": {"description": "w (as in 'water')", "common_substitution": "v", "tip": "Round lips fully, no teeth contact"},
    "ŋ": {"description": "ng (as in 'sing')", "common_substitution": "ng+k", "tip": "Don't add a 'g' or 'k' after the ng"},
}

_model = None
_processor = None


def _load_model():
    """Lazy-load wav2vec2 model. Returns (model, processor) or (None, None)."""
    global _model, _processor
    if _model is not None:
        return _model, _processor
    try:
        import torch
        import torchaudio
        bundle = torchaudio.pipelines.WAV2VEC2_ASR_BASE_960H
        _model = bundle.get_model()
        _processor = bundle
        logger.info("[pronunciation] wav2vec2 model loaded")
        return _model, _processor
    except ImportError:
        logger.info("[pronunciation] torch not available — pronunciation analysis disabled")
        return None, None
    except Exception as e:
        logger.warning("[pronunciation] model load failed: %s", e)
        return None, None


def analyze(audio_array, sample_rate=16000, expected_text=""):
    """Analyze pronunciation from audio.

    Args:
        audio_array: numpy float32 array of audio
        sample_rate: audio sample rate (default 16kHz)
        expected_text: what the user intended to say (for alignment)

    Returns:
        {
            "available": True/False,
            "word_scores": [{"word": "hello", "confidence": 0.92}, ...],
            "low_confidence_words": ["word1", "word2"],
            "l1_issues": [{"phoneme": "θ", "word": "think", "tip": "..."}],
            "overall_clarity": 0.85,
        }
    """
    model, processor = _load_model()
    if model is None:
        return {"available": False}

    try:
        import torch
        import torchaudio

        # Convert numpy to torch tensor
        if hasattr(audio_array, 'numpy'):
            waveform = audio_array
        else:
            import numpy as np
            waveform = torch.from_numpy(audio_array).unsqueeze(0)

        # Resample if needed
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)

        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)

        # Get emission probabilities
        with torch.no_grad():
            emission, _ = model(waveform)

        # Decode to get per-frame character probabilities
        emission_prob = torch.nn.functional.softmax(emission, dim=-1)

        # Get the predicted characters and their confidences
        values, indices = torch.max(emission_prob[0], dim=-1)

        # Map indices to characters
        labels = processor.get_labels()

        # Group into words by detecting spaces/silence
        words = []
        current_word = []
        current_scores = []

        for i, (idx, conf) in enumerate(zip(indices, values)):
            char = labels[idx.item()] if idx.item() < len(labels) else ""
            score = conf.item()

            if char == "|" or char == " " or char == "<pad>":
                if current_word:
                    word = "".join(current_word).replace("|", "").strip()
                    if word:
                        avg_score = sum(current_scores) / len(current_scores) if current_scores else 0
                        words.append({"word": word.lower(), "confidence": round(avg_score, 3)})
                    current_word = []
                    current_scores = []
            elif char not in ("<s>", "</s>", "<pad>", ""):
                current_word.append(char)
                current_scores.append(score)

        # Don't forget the last word
        if current_word:
            word = "".join(current_word).replace("|", "").strip()
            if word:
                avg_score = sum(current_scores) / len(current_scores) if current_scores else 0
                words.append({"word": word.lower(), "confidence": round(avg_score, 3)})

        # Identify low-confidence words
        low_conf = [w for w in words if w["confidence"] < 0.7]

        # Check for L1 (German) specific issues
        l1_issues = _check_l1_issues(expected_text or " ".join(w["word"] for w in words))

        # Overall clarity score
        all_scores = [w["confidence"] for w in words]
        overall = round(sum(all_scores) / len(all_scores), 3) if all_scores else 0.0

        return {
            "available": True,
            "word_scores": words,
            "low_confidence_words": [w["word"] for w in low_conf],
            "l1_issues": l1_issues,
            "overall_clarity": overall,
        }
    except Exception as e:
        logger.warning("[pronunciation] analysis failed: %s", e)
        return {"available": False, "error": str(e)}


def _check_l1_issues(text):
    """Check for German→English L1 transfer issues based on known problem words."""
    issues = []
    text_lower = text.lower()

    # Words containing "th" sound (θ/ð)
    th_words = ["the", "this", "that", "think", "thing", "thought", "through",
                 "three", "these", "those", "them", "then", "there", "their", "with"]
    for word in th_words:
        if word in text_lower:
            if word in ("the", "this", "that", "these", "those", "them", "then", "there", "their", "with"):
                issues.append({"phoneme": "ð", "word": word, **L1_PROBLEMS["ð"]})
            else:
                issues.append({"phoneme": "θ", "word": word, **L1_PROBLEMS["θ"]})

    # Words with "w" sound (often pronounced as "v" by Germans)
    w_words = ["what", "when", "where", "why", "which", "would", "was", "were",
               "will", "with", "want", "work", "way", "well", "world"]
    for word in w_words:
        if word in text_lower:
            issues.append({"phoneme": "w", "word": word, **L1_PROBLEMS["w"]})

    # Deduplicate by phoneme (only report each phoneme once)
    seen = set()
    unique = []
    for issue in issues:
        key = issue["phoneme"]
        if key not in seen:
            seen.add(key)
            unique.append(issue)

    return unique[:5]  # Max 5 issues per analysis


def update_pronunciation_profile(analysis_result):
    """Accumulate pronunciation analysis results over time."""
    if not analysis_result.get("available"):
        return

    try:
        profile = {}
        if os.path.exists(ANALYSIS_PATH):
            with open(ANALYSIS_PATH) as f:
                profile = json.load(f)
    except Exception:
        profile = {}

    # Accumulate word scores
    word_history = profile.get("word_history", {})
    for ws in analysis_result.get("word_scores", []):
        word = ws["word"]
        if word not in word_history:
            word_history[word] = {"scores": [], "count": 0}
        word_history[word]["scores"].append(ws["confidence"])
        word_history[word]["scores"] = word_history[word]["scores"][-20:]  # keep last 20
        word_history[word]["count"] += 1
    profile["word_history"] = word_history

    # Track L1 issues frequency
    l1_freq = profile.get("l1_issue_frequency", {})
    for issue in analysis_result.get("l1_issues", []):
        ph = issue["phoneme"]
        l1_freq[ph] = l1_freq.get(ph, 0) + 1
    profile["l1_issue_frequency"] = l1_freq

    # Overall clarity trend
    clarity_history = profile.get("clarity_history", [])
    if analysis_result.get("overall_clarity"):
        clarity_history.append(analysis_result["overall_clarity"])
        clarity_history = clarity_history[-100:]  # last 100
    profile["clarity_history"] = clarity_history

    # Save
    try:
        import math
        def sanitize(obj):
            if hasattr(obj, 'item'):
                obj = obj.item()
            if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                return 0.0
            if isinstance(obj, dict):
                return {k: sanitize(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [sanitize(v) for v in obj]
            return obj

        clean = sanitize(profile)
        serialized = json.dumps(clean, indent=2)
        tmp = ANALYSIS_PATH + ".tmp"
        with open(tmp, "w") as f:
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ANALYSIS_PATH)
    except Exception as e:
        logger.warning("[pronunciation] profile save failed: %s", e)


def get_pronunciation_report():
    """Get a summary report of pronunciation patterns."""
    try:
        if not os.path.exists(ANALYSIS_PATH):
            return {"available": False, "message": "No pronunciation data yet"}
        with open(ANALYSIS_PATH) as f:
            profile = json.load(f)
    except Exception:
        return {"available": False}

    # Words consistently below threshold
    problem_words = []
    for word, data in profile.get("word_history", {}).items():
        scores = data.get("scores", [])
        if len(scores) >= 3:
            avg = sum(scores) / len(scores)
            if avg < 0.7:
                problem_words.append({"word": word, "avg_clarity": round(avg, 2), "samples": len(scores)})

    problem_words.sort(key=lambda x: x["avg_clarity"])

    # Clarity trend
    clarity = profile.get("clarity_history", [])
    trend = "improving" if len(clarity) >= 10 and sum(clarity[-5:]) / 5 > sum(clarity[:5]) / 5 else "stable"

    # L1 issues
    l1 = profile.get("l1_issue_frequency", {})

    return {
        "available": True,
        "problem_words": problem_words[:10],
        "clarity_trend": trend,
        "avg_clarity": round(sum(clarity) / len(clarity), 3) if clarity else 0,
        "total_analyses": len(clarity),
        "l1_issues": {ph: {"count": cnt, **L1_PROBLEMS.get(ph, {})} for ph, cnt in sorted(l1.items(), key=lambda x: -x[1])},
    }
