"""llm_corrector.py — Optional LLM post-correction of Whisper output.

Default OFF. When enabled in Settings, downloads Phi-3-mini-Q4 (~2GB)
to ~/.voicetype/models/llm/ and uses it to clean up Whisper output:
- Fix obvious word-level errors based on user's correction history
- Remove disfluencies (um, uh, like)
- Apply user's preferred capitalization / punctuation style

EXPERIMENTAL — adds ~500ms latency per dictation. Off by default.
"""
from __future__ import annotations

import os

LLM_MODEL_DIR = os.path.expanduser("~/.voicetype/models/llm")
LLM_MODEL_FILE = "phi-3-mini-4k-instruct-q4.gguf"
LLM_MODEL_URL = "https://huggingface.co/microsoft/Phi-3-mini-4k-instruct-gguf/resolve/main/Phi-3-mini-4k-instruct-q4.gguf"


def is_model_available() -> bool:
    return os.path.isfile(os.path.join(LLM_MODEL_DIR, LLM_MODEL_FILE))


def download_model(on_progress=None):
    """Download Phi-3-mini-Q4 to ~/.voicetype/models/llm/.
    on_progress: Optional callable(downloaded, total)."""
    import urllib.request
    os.makedirs(LLM_MODEL_DIR, exist_ok=True)
    dest = os.path.join(LLM_MODEL_DIR, LLM_MODEL_FILE)
    with urllib.request.urlopen(LLM_MODEL_URL, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(downloaded, total)
    return dest


class LLMCorrector:
    def __init__(self):
        if not is_model_available():
            raise FileNotFoundError(f"Phi-3-mini not downloaded yet. Enable LLM post-correction in Settings to download.")
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError("llama-cpp-python not installed. Install via: pip install llama-cpp-python")
        self.llm = Llama(
            model_path=os.path.join(LLM_MODEL_DIR, LLM_MODEL_FILE),
            n_ctx=2048,
            n_threads=4,
            verbose=False,
        )

    def correct(self, whisper_text: str, user_corrections: dict[str, str] | None = None,
                recent_context: list[str] | None = None) -> str:
        """Return cleaned-up version of Whisper output.

        user_corrections: optional dict of "heard X / wanted Y" mappings.
        recent_context: optional list of recent dictations for style consistency.
        """
        prompt = self._build_prompt(whisper_text, user_corrections, recent_context)
        result = self.llm(
            prompt,
            max_tokens=len(whisper_text.split()) * 2,
            temperature=0.1,
            stop=["\n\n", "</output>"],
        )
        return result["choices"][0]["text"].strip()

    def _build_prompt(self, text: str, corrections, context) -> str:
        sys = "You are a transcription cleanup assistant. Fix obvious errors but do not change meaning. Keep the user's voice. Output ONLY the cleaned text, nothing else."
        if corrections:
            corr_str = "\n".join(f'"{k}" → "{v}"' for k, v in list(corrections.items())[:20])
            sys += f"\n\nUser's known corrections:\n{corr_str}"
        return f"<|system|>\n{sys}\n<|end|>\n<|user|>\nClean up this transcript: {text}\n<|end|>\n<|assistant|>\n"
