# paster.py
import subprocess
import time

class Paster:
    def _get_clipboard(self) -> str:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        return result.stdout

    def _set_clipboard(self, text: str):
        subprocess.run(["pbcopy"], input=text, text=True)

    def _cmd_v(self):
        subprocess.run([
            "osascript", "-e",
            'tell application "System Events" to keystroke "v" using command down'
        ])

    def paste(self, text: str):
        """Paste text into the focused app, then restore clipboard."""
        if not text:
            return
        old_clipboard = self._get_clipboard()
        self._set_clipboard(text)
        time.sleep(0.05)  # small delay for clipboard to settle
        self._cmd_v()
        time.sleep(0.1)  # wait for paste to complete
        self._set_clipboard(old_clipboard)
