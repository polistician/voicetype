# recorder.py
import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self._chunks = []
        self._stream = None
        self._recording = False

    def _callback(self, indata, frames, time_info, status):
        if self._recording:
            self._chunks.append(indata[:, 0].copy())  # mono

    def start(self):
        # Force-close any leftover stream from a previous recording
        # This prevents PortAudio device locks from stale references
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        self._chunks = []
        self._recording = True
        for attempt in range(3):
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype='float32',
                    callback=self._callback,
                )
                self._stream.start()
                return
            except Exception as e:
                print(f"Audio open failed (attempt {attempt+1}/3): {e}", flush=True)
                # Try resetting PortAudio on failure
                try:
                    sd._terminate()
                    sd._initialize()
                except Exception:
                    pass
                import time
                time.sleep(0.5)
        print("Could not open audio after 3 attempts", flush=True)
        self._recording = False

    def stop(self):
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._chunks)
