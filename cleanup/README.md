# ChatRite

A small AutoHotkey v2 script. Press Ctrl+Shift+Space in any Windows text box: it copies the selected text (or the whole box if nothing is selected), asks a language model running locally in Ollama for a short list of fixes (homophones, misheard names, doubled words, capitals), applies them and pastes the result back. Ctrl+Z undoes it.

- Set-up page for the owner: https://dmhmca.github.io/get-a-grip/cleanup/
- `cleanup.ahk` is the whole program. `version.txt` holds the newest version number; the script checks it at start and every six hours, downloads `cleanup.ahk` if newer, keeps the old copy as `cleanup.previous.ahk`, and restarts itself.
- To release a change: edit `cleanup.ahk`, raise `VERSION := n` (keep it at the start of its line), keep the final `; CHATRITE-END` line, then put the same number in `version.txt`.
- The updater runs whatever is published here, so only the owner and trusted assistants may change this folder.
- Per-PC data lives in `%APPDATA%\ChatRite` (settings, vocabulary, a log of timings without any text).
- Nothing is sent anywhere except to Ollama on the same PC (127.0.0.1) and to GitHub Pages to check for updates.
