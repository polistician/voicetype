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

from paths import helper_path as _resolve_helper

HELPER_PATH = _resolve_helper("snippet_overlay")


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

SETTINGS_HELPER_PATH = _resolve_helper("settings_window")


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
            self._emit_setting_status("auto_paste")
        elif event_type == "verify_key":
            self._on_verify_key(account, msg.get("value", ""))
        elif event_type == "set_key":
            self._on_set_key(account, msg.get("value", ""))
        elif event_type == "delete_key":
            self._on_delete_key(account)
        elif event_type == "set_setting":
            self._on_set_setting(msg.get("key", ""), msg.get("boolValue"))
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
        self._emit_key_value(account)

    def _emit_key_value(self, account: str) -> None:
        """On window open, send the saved key value (or empty) so the field pre-populates."""
        try:
            from keys import KeyStore, KeyNotFound
            store = KeyStore()
            try:
                value = store.get(account)
            except KeyNotFound:
                value = ""
            self._send({"type": "key_value", "account": account, "value": value})
        except Exception:
            # Best effort — if Keychain access fails, just don't populate.
            # Don't log the value or raise. Window stays empty.
            pass

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

    def _on_set_setting(self, key: str, bool_value) -> None:
        """Update a boolean setting in config.json."""
        cfg_path = os.path.expanduser("~/.voicetype/config.json")
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg[key] = bool_value
        try:
            with open(cfg_path, "w") as f:
                json.dump(cfg, f, indent=2)
            print(f"[settings] set {key}={bool_value}", flush=True)
        except Exception as e:
            print(f"[settings] set_setting write error: {e}", flush=True)

    def _emit_setting_status(self, key: str) -> None:
        """Emit current setting value to the settings window."""
        cfg_path = os.path.expanduser("~/.voicetype/config.json")
        defaults = {"auto_paste": True}
        try:
            with open(cfg_path) as f:
                cfg = json.load(f)
            value = cfg.get(key, defaults.get(key, True))
        except Exception:
            value = defaults.get(key, True)
        self._send({"type": "setting_status", "key": key, "boolValue": value})


# ---------------------------------------------------------------------------
# Onboarding window bridge
# ---------------------------------------------------------------------------

ONBOARDING_HELPER_PATH = _resolve_helper("onboarding")


class OnboardingBridge:
    """Spawns the onboarding Swift helper and routes its events."""

    def __init__(self, on_complete: "Callable[[], None]"):
        self.on_complete = on_complete
        self._proc: "Optional[subprocess.Popen]" = None
        self._reader: "Optional[threading.Thread]" = None

    def start(self) -> bool:
        """Spawn the helper subprocess. Returns True if spawned."""
        path = os.path.expanduser(ONBOARDING_HELPER_PATH)
        if not os.path.exists(path):
            print(f"[onboarding] helper not built yet at {path}", flush=True)
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
        """Bring the onboarding window to front."""
        self._send({"type": "open"})

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
                print(f"[onboarding] non-JSON line: {line}", flush=True)
                continue
            try:
                self._handle_event(msg)
            except Exception as e:
                print(f"[onboarding] handler error: {e}", flush=True)

    def _handle_event(self, msg: dict) -> None:
        event_type = msg.get("type")
        account = msg.get("account", "")
        value = msg.get("value", "")
        pane = msg.get("pane", "")

        if event_type == "open_pref_pane":
            self._on_open_pref_pane(pane)
        elif event_type == "check_perms":
            # Swift checks perms directly; this is a no-op safety valve
            pass
        elif event_type == "start_tutorial":
            # Hotkey is always armed; this is informational
            pass
        elif event_type == "verify_key":
            self._on_verify_key(account, value)
        elif event_type == "save_key":
            self._on_save_key(account, value)
        elif event_type == "skip_key":
            # No-op: user chose to skip, onboarding_complete will follow
            pass
        elif event_type == "onboarding_complete":
            self._on_complete()

    def _on_open_pref_pane(self, pane: str) -> None:
        pane_map = {
            "microphone": "Privacy_Microphone",
            "accessibility": "Privacy_Accessibility",
        }
        pref_key = pane_map.get(pane, pane)
        url = f"x-apple.systempreferences:com.apple.preference.security?{pref_key}"
        subprocess.run(["open", url], check=False)

    def _on_verify_key(self, account: str, value: str) -> None:
        if account == "deepl":
            ok, error = verify_deepl(value)
            reply: dict = {"type": "key_verify_result", "ok": ok}
            if not ok:
                reply["error"] = error
            self._send(reply)

    def _on_save_key(self, account: str, value: str) -> None:
        from keys import KeyStore
        try:
            KeyStore().set(account, value)
            print(f"[onboarding] saved key for {account}", flush=True)
        except Exception as e:
            print(f"[onboarding] save_key error: {e}", flush=True)
        # Saving implies verified; confirm success so UI can advance
        self._send({"type": "key_verify_result", "ok": True})

    def _on_complete(self) -> None:
        """Write the onboarding_complete flag and notify the caller."""
        flag = os.path.expanduser("~/.voicetype/onboarding_complete")
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        try:
            with open(flag, "w") as f:
                f.write("1")
            print("[onboarding] flag written — onboarding complete", flush=True)
        except Exception as e:
            print(f"[onboarding] could not write flag: {e}", flush=True)
        try:
            self.on_complete()
        except Exception as e:
            print(f"[onboarding] on_complete callback error: {e}", flush=True)
        # Terminate the subprocess
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
