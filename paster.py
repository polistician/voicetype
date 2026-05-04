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
