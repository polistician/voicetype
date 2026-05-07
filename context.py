"""context.py — Detect the frontmost macOS app to bias Whisper accordingly.

Used at recording start to record which app the user was in. Vocabulary
biasing then weights words that the user dictates frequently in that app.
"""
from __future__ import annotations

import subprocess
from typing import Optional


def frontmost_app() -> Optional[str]:
    """Return the bundle ID of the currently-focused app. None on failure."""
    try:
        # Use Cocoa via osascript — works without PyObjC dependency
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to get bundle identifier of (first process whose frontmost is true)'],
            capture_output=True, text=True, timeout=2,
        )
        if result.returncode == 0:
            bid = result.stdout.strip()
            if bid:
                return bid
    except Exception:
        pass
    return None


def app_short_name(bundle_id: str) -> str:
    """Return a short human-readable name from a bundle ID. Fallback: the bundle ID itself."""
    # Common mappings
    short = {
        "com.apple.Terminal": "Terminal",
        "com.googlecode.iterm2": "iTerm",
        "com.todesktop.230313mzl4w4u92":  "Cursor",
        "com.microsoft.VSCode": "VSCode",
        "com.apple.Safari": "Safari",
        "com.google.Chrome": "Chrome",
        "com.tinyspeck.slackmacgap": "Slack",
        "com.apple.mail": "Mail",
        "com.apple.MobileSMS": "Messages",
        "notion.id": "Notion",
        "com.openai.chat": "ChatGPT",
        "com.anthropic.claude": "Claude",
    }
    return short.get(bundle_id, bundle_id.split(".")[-1] if "." in bundle_id else bundle_id)
