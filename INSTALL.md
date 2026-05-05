# Installing VoiceType

Local voice dictation for macOS. The whole install takes about 60 seconds.

## What you'll do

1. Download `VoiceType.dmg` from [the releases page](https://github.com/polistician/voicetype/releases/latest) or [voicetype.polistician.ai](https://voicetype.polistician.ai/).
2. Double-click the DMG to mount it.
3. Drag **VoiceType** to the **Applications** shortcut.
4. Eject the DMG (right-click the mounted volume in Finder → Eject).
5. Open **/Applications/VoiceType.app** by double-clicking.
6. Click through the Gatekeeper warning (one-time).
7. Grant Microphone + Accessibility permissions.
8. Hold ⌥ C anywhere — talk — text appears.

## Step 5: First launch (Gatekeeper bypass)

VoiceType is open-source, MIT-licensed, and **not signed by Apple's notarization service** (which costs $99/year). On first launch, macOS will warn:

> *"VoiceType cannot be opened because Apple cannot check it for malicious software."*

This is **expected**. To proceed:

1. Click **Done** on the dialog (it's the only button).
2. Open **System Settings → Privacy & Security**.
3. Scroll all the way down to find: *"VoiceType was blocked from use because it is not from an identified developer."* with an **Open Anyway** button.
4. Click **Open Anyway**. Authenticate with your Mac password.
5. Confirm the second dialog ("macOS cannot verify the developer of VoiceType. Are you sure you want to open it?") — click **Open Anyway**.
6. VoiceType launches.

This whole bypass is **one-time only**. After this, VoiceType opens normally with a double-click.

### If something goes wrong

If the Gatekeeper bypass fails or the app doesn't launch after Open Anyway, run **Install.command** from inside the DMG. It will manually clear the macOS quarantine flag from the installed app. Then double-click VoiceType again.

## Step 7: Permissions

VoiceType needs two macOS permissions to function:

- **Microphone** — to hear what you say. Audio is processed locally; nothing is sent over the network.
- **Accessibility** — to press ⌘ V on your behalf so the transcribed text appears in your active app.

The first time you hold ⌥ C, macOS will pop a native dialog asking for Microphone access — click **Allow**.

For Accessibility:

1. Open **System Settings → Privacy & Security → Accessibility**.
2. You'll see VoiceType (or a `hotkey_helper` entry) in the list — toggle **ON**.
3. If it's not in the list, click **+**, navigate to `/Applications/VoiceType.app/Contents/Frameworks/hotkey_helper`, click Open, then toggle ON.

## Step 8: First dictation

Open any text field (TextEdit, Slack, Cursor, your browser's address bar, ChatGPT). **Hold ⌥ C** for 1-2 seconds, **say a sentence**, **release**.

The text appears where your cursor was.

## Optional: DeepL translation

Click the menubar 🎤 icon → **Settings…** → paste a DeepL API key → Verify → Save. Then VoiceType will translate as it pastes — speak in any language, paste English (or whatever target you set in the menubar's "Output Language" submenu).

A free DeepL API key gives you 500,000 characters per month. [Get one here](https://www.deepl.com/pro-api).

## Updating

VoiceType doesn't auto-update. To get the latest version:

1. Download the new `VoiceType.dmg` from [Releases](https://github.com/polistician/voicetype/releases/latest).
2. Drag the new VoiceType into Applications (Finder will ask to replace the existing copy — say yes).
3. Done. Your settings, vocabulary, and snippets are preserved (they live in `~/.voicetype/`, separate from the .app).

## Removing

1. Quit VoiceType: menubar 🎤 → Quit.
2. Drag `/Applications/VoiceType.app` to the Trash.
3. (Optional) Remove your data: `rm -rf ~/.voicetype`.
4. (Optional) Remove permission grants: System Settings → Privacy & Security → Accessibility / Microphone — remove any VoiceType entries.

## Privacy

What stays on your laptop:
- Audio recordings (briefly in memory, never written to disk)
- Transcribed text
- Vocabulary VoiceType learns from your use
- Saved snippets
- Settings + statistics

What leaves your laptop:
- DeepL translation requests — **only if you've added a DeepL key**.
- Nothing else.

API keys are stored in your **macOS Keychain**, never in plaintext config files.

## License

MIT. See [LICENSE](https://github.com/polistician/voicetype/blob/main/LICENSE).

## Source

[github.com/polistician/voicetype](https://github.com/polistician/voicetype)
