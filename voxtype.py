# voxtype.py
"""VoxType -- Hold Option+C to dictate, release to paste."""

import rumps
import threading
import os
from recorder import Recorder
from transcriber_v2 import TranscriberV2
from translator import Translator
from paster import Paster
from voice_profile import update as update_profile, get_whisper_prompt
from corrections import apply_corrections, seed_defaults, auto_learn_corrections
from hotkey import HotkeyListener
from config import load_config, save_default_config, LANGUAGES
from intent import route as route_intent
from snippets import Store as SnippetStore
from embedder import Embedder
from transcript_history import History as TranscriptHistory
import numpy as np


class VoxType(rumps.App):
    def __init__(self):
        super().__init__("VoxType", title="\U0001f3a4")
        self.cfg = load_config()
        save_default_config()

        self._status_item = rumps.MenuItem("Status: Idle")
        self._lang_menu = rumps.MenuItem("Output Language")
        self._build_lang_menu()

        self.menu = [self._status_item, None, self._lang_menu, None, f"Model: {self.cfg['model']}"]

        self.recorder = Recorder(sample_rate=self.cfg["sample_rate"])
        self.recording = False
        seed_defaults()  # Load domain corrections (fox→vox, etc.)
        self.output_language = self.cfg.get("output_language", "EN")

        # Set up translator if API key is configured
        api_key = self.cfg.get("deepl_api_key", "")
        self.translator = Translator(api_key) if api_key else None

        # Load model in background to not block menubar
        self._model_loaded = threading.Event()
        self.transcriber = None
        threading.Thread(target=self._load_model, daemon=True).start()

        # Start hotkey listener — also handles pasting
        self.hotkey = HotkeyListener(
            on_start=self._start_recording,
            on_stop=self._stop_recording,
            on_translate=self._translate_clipboard,
            on_open_overlay=self._open_overlay,
        )
        self.hotkey.start()

        self.paster = Paster()
        self.paster.set_hotkey(self.hotkey)

        # Snippet infrastructure — lazy init embedder to avoid blocking startup
        self.snippet_store = SnippetStore()
        self.embedder = None
        self._embedder_ready = threading.Event()
        self.snippet_cache: dict[int, np.ndarray] = {}
        self.transcript_history = TranscriptHistory(size=10)
        threading.Thread(target=self._load_embedder, daemon=True).start()

        # Overlay bridge — helper may not exist yet (built in Task 10)
        from overlay_bridge import OverlayBridge
        self.overlay = OverlayBridge(on_event=self._on_overlay_event)
        self.overlay.start()
        self.overlay_visible = False

    def _load_embedder(self):
        try:
            self.embedder = Embedder()
            self._rebuild_snippet_cache()
            self._embedder_ready.set()
            print("Embedder loaded", flush=True)
        except Exception as e:
            print(f"Embedder failed to load: {e}", flush=True)

    def _rebuild_snippet_cache(self):
        self.snippet_cache.clear()
        for s in self.snippet_store.list_all():
            if s.embedding:
                self.snippet_cache[s.id] = Embedder.blob_to_array(s.embedding, self.embedder.dim)
            else:
                # Missing embedding — compute and persist now
                vec = self.embedder.encode(f"{s.name}. {s.description}. Tags: {s.tags}")
                self.snippet_store.update(s.id, embedding=Embedder.array_to_blob(vec))
                self.snippet_cache[s.id] = vec

    def _build_lang_menu(self):
        current = self.cfg.get("output_language", "EN")
        for code, label in LANGUAGES.items():
            prefix = "\u2713 " if code == current else "   "
            item = rumps.MenuItem(f"{prefix}{label}", callback=self._on_lang_select)
            item._lang_code = code
            self._lang_menu.add(item)

    def _on_lang_select(self, sender):
        self.output_language = sender._lang_code
        # Update checkmarks
        for item in self._lang_menu.values():
            code = getattr(item, '_lang_code', None)
            if code:
                label = LANGUAGES.get(code, code)
                item.title = f"\u2713 {label}" if code == self.output_language else f"   {label}"
        mode = LANGUAGES.get(self.output_language, self.output_language)
        print(f"Output language: {mode}", flush=True)

    def _load_model(self):
        print("Loading Whisper model...", flush=True)
        model_path = os.path.join(self.cfg["model_dir"], f"ggml-{self.cfg['model']}.bin")
        self.transcriber = TranscriberV2(model_path=model_path)

        # Bias Whisper toward snippet trigger words + snippet names
        bias_words = {"snippet", "snippets", "overview", "manager", "insert", "paste", "save"}
        for s in self.snippet_store.list_all():
            for tok in s.name.split():
                if tok.isalpha() and len(tok) > 2:
                    bias_words.add(tok.lower())
        prompt = get_whisper_prompt()
        existing = set(prompt.replace("Words I use: ", "").split()) if prompt else set()
        merged = sorted(existing | bias_words)
        self.transcriber.set_vocabulary(merged)
        print(f"Loaded {len(merged)} vocabulary words (including snippet triggers)", flush=True)

        self._model_loaded.set()
        print("Model loaded!", flush=True)
        self._update_status("Idle -- ready")

    def _refresh_whisper_vocab(self):
        if not self.transcriber:
            return
        bias_words = {"snippet", "snippets", "overview", "manager", "insert", "paste", "save"}
        for s in self.snippet_store.list_all():
            for tok in s.name.split():
                if tok.isalpha() and len(tok) > 2:
                    bias_words.add(tok.lower())
        prompt = get_whisper_prompt()
        existing = set(prompt.replace("Words I use: ", "").split()) if prompt else set()
        self.transcriber.set_vocabulary(sorted(existing | bias_words))

    def _update_status(self, status):
        self._status_item.title = f"Status: {status}"

    def _start_recording(self):
        if not self._model_loaded.is_set():
            print("Model still loading, please wait...", flush=True)
            return
        if self.recording:
            # Already recording — ignore double-press
            return
        self.recording = True
        self.title = "\U0001f534"
        self._update_status("Recording...")
        self.recorder.start()
        print("Recording...", flush=True)

    def _stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.title = "\u231b"
        self._update_status("Transcribing...")
        threading.Thread(target=self._transcribe_and_paste, daemon=True).start()

    def _transcribe_and_paste(self):
        audio = self.recorder.stop()
        min_samples = int(self.cfg["min_audio_seconds"] * self.cfg["sample_rate"])
        if len(audio) < min_samples:
            self.title = "\U0001f3a4"
            self._update_status("Idle -- ready")
            return

        # Rich transcription: text + confidence + timing
        rich = self.transcriber.transcribe_rich(audio)
        text = rich["text"]

        if text:
            # 1. Apply known corrections (fox→vox, etc.)
            corrected = apply_corrections(text)
            if corrected != text:
                print(f"  [corrected] {text} → {corrected}", flush=True)
                text = corrected

            # 2. Update local voice profile (background-safe)
            try:
                update_profile(rich)
                conf = rich.get("avg_confidence", 0)
                lc = rich.get("low_confidence_words", [])
                if lc:
                    print(f"  [profile] conf={conf:.2f}, unclear: {', '.join(lc[:3])}", flush=True)
                prompt = get_whisper_prompt()
                if prompt:
                    words = prompt.replace("Words I use: ", "").split()
                    self.transcriber.set_vocabulary(words)
                auto_learn_corrections()
            except Exception:
                pass

            # 3. Pronunciation / training data — off the critical path
            audio_copy = audio.copy()
            raw_text = rich["text"]
            corrected_text = text if text != raw_text else None
            conf = rich.get("avg_confidence", 0)
            threading.Thread(target=self._background_analysis,
                             args=(audio_copy, raw_text, corrected_text, conf),
                             daemon=True).start()

            # If overlay is visible, treat speech as a search query, not dictation
            if self.overlay_visible:
                self.overlay.send({"type": "SEARCH", "query": text})
                print(f"  [overlay-search] {text}", flush=True)
                self.title = "\U0001f3a4"
                self._update_status("Idle -- ready")
                return

            # 4. Intent routing — decide whether to dictate or invoke a command
            intent = route_intent(text)
            print(f"  [intent] {intent.action} payload={intent.payload}", flush=True)

            if intent.action == "dictate":
                self.transcript_history.push(text)
                self._dictate_paste(text)
            elif intent.action == "paste_snippet":
                self._handle_paste_snippet(intent.payload.get("description", ""))
            elif intent.action == "open_overview":
                self._open_overlay()
            elif intent.action == "save_snippet":
                self._open_overlay(mode="save", from_clipboard=intent.payload.get("from_clipboard", False))

        self.title = "\U0001f3a4"
        self._update_status("Idle -- ready")


    def _translate_clipboard(self):
        """Option+T: read clipboard, auto-detect language, translate, paste."""
        if not self.translator:
            print("No DeepL API key configured", flush=True)
            return
        threading.Thread(target=self._do_translate_clipboard, daemon=True).start()

    def _background_analysis(self, audio, raw_text, corrected_text, confidence):
        """Run pronunciation + training data save in background — never blocks recording."""
        try:
            from pronunciation import analyze, update_pronunciation_profile
            pron = analyze(audio, expected_text=corrected_text or raw_text)
            if pron.get("available"):
                update_pronunciation_profile(pron)
                if pron.get("l1_issues"):
                    issues = [i["phoneme"] + ":" + i["word"] for i in pron["l1_issues"][:2]]
                    print(f"  [pronunciation] clarity={pron['overall_clarity']:.2f}, L1: {', '.join(issues)}", flush=True)
        except Exception:
            pass

        try:
            from training_data import save_training_pair
            save_training_pair(audio, raw_text, corrected=corrected_text, confidence=confidence)
        except Exception:
            pass

    def _dictate_paste(self, text: str):
        if self.output_language != "EN" and self.translator:
            self._update_status("Translating...")
            text = self.translator.translate(text, self.output_language)
        self.paster.paste(text)
        print(f"Pasted: {text}", flush=True)

    def _handle_paste_snippet(self, description: str):
        if not self._embedder_ready.is_set():
            print("Embedder not ready — falling back to dictate", flush=True)
            self._dictate_paste(description)
            return
        if not self.snippet_cache:
            print("No snippets saved — nothing to match", flush=True)
            return
        hits = self.embedder.match(description, self.snippet_cache, k=3)
        if not hits:
            return
        top_id, top_score = hits[0]
        second_score = hits[1][1] if len(hits) > 1 else 0.0
        print(f"  [match] top={top_id} score={top_score:.3f} 2nd={second_score:.3f}", flush=True)

        # Direct-paste threshold: top > 0.75 AND margin > 0.1
        if top_score >= 0.75 and (top_score - second_score) >= 0.1:
            s = self.snippet_store.get(top_id)
            if s:
                self.paster.paste(s.body)
                self.snippet_store.record_use(top_id)
                print(f"  Pasted snippet: {s.name}", flush=True)
                return

        # Medium confidence — show mini picker
        if top_score >= 0.55:
            candidates = []
            for sid, score in hits[:3]:
                s = self.snippet_store.get(sid)
                if s:
                    candidates.append({"id": sid, "name": s.name, "score": round(float(score), 3)})
            self.overlay.send({"type": "PICKER", "candidates": candidates})
            self.overlay_visible = True
            return

        # Low confidence — open full overlay with query
        self._open_overlay(mode="search", query=description)

    def _open_overlay(self, mode: str = "list", query: str = "", from_clipboard: bool = False):
        self.overlay_visible = True
        draft_body = ""
        if from_clipboard:
            import subprocess as _sp
            draft_body = _sp.run(["pbpaste"], capture_output=True, text=True).stdout
        self._push_snippet_list()
        self.overlay.send({
            "type": "OPEN",
            "mode": mode,
            "query": query,
            "draft_body": draft_body,
        })

    def _on_overlay_event(self, msg: dict):
        t = msg.get("type")
        if t == "PASTE":
            s = self.snippet_store.get(msg["id"])
            if s:
                self.paster.paste(s.body)
                self.snippet_store.record_use(s.id)
        elif t == "CREATE":
            self.create_snippet(
                name=msg.get("name", "Untitled"),
                body=msg.get("body", ""),
                description=msg.get("description", ""),
                tags=msg.get("tags", ""),
            )
            self._push_snippet_list()
        elif t == "UPDATE":
            self.update_snippet(
                id=msg["id"],
                name=msg.get("name"),
                body=msg.get("body"),
                description=msg.get("description"),
                tags=msg.get("tags"),
            )
            self._push_snippet_list()
        elif t == "DELETE":
            self.delete_snippet(msg["id"])
            self._push_snippet_list()
        elif t == "SEARCH":
            hits = self.snippet_store.search_text(msg["query"])
            self.overlay.send({"type": "SNIPPETS", "items": [self._snippet_dict(s) for s in hits]})
        elif t == "DISMISSED":
            self.overlay_visible = False

    def _push_snippet_list(self):
        items = [self._snippet_dict(s) for s in self.snippet_store.list_all()]
        self.overlay.send({"type": "SNIPPETS", "items": items})

    @staticmethod
    def _snippet_dict(s):
        return {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "body": s.body,
            "tags": s.tags,
            "used_count": s.used_count,
        }

    def create_snippet(self, name: str, body: str, description: str = "", tags: str = ""):
        """Create a snippet and compute its embedding inline so it's matchable right away."""
        s = self.snippet_store.create(name=name, body=body, description=description, tags=tags)
        if self._embedder_ready.is_set() and self.embedder:
            vec = self.embedder.encode(f"{name}. {description}. Tags: {tags}")
            self.snippet_store.update(s.id, embedding=Embedder.array_to_blob(vec))
            self.snippet_cache[s.id] = vec
        self._refresh_whisper_vocab()
        return s

    def update_snippet(self, id: int, **fields):
        text_fields = {"name", "description", "tags"}
        self.snippet_store.update(id, **fields)
        if self._embedder_ready.is_set() and any(k in fields for k in text_fields):
            s = self.snippet_store.get(id)
            vec = self.embedder.encode(f"{s.name}. {s.description}. Tags: {s.tags}")
            self.snippet_store.update(id, embedding=Embedder.array_to_blob(vec))
            self.snippet_cache[id] = vec
        self._refresh_whisper_vocab()
        return self.snippet_store.get(id)

    def delete_snippet(self, id: int):
        self.snippet_store.delete(id)
        self.snippet_cache.pop(id, None)
        self._refresh_whisper_vocab()

    def _do_translate_clipboard(self):
        import subprocess
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        clipboard = result.stdout.strip()
        if not clipboard:
            print("Clipboard empty, nothing to translate", flush=True)
            return

        self.title = "\u231b"
        self._update_status("Translating clipboard...")
        print(f"Translating clipboard: {clipboard[:80]}...", flush=True)

        translated, detected = self.translator.translate_auto(clipboard, self.output_language)
        self.paster.paste(translated)
        lang_name = LANGUAGES.get(detected, detected)
        print(f"Translated ({detected}→{'EN' if detected != 'EN' else self.output_language}): {translated[:80]}...", flush=True)

        self.title = "\U0001f3a4"
        self._update_status("Idle -- ready")


def main():
    app = VoxType()
    app.run()


if __name__ == "__main__":
    main()
