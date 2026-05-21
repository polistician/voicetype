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
    # Cleanup backend that post-processes Whisper output before pasting.
    # Values:
    #   "off"        — no cleanup; paste raw Whisper text. Default.
    #   "integrator" — route via Integrator OAuth broker to ChatGPT.
    #   "groq"       — route via Integrator to Groq Llama 4 (free, ~150ms).
    #   "local"      — Qwen 3 0.6B via MLX, fully on-device. No network.
    # Migration: legacy `ai_cleanup_enabled: true` → "integrator", legacy
    # `use_llm_correction: true` → "local". Old keys are stripped on save.
    "cleanup_backend": "off",
    # Hold ⌥⇧C to dictate an editing instruction against the last paste
    # (e.g. "make it more formal", "turn this into bullets"). The instruction
    # is sent to the configured cleanup_backend's edit() endpoint.
    "command_mode_enabled": True,
    # Tier-1 voice-edit phrases ("scratch that", "new line", "new paragraph",
    # "undo that") auto-trigger when dictated alone, with no command-mode key.
    "voice_edit_auto_detect_enabled": True,
    # Legacy keys (read for migration, stripped on save by save_config):
    "ai_cleanup_enabled": False,
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


_LEGACY_CLEANUP_KEYS = ("ai_cleanup_enabled", "use_llm_correction")


def _migrate_cleanup_backend(user: dict, config: dict) -> None:
    """Map legacy booleans to the new unified `cleanup_backend` string.

    Runs only when the user's on-disk config has no explicit `cleanup_backend`
    yet. Legacy keys remain in the in-memory config so any external code
    still reading them keeps working; save_config() strips them on write.
    """
    if "cleanup_backend" in user:
        return
    if user.get("use_llm_correction"):
        config["cleanup_backend"] = "local"
    elif user.get("ai_cleanup_enabled"):
        config["cleanup_backend"] = "integrator"
    else:
        config["cleanup_backend"] = "off"


def load_config() -> dict:
    config = DEFAULT_CONFIG.copy()
    user: dict = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            user = json.load(f)
        config.update(user)
    _migrate_cleanup_backend(user, config)
    return config


def save_config(cfg: dict) -> None:
    """Persist config to disk, stripping deprecated keys."""
    out = {k: v for k, v in cfg.items() if k not in _LEGACY_CLEANUP_KEYS}
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(out, f, indent=2)


def save_default_config():
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
