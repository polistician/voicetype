# VoiceType v0.13 — WhisperKit + multi-language streaming

**Status:** Spec / pre-implementation
**Author:** Claude (Opus 4.7) for polistician
**Date:** 2026-05-12
**Supersedes:** v0.12.x streaming pipeline (kept as fallback)
**Blocks:** v0.14 Canary backend, v0.15 model selector UI

---

## 1. Why this exists

v0.12.x shipped streaming chunked transcription via `pywhispercpp` running on
Metal-GPU. It works — long-clip latency dropped 3–4×, English accuracy is at
or above offline baseline. But two things are leaving value on the table:

1. **The Apple Neural Engine is idle.** All current decode runs on Metal-GPU.
   M-series chips have a dedicated ML accelerator (ANE) that whisper.cpp can't
   target. WhisperKit (Argmax, MIT-licensed) compiles Whisper to CoreML
   specifically for ANE and runs the same model **~2.5× faster** with
   identical weights. Free speed.

2. **Language detection is per-clip, not per-chunk.** Spoken stretches in
   different languages within one clip are forced into a single language by
   the session-level lock in `streaming_transcriber.py`. A user dictating in
   English then switching to German mid-recording gets the second half
   mangled. The fix is cheap (~50 ms per chunk) — we already auto-detect on
   chunk 0; just lift the lock conditionally.

While we're touching the transcriber, we also fix the architectural debt
that's been growing since v0.10: the model backend is hard-coded as
`TranscriberV2 → pywhispercpp.Model`. Future ships (Canary, Parakeet,
Moonshine, Distil-Whisper) need a clean abstraction. v0.13 introduces it.

---

## 2. Goals

### Must-haves (gate v0.13 ship)

1. **WhisperKit backend** running the same large-v3-turbo model with ≥ 2×
   speedup on M-series, identical or better WER on the v0.12 synthetic bench.
2. **Backend abstraction**: `TranscriberBackend` protocol with two
   implementations (`WhisperCppBackend`, `WhisperKitBackend`). All call sites
   in `voxtype.py` / `streaming_transcriber.py` go through the abstraction.
3. **Per-chunk language re-detection** when `input_language == "auto"`. Lock
   is downgraded from session-level to chunk-level with confidence thresholding.
4. **Verifier default-on** for clips ≥ 6 s (was 8 s, off by default).
   ANE-accelerated WhisperKit makes beam-5 verifier nearly free.
5. **Backwards compatibility**: whisper.cpp backend still works as fallback;
   user's `config.json`, `profile.json`, `corrections.json`, vocab biasing
   all survive unchanged.
6. **DMG size budget**: stay under 2 GB compressed (current is 1.4 GB).

### Nice-to-haves (if time permits, otherwise v0.14)

- Settings → **Models** tab with per-backend status badge
- Live language indicator in menubar (detected lang shown next to status)
- Per-chunk re-detect confidence threshold exposed in Settings

### Non-goals (explicitly deferred)

- Canary-1B / Parakeet / Moonshine backends. The abstraction must
  *accommodate* them but v0.13 ships only WhisperKit + whisper.cpp.
- Settings → Learning tab (separate work; tracked as v0.13.x follow-up).
- Download-on-demand model manager. v0.13 still bundles a single model
  (whichever WhisperKit ships as `large-v3-turbo`); v0.15 adds DLs.
- Floating live-preview overlay window. Menubar preview stays as the surface.
- Intra-sentence code-switching (genuine bilingual speech). Per-chunk detect
  helps long monolingual stretches; intra-sentence is Canary's territory.

---

## 3. Architecture

```
                 ┌──────────────────────────────────────────┐
                 │             voxtype.py                   │
                 │  (recording lifecycle, menubar, paste)   │
                 └────────────────┬─────────────────────────┘
                                  │ uses
                                  ▼
                 ┌──────────────────────────────────────────┐
                 │      streaming_transcriber.py            │
                 │  (chunk pipeline, overlap-merge dedup,   │
                 │   prompt carryover, phrase dedup)        │
                 └────────────────┬─────────────────────────┘
                                  │ uses
                                  ▼
                 ┌──────────────────────────────────────────┐
                 │       transcriber_backend.py             │
                 │           (NEW — abstract)               │
                 │                                          │
                 │   class TranscriberBackend(Protocol):    │
                 │       transcribe(...) -> RichResult      │
                 │       detect_language(...) -> (str,float)│
                 │       set_language(code: str)            │
                 │       set_vocabulary(words: list[str])   │
                 │       base_prompt: str                   │
                 │       load() / unload() / is_loaded      │
                 │       name: str   # for telemetry        │
                 └─────────┬────────────────────┬───────────┘
                           │                    │
              ┌────────────┘                    └────────────┐
              ▼                                              ▼
  ┌─────────────────────────┐              ┌─────────────────────────┐
  │ whisper_cpp_backend.py  │              │ whisperkit_backend.py   │
  │  (fallback, was V2)     │              │  (NEW — ANE primary)    │
  │  pywhispercpp.Model     │              │  spawns whisperkit_      │
  │  Metal GPU              │              │  helper subprocess,      │
  │                         │              │  JSON-stdio bridge       │
  └─────────────────────────┘              └────────────┬────────────┘
                                                        │ spawns
                                                        ▼
                                          ┌─────────────────────────────┐
                                          │  whisperkit_helper.swift    │
                                          │  (NEW — Swift binary)       │
                                          │                             │
                                          │  Swift Package: WhisperKit   │
                                          │  CoreML-compiled Whisper     │
                                          │  Runs on Apple Neural Engine │
                                          │                             │
                                          │  stdin/stdout JSON protocol  │
                                          └─────────────────────────────┘
```

Two backends, identical surface, identical output shape. `voxtype.py` picks
one at startup based on config + capability check (ANE availability).

---

## 4. New module: `transcriber_backend.py`

The protocol is small on purpose. Everything else moves into the backends.

```python
# transcriber_backend.py
"""Abstract backend protocol for VoiceType transcribers.

Two implementations ship in v0.13:
    - WhisperCppBackend (was TranscriberV2)
    - WhisperKitBackend (ANE-accelerated, default on M-series)

Future implementations slot in here (Canary, Parakeet, Moonshine).
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable
import numpy as np


class RichResult(dict):
    """Output shape — matches TranscriberV2.transcribe_rich for compat.

    Keys:
        text                str
        segments            list[{text, t0, t1, probability?}]
        avg_confidence      float
        low_confidence_words list[str]
        duration_ms         int
        words_per_minute    int
        detected_language   str | None
        backend             str   # NEW in v0.13: which backend produced this
    """


@runtime_checkable
class TranscriberBackend(Protocol):
    name: str                  # e.g. "whispercpp", "whisperkit"
    base_prompt: str           # current vocab-biased initial_prompt

    def load(self) -> None: ...
    def is_loaded(self) -> bool: ...
    def unload(self) -> None: ...

    def set_language(self, code: str | None) -> None: ...
    def set_vocabulary(self, words: list[str]) -> None: ...

    def detect_language(self, audio: np.ndarray) -> tuple[str, float]: ...

    def transcribe(
        self,
        audio: np.ndarray,
        *,
        language: str | None = None,
        initial_prompt: str = "",
        beam_size: int = 0,           # 0 = greedy
        no_speech_thold: float = 0.6,
        logprob_thold: float = -1.0,
    ) -> RichResult: ...


def pick_default_backend(cfg: dict) -> str:
    """Return 'whisperkit' on Apple Silicon with helper available; else
    'whispercpp'. Honors explicit cfg['transcriber_backend'] override.
    """
```

---

## 5. Backend: `whisperkit_backend.py`

### 5.1 Subprocess bridge (matches existing helper pattern)

WhisperKit is a Swift library. We can't import it from Python; we wrap it in
a Swift binary and talk to it over stdin/stdout JSON — same pattern as
`overlay_bridge.py` / `settings_window` / `onboarding`.

```
Python → Swift (one JSON line per request):
    {"op":"load","model_path":"/path/to/.mlmodelc"}
    {"op":"set_lang","code":"de"}
    {"op":"set_vocab","words":["polystition","Berlin",...]}
    {"op":"detect","audio_b64":"...","sr":16000}
    {"op":"transcribe","audio_b64":"...","sr":16000,
     "lang":"auto"|"en"|...,"prompt":"...","beam_size":0,
     "no_speech_thold":0.6,"logprob_thold":-1.0,"id":42}
    {"op":"unload"}

Swift → Python:
    {"event":"loaded","model":"large-v3-turbo","took_ms":1234}
    {"event":"detect_result","code":"de","prob":0.91,"id":42}
    {"event":"transcribe_result","id":42,
     "text":"...","segments":[...],"avg_logprob":-0.31,
     "detected_lang":"de","took_ms":420}
    {"event":"error","id":42,"message":"..."}
```

Audio payloads are float32 16 kHz PCM, base64-encoded. For a 30 s clip
that's ~640 KB encoded — fits comfortably in a single stdio line.
(Alternative: shared-memory mmap. Worth it only if encoding overhead shows up
in profiling; not expected.)

### 5.2 Swift helper: `whisperkit_helper.swift`

```swift
import Foundation
import WhisperKit

@main
struct WhisperKitHelper {
    static func main() async {
        var whisper: WhisperKit? = nil
        // Buffered stdin reader → JSON-decode each line → dispatch.
        // Buffered stdout writer with explicit flushes after each event.
        // Errors caught at boundary; emit {"event":"error",...} not exit.
    }
}
```

Lifecycle: spawn once at app start, stays alive for the session. On config
change (model swap, language pin), send `{"op":"load"}` or `{"op":"set_lang"}`
— no restart. Subprocess crash → Python detects EOF → falls back to
`WhisperCppBackend` automatically.

### 5.3 Model file format

WhisperKit uses Apple CoreML's `.mlmodelc` directory format, not whisper.cpp's
`.bin`. Models are downloadable from
`https://huggingface.co/argmaxinc/whisperkit-coreml` per release.

Bundle `openai_whisper-large-v3-turbo` (the WhisperKit equivalent of our
current model). Size on disk: ~1.4 GB — same ballpark as current 1.5 GB GGML.

DMG net change: **+0 to +200 MB** (we drop the GGML model if we commit fully
to WhisperKit, or keep both for fallback and pay the storage cost).

Strategy for v0.13: **keep both bundled** (whisper.cpp `.bin` for fallback,
WhisperKit `.mlmodelc` for primary). Total: ~3 GB on-disk. DMG compresses to
~1.6 GB. Acceptable.

v0.14: introduce model download-on-demand; drop bundled `.bin`. DMG falls
back under 1 GB.

### 5.4 Build integration

`build/VoiceType.spec` additions:

- Add `whisperkit_helper` to `swift_helpers` list
- Add `models/whisperkit/openai_whisper-large-v3-turbo` directory tree to
  `model_files`
- `build/build-app.sh` step to compile the Swift helper with Swift Package
  Manager:
  ```
  swift build -c release --package-path build/whisperkit-helper
  cp .build/release/whisperkit-helper /Users/beauregard/voicetype/whisperkit_helper
  ```
- WhisperKit Swift Package declared in `Package.swift` at
  `build/whisperkit-helper/Package.swift`
- Code-sign + bundle into `.app/Contents/Frameworks/`

PyInstaller doesn't need to know about WhisperKit's CoreML model — it's a
data file, treated like any other.

---

## 6. Backend: `whisper_cpp_backend.py`

This is `TranscriberV2` renamed and adapted to the new protocol. Public
behavior unchanged. Used as fallback whenever WhisperKit is unavailable
(non-Apple-Silicon, bundle missing, helper crash, user pin via config).

```python
# whisper_cpp_backend.py
from transcriber_backend import TranscriberBackend, RichResult

class WhisperCppBackend(TranscriberBackend):
    name = "whispercpp"

    def __init__(self, model_path: str, n_threads: int = 4):
        self.model_path = model_path
        self.model = None  # lazy-loaded
        ...

    def load(self) -> None:
        from pywhispercpp.model import Model
        self.model = Model(self.model_path, n_threads=self._n_threads)

    # ... (rest is TranscriberV2 logic, mechanically lifted)
```

Net code change: a rename + a few mechanical changes to the constructor and
the rich-result emission. The transcribe logic itself is untouched.

---

## 7. Changes to existing files

### 7.1 `streaming_transcriber.py`

Replace direct `self.model` access with backend protocol calls.

```python
class StreamingTranscriber:
    def __init__(
        self,
        backend: TranscriberBackend,    # was: model: pywhispercpp.Model
        vad=None,
        ...
    ):
        self.backend = backend
        ...
```

Inside `_decode_chunk`:
```python
result = self.backend.transcribe(
    audio,
    language=lang,
    initial_prompt=initial_prompt,
    beam_size=0,
    no_speech_thold=0.6,
    logprob_thold=-1.0,
)
```

Inside language-detect block:
```python
code, prob = self.backend.detect_language(detect_audio)
```

**New behavior — per-chunk re-detect:**

```python
# Replace the chunk-0-only detect with a per-chunk policy.
# Two thresholds:
#   - PROMOTE: confidence at which we accept the new language
#   - DEMOTE:  confidence at which we drop the locked language
DETECT_PROMOTE = 0.85
DETECT_HYSTERESIS = 0.15  # require new lang's prob to beat locked by this

if self.session_pinned_language is None:
    # auto mode
    new_code, new_prob = self.backend.detect_language(audio)
    if self.locked_language is None or self.locked_language == "en":
        # Adopt new only if confident enough
        if new_prob >= DETECT_PROMOTE:
            self.locked_language = new_code
    elif new_code != self.locked_language:
        # Locked language switch: require new lang's confidence to clearly
        # beat the locked one. Avoids flicker on uncertain chunks.
        if new_prob >= self.locked_language_prob + DETECT_HYSTERESIS:
            self.locked_language = new_code
            self.locked_language_prob = new_prob
```

Hysteresis matters: without it, every uncertain chunk flips the language and
the output becomes "Hallo, my name is Beau, ich freue mich…" with weird
phonology drift.

### 7.2 `voxtype.py`

Replace `from transcriber_v2 import TranscriberV2` with:

```python
from transcriber_backend import pick_default_backend
from whisper_cpp_backend import WhisperCppBackend
from whisperkit_backend import WhisperKitBackend
```

Replace `_load_model` body:

```python
def _load_model(self):
    model_dir = self.cfg["model_dir"]
    backend_name = self.cfg.get(
        "transcriber_backend", pick_default_backend(self.cfg),
    )
    if backend_name == "whisperkit":
        try:
            self.transcriber = WhisperKitBackend(
                model_path=os.path.join(model_dir, "whisperkit/openai_whisper-large-v3-turbo"),
            )
            self.transcriber.load()
        except Exception as e:
            print(f"[backend] WhisperKit failed ({e}), falling back to whisper.cpp", flush=True)
            backend_name = "whispercpp"

    if backend_name == "whispercpp" or not getattr(self, "transcriber", None):
        ggml_path = os.path.join(model_dir, f"ggml-{self.cfg['model']}.bin")
        self.transcriber = WhisperCppBackend(model_path=ggml_path)
        self.transcriber.load()

    self.transcriber.set_language(self.cfg.get("input_language", "auto"))
    # ... rest of vocab biasing unchanged
```

Pass `self.transcriber` (the backend) into `StreamingTranscriber` constructor
instead of `self.transcriber.model`.

### 7.3 `config.py`

New keys:

```python
DEFAULT_CONFIG = {
    ...
    # Transcriber backend. "auto" → pick_default_backend picks based on
    # capability (WhisperKit on Apple Silicon, whisper.cpp elsewhere).
    # Force a specific backend by setting to "whispercpp" or "whisperkit".
    "transcriber_backend": "auto",
    # Per-chunk re-detection of input language (auto mode only). On long
    # clips that span languages, this lets each chunk pick its own.
    # Hysteresis prevents flicker.
    "per_chunk_lang_detect": True,
    # Default verifier-on (was off). ANE-accelerated WhisperKit makes the
    # beam-5 verifier nearly free; net latency unchanged, accuracy ↑.
    "verifier_enabled": True,
    "verifier_min_duration_s": 6.0,    # was 8.0
}
```

### 7.4 `build/VoiceType.spec`

```python
swift_helpers = []
for h in ["hotkey_helper", "paste_helper", "snippet_overlay",
          "settings_window", "onboarding", "keys_helper",
          "whisperkit_helper"]:   # NEW
    p = os.path.join(HOME, h)
    if os.path.exists(p):
        swift_helpers.append((p, "."))

# WhisperKit CoreML model bundle (directory tree)
whisperkit_model_dir = os.path.join(MODELS_DIR, "whisperkit", "openai_whisper-large-v3-turbo")
if os.path.isdir(whisperkit_model_dir):
    for root, _, files in os.walk(whisperkit_model_dir):
        rel_root = os.path.relpath(root, MODELS_DIR)
        for fn in files:
            model_files.append((os.path.join(root, fn),
                                os.path.join("models", rel_root)))

hiddenimports=[
    ...
    "whisper_cpp_backend",
    "whisperkit_backend",
    "transcriber_backend",
],
```

### 7.5 `paths.py`

Add `helper_path("whisperkit_helper")` resolution (same pattern as existing
helpers). No code change needed if `_resolve_helper` is generic.

---

## 8. Migration

### Phase 1 — Backend abstraction (low-risk refactor)
Day 1–2. Pure refactor. No behavior change. After this, both backend names
exist but only `WhisperCppBackend` does anything.

- [ ] Create `transcriber_backend.py` with protocol
- [ ] Rename `transcriber_v2.py` → `whisper_cpp_backend.py`, conform to protocol
- [ ] Update `voxtype.py` imports + `_load_model` + `_spawn_streamer`
- [ ] Update `streaming_transcriber.py` constructor + `_decode_chunk`
- [ ] Smoke-test: `python -m bench` shows identical output to v0.12.2 baseline

**Ship gate:** WER unchanged on the v0.12 synthetic bench (short_en, medium_en,
long_en, medium_de). Latency within ±5%.

### Phase 2 — WhisperKit helper (Swift, isolated)
Day 3–5. Build the Swift binary in isolation; no Python integration yet.

- [ ] `build/whisperkit-helper/Package.swift` declaring WhisperKit dep
- [ ] `whisperkit_helper.swift` implementing the JSON-stdio protocol
- [ ] Download WhisperKit's `openai_whisper-large-v3-turbo` `.mlmodelc` bundle
- [ ] Manual test: pipe a base64 audio sample to the binary, verify output JSON

**Ship gate:** Standalone helper transcribes a 5 s WAV in < 1 s on M4.

### Phase 3 — Wire WhisperKit backend (Python integration)
Day 6–7. Create `whisperkit_backend.py` that spawns the helper and routes
calls through.

- [ ] `whisperkit_backend.py` with subprocess management + JSON bridge
- [ ] Streaming pipeline + verifier path both work through WhisperKit
- [ ] Cold-start handling (helper boot takes time; queue requests during load)
- [ ] Crash recovery (auto-fallback to WhisperCppBackend on helper EOF)
- [ ] Per-chunk language re-detect with hysteresis

**Ship gate:** Bench results show:
- Latency: ≥ 2× faster on long_en than v0.12 (tail wait drops from ~0.6 s to
  ~0.25 s, full-clip decode time drops from ~2 s to ~0.8 s).
- WER: identical or better than v0.12 on all four bench cases.
- Per-chunk re-detect: feeds a synthetic EN→DE switch and verify both
  halves transcribe in their correct language.

### Phase 4 — Build + ship
Day 8.

- [ ] PyInstaller spec updated to bundle WhisperKit helper + `.mlmodelc`
- [ ] DMG size check (target < 2 GB compressed)
- [ ] In-app updater test: install v0.12.2, click "Check for Updates",
      arrive at v0.13.0
- [ ] Release notes + migration FAQ
- [ ] Commit + tag + ship

---

## 9. Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| WhisperKit model bundle bloats DMG past 2 GB | Medium | Drop the `.bin` if WhisperKit proves stable in user testing; revisit at v0.14 |
| Swift Package Manager fails to integrate into PyInstaller flow | Medium | Build helper externally, copy binary into bundle (same pattern as existing helpers; already proven) |
| ANE returns slightly different numerical results vs Metal | Low | Already accepted: same Whisper weights → same output up to FP rounding. Bench gates regression |
| WhisperKit's CoreML compilation step pegs CPU on first load | High | Pre-compile during build, ship the compiled `.mlmodelc` (not `.mlpackage`). First-launch latency stays cold |
| Subprocess bridge IPC overhead negates ANE speedup | Low | base64-over-stdio is ~0.5 ms per 30 s clip. Negligible vs 200+ ms decode |
| Per-chunk re-detect flickers mid-sentence | Medium | Hysteresis threshold (0.15) + require 2 successive chunks to flip before commit |
| User's custom config keys conflict | Low | All new keys are additive; old configs continue to work; defaults applied for missing keys |

---

## 10. Future-proofing (v0.14+)

The abstraction is designed so each future backend is one file. Sketch:

**v0.14 — Canary-1B**
- New file: `canary_backend.py`
- Embeds NeMo via PyInstaller (heavy: +4 GB deps); or runs in its own venv
  managed by VoiceType
- Settings → Models tab: download button, removes Canary on toggle-off
- Targets users who routinely speak intra-sentence mixed languages

**v0.15 — Parakeet-TDT / Moonshine**
- English-only fast paths. Same backend pattern.
- User picks "Speed mode" in Settings; we route to Parakeet (5–10× faster
  than Whisper for EN) and gray out non-EN languages in the Input Language menu.

**v0.16 — Model selector UI**
- Settings tab listing each backend with:
  - Disk size
  - Languages supported
  - Speed rating
  - Status: **Active** / Downloaded / Available to download
- Toggle activates one backend; "Remove" frees disk
- Download progress via the same Swift Settings helper (extends
  `overlay_bridge.SettingsBridge` with new event types)

**v0.17 — Cross-backend speculative ASR**
- Run streaming with the fast backend (Moonshine), verify with the accurate
  backend (Whisper / Canary)
- The current `verifier_enabled` toggle becomes the on-ramp for this
- ANE + Metal parallelism means the two backends genuinely run concurrently

---

## 11. Backwards compatibility

| Surface | v0.12.2 | v0.13 | Notes |
|---|---|---|---|
| `~/.voicetype/config.json` | works | works | New keys added; old keys honored |
| `~/.voicetype/profile.json` | works | works | Unchanged schema |
| `~/.voicetype/corrections.json` | works | works | Unchanged schema |
| Output Language menu | works | works | Unchanged |
| Input Language menu | works | works | Unchanged; affects both backends |
| Settings → DeepL key | works | works | Unchanged |
| Settings → Integrator | works | works | Unchanged |
| In-app updater | works | works | Same channel; v0.13.0 → v0.12.2 users get prompt |
| Hotkeys (⌥C, ⌥T, ⌥⇧S) | works | works | Unchanged |
| `TranscriberV2` symbol import | exists | aliased | Re-exported from `whisper_cpp_backend` for any downstream import |

---

## 12. Testing plan

### Unit
- `transcriber_backend.py` protocol conformance test for both backends
- `streaming_transcriber.py` per-chunk re-detect: synthetic EN→DE clip,
  expect both halves correctly transcribed
- Hysteresis test: alternating-confidence chunks shouldn't flip language

### Integration
- Existing v0.12 synthetic bench (`/tmp/vt_bench/bench.py`) extended to run
  both backends and compare:
  - WER per case, per backend
  - Latency per case, per backend
  - WhisperKit must be ≥ 2× faster on long_en with WER no worse
- Crash recovery: kill `whisperkit_helper` mid-recording → verify
  `voxtype.py` falls back to whisper.cpp without user-visible break

### Manual (M4 Pro)
- Short, medium, long English clips with auto language: verify menubar
  preview, perceived wait, accuracy
- German clip with menubar pinned to German: should be in German
- German clip with auto: verify the longer-detection window catches it
- Mid-clip language switch: speak 10 s English, 10 s German in one clip;
  verify per-chunk re-detect produces correctly-transcribed halves
- All TextEdit, VSCode, Safari, Mail — verify per-app vocab biasing still
  fires through the new backend abstraction

---

## 13. Open questions tracked, not blocking ship

1. WhisperKit's `WhisperKit.transcribe(...)` API supports streaming natively
   (it has a `decodingOptions.usePrefillPrompt` for prompt carryover and
   chunk callbacks). Should we drop our own chunk pipeline in favor of
   WhisperKit's? **Decision: not for v0.13.** Our chunk pipeline is backend-
   agnostic and lets us swap to Canary later without rewriting the streaming
   layer. WhisperKit's native streaming is a v0.14 optimization candidate.
2. Should the verifier pass run on the *other* backend for true speculative
   ASR (whisper.cpp greedy stream → WhisperKit beam verify)? **Decision: no
   for v0.13.** Both paths run on WhisperKit. The cross-backend variant
   becomes interesting only with Canary; tracked for v0.17.
3. CoreML model compilation can be deferred to first run, which costs ~30 s
   on first launch but ships smaller. **Decision: ship pre-compiled
   `.mlmodelc`.** First-launch UX matters more than a 200 MB saving.

---

## 14. Definition of "ready to ship"

All of:

- [ ] Bench shows ≥ 2× speedup on long_en, no WER regression on any case
- [ ] German auto-detect works on user's real speech (validated manually)
- [ ] Mid-clip EN→DE switch produces correct per-half transcription
- [ ] Crash recovery: helper kill mid-recording results in seamless fallback
- [ ] DMG ≤ 2 GB compressed
- [ ] In-app updater path verified: 0.12.2 → 0.13.0
- [ ] Release notes drafted, migration FAQ for users who pinned a backend manually
