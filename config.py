# config.py
import json
import os

DEFAULT_CONFIG = {
    "model": "base.en",
    "model_dir": os.path.expanduser("~/voxtype/models"),
    "sample_rate": 16000,
    "min_audio_seconds": 0.3,
}

CONFIG_PATH = os.path.expanduser("~/.voxtype/config.json")


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
