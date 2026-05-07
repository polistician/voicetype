"""Integrator-as-IdP — opt-in ChatGPT cleanup pass for VoiceType dictation.

Sits between Whisper transcription and the paste step in `voxtype.py`. When
`ai_cleanup_enabled` is True in config, transcripts (NOT audio) are sent to
ChatGPT via Integrator for cleanup (remove "um"s, fix punctuation/casing,
restructure rambling speech) before being pasted.

Pipeline:

  1. `connect()` runs OAuth 2.1 + PKCE against https://integrator.polistician.ai
     (browser opens, user signs in, Integrator redirects to localhost:1718,
      we capture the code and exchange it for an iat_ token).
  2. Tokens (access, refresh, expiry, scope) are stored in macOS Keychain via
     the existing `keys.py` helper under account "integrator". This matches
     VoiceType's existing convention (DeepL key, etc.) — no plaintext config.
  3. `cleanup(raw_text)` POSTs to /api/v1/chat/completions with the user's
     iat_ bearer token. Integrator brokers to the user's vaulted ChatGPT
     subscription via Codex. 2-second timeout — on ANY error, returns the
     raw text unchanged. Dictation latency is sacred.

Stdlib-only (no httpx, no requests) to match VoiceType's `translator.py` /
`soma_hook.py` conventions and avoid pulling extra dependencies into the
PyInstaller bundle.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Optional

log = logging.getLogger("voicetype.integrator")


# ── Configuration ──────────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://integrator.polistician.ai"

# Public client (PKCE-only, no secret). Registered via /api/admin/apps.
DEFAULT_CLIENT_ID = "voicetype-37ca28"

# Both 127.0.0.1 and localhost must be on the app's redirect_uri allowlist.
# 1718 — distinct from MacSweep's 1717.
LOCAL_PORT = 1718
LOCAL_REDIRECT_URI = f"http://127.0.0.1:{LOCAL_PORT}/auth/callback"

DEFAULT_SCOPES = ("chatgpt:chat",)

# How early before expiry we treat the access token as stale and refresh.
REFRESH_SKEW_S = 60

# Keychain account name where we stash the JSON-serialized token bundle.
_KEYCHAIN_ACCOUNT = "integrator"


# ── Keychain-backed state ──────────────────────────────────────────────────
#
# VoiceType stores secrets in macOS Keychain via `keys.py` (which shells out
# to a compiled Swift helper). We piggyback on that for tokens too. The full
# bundle (access_token, refresh_token, expires_at, scope, base_url, client_id,
# user_email, paired_at) is JSON-encoded into a single Keychain entry.


def _keystore():
    """Lazy import so import-time doesn't fail when running tests / CLI in a
    bare environment without the helper compiled. Returns a KeyStore instance
    or raises IntegratorError."""
    try:
        from keys import KeyStore  # type: ignore
    except Exception as e:
        raise IntegratorError(f"keys.py unavailable: {e}") from None
    return KeyStore()


def _read() -> dict:
    """Load the token bundle from Keychain. Returns {} if not paired."""
    try:
        from keys import KeyNotFound  # type: ignore
    except Exception:
        return {}
    try:
        store = _keystore()
        raw = store.get(_KEYCHAIN_ACCOUNT)
    except IntegratorError:
        return {}
    except KeyNotFound:
        return {}
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _write(state: dict) -> None:
    """Persist the token bundle to Keychain as JSON."""
    store = _keystore()
    store.set(_KEYCHAIN_ACCOUNT, json.dumps(state))


def _clear() -> None:
    """Remove the token bundle from Keychain."""
    try:
        from keys import KeyNotFound  # type: ignore
    except Exception:
        return
    try:
        store = _keystore()
        store.delete(_KEYCHAIN_ACCOUNT)
    except (IntegratorError, KeyNotFound):
        pass
    except Exception:
        pass


# ── PKCE primitives ────────────────────────────────────────────────────────


def _make_pkce() -> tuple[str, str]:
    """Returns (verifier, challenge_S256). Verifier kept locally, challenge
    sent to /oauth/authorize."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── HTTP helper (stdlib, no extra deps) ────────────────────────────────────

# Cloudflare in front of integrator.polistician.ai blocks Python's default
# urllib User-Agent (returns 403 / error 1010). Send a real browser-ish UA
# on every request so we look like any other client.
_DEFAULT_UA = "Mozilla/5.0 (VoiceType/1.0; +https://github.com/polistician/voicetype)"


class IntegratorError(RuntimeError):
    """Anything that prevents a chat — auth missing, refresh failed, upstream 4xx."""


def _post_form(url: str, data: dict, *, timeout: int = 20) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": _DEFAULT_UA,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode("utf-8")
        except Exception:
            err = str(e)
        raise IntegratorError(f"HTTP {e.code}: {err}") from None


def _post_json(url: str, data: dict, headers: dict, *, timeout: int = 30) -> dict:
    body = json.dumps(data).encode("utf-8")
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": _DEFAULT_UA,
        **headers,
    }
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = e.read().decode("utf-8")
        except Exception:
            err = str(e)
        raise IntegratorError(f"HTTP {e.code}: {err}") from None


def _http_get_json(url: str, headers: dict, *, timeout: int = 10) -> dict:
    h = {"User-Agent": _DEFAULT_UA, "Accept": "application/json", **headers}
    req = urllib.request.Request(url, headers=h, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Local callback server ──────────────────────────────────────────────────


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    """One-shot handler that grabs ?code=&state= from the redirect.

    Stashes results on the server instance so the main thread can read them.
    """

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/auth/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.server.captured = params  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        # Friendly success page; the user can close the tab.
        self.wfile.write(b"""
<!doctype html><html><head><meta charset=utf-8><title>VoiceType paired</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, sans-serif;
         display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; background: #0b0b0e; color: #eceded; }
  .card { max-width: 360px; padding: 32px; border: 1px solid rgba(255,255,255,.1);
          border-radius: 14px; text-align: center; }
  h1 { font-size: 22px; margin: 0 0 12px; font-weight: 600; }
  p { color: #8a8a92; margin: 0; line-height: 1.5; }
</style></head>
<body><div class=card>
  <h1>Paired with Integrator.</h1>
  <p>You can close this tab and return to VoiceType.</p>
</div></body></html>
""")

    def log_message(self, *args, **kwargs):  # silence default access logs
        pass


def _start_callback_server(port: int = LOCAL_PORT) -> http.server.HTTPServer:
    server = http.server.HTTPServer(("127.0.0.1", port), _CallbackHandler)
    server.captured = None  # type: ignore[attr-defined]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


# ── Public API ─────────────────────────────────────────────────────────────


def status() -> dict:
    """Return UI-facing snapshot. Safe to call always."""
    state = _read()
    if not state.get("access_token"):
        return {"connected": False}
    return {
        "connected": True,
        "base_url": state.get("base_url") or DEFAULT_BASE_URL,
        "client_id": state.get("client_id") or DEFAULT_CLIENT_ID,
        "scope": state.get("scope") or " ".join(DEFAULT_SCOPES),
        "expires_at": state.get("expires_at"),
        "user_email": state.get("user_email"),
    }


def is_connected() -> bool:
    return bool(_read().get("access_token"))


def disconnect() -> None:
    _clear()


def connect(
    *,
    base_url: str = DEFAULT_BASE_URL,
    client_id: str = DEFAULT_CLIENT_ID,
    scopes: tuple[str, ...] = DEFAULT_SCOPES,
    open_browser: bool = True,
    timeout_s: int = 300,
) -> dict:
    """Run the OAuth dance against Integrator. Blocks until done or timeout.

    Returns the final state dict. On error raises IntegratorError.

    If `open_browser=False`, the function prints the auth URL and waits — the
    caller can render that URL themselves (used by tests + CLI in 'manual' mode).
    """
    # Refuse if the port is busy — almost always means another VoiceType run
    # didn't clean up. Surface clearly.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", LOCAL_PORT))
    except OSError:
        raise IntegratorError(
            f"port {LOCAL_PORT} is already in use — close the other VoiceType "
            "instance or wait 30s for the old one to release the port"
        )
    finally:
        sock.close()

    verifier, challenge = _make_pkce()
    state = secrets.token_urlsafe(32)

    auth_url = (
        f"{base_url.rstrip('/')}/oauth/authorize?"
        + urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": LOCAL_REDIRECT_URI,
                "scope": " ".join(scopes),
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    server = _start_callback_server(LOCAL_PORT)
    try:
        if open_browser:
            opened = webbrowser.open(auth_url)
            if not opened:
                log.warning("could not open browser; paste this URL: %s", auth_url)
        else:
            print(auth_url)

        # Poll until the callback fires or we time out.
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            captured = getattr(server, "captured", None)
            if captured:
                break
            time.sleep(0.2)
        else:
            raise IntegratorError("timed out waiting for OAuth callback")

        captured = server.captured  # type: ignore[attr-defined]
        if "error" in captured:
            raise IntegratorError(
                f"oauth error: {captured.get('error')}: "
                f"{captured.get('error_description', '')}"
            )

        if captured.get("state") != state:
            raise IntegratorError("state mismatch — possible CSRF; re-run connect")

        code = captured.get("code")
        if not code:
            raise IntegratorError("callback missing code parameter")

        # Exchange code → tokens.
        token_resp = _post_form(
            f"{base_url.rstrip('/')}/oauth/token",
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": LOCAL_REDIRECT_URI,
                "code_verifier": verifier,
                "client_id": client_id,
            },
        )

        access_token = token_resp.get("access_token")
        refresh_token = token_resp.get("refresh_token")
        expires_in = int(token_resp.get("expires_in", 3600))
        if not access_token:
            raise IntegratorError(f"token endpoint missing access_token: {token_resp}")

        new_state = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": int(time.time()) + expires_in,
            "scope": token_resp.get("scope") or " ".join(scopes),
            "base_url": base_url,
            "client_id": client_id,
            "paired_at": int(time.time()),
        }

        # Best-effort: enrich with the user's email from /api/auth/me. Skip on
        # failure — Integrator may not expose this anonymously.
        try:
            me = _http_get_json(
                f"{base_url.rstrip('/')}/api/auth/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if isinstance(me, dict) and me.get("email"):
                new_state["user_email"] = me["email"]
        except Exception:
            pass

        _write(new_state)
        return status()
    finally:
        server.shutdown()


def _refresh_if_needed() -> str:
    """Return a fresh access_token; refresh in place if near expiry. Raises
    IntegratorError if no refresh_token or refresh fails."""
    state = _read()
    if not state.get("access_token"):
        raise IntegratorError("not paired — run `python -m integrator_chat connect` first")

    expires_at = int(state.get("expires_at") or 0)
    if expires_at and (expires_at - int(time.time())) > REFRESH_SKEW_S:
        return state["access_token"]

    refresh_token = state.get("refresh_token")
    if not refresh_token:
        raise IntegratorError("access token expired and no refresh_token on file")

    base_url = state.get("base_url") or DEFAULT_BASE_URL
    client_id = state.get("client_id") or DEFAULT_CLIENT_ID

    body = _post_form(
        f"{base_url.rstrip('/')}/oauth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
    )
    new_access = body.get("access_token")
    if not new_access:
        raise IntegratorError(f"refresh missing access_token: {body}")

    state["access_token"] = new_access
    state["refresh_token"] = body.get("refresh_token") or refresh_token
    state["expires_at"] = int(time.time()) + int(body.get("expires_in", 3600))
    _write(state)
    return new_access


def chat(
    messages: list[dict],
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 512,
    response_format: Optional[dict] = None,
    timeout_s: int = 30,
) -> dict:
    """Call Integrator's chat-completions endpoint. Returns the parsed JSON
    response (OpenAI-compatible: `{choices: [{message: {content: ...}}], ...}`).

    Auto-refreshes the access token if expired. Raises IntegratorError on any
    upstream failure.
    """
    state = _read()
    if not state.get("access_token"):
        raise IntegratorError("not paired — run `python -m integrator_chat connect` first")

    base_url = state.get("base_url") or DEFAULT_BASE_URL
    token = _refresh_if_needed()

    body: dict = {
        "messages": messages,
        "stream": False,
        "max_tokens": max_tokens,
    }
    if model:
        body["model"] = model
    if temperature is not None:
        body["temperature"] = temperature
    if response_format:
        body["response_format"] = response_format

    try:
        return _post_json(
            f"{base_url.rstrip('/')}/api/v1/chat/completions",
            body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_s,
        )
    except IntegratorError as e:
        # If the broker says 401 once, our cached access_token is stale beyond
        # what expires_at indicated — force a refresh and retry once.
        if "HTTP 401" in str(e):
            log.info("integrator chat 401 — forcing refresh and retrying once")
            state["expires_at"] = 0
            _write(state)
            token = _refresh_if_needed()
            return _post_json(
                f"{base_url.rstrip('/')}/api/v1/chat/completions",
                body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout_s,
            )
        raise


def chat_json(
    *,
    system: str,
    user: str,
    max_tokens: int = 512,
    temperature: float = 0.2,
    model: Optional[str] = None,
) -> Optional[dict]:
    """JSON-mode wrapper. Returns the parsed JSON object the model produced,
    or None on parse failure."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    resp = chat(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        log.warning("chat_json: model did not return valid JSON: %.200s", content)
        return None


# ── VoiceType-specific helper ──────────────────────────────────────────────


_CLEANUP_SYSTEM = (
    "You clean up dictation transcripts. Given a raw Whisper transcript:\n"
    "  • Remove disfluencies (um, uh, like, you know, sort of, kind of).\n"
    "  • Fix punctuation and capitalization.\n"
    "  • Restructure obviously rambling sentences into clear ones.\n"
    "  • Preserve the speaker's intent, tone, and word choice.\n"
    "  • Keep technical terms, names, and proper nouns exactly as transcribed.\n"
    "  • If the input is already clean, return it unchanged.\n"
    "Reply with ONLY the cleaned text — no preamble, no quotes, no explanation."
)


def cleanup(raw_text: str, *, timeout_s: float = 2.0) -> str:
    """Clean up a dictation transcript via Integrator.

    Always degrades gracefully: if not connected, network is down, the call
    times out, or the response is malformed, returns `raw_text` unchanged.
    Dictation latency is sacred — never raise to the caller.
    """
    text = (raw_text or "").strip()
    if not text:
        return raw_text
    if not is_connected():
        return raw_text
    try:
        # urlopen wants an int timeout; round up the float.
        upstream_timeout = max(1, int(round(timeout_s)))
        resp = chat(
            [
                {"role": "system", "content": _CLEANUP_SYSTEM},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=max(64, len(text.split()) * 4),
            timeout_s=upstream_timeout,
        )
    except Exception as e:
        log.warning("integrator cleanup failed: %s — falling back to raw", e)
        return raw_text
    try:
        cleaned = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        log.warning("integrator cleanup: malformed response — falling back to raw")
        return raw_text
    if not isinstance(cleaned, str):
        return raw_text
    cleaned = cleaned.strip()
    # Strip wrapping quotes models sometimes add despite the prompt.
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()
    return cleaned or raw_text


# ── CLI: `python -m integrator_chat <cmd>` ─────────────────────────────────


def _cli(argv: list[str]) -> int:
    cmd = (argv[0] if argv else "status").lower()
    if cmd == "connect":
        try:
            print(json.dumps(connect(), indent=2))
            print("\n✓ paired. Try: python -m integrator_chat test \"um so like make me a button\"")
            return 0
        except IntegratorError as e:
            print(f"✗ {e}")
            return 1
    if cmd == "disconnect":
        disconnect()
        print("✓ disconnected")
        return 0
    if cmd == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if cmd == "test":
        prompt = " ".join(argv[1:]) or "um so like make me a button that uh saves the thing"
        try:
            cleaned = cleanup(prompt, timeout_s=10.0)
            print(f"raw     : {prompt}")
            print(f"cleaned : {cleaned}")
            return 0
        except IntegratorError as e:
            print(f"✗ {e}")
            return 1
    print("usage: python -m integrator_chat {connect|disconnect|status|test [text]}")
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
