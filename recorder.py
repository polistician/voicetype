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
        self._chunks = []
        self._recording = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype='float32',
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        if not self._chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._chunks)
