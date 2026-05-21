# paster.py
# Paste is now handled by hotkey_helper via HotkeyListener.paste()
# This module is kept for API compatibility but delegates to the helper.


class Paster:
    def __init__(self):
        self._hotkey = None

    def set_hotkey(self, hotkey):
        """Link to the HotkeyListener that handles pasting."""
        self._hotkey = hotkey

    def paste(self, text: str):
        if not text or not self._hotkey:
            return
        self._hotkey.paste(text)

    def set_clipboard_only(self, text: str):
        """Write to clipboard without synthesizing Cmd+V (manual-paste mode).

        LANG=en_US.UTF-8 forces pbcopy to treat stdin as UTF-8. When VoiceType
        is launched as a .app, the process inherits no LANG/LC_* vars and
        pbcopy falls back to MacRoman — silently mangling umlauts and any
        non-ASCII text (German ö → √∂, French é → √©, etc.).
        """
        import os
        import subprocess
        env = {**os.environ, "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"}
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), env=env, check=False, timeout=2)
        except Exception:
            pass
