"""WhisperKit backend — Apple Neural Engine acceleration via subprocess bridge.

Architecture
------------
WhisperKit is a Swift library; we wrap it in a Swift binary (whisperkit_helper)
and talk to it over stdin/stdout JSON. Same pattern as overlay_bridge,
settings_window, onboarding.

Why a subprocess rather than a PyObjC bridge:
- WhisperKit's runtime is CoreML + ANE; PyObjC would need to marshal MLMultiArray
  buffers across the Python/Objective-C boundary, which is messy and fragile.
- Subprocess gives us crash-isolation: if WhisperKit segfaults, voxtype.py
  catches the helper EOF and falls back to WhisperCppBackend transparently.
- Same pattern as our other Swift helpers — one less concept in the codebase.

Cold start: ~130s for first ``load`` while CoreML compiles ANE kernels.
After load, transcribe latency is comparable to whisper.cpp at ~RTF 0.2 on M4.
Warm-cache transcribe is faster, but the first clip after launch pays the
kernel-compilation cost.

See ``docs/SPEC-v0.13-whisperkit.md`` § 5 for the full architecture.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import threading
import time
import queue as _queue
from typing import Any

import numpy as np

from paths import helper_path as _resolve_helper
from transcriber_backend import RichResult


HELPER_PATH = _resolve_helper("whisperkit_helper")


class WhisperKitHelperError(Exception):
    """Raised when the helper subprocess returns an explicit error or dies."""


class WhisperKitBackend:
    """``TranscriberBackend`` impl backed by the WhisperKit Swift subprocess.

    Lifecycle:
        b = WhisperKitBackend(model_path="/.../whisperkit/openai_whisper-large-v3_turbo")
        b.load()                            # spawns helper, sends 'load'
        b.set_language("auto")
        b.set_vocabulary([...])
        text = b.transcribe(audio, language="auto")
        b.unload()                          # terminates helper

    Thread safety: the helper handles one request at a time over its stdio
    pipes, so the backend serializes calls with an internal lock. The
    streaming pipeline doesn't need parallel decodes — chunks come in
    sequentially anyway.
    """

    name = "whisperkit"

    # Helper protocol — see whisperkit-helper/Sources/.../main.swift
    _LOAD_TIMEOUT_S = 240.0     # cold CoreML compilation can take ~130s
    _CALL_TIMEOUT_S = 60.0      # any single transcribe call

    def __init__(self, model_path: str):
        self.model_path = model_path
        self._vocabulary: list[str] = []
        self._prompt: str = ""
        self.language: str = "auto"

        self._proc: subprocess.Popen | None = None
        self._proc_lock = threading.Lock()
        self._call_lock = threading.Lock()
        self._next_id = 0
        self._loaded = False

        # Helper events arrive on its stdout; we read them in a single
        # reader thread and dispatch to per-call queues by id.
        self._inbox: dict[int, _queue.Queue] = {}
        self._inbox_lock = threading.Lock()
        self._async_events: _queue.Queue = _queue.Queue()  # events without an id
        self._reader_thread: threading.Thread | None = None

    # ── lifecycle ──────────────────────────────────────────────────────────

    def load(self) -> None:
        if self._loaded:
            return
        if not os.path.isfile(HELPER_PATH):
            raise WhisperKitHelperError(
                f"whisperkit_helper binary not found at {HELPER_PATH}"
            )
        if not os.path.isdir(self.model_path):
            raise WhisperKitHelperError(
                f"WhisperKit model dir not found at {self.model_path}"
            )

        # Spawn helper. text=False so we can encode JSON ourselves and
        # avoid the line-buffering quirks of text-mode subprocess.
        self._proc = subprocess.Popen(
            [HELPER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True, name="whisperkit-reader",
        )
        self._reader_thread.start()

        # Wait for "ready" event
        ev = self._async_events.get(timeout=10.0)
        if ev.get("event") != "ready":
            raise WhisperKitHelperError(f"unexpected first event: {ev}")

        # Send load
        ev = self._call({"op": "load", "model_path": self.model_path},
                        timeout=self._LOAD_TIMEOUT_S)
        if ev.get("event") != "loaded":
            raise WhisperKitHelperError(f"load failed: {ev}")
        self._loaded = True

    def is_loaded(self) -> bool:
        return self._loaded and self._proc is not None and self._proc.poll() is None

    def unload(self) -> None:
        if not self._proc:
            return
        try:
            self._call({"op": "unload"}, timeout=5.0, expect_event="unloaded")
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=2.0)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass
        self._proc = None
        self._loaded = False

    # ── configuration ─────────────────────────────────────────────────────

    def set_language(self, code: str | None) -> None:
        if not code:
            self.language = "auto"
        else:
            self.language = code.lower()
        if self.is_loaded():
            try:
                self._call({"op": "set_lang", "code": self.language},
                           timeout=2.0, expect_event="set_lang_ok")
            except Exception:
                # set_lang is best-effort; the per-call language overrides anyway.
                pass

    def set_vocabulary(self, words: list[str]) -> None:
        self._vocabulary = list(words)[:50]
        clean = [w for w in self._vocabulary if w.strip()]
        self._prompt = (
            "Words I use: " + " ".join(clean) if clean else ""
        )
        if self.is_loaded():
            try:
                self._call({"op": "set_vocab", "words": self._vocabulary},
                           timeout=2.0, expect_event="set_vocab_ok")
            except Exception:
                pass

    @property
    def base_prompt(self) -> str:
        return self._prompt or ""

    # ── inference ─────────────────────────────────────────────────────────

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]:
        if not self.is_loaded():
            return ("en", 0.0)
        try:
            ev = self._call(
                {"op": "detect", "audio_b64": _encode_audio(audio), "sr": 16000},
                timeout=10.0,
                expect_event="detect_result",
            )
            return (ev.get("code", "en"), float(ev.get("prob", 0.0)))
        except Exception:
            return ("en", 0.0)

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        initial_prompt: str = "",
        beam_size: int = 0,
        no_speech_thold: float = 0.6,
        logprob_thold: float = -1.0,
    ) -> RichResult:
        if not self.is_loaded():
            raise WhisperKitHelperError("WhisperKit backend not loaded")

        if len(audio) == 0:
            return RichResult(
                text="", segments=[], avg_confidence=0.0,
                low_confidence_words=[], duration_ms=0, words_per_minute=0,
                detected_language=None, backend=self.name,
            )

        lang = (language or self.language or "auto").lower()
        req = {
            "op": "transcribe",
            "audio_b64": _encode_audio(audio),
            "sr": 16000,
            "lang": lang,
            "prompt": initial_prompt or self._prompt or "",
            "beam_size": int(beam_size or 0),
            "no_speech_thold": float(no_speech_thold),
            "logprob_thold": float(logprob_thold),
        }
        ev = self._call(req, timeout=self._CALL_TIMEOUT_S,
                        expect_event="transcribe_result")

        # Extract low-confidence words client-side (helper doesn't compute
        # this — it gives us per-segment probabilities which we threshold).
        segments_raw = ev.get("segments", []) or []
        segments: list[dict[str, Any]] = []
        all_probs: list[float] = []
        low_conf: list[str] = []
        for s in segments_raw:
            t = (s.get("text") or "").strip()
            if not t:
                continue
            seg_out: dict[str, Any] = {"text": t}
            if "t0" in s:
                seg_out["t0"] = int(s["t0"])
            if "t1" in s:
                seg_out["t1"] = int(s["t1"])
            p = s.get("probability")
            if p is not None:
                p = float(p)
                seg_out["probability"] = round(p, 4)
                all_probs.append(p)
                if p < 0.7:
                    for w in t.split():
                        clean = w.strip(".,!?;:'\"").lower()
                        if clean and len(clean) > 1:
                            low_conf.append(clean)
            segments.append(seg_out)

        full_text = (ev.get("text") or "").strip()
        avg_conf = (
            float(ev.get("avg_confidence")) if ev.get("avg_confidence") is not None
            else (sum(all_probs) / len(all_probs) if all_probs else 0.0)
        )
        duration_ms = int(len(audio) / 16000 * 1000)
        word_count = len(full_text.split())
        wpm = int(word_count / (duration_ms / 60000)) if duration_ms > 0 else 0

        return RichResult(
            text=full_text,
            segments=segments,
            avg_confidence=round(avg_conf, 4),
            low_confidence_words=list(set(low_conf)),
            duration_ms=duration_ms,
            words_per_minute=wpm,
            detected_language=ev.get("detected_lang") or lang,
            backend=self.name,
        )

    # ── plumbing ──────────────────────────────────────────────────────────

    def _read_loop(self) -> None:
        """Stdout reader. Routes events to per-id inboxes; non-id-tagged
        events (like "ready") go to ``_async_events``."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        for raw in proc.stdout:
            if not raw:
                continue
            try:
                ev = json.loads(raw.decode("utf-8").strip())
            except json.JSONDecodeError:
                continue
            cid = ev.get("id")
            if cid is None:
                self._async_events.put(ev)
                continue
            with self._inbox_lock:
                q = self._inbox.get(int(cid))
            if q is not None:
                q.put(ev)
            else:
                # Late or untracked id — drop. (Could happen on timeout.)
                pass

    def _call(
        self,
        req: dict[str, Any],
        *,
        timeout: float,
        expect_event: str | None = None,
    ) -> dict[str, Any]:
        """Send a request and block for the matching event.

        ``expect_event``: if set, raises if the returned event's "event"
        field isn't equal. Set to None to accept anything (including
        ``error``).
        """
        with self._call_lock:
            if not self._proc or self._proc.stdin is None:
                raise WhisperKitHelperError("helper subprocess not running")
            self._next_id += 1
            cid = self._next_id
            req["id"] = cid
            q: _queue.Queue = _queue.Queue(maxsize=1)
            with self._inbox_lock:
                self._inbox[cid] = q
            try:
                line = (json.dumps(req) + "\n").encode("utf-8")
                self._proc.stdin.write(line)
                self._proc.stdin.flush()
            except (BrokenPipeError, ValueError) as e:
                raise WhisperKitHelperError(f"helper stdin closed: {e}")

            try:
                ev = q.get(timeout=timeout)
            except _queue.Empty:
                raise WhisperKitHelperError(f"helper timeout after {timeout}s")
            finally:
                with self._inbox_lock:
                    self._inbox.pop(cid, None)

            if ev.get("event") == "error":
                raise WhisperKitHelperError(ev.get("message", "unknown error"))
            if expect_event is not None and ev.get("event") != expect_event:
                raise WhisperKitHelperError(
                    f"expected {expect_event}, got {ev.get('event')}: {ev}"
                )
            return ev


def _encode_audio(audio: np.ndarray) -> str:
    """Encode float32 16-kHz PCM as base64 for the JSON wire."""
    arr = np.ascontiguousarray(audio.astype(np.float32))
    return base64.b64encode(arr.tobytes()).decode("ascii")
