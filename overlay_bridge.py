# overlay_bridge.py
"""Python side of the Swift snippet-overlay helper bridge.

Spawns the Swift helper as a subprocess, sends events on stdin, reads user
actions from stdout. Protocol is line-oriented JSON.

Protocol (Python → Swift):
  {"type":"OPEN","mode":"list"|"save"|"search","query":"optional","draft_body":"optional"}
  {"type":"PICKER","candidates":[{"id":1,"name":"...","score":0.71},...]}
  {"type":"SNIPPETS","items":[{"id":1,"name":"...","description":"...","body":"...","tags":"...","used_count":42}, ...]}
  {"type":"CLIPBOARD","text":"..."}
  {"type":"HISTORY","items":[{"text":"...","ts":1706000000}, ...]}
  {"type":"HIDE"}

Protocol (Swift → Python):
  {"type":"PASTE","id":1}
  {"type":"CREATE","name":"...","body":"...","description":"...","tags":"..."}
  {"type":"UPDATE","id":1,"name":"...","body":"...","description":"...","tags":"..."}
  {"type":"DELETE","id":1}
  {"type":"SEARCH","query":"..."}  # requests fresh filtered list
  {"type":"DISMISSED"}
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from typing import Callable, Optional


HELPER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "VoxType.app", "Contents", "MacOS", "snippet_overlay",
)


class OverlayBridge:
    def __init__(self, on_event: Callable[[dict], None]):
        self.on_event = on_event
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Start the helper. Returns True if it spawned; False if binary missing."""
        if not os.path.exists(HELPER_PATH):
            print(f"[overlay] helper not built yet at {HELPER_PATH}", flush=True)
            return False
        self._proc = subprocess.Popen(
            [HELPER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def send(self, msg: dict) -> None:
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
                print(f"[overlay] non-JSON line: {line}", flush=True)
                continue
            try:
                self.on_event(msg)
            except Exception as e:
                print(f"[overlay] handler error: {e}", flush=True)
