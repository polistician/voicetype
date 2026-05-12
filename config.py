# config.py
import json
import os

DEFAULT_CONFIG = {
    "model": "large-v3-turbo",
    "model_dir": os.path.expanduser("~/voicetype/models"),
    "sample_rate": 16000,
    "min_audio_seconds": 0.15,
    "deepl_api_key": "",
    "output_language": "EN",
    # Input-side language: "auto" → Whisper detects per clip (multilingual).
    # Set to ISO code ("en", "de", "es", ...) to pin a specific language.
    # The old "language=en" hard-pin caused non-English dictation to be
    # silently translated; "auto" preserves the user's actual words.
    "input_language": "auto",
    # Transcriber backend selection.
    # "auto"        — pick_default_backend resolves: today this is whispercpp
    # "whispercpp"  — pywhispercpp on Metal (fastest on M-series)
    # "whisperkit"  — WhisperKit on Apple Neural Engine. Slower per-call than
    #                 whisper.cpp on M-series, but dramatically more accurate
    #                 on multilingual (German/Spanish/French) and produces
    #                 proper capitalization + punctuation. Worth it if your
    #                 dictation is mostly non-English.
    "transcriber_backend": "auto",
    # Streaming transcription: decode chunks in the background while the user
    # is still speaking, so only the final tail needs decoding on release.
    # For an M4 Pro with large-v3-turbo this cuts perceived latency by ~10×
    # on long clips with no accuracy regression (prompt carryover + LA2).
    "streaming_enabled": True,
    # Beam-search verifier on release. Re-decodes the entire clip with beam
    # search and swaps in that result when it disagrees substantially with
    # the streamed text. Default OFF because the streaming path (with
    # overlap-merge + phrase-repeat dedup) now matches or beats offline
    # accuracy on English (benchmarked 0–8% WER vs 7–11% offline) and the
    # verifier doubles latency. Flip on for paranoid mode or when accuracy
    # in the target language is unstable.
    "verifier_enabled": False,
    "verifier_min_duration_s": 8.0,
    "verifier_beam_size": 5,
    # When True, the Fix surface falls back to `claude -p` for free-text
    # descriptions the regex parser can't handle. Uses the user's existing
    # Claude Code sign-in (no API key). Default off — opt-in.
    "use_claude_cli_for_fix": False,
    # If False, clipboard is set but ⌘V is not synthesized — user pastes manually.
    "auto_paste": True,
    # When True, transcripts are sent to ChatGPT via Integrator for cleanup
    # (remove "um"s, fix punctuation, restructure rambling) before pasting.
    # Audio never leaves the machine — only the transcribed text. Default off.
    # Pair the user's Integrator account first via Settings or
    # `python -m integrator_chat connect`.
    "ai_cleanup_enabled": False,
    # EXPERIMENTAL: LLM post-correction via Phi-3-mini (local, ~2GB model).
    # When True, downloads Phi-3-mini-Q4 to ~/.voicetype/models/llm/ on first use
    # and runs it after Whisper + rule-based corrections. Adds ~500ms latency.
    # Enable in Settings → Experimental, or set directly here.
    # Requires llama-cpp-python (optional dep, NOT in install.sh):
    #   pip install llama-cpp-python
    "use_llm_correction": False,
}

LANGUAGES = {
    "EN": "English (no translation)",
    "ES": "Spanish",
    "FR": "French",
    "PT-BR": "Portuguese",
    "DE": "German",
    "IT": "Italian",
    "JA": "Japanese",
    "ZH": "Chinese",
}

CONFIG_PATH = os.path.expanduser("~/.voicetype/config.json")


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            user = json.load(f)
        config.update(user)
    return config


def save_default_config():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
