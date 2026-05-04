# VoiceType

Local voice dictation for macOS. Hold ⌥ C, speak, the words paste into whatever app you were just typing in. Whisper.cpp runs on your laptop. Audio never leaves the machine.

Site: https://voicetype.polistician.ai
Download: https://github.com/polistician/voicetype/releases/latest

## What it does

- **Dictate** — voice to text in any app that accepts ⌘V.
- **Steer** — configure custom voice commands. Say `help`, the settings overlay opens. Say a saved phrase name, the saved text pastes itself.
- **Translate** — optional. Drop a DeepL API key into Settings and VoiceType translates as it pastes.

## Install

Download `VoiceType.dmg` from the Releases page → drag to Applications → right-click → Open (one-time Gatekeeper bypass) → grant Microphone + Accessibility → hold ⌥ C.

The first launch shows a 4-screen guided onboarding (welcome → permissions → live dictation tutorial → optional API key).

## Build from source

```bash
git clone https://github.com/polistician/voicetype.git
cd voicetype
./install.sh         # installs deps, downloads Whisper model
./build/release.sh    # builds VoiceType.app + DMG
```

## Privacy

What stays on your laptop: audio, transcripts, vocabulary, snippets, corrections, statistics, decision log.

What leaves your laptop: only DeepL translation requests, only if you've added a DeepL key in Settings.

API keys (DeepL etc.) are stored in macOS Keychain, never in plaintext config files.

## License

MIT — see [LICENSE](./LICENSE).
