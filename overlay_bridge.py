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


# ---------------------------------------------------------------------------
# Settings window bridge
# ---------------------------------------------------------------------------

SETTINGS_HELPER_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "settings_window",
)


def verify_deepl(key: str) -> tuple[bool, str]:
    """Check the key by hitting DeepL's /usage endpoint. Returns (ok, error_msg)."""
    if not key:
        return (False, "empty key")
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(
            "https://api-free.deepl.com/v2/usage",
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return (resp.status == 200, "")
    except urllib.error.HTTPError as e:
        return (False, f"HTTP {e.code}")
    except Exception as e:
        return (False, str(e))


class SettingsBridge:
    """Spawns the settings_window Swift helper and routes its events."""

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._reader: Optional[threading.Thread] = None

    def start(self) -> bool:
        """Spawn the helper subprocess. Returns True if spawned."""
        path = os.path.expanduser(SETTINGS_HELPER_PATH)
        if not os.path.exists(path):
            print(f"[settings] helper not built yet at {path}", flush=True)
            return False
        self._proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        return True

    def _send(self, msg: dict) -> None:
        if not self._proc or not self._proc.stdin:
            return
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError):
            pass

    def open_window(self) -> None:
        """Bring the settings window to front."""
        self._send({"type": "open"})

    def close_window(self) -> None:
        """Hide the settings window."""
        self._send({"type": "close"})

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
                print(f"[settings] non-JSON line: {line}", flush=True)
                continue
            try:
                self._handle_event(msg)
            except Exception as e:
                print(f"[settings] handler error: {e}", flush=True)

    def _handle_event(self, msg: dict) -> None:
        event_type = msg.get("type")
        account = msg.get("account", "")

        if event_type == "refresh_status":
            self._on_refresh_status(account)
        elif event_type == "verify_key":
            self._on_verify_key(account, msg.get("value", ""))
        elif event_type == "set_key":
            self._on_set_key(account, msg.get("value", ""))
        elif event_type == "delete_key":
            self._on_delete_key(account)
        elif event_type == "window_closed":
            # User closed the window — subprocess stays alive for reopening
            pass

    def _on_refresh_status(self, account: str) -> None:
        from keys import KeyStore, KeyNotFound
        try:
            KeyStore().get(account)
            present = True
        except KeyNotFound:
            present = False
        except Exception:
            present = False
        self._send({"type": "key_status", "account": account, "present": present})

    def _on_verify_key(self, account: str, value: str) -> None:
        if account == "deepl":
            ok, error = verify_deepl(value)
            msg: dict = {"type": "verify_result", "account": account, "ok": ok}
            if not ok:
                msg["error"] = error
            self._send(msg)

    def _on_set_key(self, account: str, value: str) -> None:
        from keys import KeyStore
        try:
            KeyStore().set(account, value)
            self._send({"type": "key_status", "account": account, "present": True})
        except Exception as e:
            print(f"[settings] set_key error: {e}", flush=True)

    def _on_delete_key(self, account: str) -> None:
        from keys import KeyStore, KeyNotFound
        try:
            KeyStore().delete(account)
        except KeyNotFound:
            pass
        except Exception as e:
            print(f"[settings] delete_key error: {e}", flush=True)
        self._send({"type": "key_status", "account": account, "present": False})
