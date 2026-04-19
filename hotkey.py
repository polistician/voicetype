# hotkey.py
"""Global hotkey + paste via native Swift .app bundle."""

import subprocess
import threading
import os

HELPER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "VoxType.app", "Contents", "MacOS", "hotkey_helper"
)


class HotkeyListener:
    def __init__(self, on_start, on_stop, on_translate=None, on_open_overlay=None):
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_translate = on_translate
        self.on_open_overlay = on_open_overlay
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
        for line in self._proc.stdout:
            line = line.strip()
            if line == "READY":
                print("Hotkey listener active (Option+C dictate, Option+T translate)", flush=True)
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
            elif line == "PASTED":
                print("Paste confirmed", flush=True)
