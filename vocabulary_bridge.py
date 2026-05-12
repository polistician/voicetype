"""Python ↔ Swift bridge for the Vocabulary panel helper.

Mirrors the architecture of overlay_bridge.SettingsBridge / OverlayBridge:
spawn the Swift helper as a subprocess once per app run, send line-JSON
events to its stdin, read line-JSON events from its stdout, route them to
``vocabulary.py`` accessors.

The bridge holds no domain state — it's a thin event translator. All
truth lives in ``~/.voicetype/vocabulary.json`` via ``vocabulary.py``.

Wire protocol — see vocabulary_window.swift's top-of-file comment.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Callable, Optional

import vocabulary
from paths import helper_path as _resolve_helper


HELPER_PATH = _resolve_helper("vocabulary_window")


class VocabularyBridge:
    """Spawns vocabulary_window helper and routes its events.

    on_vocab_changed: callback fired whenever the vocab store changes
    (add/remove/update/dump). Voxtype passes a function that calls
    ``_refresh_whisper_vocab`` so the backend's prompt updates without
    a daemon restart.
    """

    def __init__(self, on_vocab_changed: Optional[Callable[[], None]] = None):
        self.on_vocab_changed = on_vocab_changed
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None

    def start(self) -> bool:
        if not os.path.isfile(HELPER_PATH):
            print(f"[vocab] helper not built at {HELPER_PATH}", flush=True)
            return False
        self._proc = subprocess.Popen(
            [HELPER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name="vocab-bridge")
        self._reader.start()
        return True

    def open_window(self) -> None:
        self._send({"type": "open"})
        # Push current state right away so the window doesn't flash empty.
        self._push_state()

    def close_window(self) -> None:
        self._send({"type": "close"})

    # ── outgoing ─────────────────────────────────────────────────────────

    def _send(self, msg: dict) -> None:
        if not self._proc or not self._proc.stdin:
            return
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    def _push_state(self) -> None:
        """Send a fresh snapshot of vocab + suggestions to the helper."""
        self._send({
            "type": "vocab_state",
            "words": vocabulary.list_all(),
            "suggestions": vocabulary.suggest_from_profile(),
        })

    # ── incoming ─────────────────────────────────────────────────────────

    def _read_loop(self) -> None:
        if not self._proc or not self._proc.stdout:
            return
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                print(f"[vocab] non-JSON line: {line}", flush=True)
                continue
            try:
                self._handle(msg)
            except Exception as e:
                print(f"[vocab] handler error: {e}", flush=True)

    def _handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "refresh":
            self._push_state()
            return
        if t == "add":
            ok = vocabulary.add(
                msg.get("canonical", ""), msg.get("alias") or None,
            )
            if ok:
                self._after_change()
            return
        if t == "add_many":
            words = msg.get("words") or []
            n = vocabulary.add_many(list(words))
            if n:
                self._after_change()
            return
        if t == "paste_dump":
            text = msg.get("text", "") or ""
            candidates = vocabulary.extract_proper_nouns(text)
            n = vocabulary.add_many(candidates)
            print(f"[vocab] paste-dump extracted {len(candidates)} candidates, "
                  f"{n} added", flush=True)
            if n:
                self._after_change()
            return
        if t == "update":
            ok = vocabulary.update(
                msg.get("old", ""), msg.get("new", ""), msg.get("alias") or None,
            )
            if ok:
                self._after_change()
            return
        if t == "remove":
            ok = vocabulary.remove(msg.get("canonical", ""))
            if ok:
                self._after_change()
            return
        if t == "dismiss_suggestion":
            vocabulary.dismiss_suggestion(msg.get("raw", ""))
            self._push_state()
            return
        if t == "accept_suggestion":
            raw = msg.get("raw", "")
            canonical = msg.get("canonical", "")
            if canonical:
                vocabulary.add(canonical)
                vocabulary.dismiss_suggestion(raw)
                self._after_change()
            return
        if t == "window_closed":
            return

    def _after_change(self) -> None:
        """Re-snapshot and notify voxtype to re-prime Whisper's prompt."""
        self._push_state()
        if self.on_vocab_changed:
            try:
                self.on_vocab_changed()
            except Exception as e:
                print(f"[vocab] on_vocab_changed callback failed: {e}", flush=True)
