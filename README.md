## Snippets

VoxType includes a voice + keyboard snippet manager.

### Invocation

**Voice (hold Option+C):**
- `snippet <description>` → paste the snippet matching that description (e.g. "snippet deploy the crypto app")
- `open snippet overview` → opens the manager
- `save snippet from clipboard` → creates a new snippet with the clipboard body

**Keyboard:**
- `Option+Shift+S` — open the manager
- Inside the manager:
  - `↑↓` navigate, `⏎` paste, `Esc` close
  - `⌘N` new, `⌘E` edit, `⌘⌫` delete
  - Hold `Option+C` inside the manager to dictate a search query

### How reliable matching works

1. Whisper is primed with trigger words + snippet names as vocabulary.
2. `rapidfuzz` catches Whisper misrecognitions like "snipped", "senate", "snippets".
3. A rule-based router picks the action (paste / open / save).
4. `mxbai-embed-xsmall-v1` embeddings rank candidates by meaning.
5. Confidence gate: >0.75 pastes directly, 0.55–0.75 shows a 3-option picker, <0.55 opens the manager with the query pre-filled.
