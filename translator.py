# translator.py
"""Translate text via DeepL API Free."""

import json
import urllib.request
import urllib.parse

DEEPL_FREE_URL = "https://api-free.deepl.com/v2/translate"


class Translator:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def translate(self, text: str, target_lang: str) -> str:
        """Translate text to target_lang (e.g. 'ES', 'FR'). Returns translated text."""
        return self._call_deepl(text, target_lang)

    def translate_auto(self, text: str, preferred_lang: str) -> tuple[str, str]:
        """Auto-detect source language. If source matches preferred_lang, translate to EN instead.
        Returns (translated_text, detected_source_lang)."""
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
                "Authorization": f"DeepL-Auth-Key {self.api_key}",
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
