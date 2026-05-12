"""Python ↔ Swift bridge for the Quick Fix floating bar.

Triggered by ⌥⇧V. Shows the last transcript as word chips, lets the user
click a wrong word and type the right spelling. The fix lands in two
places:

    1. vocabulary.json  — Whisper biases toward the correct word on
       future dictations.
    2. corrections.json — text-level rewrite for any future occurrence
       Whisper still produces wrong (catches the misspelling even before
       vocab bias takes effect on subsequent dictations).

Same subprocess + JSON-stdio pattern as the rest of the Swift helpers.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Callable, Optional

import vocabulary
from paths import helper_path as _resolve_helper


HELPER_PATH = _resolve_helper("quickfix_bar")
CORRECTIONS_PATH = os.path.expanduser("~/.voicetype/corrections.json")


def _load_corrections() -> dict[str, str]:
    if not os.path.isfile(CORRECTIONS_PATH):
        return {}
    try:
        with open(CORRECTIONS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_corrections(d: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(CORRECTIONS_PATH), exist_ok=True)
    tmp = CORRECTIONS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CORRECTIONS_PATH)


class QuickFixBridge:
    """Spawns quickfix_bar helper subprocess, routes its events.

    on_fix_saved: callback fired after a successful fix is persisted, so
    voxtype can re-prime Whisper's prompt with the new vocab word.
    """

    def __init__(self, on_fix_saved: Optional[Callable[[], None]] = None):
        self.on_fix_saved = on_fix_saved
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None

    def start(self) -> bool:
        if not os.path.isfile(HELPER_PATH):
            print(f"[quickfix] helper not built at {HELPER_PATH}", flush=True)
            return False
        self._proc = subprocess.Popen(
            [HELPER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True,
                                        name="quickfix-bridge")
        self._reader.start()
        return True

    def open_with(self, transcript: str) -> None:
        self._send({"type": "open", "text": transcript})

    def _send(self, msg: dict) -> None:
        if not self._proc or not self._proc.stdin:
            return
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

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
                print(f"[quickfix] non-JSON line: {line}", flush=True)
                continue
            try:
                self._handle(msg)
            except Exception as e:
                print(f"[quickfix] handler error: {e}", flush=True)

    def _handle(self, msg: dict) -> None:
        t = msg.get("type")
        if t == "fix":
            wrong = (msg.get("wrong") or "").strip()
            correct = (msg.get("correct") or "").strip()
            if not wrong or not correct:
                return
            # 1) Add the correct spelling to vocabulary (Whisper bias)
            added = vocabulary.add(correct)
            # 2) Add a text-level correction rule. apply_corrections() lowercases
            #    on lookup, so storing the wrong form lowercased is safe.
            corr = _load_corrections()
            corr[wrong.lower()] = correct
            _save_corrections(corr)
            print(f"[quickfix] {wrong} → {correct}  (vocab+={int(added)})",
                  flush=True)
            if self.on_fix_saved:
                try:
                    self.on_fix_saved()
                except Exception as e:
                    print(f"[quickfix] on_fix_saved failed: {e}", flush=True)
            return
        if t == "closed":
            return
