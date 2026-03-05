# voxtype.py
"""VoxType -- Hold Option+Space to dictate, release to paste."""

import rumps
import threading
import os
from pynput import keyboard
from recorder import Recorder
from transcriber import Transcriber
from paster import Paster

MODEL_PATH = os.path.expanduser("~/voxtype/models/ggml-base.en.bin")
HOTKEY = keyboard.Key.space  # with alt modifier


class VoxType(rumps.App):
    def __init__(self):
        super().__init__("VoxType", title="\U0001f3a4")
        self.menu = ["Status: Idle", None, "Model: base.en"]

        self.recorder = Recorder(sample_rate=16000)
        self.paster = Paster()
        self.recording = False
        self.alt_held = False

        # Load model in background to not block menubar
        self._model_loaded = threading.Event()
        self.transcriber = None
        threading.Thread(target=self._load_model, daemon=True).start()

        # Start hotkey listener
        self.listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self.listener.start()

    def _load_model(self):
        print("Loading Whisper model...")
        self.transcriber = Transcriber(model_path=MODEL_PATH)
        self._model_loaded.set()
        print("Model loaded!")
        self._update_status("Idle -- ready")

    def _update_status(self, status):
        try:
            self.menu["Status: Idle"].title = f"Status: {status}"
        except Exception:
            pass

    def _on_press(self, key):
        # Track alt/option key
        if key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
            self.alt_held = True
            return

        # Alt+Space triggers recording
        if key == HOTKEY and self.alt_held and not self.recording:
            if not self._model_loaded.is_set():
                print("Model still loading, please wait...")
                return
            self.recording = True
            self.title = "\U0001f534"
            self._update_status("Recording...")
            self.recorder.start()

    def _on_release(self, key):
        if key == keyboard.Key.alt_l or key == keyboard.Key.alt_r:
            self.alt_held = False
            # If we were recording and alt is released, stop
            if self.recording:
                self._finish_recording()
            return

        if key == HOTKEY and self.recording:
            self._finish_recording()

    def _finish_recording(self):
        self.recording = False
        self.title = "\u231b"
        self._update_status("Transcribing...")

        # Run transcription in background to not block hotkey listener
        threading.Thread(target=self._transcribe_and_paste, daemon=True).start()

    def _transcribe_and_paste(self):
        audio = self.recorder.stop()
        if len(audio) < 1600:  # less than 0.1s of audio -- ignore
            self.title = "\U0001f3a4"
            self._update_status("Idle -- ready")
            return

        text = self.transcriber.transcribe(audio)
        if text:
            self.paster.paste(text)
            print(f"Pasted: {text}")

        self.title = "\U0001f3a4"
        self._update_status("Idle -- ready")


def main():
    app = VoxType()
    app.run()


if __name__ == "__main__":
    main()
