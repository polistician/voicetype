# VoiceType

Local voice dictation for macOS. Hold ⌥ C, speak, the words paste into whatever app you were just typing in. Whisper.cpp runs on your laptop. **Audio never leaves the machine.**

Site: https://voicetype.polistician.ai
Download: https://github.com/polistician/voicetype/releases/latest

## What it does

- **Dictate** — voice to text in any app that accepts ⌘V.
- **Steer** — configure custom voice commands. Say `help`, the settings overlay opens. Say a saved phrase name, the saved text pastes itself.
- **Translate** — optional. Drop a DeepL API key into Settings and VoiceType translates as it pastes.
- **AI cleanup** — optional, off by default. Pair your ChatGPT subscription via [Integrator](https://integrator.polistician.ai) and VoiceType will tidy each transcript (remove "um"s, fix punctuation, restructure rambling speech) before pasting. Audio still never leaves your Mac — only the transcript text.

## Install

Download `VoiceType.dmg` from the Releases page → drag to Applications → right-click → Open (one-time Gatekeeper bypass) → grant Microphone + Accessibility → hold ⌥ C.

The first launch shows a 5-screen guided onboarding (welcome → permissions → live dictation tutorial → optional DeepL key → optional AI cleanup pairing).

## Build from source

```bash
git clone https://github.com/polistician/voicetype.git
cd voicetype
./install.sh         # installs deps, downloads Whisper model
./build/release.sh    # builds VoiceType.app + DMG
```

## Privacy

**Audio never leaves your Mac** — Whisper.cpp transcribes locally, always.

What stays on your laptop by default: audio, transcripts, vocabulary, snippets, corrections, statistics, decision log.

What can optionally leave your laptop, only after you opt in:

- **DeepL translation requests** — only the transcript text, only if you've added a DeepL key in Settings.
- **AI cleanup** — only the transcript text, only if you've paired Integrator and enabled "AI cleanup" in Settings. Transcripts are sent to ChatGPT (via your own subscription, brokered by [Integrator](https://integrator.polistician.ai)) for cleanup before pasting. Off by default. The cleanup call has a 2-second budget — if anything goes wrong (network down, Integrator unreachable, slow response), VoiceType silently falls back to pasting the raw transcript.

API keys (DeepL) and OAuth tokens (Integrator) are stored in macOS Keychain, never in plaintext config files.

## License

MIT — see [LICENSE](./LICENSE).
