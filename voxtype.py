# voxtype.py
"""VoxType -- Hold Option+C to dictate, release to paste."""

import rumps
import threading
import os
import user_fixes
import stats as vox_stats
import integrator_chat
from recorder import Recorder
from transcriber_v2 import TranscriberV2
from translator import Translator
from paster import Paster
from voice_profile import update as update_profile, get_whisper_prompt, get_whisper_prompt_for_app
from corrections import apply_corrections, seed_defaults, auto_learn_corrections
from hotkey import HotkeyListener
from config import load_config, save_default_config, LANGUAGES
from intent import route as route_intent
from snippets import Store as SnippetStore
from transcript_history import History as TranscriptHistory
from autogen import generate as autogen_metadata
import numpy as np


class VoxType(rumps.App):
    def __init__(self):
        super().__init__("VoxType", title="\U0001f3a4")
        self.cfg = load_config()
        save_default_config()
        self._maybe_run_onboarding()

        self._status_item = rumps.MenuItem("Status: Idle")
        self._lang_menu = rumps.MenuItem("Output Language")
        self._build_lang_menu()

        self._update_item = rumps.MenuItem("Check for Updates…", callback=self._on_update_click)
        self._settings_item = rumps.MenuItem("Settings…", callback=self._on_settings_click)
        self._help_item = rumps.MenuItem("Help…", callback=self._on_help_click)
        self._stats_item = rumps.MenuItem("Stats…", callback=self._on_stats_click)
        self.menu = [
            self._status_item, None, self._lang_menu, None,
            f"Model: {self.cfg['model']}", None,
            self._update_item,
            self._settings_item,
            self._help_item, self._stats_item,
        ]

        self.recorder = Recorder(sample_rate=self.cfg["sample_rate"])
        self.recording = False
        seed_defaults()  # Load domain corrections (fox→vox, etc.)
        self.output_language = self.cfg.get("output_language", "EN")

        # Translator always exists — it lazy-loads the key from Keychain at translate-time
        # (with config.json fallback for backward compat). No-op if no key configured.
        self.translator = Translator()

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

        self._vad = None  # lazy-init on first audio (keeps cold-start fast)
        self._current_app: str | None = None  # bundle ID of focused app at recording start
        self._llm_corrector = None  # lazy-init on first use (opt-in, off by default)

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
        self._intent_history: list[dict] = []  # recent (text, action) tuples, last 20

        self._ensure_spotlight_indexed()

    def _load_embedder(self):
        try:
            from embedder import Embedder  # lazy: pulls in sentence-transformers + torch
            self.embedder = Embedder()
            self._rebuild_snippet_cache()
            self._embedder_ready.set()
            print("Embedder loaded", flush=True)
        except Exception as e:
            print(f"Embedder failed to load (snippet semantic match disabled): {e}", flush=True)
            self.embedder = None

    def _rebuild_snippet_cache(self):
        from embedder import Embedder  # already loaded at this point; cached by Python
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

    def _on_settings_click(self, _sender):
        """Open the Settings window via the SettingsBridge."""
        if not hasattr(self, "settings"):
            from overlay_bridge import SettingsBridge
            self.settings = SettingsBridge()
            self.settings.start()
        self.settings.open_window()

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
        bias_words = {"snippet", "snippets", "overview", "manager", "insert", "paste", "save", "help", "clipboard"}
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

    def _refresh_whisper_vocab(self, app: str | None = None):
        """Rebuild Whisper vocabulary, optionally biased toward a specific app."""
        if not self.transcriber:
            return
        bias_words = {"snippet", "snippets", "overview", "manager", "insert", "paste", "save", "help", "clipboard"}
        for s in self.snippet_store.list_all():
            for tok in s.name.split():
                if tok.isalpha() and len(tok) > 2:
                    bias_words.add(tok.lower())
        prompt = get_whisper_prompt_for_app(app) if app else get_whisper_prompt()
        existing = set(prompt.replace("Words I use: ", "").split()) if prompt else set()
        self.transcriber.set_vocabulary(sorted(existing | bias_words))

    def _update_status(self, status):
        self._status_item.title = f"Status: {status}"

    def _flash_skip(self, reason: str):
        """Briefly show skip feedback so the user knows the recording was rejected.

        Sets the menubar title to a 'no' icon + reason, then resets after 1.8s.
        Without this, skipped recordings look identical to silent failures and
        the user wonders why no new text appeared.
        """
        self.title = "\U0001f6ab"  # 🚫
        self._update_status(f"Skipped: {reason}")
        def _reset():
            import time
            time.sleep(1.8)
            self.title = "\U0001f3a4"  # 🎤
            self._update_status("Idle -- ready")
        threading.Thread(target=_reset, daemon=True).start()

    def _get_vad(self):
        """Lazy-init Silero VAD. Returns SileroVAD instance, or False if unavailable."""
        if self._vad is None:
            try:
                from vad import SileroVAD
                self._vad = SileroVAD()
                print("[vad] Silero VAD ready", flush=True)
            except Exception as e:
                print(f"[vad] init failed, falling back to RMS gate: {e}", flush=True)
                self._vad = False  # sentinel: not available
        return self._vad

    def _start_recording(self):
        if not self._model_loaded.is_set():
            print("Model still loading, please wait...", flush=True)
            return
        if self.recording:
            # Stale recording state — previous STOP was lost (Whisper thread
            # hung, audio device got confused, etc.). Force-reset instead of
            # silently no-op'ing, so the user's next Option+C press works.
            print("  [warn] previous recording never released — force-resetting", flush=True)
            try:
                self.recorder.stop()  # drain stream & reset PortAudio
            except Exception as e:
                print(f"  [warn] recorder.stop() during reset failed: {e}", flush=True)
            self.recording = False
        # Capture frontmost app before we steal focus — so we know the user's context
        from context import frontmost_app, app_short_name
        self._current_app = frontmost_app()
        self.recording = True
        self.title = "\U0001f534"
        app_label = app_short_name(self._current_app) if self._current_app else None
        self._update_status(f"Recording in {app_label}…" if app_label else "Recording...")
        try:
            self.recorder.start()
        except Exception as e:
            print(f"  [err] recorder.start() failed: {e}", flush=True)
            self.recording = False
            self.title = "\U0001f3a4"
            self._update_status("Idle -- ready")
            return
        print(f"Recording... (app={self._current_app or 'unknown'})", flush=True)

    def _stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self.title = "\u231b"
        self._update_status("Transcribing...")
        threading.Thread(target=self._transcribe_and_paste, daemon=True).start()

    def _transcribe_and_paste(self):
        try:
            audio = self.recorder.stop()
        except Exception as e:
            print(f"  [err] recorder.stop() failed: {e}", flush=True)
            self.title = "\U0001f3a4"
            self._update_status("Idle -- ready")
            return

        duration = len(audio) / self.cfg["sample_rate"] if len(audio) else 0
        min_samples = int(self.cfg["min_audio_seconds"] * self.cfg["sample_rate"])
        if len(audio) < min_samples:
            print(f"  [skip] audio too short ({duration:.2f}s < {self.cfg['min_audio_seconds']}s)", flush=True)
            vox_stats.log_decision("", "skip_short", f"{duration:.2f}s < {self.cfg['min_audio_seconds']}s",
                                    duration_s=duration)
            self._flash_skip(f"too short ({duration:.2f}s)")
            return

        # VAD gate (replaces RMS): catches clips with no speech before they hit Whisper.
        # Silero VAD is a neural model — far more accurate than RMS at distinguishing
        # real speech from ambient noise, keyboard clicks, or accidental keypresses.
        # Falls back gracefully to RMS if VAD fails to initialise.
        vad = self._get_vad()
        if vad:  # SileroVAD instance
            if not vad.contains_speech(audio, sample_rate=self.cfg["sample_rate"]):
                print(f"  [skip] VAD: no speech detected ({duration:.2f}s)", flush=True)
                vox_stats.log_decision("", "skip_no_speech", "vad rejected", duration_s=duration)
                self._flash_skip("no speech")
                return
        else:
            # Fallback to RMS gate if VAD failed to init
            import numpy as _np
            rms = float(_np.sqrt(_np.mean(audio.astype(_np.float32) ** 2))) if len(audio) else 0.0
            min_rms = self.cfg.get("min_rms", 0.005)
            if rms < min_rms:
                print(f"  [skip] audio too quiet (rms={rms:.4f} < {min_rms})", flush=True)
                vox_stats.log_decision("", "skip_quiet", f"rms={rms:.4f}", duration_s=duration)
                self._flash_skip("too quiet")
                return

        # Rich transcription: text + confidence + timing
        try:
            rich = self.transcriber.transcribe_rich(audio)
        except Exception as e:
            print(f"  [err] transcribe_rich failed: {e}", flush=True)
            self.title = "\U0001f3a4"
            self._update_status("Idle -- ready")
            return
        text = rich["text"]

        if not text:
            print(f"  [skip] whisper returned empty text (audio {duration:.2f}s)", flush=True)
            vox_stats.log_decision("", "skip_empty", f"audio {duration:.2f}s",
                                    duration_s=duration)
            self._flash_skip("no speech detected")
            return

        # Low-confidence short-output gate: catches Whisper hallucinations that
        # slip past the energy gate. Real one-word commands ("okay", "yes") have
        # high confidence; hallucinations like "hope"/"hello" sit at 0.3-0.55.
        max_words = self.cfg.get("hallucination_max_words", 2)
        min_conf = self.cfg.get("hallucination_min_confidence", 0.6)
        avg_conf = rich.get("avg_confidence", 0) or 0
        word_count = len(text.split())
        if word_count <= max_words and 0 < avg_conf < min_conf:
            print(f"  [skip] likely hallucination ({word_count}w, conf={avg_conf:.2f}): {text!r}", flush=True)
            vox_stats.log_decision(text, "skip_hallucination",
                                    f"{word_count}w conf={avg_conf:.2f}", duration_s=duration)
            self._flash_skip(f"low confidence ({avg_conf:.2f})")
            return

        if text:
            raw_whisper_text = text
            # 1. Apply known corrections (fox→vox, etc.)
            corrected = apply_corrections(text)
            if corrected != text:
                print(f"  [corrected] {text} → {corrected}", flush=True)
                text = corrected
                vox_stats.increment("corrections_applied")

            # 2. Update local voice profile (background-safe)
            try:
                update_profile(rich, app=self._current_app)
                conf = rich.get("avg_confidence", 0)
                lc = rich.get("low_confidence_words", [])
                if lc:
                    print(f"  [profile] conf={conf:.2f}, unclear: {', '.join(lc[:3])}", flush=True)
                self._refresh_whisper_vocab(app=self._current_app)
                auto_learn_corrections()
            except Exception:
                pass

            # 2b. Optional LLM post-correction (default OFF — set use_llm_correction in config)
            if self.cfg.get("use_llm_correction", False):
                try:
                    if self._llm_corrector is None:
                        from llm_corrector import LLMCorrector
                        self._llm_corrector = LLMCorrector()
                    from corrections import get_corrections_dict
                    user_corr = get_corrections_dict() if callable(getattr(__import__('corrections'), 'get_corrections_dict', None)) else None
                    text = self._llm_corrector.correct(text, user_corrections=user_corr)
                except Exception as e:
                    print(f"[llm-correct] failed, using raw transcript: {e}", flush=True)

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
            self._intent_history.append({"text": text, "action": intent.action})
            self._intent_history = self._intent_history[-20:]

            if intent.action == "dictate":
                # Optional ChatGPT cleanup pass — opt-in, off by default.
                # Only the transcript text leaves the machine, never audio.
                # Cleanup degrades gracefully on any error/timeout — see
                # integrator_chat.cleanup() for the contract.
                if self.cfg.get("ai_cleanup_enabled"):
                    self._update_status("Cleaning…")
                    pre_cleanup = text
                    try:
                        text = integrator_chat.cleanup(text, timeout_s=2.0)
                    except Exception as e:
                        # cleanup() should already swallow exceptions, but belt-and-braces:
                        print(f"  [warn] integrator cleanup failed: {e} — pasting raw", flush=True)
                        text = pre_cleanup
                    if text != pre_cleanup:
                        print(f"  [cleaned] {pre_cleanup} → {text}", flush=True)
                        vox_stats.increment("ai_cleanups_applied")
                self.transcript_history.push(text)
                self._dictate_paste(text)
                vox_stats.increment("recordings_total")
                vox_stats.increment("words_dictated_total", by=len(text.split()))
                vox_stats.log_decision(raw_whisper_text, "dictate", text[:200] if text != raw_whisper_text else "",
                                        duration_s=duration,
                                        was_corrected=(text != raw_whisper_text))
            elif intent.action == "paste_snippet":
                self._handle_paste_snippet(intent.payload.get("description", ""))
            elif intent.action == "open_overview":
                self._open_overlay()
                vox_stats.increment("overview_opens")
                vox_stats.log_decision(raw_whisper_text, "open_overview", "",
                                        duration_s=duration)
            elif intent.action == "save_snippet":
                self._open_overlay(mode="save", from_clipboard=intent.payload.get("from_clipboard", False))
                vox_stats.increment("overview_opens")
                vox_stats.log_decision(raw_whisper_text, "save_snippet", "",
                                        duration_s=duration)
            elif intent.action == "open_help":
                self._show_help()
                vox_stats.increment("help_opens")
                _help_tokens = raw_whisper_text.lower().split()
                if _help_tokens and _help_tokens[-1] != "help":
                    vox_stats.increment("fuzzy_help_saves")
                vox_stats.log_decision(raw_whisper_text, "open_help",
                                        f"confidence={intent.confidence}",
                                        duration_s=duration)
            elif intent.action == "open_fix":
                self._show_fix_surface()
                vox_stats.increment("fix_opens")
                vox_stats.log_decision(raw_whisper_text, "open_fix", "",
                                        duration_s=duration)
            elif intent.action == "open_stats":
                self._show_stats_surface()
                # Don't count opens of the stats view itself — too meta
                vox_stats.log_decision(raw_whisper_text, "open_stats", "",
                                        duration_s=duration)

        self.title = "\U0001f3a4"
        self._update_status("Idle -- ready")


    def _translate_clipboard(self):
        """Option+T: read clipboard, auto-detect language, translate, paste."""
        if not self.translator._get_key():
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
        if self.output_language != "EN" and self.translator._get_key():
            self._update_status("Translating...")
            text = self.translator.translate(text, self.output_language)
        if self.cfg.get("auto_paste", True):
            self.paster.paste(text)
            print(f"Pasted: {text}", flush=True)
        else:
            self.paster.set_clipboard_only(text)
            print(f"Clipboard set (manual paste): {text}", flush=True)

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
                vox_stats.increment("snippet_pastes")
                vox_stats.log_decision(description, "paste_snippet", s.name, duration_s=0.0)
                return

        # Medium confidence — show mini picker
        if top_score >= 0.55:
            candidates = []
            for sid, score in hits[:3]:
                s = self.snippet_store.get(sid)
                if s:
                    candidates.append({"id": sid, "name": s.name, "score": round(float(score), 3)})
            self.overlay.send({"type": "PICKER", "candidates": candidates})
            # Picker is decided by 1/2/3/Esc, not voice — don't intercept.
            self.overlay_visible = False
            return

        # Low confidence — open full overlay with query
        self._open_overlay(mode="search", query=description)

    def _open_overlay(self, mode: str = "list", query: str = "", from_clipboard: bool = False):
        # Only the list/search mode intercepts voice-into-search.
        # Help, picker, and editor modes should let subsequent dictation
        # pass through to normal intent routing.
        self.overlay_visible = mode in {"list", "search"}
        draft_body = ""
        if from_clipboard:
            import subprocess as _sp
            draft_body = _sp.run(["pbpaste"], capture_output=True, text=True).stdout
        self._push_snippet_list()

        # Save flow: auto-generate name/description/tags and open the editor
        # directly with everything pre-filled, so the user reviews instead of
        # filling from scratch.
        if mode == "save":
            # Editor has its own focused text fields — don't intercept voice.
            self.overlay_visible = False
            meta = autogen_metadata(draft_body)
            print(f"  [autogen] name={meta['name']!r} tags={meta['tags']!r}", flush=True)
            self.overlay.send({
                "type": "OPEN_EDITOR",
                "body": draft_body,
                "name": meta["name"],
                "description": meta["description"],
                "tags": meta["tags"],
            })
            return

        self.overlay.send({
            "type": "OPEN",
            "mode": mode,
            "query": query,
            "draft_body": draft_body,
        })

    def _show_help(self):
        # Help is a passive viewer — let subsequent Option+C dictation
        # flow through intent routing instead of getting swallowed as SEARCH.
        self.overlay_visible = False
        self.overlay.send({"type": "SHOW_HELP"})

    def _show_fix_surface(self):
        # Fix is an input surface — don't intercept subsequent dictation
        self.overlay_visible = False
        recent_intents = list(self._intent_history[-5:]) if hasattr(self, "_intent_history") else []
        self.overlay.send({
            "type": "SHOW_FIX",
            "recent": recent_intents,
        })

    def _show_stats_surface(self):
        # Stats is a read-only view — don't intercept subsequent dictation
        self.overlay_visible = False
        data = vox_stats.load()
        recent_full = vox_stats.recent_decisions(n=50)  # wider window for suggestions
        data["_snippets_total"] = len(self.snippet_store.list_all())
        data["_session_since"] = data.get("first_used_at")

        # Mine the decision log for repeat-dictation snippet candidates
        try:
            from suggestions import suggest as _suggest
            existing_bodies = [s.body for s in self.snippet_store.list_all()]
            sugs = _suggest(recent_full, existing_bodies)
        except Exception as e:
            print(f"  [stats] suggest failed: {e}", flush=True)
            sugs = []

        self.overlay.send({
            "type": "SHOW_STATS",
            "stats": data,
            "recent_decisions": recent_full[:10],
            "suggestions": sugs,
        })

    def _on_stats_click(self, _sender):
        self._show_stats_surface()

    def _on_help_click(self, _sender):
        self._show_help()

    def _on_overlay_event(self, msg: dict):
        t = msg.get("type")
        if t == "PASTE":
            s = self.snippet_store.get(msg["id"])
            if s:
                self.paster.paste(s.body)
                self.snippet_store.record_use(s.id)
            # Overlay closes after paste — clear flag so next Option+C dictates
            self.overlay_visible = False
        elif t == "SAVE_FROM_CLIPBOARD":
            # Capture strip ⌘S — route through the save flow so autogen fires
            self._open_overlay(mode="save", from_clipboard=True)
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
        elif t == "REQUEST_STATS":
            self._show_stats_surface()
        elif t == "FIX_APPLY":
            desc = msg.get("description", "")
            fix = user_fixes.parse_heuristic(desc)
            source = "heuristic"
            if not fix and self.cfg.get("use_claude_cli_for_fix", False):
                # Signal the overlay that we're waiting on Claude
                self.overlay.send({"type": "FIX_RESULT", "success": True,
                                   "message": "Asking Claude…"})
                # Run the LLM call in a thread so we don't block overlay events
                threading.Thread(
                    target=self._fix_via_claude_async,
                    args=(desc,),
                    daemon=True,
                ).start()
                return
            if fix:
                result = user_fixes.apply(fix)
                try:
                    import intent as _intent
                    _intent.reload_user_fixes()
                except Exception as e:
                    print(f"  [fix] reload failed: {e}", flush=True)
                print(f"  [fix/{source}] {result}", flush=True)
                self.overlay.send({"type": "FIX_RESULT", "success": True, "message": result})
            else:
                hint = "Try 'X should be Y' or 'when I say X treat as Y'."
                if not self.cfg.get("use_claude_cli_for_fix", False):
                    hint += " (Or enable use_claude_cli_for_fix in config for natural-language fixes.)"
                self.overlay.send({"type": "FIX_RESULT", "success": False, "message": "Couldn't parse. " + hint})
        elif t == "FIX_QUICK":
            # One-click fix: user clicked "↪ help" on a recent transcription
            text = msg.get("text", "").strip().lower()
            intent_key = msg.get("intent_key", "")
            if text and intent_key in {"help", "snippet", "save", "clipboard"}:
                word = text.split()[-1]  # last token of the utterance
                user_fixes.add_variant(intent_key, word)
                try:
                    import intent as _intent
                    _intent.reload_user_fixes()
                except Exception:
                    pass
                print(f"  [fix] added {word!r} as {intent_key} variant", flush=True)
                self.overlay.send({
                    "type": "FIX_RESULT",
                    "success": True,
                    "message": f"Next time {text!r}, it'll route to {intent_key}.",
                })

    def _fix_via_claude_async(self, description: str):
        recent = list(self._intent_history[-5:]) if hasattr(self, "_intent_history") else []
        fix = user_fixes.parse_with_claude(description, recent_intents=recent)
        if not fix:
            self.overlay.send({
                "type": "FIX_RESULT",
                "success": False,
                "message": "Claude couldn't parse the fix. Try rephrasing or use 'X should be Y'.",
            })
            return
        result = user_fixes.apply(fix)
        try:
            import intent as _intent
            _intent.reload_user_fixes()
        except Exception as e:
            print(f"  [fix] reload failed: {e}", flush=True)
        print(f"  [fix/claude] {result}", flush=True)
        self.overlay.send({"type": "FIX_RESULT", "success": True, "message": result})

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
            from embedder import Embedder  # already loaded; cached by Python
            vec = self.embedder.encode(f"{name}. {description}. Tags: {tags}")
            self.snippet_store.update(s.id, embedding=Embedder.array_to_blob(vec))
            self.snippet_cache[s.id] = vec
        self._refresh_whisper_vocab()
        return s

    def update_snippet(self, id: int, **fields):
        text_fields = {"name", "description", "tags"}
        self.snippet_store.update(id, **fields)
        if self._embedder_ready.is_set() and any(k in fields for k in text_fields):
            from embedder import Embedder  # already loaded; cached by Python
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

    # ------------------------------------------------------------------
    # First-launch onboarding
    # ------------------------------------------------------------------

    def _maybe_run_onboarding(self):
        """If no onboarding_complete flag, launch the onboarding flow."""
        flag = os.path.expanduser("~/.voicetype/onboarding_complete")
        if os.path.exists(flag):
            return
        from overlay_bridge import OnboardingBridge
        self.onboarding = OnboardingBridge(
            on_complete=lambda: self._mark_onboarding_done(flag)
        )
        self.onboarding.start()
        self.onboarding.open_window()

        # Belt-and-suspenders fallback: if the onboarding window never visibly
        # appeared (e.g. activation policy race in bundled .app), the user would
        # be stuck with no guidance.  After 30 seconds, if the flag still hasn't
        # been written, fire a native NSAlert via osascript so they always get
        # the manual-grant path even in the worst case.
        import threading

        def _fallback():
            if os.path.exists(flag):
                return  # onboarding completed normally — nothing to do
            print("[onboarding] fallback: 30s elapsed without completion — showing NSAlert", flush=True)
            import subprocess
            try:
                result = subprocess.run(
                    [
                        "osascript", "-e",
                        'display alert "VoiceType is ready" message '
                        '"Grant Microphone + Accessibility in System Settings → Privacy & Security, '
                        'then hold ⌥ C in any text field to start dictating." '
                        'buttons {"Open Settings", "Got it"} default button "Open Settings"',
                    ],
                    timeout=120,
                    capture_output=True,
                    text=True,
                )
                # osascript writes the clicked button name to stdout
                if "Open Settings" in (result.stdout or ""):
                    subprocess.Popen([
                        "open",
                        "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
                    ])
            except Exception as e:
                print(f"[onboarding] fallback alert failed: {e}", flush=True)
            # Mark complete so we don't nag on every subsequent launch
            self._mark_onboarding_done(flag)

        timer = threading.Timer(30.0, _fallback)
        timer.daemon = True
        timer.start()

    def _ensure_spotlight_indexed(self):
        """One-shot: register the bundled .app with LaunchServices and Spotlight.
        Only runs in bundled mode (when running from /Applications/VoiceType.app)."""
        import sys, os, subprocess
        # Detect bundled mode via sys._MEIPASS or path
        if not hasattr(sys, '_MEIPASS') and "/Applications/VoiceType.app" not in sys.executable:
            return  # source-tree mode; skip
        app_path = "/Applications/VoiceType.app"
        if not os.path.isdir(app_path):
            return
        flag = os.path.expanduser("~/.voicetype/.spotlight_indexed")
        if os.path.exists(flag):
            return  # only run once
        try:
            subprocess.run([
                "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
                "-f", app_path
            ], capture_output=True, timeout=5)
            subprocess.run(["mdimport", app_path], capture_output=True, timeout=5)
            os.makedirs(os.path.dirname(flag), exist_ok=True)
            with open(flag, "w") as f:
                f.write("1")
        except Exception:
            pass  # best effort

    def _mark_onboarding_done(self, flag: str):
        os.makedirs(os.path.dirname(flag), exist_ok=True)
        with open(flag, "w") as f:
            f.write("1")

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def _on_update_click(self, _sender):
        """Check GitHub Releases for a newer version. Show NSAlert with result.
        If newer, offer to update in-app."""
        threading.Thread(target=self._check_for_updates, daemon=True).start()

    def _check_for_updates(self):
        import urllib.request, json
        try:
            with urllib.request.urlopen(
                "https://api.github.com/repos/polistician/voicetype/releases/latest",
                timeout=10
            ) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            self._show_alert("Update check failed",
                             f"Could not reach GitHub: {e}",
                             buttons=["OK"])
            return
        latest = (data.get("tag_name", "") or "").lstrip("v")
        current = self._read_current_version()
        if not latest:
            self._show_alert("Update check failed",
                             "Could not determine latest version.",
                             buttons=["OK"])
            return
        if latest == current:
            self._show_alert("VoiceType is up to date",
                             f"You're on v{current}, the latest version.",
                             buttons=["OK"])
            return
        # Newer version available — offer in-app update
        clicked = self._show_alert(
            f"Update available: v{latest}",
            f"You're on v{current}. Update now? VoiceType will download v{latest}, verify it, install to /Applications, and relaunch automatically.",
            buttons=["Update Now", "Later"]
        )
        if "Update Now" in clicked:
            self._perform_update_async(latest)

    def _perform_update_async(self, new_version_label: str):
        """Run the updater on a background thread; show progress + final alert."""
        from updater import perform_update, relaunch, UpdateError, APP_PATH

        def _run():
            # Bundled-mode safety: require /Applications/VoiceType.app exists.
            # If not, the user is running source-tree — direct them to manual install.
            if not os.path.isdir(APP_PATH):
                self._show_alert(
                    "Source-tree mode",
                    "You're running VoiceType from source, not from /Applications/VoiceType.app. Install via DMG once first, then in-app updates will work.",
                    buttons=["OK"]
                )
                return

            # Save current title to restore on error
            original_title = self.title or "\U0001f3a4"

            def _on_progress(msg: str):
                print(f"[updater] {msg}", flush=True)
                short = msg if len(msg) <= 28 else msg[:27] + "…"
                self.title = f"⏳ {short}"
                self._update_status(msg)

            try:
                new_v = perform_update(on_progress=_on_progress)
            except UpdateError as e:
                self.title = original_title
                self._show_alert("Update failed", str(e), buttons=["OK"])
                return
            except Exception as e:
                self.title = original_title
                self._show_alert("Update failed", f"Unexpected error: {e}", buttons=["OK"])
                return

            self.title = "✅"
            clicked = self._show_alert(
                f"Updated to v{new_v}",
                "VoiceType has been updated. Click OK to relaunch.\n\nNote: macOS may ask you to re-grant Microphone + Accessibility because the new binary has a different signature.",
                buttons=["Relaunch", "Later"]
            )
            if "Relaunch" in clicked:
                relaunch()
            # If user clicks Later, restore the title
            self.title = original_title

        threading.Thread(target=_run, daemon=True).start()

    def _read_current_version(self) -> str:
        """Resolve the running app's version.

        BUNDLED: read CFBundleShortVersionString from the .app's Info.plist —
        canonical truth, can never disagree with what macOS shows. We walk up
        from sys._MEIPASS (which is .../VoiceType.app/Contents/Resources/...)
        to find Contents/Info.plist.

        SOURCE-TREE: read ~/voicetype/VERSION as the dev-mode source of truth.
        """
        import sys, subprocess
        # BUNDLED mode — Info.plist is canonical
        if hasattr(sys, "_MEIPASS"):
            mp = sys._MEIPASS
            # Walk up to find Contents/Info.plist
            head = mp
            for _ in range(6):  # bounded — Resources/{...}.app/Contents
                contents = os.path.join(head, "Info.plist")
                if os.path.isfile(contents) and "Contents" in head:
                    try:
                        result = subprocess.run(
                            ["plutil", "-extract", "CFBundleShortVersionString", "raw", contents],
                            capture_output=True, text=True, timeout=2
                        )
                        if result.returncode == 0:
                            v = result.stdout.strip()
                            if v:
                                return v
                    except Exception:
                        pass
                    break
                head = os.path.dirname(head)
                if head in ("/", ""):
                    break
            # Fallback: bundled VERSION file
            try:
                with open(os.path.join(sys._MEIPASS, "VERSION")) as f:
                    v = f.read().strip()
                    if v:
                        return v
            except Exception:
                pass

        # SOURCE-TREE mode
        for p in (
            os.path.expanduser("~/voicetype/VERSION"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION"),
        ):
            try:
                with open(p) as f:
                    v = f.read().strip()
                    if v:
                        return v
            except Exception:
                pass
        return "unknown"

    def _show_alert(self, title: str, message: str, buttons: list) -> str:
        """Show a native NSAlert via osascript. Returns the clicked button name."""
        import subprocess
        buttons_str = ", ".join(f'"{b}"' for b in buttons)
        script = (
            f'display alert "{title}" message "{message}" '
            f'buttons {{{buttons_str}}} default button "{buttons[0]}"'
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=300
            )
            return result.stdout.strip()
        except Exception:
            return ""

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
