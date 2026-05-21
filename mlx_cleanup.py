"""mlx_cleanup.py — On-device cleanup via Qwen 3 0.6B on Apple Silicon (MLX).

Default OFF. When the user picks `cleanup_backend="local"` in Settings, this
module is lazy-imported. On first use it downloads the model from
Hugging Face to ~/.voicetype/models/cleanup/qwen3-0.6b-4bit/ (~400 MB, one
time) and runs inference via mlx-lm on the Apple Neural Engine.

Typical cleanup latency on an M-series Mac: ~150–400 ms for a 200-token
transcript. No network calls beyond the one-time model download.

Imports of `mlx_lm` and `huggingface_hub` happen INSIDE methods, never at
module top — PyInstaller's static analysis doesn't see them otherwise, but
this module must remain importable even when those heavyweight deps are
missing (so the dispatcher in voxtype.py can fall back gracefully).

Fallback path: if `MLX_FALLBACK_LLAMACPP=1` or `mlx_lm` import fails, this
module switches to llama-cpp-python with a Qwen3 GGUF build. Same public
interface — the caller doesn't need to branch.
"""
from __future__ import annotations

import os
from typing import Callable, Optional


MLX_MODEL_REPO = "mlx-community/Qwen3-0.6B-Instruct-4bit"
MLX_MODEL_DIR = os.path.expanduser("~/.voicetype/models/cleanup/qwen3-0.6b-4bit")

# Fallback (llama.cpp + GGUF) — Qwen3 0.6B in Q4_K_M, smaller and slower than
# MLX but works when MLX can't be loaded (e.g. PyInstaller hostile imports).
GGUF_MODEL_URL = (
    "https://huggingface.co/Qwen/Qwen3-0.6B-Instruct-GGUF/resolve/main/"
    "qwen3-0.6b-instruct-q4_k_m.gguf"
)
GGUF_MODEL_PATH = os.path.expanduser(
    "~/.voicetype/models/cleanup/qwen3-0.6b-q4km.gguf"
)


def _force_llamacpp() -> bool:
    return os.getenv("MLX_FALLBACK_LLAMACPP") == "1"


def is_model_available() -> bool:
    """True if the MLX (or GGUF fallback) model is on disk and usable."""
    if _force_llamacpp():
        return os.path.isfile(GGUF_MODEL_PATH)
    return os.path.isfile(os.path.join(MLX_MODEL_DIR, "config.json"))


def download_model(on_progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Download the MLX model from Hugging Face on first use.

    on_progress: optional callable(downloaded_bytes, total_bytes) for UI
    progress reporting. The Hugging Face snapshot API doesn't expose
    byte-granular progress, so we emit start/finish markers only.

    Returns the local path where the model lives. Raises on download failure;
    the caller catches and falls back to raw text.
    """
    if _force_llamacpp():
        return _download_gguf(on_progress)

    if on_progress:
        on_progress(0, 1)
    from huggingface_hub import snapshot_download  # heavy; lazy
    os.makedirs(MLX_MODEL_DIR, exist_ok=True)
    path = snapshot_download(MLX_MODEL_REPO, local_dir=MLX_MODEL_DIR)
    if on_progress:
        on_progress(1, 1)
    return path


def _download_gguf(on_progress: Optional[Callable[[int, int], None]]) -> str:
    import urllib.request
    os.makedirs(os.path.dirname(GGUF_MODEL_PATH), exist_ok=True)
    with urllib.request.urlopen(GGUF_MODEL_URL, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0
        with open(GGUF_MODEL_PATH, "wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress and total:
                    on_progress(downloaded, total)
    return GGUF_MODEL_PATH


class MLXCleanup:
    """Run cleanup / edit prompts against a local Qwen 3 0.6B model.

    The same instance is reused across calls — the model load is the
    expensive step (~500 ms cold), generation is ~150–400 ms for typical
    dictation lengths. Caller (voxtype._run_cleanup) lazy-inits and caches.
    """

    def __init__(self):
        if not is_model_available():
            raise FileNotFoundError(
                "Qwen 3 0.6B model not downloaded yet. "
                "Trigger download via mlx_cleanup.download_model() first."
            )
        if _force_llamacpp():
            self._impl = _LlamaCppImpl(GGUF_MODEL_PATH)
            return
        # Try MLX first; fall back to llama.cpp if mlx_lm import errors.
        try:
            self._impl = _MLXImpl(MLX_MODEL_DIR)
        except Exception as e:
            # If MLX isn't available (Intel Mac, missing dep, PyInstaller
            # bundling problem), try the GGUF fallback if the file is on disk.
            if os.path.isfile(GGUF_MODEL_PATH):
                self._impl = _LlamaCppImpl(GGUF_MODEL_PATH)
            else:
                raise RuntimeError(f"MLX unavailable and no GGUF fallback: {e}") from e

    def cleanup(self, text: str) -> str:
        from cleanup_prompts import CLEANUP_SYSTEM
        from integrator_chat import _fallback_if_mangled
        if not text or not text.strip():
            return text
        out = self._impl.generate(CLEANUP_SYSTEM, text)
        return _fallback_if_mangled(text, out, threshold=0.5)

    def edit(self, context: str, instruction: str) -> str:
        from cleanup_prompts import EDIT_SYSTEM
        from integrator_chat import _fallback_if_mangled
        if not context or not instruction:
            return context
        user_msg = f"Text:\n{context}\n\nInstruction:\n{instruction}"
        out = self._impl.generate(EDIT_SYSTEM, user_msg)
        return _fallback_if_mangled(context, out, threshold=0.3)


class _MLXImpl:
    """mlx-lm-backed implementation. Loads model into Apple unified memory."""

    def __init__(self, model_dir: str):
        from mlx_lm import load  # lazy
        self.model, self.tokenizer = load(model_dir)

    def generate(self, system: str, user: str) -> str:
        from mlx_lm import generate  # lazy
        # Qwen3 chat templates accept the same OpenAI-style role messages.
        prompt = self.tokenizer.apply_chat_template(
            [{"role": "system", "content": system},
             {"role": "user", "content": user}],
            add_generation_prompt=True,
            tokenize=False,
        )
        # max_tokens grows with input length, capped at a sane upper bound.
        max_tokens = max(64, min(1024, len(user.split()) * 4))
        out = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            verbose=False,
        )
        # Strip whitespace + wrapping quotes that some chat templates add.
        out = (out or "").strip()
        if len(out) >= 2 and out[0] == out[-1] and out[0] in ('"', "'"):
            out = out[1:-1].strip()
        return out


class _LlamaCppImpl:
    """llama-cpp-python fallback. Used on Intel Macs or when mlx_lm fails."""

    def __init__(self, model_path: str):
        from llama_cpp import Llama  # lazy
        self.llm = Llama(
            model_path=model_path,
            n_ctx=2048,
            n_threads=4,
            verbose=False,
        )

    def generate(self, system: str, user: str) -> str:
        # Use the Llama instance's chat-completions interface (mirrors OpenAI).
        max_tokens = max(64, min(1024, len(user.split()) * 4))
        resp = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=max_tokens,
        )
        try:
            out = resp["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return ""
        out = (out or "").strip()
        if len(out) >= 2 and out[0] == out[-1] and out[0] in ('"', "'"):
            out = out[1:-1].strip()
        return out
