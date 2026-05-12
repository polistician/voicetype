# hotkey.py
"""Global hotkey + paste via native Swift .app bundle."""

import subprocess
import threading
import os

from paths import helper_path as _resolve_helper

HELPER_PATH = _resolve_helper("hotkey_helper")


class HotkeyListener:
    def __init__(self, on_start, on_stop, on_translate=None,
                 on_open_overlay=None, on_open_quick_fix=None):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_translate = on_translate
        self.on_open_overlay = on_open_overlay
        self.on_open_quick_fix = on_open_quick_fix
        self._proc = None

    def start(self):
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def paste(self, text: str):
        """Send text to the helper for pasting into frontmost app."""
        if self._proc and self._proc.stdin:
            clean = text.replace("\n", " ").replace("\r", "")
            self._proc.stdin.write(f"PASTE:{clean}\n")
            self._proc.stdin.flush()

    def _run(self):
        self._proc = subprocess.Popen(
            [HELPER_PATH],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Also forward helper stderr (contains ERROR: lines from registration)
        threading.Thread(target=self._read_stderr, daemon=True).start()

        for line in self._proc.stdout:
            line = line.strip()
            if line == "READY":
                print("Hotkey listener active (Option+C, Option+T, Option+Shift+S, Option+Shift+V)", flush=True)
            elif line == "START":
                self.on_start()
            elif line == "STOP":
                self.on_stop()
            elif line == "TRANSLATE":
                if self.on_translate:
                    self.on_translate()
            elif line == "OPEN_OVERLAY":
                if self.on_open_overlay:
                    self.on_open_overlay()
            elif line == "OPEN_QUICK_FIX":
                if self.on_open_quick_fix:
                    self.on_open_quick_fix()
            elif line == "PASTED":
                print("Paste confirmed", flush=True)
            elif line:
                # Forward anything else (PERMISSIONS, WARNING, etc.) so the user
                # sees diagnostic info in the VoxType log.
                print(f"[hotkey_helper] {line}", flush=True)

    def _read_stderr(self):
        if not self._proc or not self._proc.stderr:
            return
        for line in self._proc.stderr:
            line = line.rstrip()
            if line:
                print(f"[hotkey_helper stderr] {line}", flush=True)
