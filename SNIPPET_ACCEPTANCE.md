# Snippet Manager Acceptance Checklist

Walk through each row against a freshly-started VoxType. If anything fails, the "Failure" column tells you what to look at. Expected terminal output assumes you're tailing `~/.voxtype/voxtype.log`.

## Preparation

```bash
# Stop the launchd-managed VoxType so we get a clean code reload
launchctl unload ~/Library/LaunchAgents/com.voxtype.app.plist

# (Optional) wipe the snippet DB to start fresh
rm -f ~/.voxtype/snippets.db

# Make sure the bundle is consistently signed
codesign --force --deep --sign - /Users/beauregard/voxtype/VoxType.app

# Start VoxType
launchctl load ~/Library/LaunchAgents/com.voxtype.app.plist

# Tail the log in another terminal
tail -f ~/.voxtype/voxtype.log
```

Expected startup lines in the log:

```
Loading Whisper model...
Loaded N vocabulary words (including snippet triggers)
Model loaded!
[hotkey_helper] PERMISSIONS: AXTrusted=true CGPostAccess=true
Hotkey listener active (Option+C, Option+T, Option+Shift+S)
Embedder loaded
```

If `AXTrusted=false` → re-toggle `hotkey_helper` in System Settings → Privacy & Security → Accessibility.

## Matrix

| # | Step | Expected | Failure points |
|---|------|----------|----------------|
| 1 | Hold Option+C, say "hello world" | Pastes `hello world`; log shows `[intent] dictate` | Dictation broken — check Accessibility |
| 2 | Press Option+Shift+S | Overlay opens (search field, empty list) | Accessibility grant missing; log shows `OPEN_OVERLAY` not arriving |
| 3 | Esc | Overlay closes | `[overlay] DISMISSED` in log |
| 4 | Option+Shift+S → ⌘N → fill name=`deploy v3`, description=`push crypto app`, body=`./deploy.sh v3` → Save | Editor closes; list shows new row `deploy v3 — 0×` | `CREATE` event in log; if no row appears, `SNIPPETS` push failed |
| 5 | ⌘N again → `brew cleanup` / `free disk space` / `brew cleanup -s` → Save | Second row appears | same as #4 |
| 6 | Hold Option+C, say "snippet deploy v3" | Pastes `./deploy.sh v3`; log shows `[intent] paste_snippet` + `[match] top=... score=0.X direct` | Embedder not loaded, or match score below threshold |
| 7 | Hold Option+C, say "snippet push the crypto app to production" | Either direct-paste (if score >0.75) or mini picker with 3 options → press 1 | If picker doesn't appear, `PICKER` message didn't reach overlay |
| 8 | Hold Option+C, say "snippet quantum hamiltonian eigenstate" | Full overlay opens in search mode with the query pre-filled | `mode="search"` + `query=...` in OPEN event |
| 9 | Hold Option+C, say "open snippets" | Overlay opens | `[intent] open_overview` in log |
| 10 | Copy text to clipboard. Hold Option+C, say "save snippet from clipboard" | Overlay opens, capture strip shows clipboard preview | `[intent] save_snippet` + `draft_body` set in OPEN event |
| 11 | Select `deploy v3` → ⌘E → rename to `deploy v3 prod` → Save | Row reflects rename | `UPDATE` event + re-embedding |
| 12 | Hold Option+C, say "snippet deploy v3 prod" | Pastes correctly | Confirms re-embedding works |
| 13 | Select `brew cleanup` → ⌘⌫ | Row removed | `DELETE` event + snippet removed from list |
| 14 | `launchctl unload`; `launchctl load` | On restart, repeat #12 — still works | Confirms persistence + cache rebuild from SQLite |

## If anything fails

Open a bug with:
1. The row # that failed
2. The last ~50 lines of `~/.voxtype/voxtype.log`
3. What happened vs. what should have happened

The SQLite cross-thread bug and the hotkey_helper diagnostic forwarding were already fixed in commit `5e4332b`. Any new errors are likely new regressions.
