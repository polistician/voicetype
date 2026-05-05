"""Keys.py — Python wrapper around keys_helper.swift for macOS Keychain.

Usage:
    store = KeyStore()
    store.set("deepl", "your-api-key")
    key = store.get("deepl")
    store.delete("deepl")
    accounts = store.list()
"""
from __future__ import annotations

import json
import os
import subprocess

from paths import helper_path as _resolve_helper


class KeyNotFound(Exception):
    pass


class KeyStoreError(Exception):
    pass


class KeyStore:
    def __init__(self, helper_path: str = None):
        if helper_path is None:
            helper_path = _resolve_helper("keys_helper")
        self.helper_path = helper_path

    def _call(self, payload: dict) -> dict:
        if not os.path.exists(self.helper_path):
            raise KeyStoreError(
                f"keys_helper not found at {self.helper_path}. "
                "Run install.sh to compile it."
            )
        line = json.dumps(payload).encode("utf-8") + b"\n"
        proc = subprocess.run(
            [self.helper_path],
            input=line,
            capture_output=True,
            timeout=5,
        )
        if proc.returncode != 0:
            raise KeyStoreError(f"helper exited {proc.returncode}: {proc.stderr.decode()}")
        try:
            return json.loads(proc.stdout.decode("utf-8").strip())
        except json.JSONDecodeError as e:
            raise KeyStoreError(f"helper returned non-JSON: {proc.stdout!r}") from e

    def set(self, account: str, value: str) -> None:
        resp = self._call({"action": "set", "account": account, "value": value})
        if not resp.get("ok"):
            raise KeyStoreError(resp.get("error", "set failed"))

    def get(self, account: str) -> str:
        resp = self._call({"action": "get", "account": account})
        if not resp.get("ok"):
            err = resp.get("error", "")
            if "not found" in err:
                raise KeyNotFound(account)
            raise KeyStoreError(err)
        return resp["value"]

    def delete(self, account: str) -> None:
        resp = self._call({"action": "delete", "account": account})
        if not resp.get("ok"):
            err = resp.get("error", "")
            if "not found" in err:
                raise KeyNotFound(account)
            raise KeyStoreError(err)

    def list(self) -> list[str]:
        resp = self._call({"action": "list"})
        if not resp.get("ok"):
            raise KeyStoreError(resp.get("error", "list failed"))
        return resp.get("accounts", [])
