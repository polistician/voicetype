"""Streaming Whisper transcription with VAD-cut chunks and LocalAgreement-2.

Why this exists
---------------
Whisper is an encoder-decoder model with O(N²) attention within its 30s window.
For a 60s clip the model has to split into two 30s windows and reconcile them,
producing disproportionate latency. Decoding only AFTER the user releases the
hotkey means the user always waits at least `clip_duration × RTF` seconds.

Streaming inverts this: decode chunks in the background while the user is still
speaking, so when the hotkey releases only the final tail chunk needs decoding.

Math (M4 Pro Metal, large-v3-turbo, RTF ~0.1):
    60s clip — offline: ~6s wait
    60s clip — streaming, 4s chunks: ~0.5s wait  (12× faster)

Architecture
------------
- A *slicer* watches the live audio buffer. When ≥ `chunk_min_s` of audio has
  accumulated since the last cut, the slicer:
    1. Force-cuts at `chunk_max_s` if reached, OR
    2. Cuts at the earliest VAD-detected silence ≥ `silence_min_s` long.
  Each chunk overlaps the previous by `overlap_s` to give LocalAgreement-2 a
  seam to compare across.

- A *decoder* thread pulls chunks from a queue and runs pywhispercpp on each.
  Language is auto-detected on chunk 0 (~50ms) and locked. The `initial_prompt`
  is `base_prompt + last_100_tokens(committed_text)`, which carries linguistic
  context across the chunk boundary and closes most of the chunked-vs-monolithic
  accuracy gap (Macháček 2023).

- *LocalAgreement-2* (Macháček 2023): a token is committed only when it appears
  in the same position across two successive chunk decodes. This eliminates the
  flicker of optimistic streaming and gives near-offline accuracy. We adapt it
  word-level (whisper.cpp doesn't expose stable token-level positions cheaply).

- On `finalize()`: drain any remaining audio as the final chunk, decode it,
  emit committed + tentative text, return the full transcript.

Failure modes & mitigations
---------------------------
- Whisper hallucinates ". Thank you for watching!" / ". So." on quiet chunk
  tails. Filtered via JUNK list inherited from TranscriberV2 + `no_speech_thold`.
- VAD false-negatives can prevent cuts indefinitely. Hard cap at `chunk_max_s`.
- Decoder falls behind on bursts (RTF spikes). Queue absorbs; finalize() waits.
- Chunk boundary inside a word: overlap region + LocalAgreement-2 dedup catches
  most cases; remaining word-split residue is rare and small.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

import numpy as np


def _word_overlap_merge(committed: str, new_text: str, max_search_words: int = 12) -> str:
    """Merge two chunk transcripts by finding their longest shared boundary.

    The new chunk's audio overlaps the committed audio by ~`overlap_s`, so the
    new chunk's first words should repeat the committed text's last words.
    Find the longest such overlap and splice cleanly.

    Returns the *full merged text* (committed + new, with overlap removed).
    Falls back to space-join if no overlap is found (rare; would only happen
    on silence-only overlap regions or model disagreement).
    """
    if not committed:
        return new_text
    if not new_text:
        return committed

    a_words = committed.split()
    b_words = new_text.split()
    if not a_words or not b_words:
        return (committed + " " + new_text).strip()

    # Search for the longest k such that last-k words of a == first-k of b.
    # Words are normalized lower-case + stripped of trailing punctuation for the match.
    def norm(w: str) -> str:
        return w.strip(".,!?;:'\"()[]{}").lower()

    a_norm = [norm(w) for w in a_words]
    b_norm = [norm(w) for w in b_words]

    max_k = min(len(a_words), len(b_words), max_search_words)
    best_k = 0
    for k in range(max_k, 0, -1):
        if a_norm[-k:] == b_norm[:k]:
            best_k = k
            break

    if best_k == 0:
        return (committed + " " + new_text).strip()
    return (" ".join(a_words) + " " + " ".join(b_words[best_k:])).strip()


def _local_agreement_2(prev_chunk_text: str, curr_chunk_text: str) -> tuple[str, str]:
    """LocalAgreement-2 word-level commit policy.

    Returns (committed_prefix, tentative_suffix).

    A word is committed when two successive chunk decodes agree on it at the
    same prefix position. Disagreement → keep both in tentative.

    For VoiceType's chunked (vs sliding-window) pipeline, we apply this only
    to the *overlap region*: the new chunk's first ~K words should match the
    previous chunk's last ~K words. Words that match are committed.
    """
    if not prev_chunk_text:
        return ("", curr_chunk_text)
    if not curr_chunk_text:
        return (prev_chunk_text, "")

    a = prev_chunk_text.split()
    b = curr_chunk_text.split()

    def norm(w: str) -> str:
        return w.strip(".,!?;:'\"()[]{}").lower()

    # Match longest common prefix of b with any suffix of a.
    a_norm = [norm(w) for w in a]
    b_norm = [norm(w) for w in b]

    # Find the longest k such that a's last-k words equal b's first-k words.
    max_k = min(len(a), len(b))
    best_k = 0
    for k in range(max_k, 0, -1):
        if a_norm[-k:] == b_norm[:k]:
            best_k = k
            break

    if best_k == 0:
        # No agreement — emit prev as committed (best we have), reset.
        return (prev_chunk_text, curr_chunk_text)

    # Commit through the agreement point, leave the rest tentative.
    committed = " ".join(a[: len(a) - best_k] + b[:best_k]).strip()
    tentative = " ".join(b[best_k:]).strip()
    return (committed, tentative)


# Hallucination tokens to filter at chunk boundaries (Whisper's silence-fillers).
_JUNK = {
    "[BLANK_AUDIO]", "[silence]", "(silence)", "[music]", "(music)",
    "[applause]", "[laughter]", "Thank you.", "Thanks for watching!",
    "Thanks for watching.", ". Thank you.", "So.", ". So.",
    "Bye.", "Bye!", "you", "You.", ".",
}


def _dedupe_phrase_repeats(text: str, max_phrase: int = 8) -> str:
    """Catch and remove immediately-repeated multi-word phrases.

    Whisper sometimes emits ". This is a longer-term care system. This is a
    longer-term care system." at chunk boundaries — a hallucinated phrase
    repeated verbatim. Drop the second occurrence.

    Scans for runs of length 2..max_phrase words that repeat back-to-back
    (allowing one word of punctuation drift). Removes only adjacent
    duplicates; legitimate repetition with intervening words is preserved.
    """
    if not text:
        return text
    words = text.split()
    if len(words) < 4:
        return text

    def norm(w: str) -> str:
        return w.strip(".,!?;:'\"()[]{}").lower()

    norm_words = [norm(w) for w in words]
    out: list[int] = list(range(len(words)))  # indices to keep
    i = 0
    while i < len(words):
        removed = False
        # Look for the longest k-gram starting at i that repeats at i+k
        for k in range(max_phrase, 1, -1):
            if i + 2 * k > len(words):
                continue
            if norm_words[i : i + k] == norm_words[i + k : i + 2 * k]:
                # Drop the second occurrence
                out = out[: out.index(i + k)] + out[out.index(i + 2 * k) :] if (i + 2 * k) in out else out
                # Rebuild norm_words/words view by skipping
                del words[i + k : i + 2 * k]
                del norm_words[i + k : i + 2 * k]
                removed = True
                break
        if not removed:
            i += 1
    return " ".join(words)


class StreamingTranscriber:
    """Background streaming Whisper with VAD-cut chunking and LocalAgreement-2.

    Lifecycle:
        st = StreamingTranscriber(model, vad, sample_rate=16000,
                                  base_prompt="...", language=None)
        st.start(on_preview=lambda text: ...)
        # ... while recording, periodically:
        st.feed_audio(new_samples)
        # ... on hotkey release:
        result = st.finalize(remaining_samples)
        st.stop()

    `result` is a dict matching TranscriberV2.transcribe_rich's shape so the
    rest of voxtype.py is unchanged downstream.
    """

    def __init__(
        self,
        model,  # pywhispercpp.model.Model instance
        vad=None,  # SileroVAD instance or None
        sample_rate: int = 16000,
        base_prompt: str = "",
        language: Optional[str] = None,  # None = auto-detect
        chunk_min_s: float = 2.0,
        chunk_target_s: float = 4.0,
        chunk_max_s: float = 7.0,
        overlap_s: float = 0.6,
        silence_min_s: float = 0.35,
        n_threads: int = 4,
    ):
        self.model = model
        self.vad = vad
        self.sample_rate = sample_rate
        self.base_prompt = base_prompt
        self.language = language
        self.locked_language = language  # set on first detect if None
        self.chunk_min_s = chunk_min_s
        self.chunk_target_s = chunk_target_s
        self.chunk_max_s = chunk_max_s
        self.overlap_s = overlap_s
        self.silence_min_s = silence_min_s
        self.n_threads = n_threads

        # Audio state: single contiguous ndarray growing in feed_audio.
        # _cursor points to the next sample to be considered for chunking.
        self._audio = np.array([], dtype=np.float32)
        self._cursor = 0
        self._audio_lock = threading.Lock()

        # Decoder pipeline
        self._chunk_queue: "queue.Queue[tuple[int, np.ndarray, bool]]" = queue.Queue()
        self._decoder_thread: Optional[threading.Thread] = None
        self._running = False
        self._stopping = False
        self._next_chunk_idx = 0

        # Reconciliation state
        self._committed_text = ""
        self._pending_chunk_text = ""  # last chunk's full output, awaiting next chunk for LA2
        self._all_segments: list[dict] = []
        self._all_probs: list[float] = []
        self._low_confidence: list[str] = []

        self._on_preview: Optional[Callable[[str, str], None]] = None  # (committed, tentative)
        self._error: Optional[Exception] = None

    # ── public API ─────────────────────────────────────────────────────────

    def start(self, on_preview: Optional[Callable[[str, str], None]] = None) -> None:
        """Start the background decoder thread."""
        if self._running:
            return
        self._on_preview = on_preview
        self._running = True
        self._stopping = False
        self._decoder_thread = threading.Thread(
            target=self._decoder_loop, daemon=True, name="streaming-decoder",
        )
        self._decoder_thread.start()

    def feed_audio(self, samples: np.ndarray) -> None:
        """Append new audio samples; may trigger chunk emission."""
        if samples is None or len(samples) == 0:
            return
        if samples.dtype != np.float32:
            samples = samples.astype(np.float32)
        with self._audio_lock:
            self._audio = (
                np.concatenate([self._audio, samples])
                if len(self._audio) else samples.copy()
            )
        self._maybe_emit_chunk(final=False)

    def finalize(self, tail_samples: Optional[np.ndarray] = None, timeout_s: float = 30.0) -> dict:
        """Drain the pipeline and return the final transcription.

        Blocks until all queued chunks are decoded (capped at `timeout_s`).
        Returns the same shape as TranscriberV2.transcribe_rich.
        """
        if tail_samples is not None and len(tail_samples) > 0:
            self.feed_audio(tail_samples)
        # Force-emit whatever audio remains, even if below chunk_min_s
        self._maybe_emit_chunk(final=True)

        # Signal decoder there's no more input; let it drain and exit.
        self._chunk_queue.put((-1, None, True))  # sentinel

        if self._decoder_thread:
            self._decoder_thread.join(timeout=timeout_s)

        # Promote any still-pending tentative chunk text to committed.
        if self._pending_chunk_text:
            self._committed_text = _word_overlap_merge(self._committed_text, self._pending_chunk_text)
            self._pending_chunk_text = ""

        text = self._scrub_junk(self._committed_text)
        with self._audio_lock:
            audio_total = len(self._audio)
        duration_ms = int(audio_total / self.sample_rate * 1000)
        word_count = len(text.split())
        wpm = int(word_count / (duration_ms / 60000)) if duration_ms > 0 else 0
        avg_conf = (
            sum(self._all_probs) / len(self._all_probs) if self._all_probs else 0.0
        )
        return {
            "text": text,
            "segments": self._all_segments,
            "avg_confidence": round(avg_conf, 4),
            "low_confidence_words": list(set(self._low_confidence)),
            "duration_ms": duration_ms,
            "words_per_minute": wpm,
            "detected_language": self.locked_language,
        }

    def stop(self) -> None:
        """Hard stop — abandons any in-flight chunks."""
        self._running = False
        self._stopping = True
        # Drain queue
        try:
            while True:
                self._chunk_queue.get_nowait()
        except queue.Empty:
            pass
        if self._decoder_thread and self._decoder_thread.is_alive():
            self._chunk_queue.put((-1, None, True))
            self._decoder_thread.join(timeout=1.0)

    # ── slicer ─────────────────────────────────────────────────────────────

    def _maybe_emit_chunk(self, final: bool) -> None:
        """Cut a chunk off the buffer if it's ready (or `final=True`)."""
        with self._audio_lock:
            available_samples = len(self._audio) - self._cursor
            available_s = available_samples / self.sample_rate
            min_samples = int(self.chunk_min_s * self.sample_rate)
            target_samples = int(self.chunk_target_s * self.sample_rate)
            max_samples = int(self.chunk_max_s * self.sample_rate)
            overlap_samples = int(self.overlap_s * self.sample_rate)

            pending = self._audio[self._cursor : self._cursor + max_samples + overlap_samples]

            if not final and available_samples < min_samples:
                return

            cut_end: int  # exclusive index into `pending`
            if final:
                # Send everything remaining as the last chunk (no cap).
                cut_end = len(self._audio) - self._cursor
                if cut_end <= 0:
                    return
            elif available_samples >= max_samples:
                # Hard cap reached → force-cut at max
                cut_end = max_samples
            elif available_samples >= target_samples and self.vad is not None:
                # In sweet spot — look for silence to cut at
                cut_in_pending = self._find_silence_boundary(pending, target_samples, max_samples)
                if cut_in_pending is None:
                    return  # wait for more audio
                cut_end = cut_in_pending
            else:
                return

            chunk_audio = self._audio[self._cursor : self._cursor + cut_end].copy()
            # Advance cursor by (cut_end - overlap) so the next chunk starts with
            # `overlap_samples` of audio already-decoded; that's the seam for LA2.
            advance = max(cut_end - overlap_samples, 1) if not final else cut_end
            self._cursor += advance

            chunk_idx = self._next_chunk_idx
            self._next_chunk_idx += 1

        self._chunk_queue.put((chunk_idx, chunk_audio, final))

    def _find_silence_boundary(
        self, pending: np.ndarray, target_samples: int, max_samples: int
    ) -> Optional[int]:
        """Return the first sample index (in `pending`) where a silence ≥
        `silence_min_s` begins, between `target_samples` and `max_samples`.

        Returns `None` if no silence found in that window.
        """
        if self.vad is None:
            return None
        sr = self.sample_rate
        silence_samples = int(self.silence_min_s * sr)
        # Silero v5 wants 512-sample chunks at 16kHz
        chunk_size = 512 if sr == 16000 else 256

        # Walk pending in chunk_size strides starting from target_samples-silence_samples
        # so we can detect silence that starts before target and runs through it.
        start = max(target_samples - silence_samples, chunk_size)
        end = min(len(pending), max_samples)
        if end - start < silence_samples:
            return None

        self.vad.reset_state()
        sr_arr = np.array(sr, dtype=np.int64)
        silent_run = 0
        cut_at: Optional[int] = None
        # We scan through pending in 512-sample windows starting from `start`.
        for i in range(start, end - chunk_size + 1, chunk_size):
            chunk = pending[i : i + chunk_size].astype(np.float32)
            try:
                if self.vad._api == "v5":
                    outputs = self.vad.sess.run(None, {
                        "input": chunk[np.newaxis, :],
                        "sr": sr_arr,
                        "state": self.vad._state,
                    })
                    prob, self.vad._state = outputs
                else:
                    outputs = self.vad.sess.run(None, {
                        "input": chunk[np.newaxis, :],
                        "sr": sr_arr,
                        "h": self.vad._h,
                        "c": self.vad._c,
                    })
                    prob, self.vad._h, self.vad._c = outputs
                p = float(prob[0, 0])
            except Exception:
                return None

            if p < self.vad.threshold:
                silent_run += chunk_size
                if silent_run >= silence_samples:
                    # Cut at the start of this silent run + a tiny margin so we
                    # don't clip the trailing breath of the last word.
                    cut_at = i + chunk_size - silent_run + chunk_size  # silent_run end
                    break
            else:
                silent_run = 0

        return cut_at

    # ── decoder ────────────────────────────────────────────────────────────

    def _decoder_loop(self) -> None:
        # Each chunk's audio overlaps the previous by `overlap_s`. We rely on
        # `_word_overlap_merge` to deduplicate the seam — that's robust even
        # when chunks disagree on exact wording (it finds the longest matching
        # boundary, falls back to space-join only on total disagreement).
        # We tried LocalAgreement-2 as a primary commit policy but its
        # "no agreement" branch duplicated the overlap region, blowing up WER
        # on long-form clips. Overlap-merge alone is simpler and more robust.
        while self._running:
            try:
                idx, audio, is_final = self._chunk_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if idx < 0:
                # Sentinel — drain done
                break
            if audio is None or len(audio) == 0:
                continue
            if self._stopping:
                break

            try:
                text, segments, probs, low_conf = self._decode_chunk(audio, idx)
            except Exception as e:
                self._error = e
                print(f"[streaming] decode chunk {idx} failed: {e}", flush=True)
                continue

            text = self._scrub_junk(text)
            if not text:
                continue

            # Merge: overlap-dedupe against the rolling committed text.
            # When this chunk's audio overlaps the previous chunk's tail
            # (by `overlap_s`), Whisper's transcription of this chunk's first
            # words should match the committed text's last words. The merge
            # finds and trims that overlap.
            if self._committed_text:
                merged = _word_overlap_merge(self._committed_text, text)
            else:
                merged = text

            # Catch hallucinated phrase duplicates — Whisper sometimes emits a
            # phrase twice on chunk boundaries (e.g. "the lazy dog the lazy dog").
            merged = _dedupe_phrase_repeats(merged)
            self._committed_text = merged
            # Tentative is empty under the overlap-merge regime — everything
            # in self._committed_text is the current best estimate. (No need
            # to track LA2 tentative anymore.)
            self._pending_chunk_text = ""

            # Accumulate telemetry
            self._all_segments.extend(segments)
            self._all_probs.extend(probs)
            self._low_confidence.extend(low_conf)

            if self._on_preview is not None:
                try:
                    self._on_preview(self._committed_text, self._pending_chunk_text)
                except Exception:
                    pass

            if is_final:
                break

    def _decode_chunk(
        self, audio: np.ndarray, idx: int
    ) -> tuple[str, list[dict], list[float], list[str]]:
        """Run whisper on a single chunk and return (text, segments, probs, low_conf_words)."""
        # Build initial_prompt = base_prompt + last 100 tokens of committed text.
        # We approximate "tokens" with words; Whisper's encoder accepts up to ~224
        # tokens of prompt, so 100 words ≈ 130-150 tokens — safe.
        prompt_parts = []
        if self.base_prompt:
            prompt_parts.append(self.base_prompt.rstrip())
        if self._committed_text:
            tail_words = self._committed_text.split()[-100:]
            if tail_words:
                prompt_parts.append(" ".join(tail_words))
        initial_prompt = "  ".join(prompt_parts) if prompt_parts else ""

        # Language: detect on first chunk if not pinned, else use locked.
        # Whisper's lang_id has a strong English bias on short clips, so we
        # peek into the full audio buffer (up to 12s) for the detect pass
        # instead of just this chunk. That gives the model more signal and
        # cuts the false-en-detection rate on German/Spanish/etc.
        lang = self.locked_language
        if lang is None and idx == 0:
            try:
                detect_audio = audio
                with self._audio_lock:
                    buf_len = len(self._audio)
                    if buf_len > len(audio):
                        # Use up to 12s of buffered audio (auto_detect_language
                        # only looks at the first 30 mel frames anyway, but
                        # giving it the full available signal helps the
                        # encoder produce a stable hidden state).
                        end = min(buf_len, self.sample_rate * 12)
                        detect_audio = self._audio[:end]
                detect_out = self.model.auto_detect_language(
                    detect_audio, n_threads=self.n_threads,
                )
                code = detect_out[0][0] if isinstance(detect_out, tuple) else None
                prob = detect_out[0][1] if isinstance(detect_out, tuple) else 0
                if code:
                    self.locked_language = code
                    lang = code
                    print(f"[streaming] detected language: {code} (p={float(prob):.2f}, "
                          f"on {len(detect_audio)/self.sample_rate:.1f}s)", flush=True)
            except Exception as e:
                print(f"[streaming] language detect failed, falling back to 'en': {e}", flush=True)
                self.locked_language = "en"
                lang = "en"
        if lang is None:
            lang = "en"

        params: dict = {
            "language": lang,
            "n_threads": self.n_threads,
            "token_timestamps": True,
            "extract_probability": True,
            # Tighten silence rejection so end-of-chunk hallucinations are rarer.
            "no_speech_thold": 0.6,
            "logprob_thold": -1.0,
            # Greedy is faster; reserve beam for verifier pass.
            "temperature": 0.0,
            "suppress_blank": True,
        }
        if initial_prompt:
            params["initial_prompt"] = initial_prompt

        segments = self.model.transcribe(audio, **params)

        text_parts: list[str] = []
        seg_out: list[dict] = []
        probs: list[float] = []
        low_conf: list[str] = []
        import math
        for seg in segments:
            t = seg.text.strip()
            if not t or t in _JUNK:
                continue
            t0 = int(getattr(seg, "t0", 0))
            t1 = int(getattr(seg, "t1", 0))
            raw_prob = getattr(seg, "probability", None)
            p = float(raw_prob) if raw_prob is not None else None
            seg_dict = {"text": t, "t0": t0, "t1": t1}
            if p is not None and not math.isnan(p):
                seg_dict["probability"] = round(p, 4)
                probs.append(p)
                if p < 0.7:
                    for word in t.split():
                        clean = word.strip(".,!?;:'\"").lower()
                        if clean and len(clean) > 1:
                            low_conf.append(clean)
            seg_out.append(seg_dict)
            text_parts.append(t)
        return (" ".join(text_parts).strip(), seg_out, probs, low_conf)

    # ── helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _scrub_junk(text: str) -> str:
        """Remove standalone hallucination tokens from text."""
        if not text:
            return text
        # Drop standalone junk by splitting on spaces and rejecting exact matches
        out = []
        for tok in text.split():
            if tok in _JUNK:
                continue
            out.append(tok)
        cleaned = " ".join(out).strip()
        # Drop entire repeated hallucination phrases that survive token-level filter
        for junk in (". Thank you for watching!", "Thank you for watching!", ". So.", ". Bye."):
            if cleaned.endswith(junk):
                cleaned = cleaned[: -len(junk)].strip()
        return cleaned
