# transcript_history.py
"""In-memory ring buffer of recent transcriptions.

Not persisted. Feeds the overlay's "Last dictated" capture strip so you can
turn a thing you just said into a snippet without typing it again.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class Entry:
    text: str
    timestamp: float


class History:
    def __init__(self, size: int = 10):
        self._buf: deque[Entry] = deque(maxlen=size)

    def push(self, text: str) -> None:
        if text:
            self._buf.append(Entry(text=text, timestamp=time.time()))

    def recent(self) -> list[Entry]:
        """Most-recent-first list of entries."""
        return list(reversed(self._buf))

    def most_recent(self) -> str | None:
        """Just the most recent transcript text, or None when buffer empty."""
        if not self._buf:
            return None
        return self._buf[-1].text

    def pop_most_recent(self) -> str | None:
        """Remove and return the most recent entry. Used by Tier-1 'scratch that'.
        Returns None when the buffer is empty."""
        if not self._buf:
            return None
        return self._buf.pop().text

    def clear(self) -> None:
        self._buf.clear()
