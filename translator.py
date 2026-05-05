# translator.py
"""Translate text via DeepL API Free."""

import json
import urllib.request
import urllib.parse

DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"


class Translator:
    def __init__(self, api_key: str = ""):
        # Priority: explicit api_key arg > Keychain > config.json fallback > none
        self._explicit_key = api_key
        self._cached_key: str | None = None
        self._store = None

    def _get_key(self) -> str:
        if self._explicit_key:
            return self._explicit_key
        if self._cached_key is not None:
            return self._cached_key

        # Try Keychain
        try:
            from keys import KeyStore, KeyNotFound
            if self._store is None:
                self._store = KeyStore()
            try:
                key = self._store.get("deepl")
                self._cached_key = key
                return key
            except KeyNotFound:
                pass
        except Exception:
            # keys.py or helper unavailable — fall through to config.json
            pass

        # Fall back to config.json (legacy path; will be deprecated after Phase 6)
        try:
            import os
            cfg_path = os.path.expanduser("~/.voicetype/config.json")
            if os.path.exists(cfg_path):
                with open(cfg_path) as f:
                    cfg = json.load(f)
                key = cfg.get("deepl_api_key", "")
                if key:
                    self._cached_key = key
                    return key
        except Exception:
            pass

        self._cached_key = ""
        return ""

    def translate(self, text: str, target_lang: str) -> str:
        """Translate text to target_lang (e.g. 'ES', 'FR'). Returns translated text."""
        if not self._get_key():
            return text  # no-op when no key configured
        return self._call_deepl(text, target_lang)

    def translate_auto(self, text: str, preferred_lang: str) -> tuple[str, str]:
        """Auto-detect source language. If source matches preferred_lang, translate to EN instead.
        Returns (translated_text, detected_source_lang)."""
        if not self._get_key():
            return text, ""  # no-op when no key configured
        # First, detect by translating to EN
        result = self._call_deepl_raw(text, "EN-US")
        detected = result.get("detected_source_language", "")
        translated = result.get("text", text)

        # If it's already English, translate to the preferred language instead
        if detected == "EN" and preferred_lang != "EN":
            return self._call_deepl(text, preferred_lang), "EN"

        return translated, detected

    def _call_deepl(self, text: str, target_lang: str) -> str:
        result = self._call_deepl_raw(text, target_lang)
        return result.get("text", text)

    def _call_deepl_raw(self, text: str, target_lang: str) -> dict:
        data = json.dumps({
            "text": [text],
            "target_lang": target_lang,
        }).encode("utf-8")

        req = urllib.request.Request(
            DEEPL_FREE_URL,
            data=data,
            headers={
                "Authorization": f"DeepL-Auth-Key {self._get_key()}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
            t = result["translations"][0]
            return {"text": t["text"], "detected_source_language": t.get("detected_source_language", "")}
        except Exception as e:
            print(f"Translation failed: {e}", flush=True)
            return {"text": text, "detected_source_language": ""}
