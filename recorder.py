# recorder.py
import threading
import numpy as np
import sounddevice as sd


class Recorder:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self._chunks = []
        self._stream = None
        self._recording = False
        # Last device that successfully opened — try this one first next time
        # so we don't re-probe everything when the user's preferred mic works.
        self._last_good = None
        # Streaming-mode support: a separate cursor lets a poller drain audio
        # incrementally during recording without disturbing the final stop()
        # result. _pop_cursor is the index of the next un-popped chunk.
        self._pop_cursor = 0
        self._chunks_lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        if self._recording:
            mono = indata[:, 0].copy()
            with self._chunks_lock:
                self._chunks.append(mono)

    def pop_new(self) -> np.ndarray:
        """Return audio appended since the last call. Non-destructive — the
        full buffer remains intact and is returned in full by stop().

        Used by the streaming transcriber's polling loop.
        """
        with self._chunks_lock:
            start = self._pop_cursor
            new_chunks = self._chunks[start:]
            self._pop_cursor = len(self._chunks)
        if not new_chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(new_chunks)

    def _candidate_devices(self):
        """Return all input devices that *could* accept a stream, ordered by
        preference. Probes via PortAudio's `check_input_settings` so we
        skip devices that can't deliver our sample rate / channel layout.

        Priority:
          1. Last known good device (avoids re-probing on every recording)
          2. System default (None — what the user has selected in System Settings)
          3. Every other input device that survives probing

        No hardcoded name patterns — works regardless of mac model, OS, or
        whatever Apple decides to call the built-in mic this year.
        """
        seen = set()
        ordered = []

        def _add(dev):
            key = "default" if dev is None else dev
            if key in seen:
                return
            seen.add(key)
            ordered.append(dev)

        if self._last_good is not None:
            _add(self._last_good)
        _add(None)  # system default

        try:
            for i, d in enumerate(sd.query_devices()):
                if d.get("max_input_channels", 0) <= 0:
                    continue
                # Probe — fast, doesn't actually open the device, just validates
                # that PortAudio thinks the requested format is supportable.
                try:
                    sd.check_input_settings(
                        device=i,
                        samplerate=self.sample_rate,
                        channels=1,
                        dtype='float32',
                    )
                except Exception:
                    continue
                _add(i)
        except Exception as e:
            print(f"  [recorder] device enumeration failed: {e}", flush=True)
        return ordered

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

        with self._chunks_lock:
            self._chunks = []
            self._pop_cursor = 0
        self._recording = True

        last_error = None
        for device in self._candidate_devices():
            for attempt in range(2):
                try:
                    self._stream = sd.InputStream(
                        samplerate=self.sample_rate,
                        channels=1,
                        dtype='float32',
                        callback=self._callback,
                        device=device,
                    )
                    self._stream.start()
                    self._last_good = device
                    if device is not None:
                        try:
                            name = sd.query_devices(device)["name"]
                            print(f"  [recorder] using fallback device [{device}] {name}", flush=True)
                        except Exception:
                            pass
                    return
                except Exception as e:
                    last_error = e
                    label = f"device={device}" if device is not None else "default"
                    print(f"  [recorder] open failed ({label}, attempt {attempt+1}/2): {e}", flush=True)
                    try:
                        sd._terminate()
                        sd._initialize()
                    except Exception:
                        pass
                    import time
                    time.sleep(0.3)
        print(f"  [recorder] no audio device worked. Last error: {last_error}", flush=True)
        self._recording = False

    def stop(self):
        self._recording = False
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        with self._chunks_lock:
            chunks_snapshot = list(self._chunks)
        if not chunks_snapshot:
            return np.array([], dtype=np.float32)
        return np.concatenate(chunks_snapshot)
