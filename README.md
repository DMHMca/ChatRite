# ChatRite

Local dictation tools for Windows. Everything runs on your own PC.

- **ChatRite** (`cleanup/`): AutoHotkey v2. Press Ctrl+Shift+Space in any text box to fix speech-to-text mistakes, or Ctrl+Shift+Alt+Space to polish punctuation and capitals, using a language model running locally in Ollama.
- **ChatRite Dictate** (`dictate/`): Python. Switch it on once and it keeps listening and types what you say into whichever window has focus, using Whisper on your NVIDIA graphics card.

Set-up page: https://dmhmca.github.io/get-a-grip/cleanup/ (moves when this project gets its own address).

For people working on the code: read `CLAUDE.md`, then `HANDOVER.md`.

Nothing is sent anywhere except Ollama on the same PC, GitHub Pages for update checks, and one-off model downloads.
