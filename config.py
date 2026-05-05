# config.py
import json
import os

DEFAULT_CONFIG = {
    "model": "base.en",
    "model_dir": os.path.expanduser("~/voicetype/models"),
    "sample_rate": 16000,
    "min_audio_seconds": 0.3,
    "deepl_api_key": "",
    "output_language": "EN",
    # When True, the Fix surface falls back to `claude -p` for free-text
    # descriptions the regex parser can't handle. Uses the user's existing
    # Claude Code sign-in (no API key). Default off — opt-in.
    "use_claude_cli_for_fix": False,
    # If False, clipboard is set but ⌘V is not synthesized — user pastes manually.
    "auto_paste": True,
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
