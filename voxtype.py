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
        )
        self.hotkey.start()

        self.paster = Paster()
        self.paster.set_hotkey(self.hotkey)

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

        # Feed learned vocabulary into Whisper for better recognition
        prompt = get_whisper_prompt()
        if prompt:
            self.transcriber.set_vocabulary(prompt.split(", "))
            print(f"Loaded {len(prompt.split(', '))} vocabulary words", flush=True)

        self._model_loaded.set()
        print("Model loaded!", flush=True)
        self._update_status("Idle -- ready")

    def _update_status(self, status):
        self._status_item.title = f"Status: {status}"

    def _start_recording(self):
        if not self._model_loaded.is_set():
            print("Model still loading, please wait...", flush=True)
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
            # 1. Apply known corrections (fox→vox, etc.) — BEFORE paste
            corrected = apply_corrections(text)
            if corrected != text:
                print(f"  [corrected] {text} → {corrected}", flush=True)
                text = corrected

            # 2. Update local voice profile
            try:
                update_profile(rich)
                conf = rich.get("avg_confidence", 0)
                lc = rich.get("low_confidence_words", [])
                if lc:
                    print(f"  [profile] conf={conf:.2f}, unclear: {', '.join(lc[:3])}", flush=True)

                # Hot-reload vocabulary into Whisper
                prompt = get_whisper_prompt()
                if prompt:
                    words = prompt.replace("Words I use: ", "").split()
                    self.transcriber.set_vocabulary(words)

                # Auto-learn corrections from low-confidence patterns
                auto_learn_corrections()
            except Exception:
                pass

            # 3. Pronunciation + training data — run in background (never block next recording)
            audio_copy = audio.copy()  # copy before thread — audio array may be reused
            raw_text = rich["text"]
            corrected_text = text if text != raw_text else None
            conf = rich.get("avg_confidence", 0)
            threading.Thread(target=self._background_analysis,
                             args=(audio_copy, raw_text, corrected_text, conf),
                             daemon=True).start()

            # 5. Translate if needed
            if self.output_language != "EN" and self.translator:
                self._update_status("Translating...")
                text = self.translator.translate(text, self.output_language)

            self.paster.paste(text)
            print(f"Pasted: {text}", flush=True)

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
