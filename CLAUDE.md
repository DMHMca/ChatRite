# ChatRite: project brief for Claude Code

Read this first, then `HANDOVER.md` (the full history, decisions, current state and next steps).

## The owner and how to work with them

- The owner has very little coding experience. Explain in plain English and give step-by-step instructions for anything they must do, saying exactly what they should see on screen.
- British English. Short, practical, direct prose. Prefer prose to bullet lists.
- Always give web addresses as CLICKABLE markdown links with the full address and a few words on what each opens.
- They often work on a Surface tablet or phone where copying is hard: give every command or text to copy as its own fenced code block, one per command.
- Never ask them to paste secrets into chat. API keys go in through the tool's own dialog or Windows Credential Manager.
- They often dictate by speech-to-text, so messages can be garbled. When a request is ambiguous or they are thinking aloud, first restate in one or two sentences what you understand and wait for a yes. When it is clear ("build X", "yes, go ahead"), just do it. Never remove or rename something they have not clearly asked you to.
- Get something operational and let real use be the test. No elaborate test suites. Say honestly what was and was not tested.
- Tray icons use grey, blue and amber (no red or green), a deliberate design choice: keep it.
- Keep sessions focused, avoid repeated questions, and say what changed after each piece of work.
- The name is **ChatRite**.
- This repository is public. Never put personal details, keys, logs or dictated text in it.

## What this project is

Local dictation tools for Windows, running on his RTX 4080 laptop (this machine):

- `cleanup/cleanup.ahk`: ChatRite, AutoHotkey v2. Ctrl+Shift+Space fixes wrong words in selected text; Ctrl+Shift+Alt+Space polishes punctuation and capitals. Talks to Ollama at `http://127.0.0.1:11434`. Installs and starts Dictate. Self-updating.
- `dictate/dictate.py`: ChatRite Dictate, Python. Always-listening voice typing with Whisper `large-v3-turbo` on the GPU, typed into any window. Spoken commands: new line, new paragraph, stop dictation, polish, and spoken punctuation. Self-updating.
- Ollama runs `qwen2.5:7b` (upgrade: `qwen2.5:14b`).

A second machine, a Surface Pro 11 (ARM, no NVIDIA), needs a cloud engine (Soniox). Not started; do the 4080 first.

## Files

See the file map in `HANDOVER.md` section 5. Pure logic is tested with `python tests/dict_test.py` (25 checks). Everything touching AutoHotkey, the microphone, the GPU, the clipboard, SendInput and the tray can only be run on Windows, which is where you now are: run it.

## Releasing (the programs update themselves from GitHub Pages)

- ChatRite: raise `VERSION := n` in `cleanup/cleanup.ahk` (keep it at the start of its line), keep the last line `; CHATRITE-END`, put the same number in `cleanup/version.txt`, update the `cleanup.ahk?v=n` link in `cleanup/index.html`.
- Dictate: raise `VERSION = n` in `dictate/dictate.py`, keep the last line `# CHATRITE-DICTATE-END`, put the same number in `dictate/version.txt`.
- Push to the main branch. GitHub Pages can take up to ten minutes; the `version.txt` address shows when it is live. Installed copies check at start and every six hours, or from the tray ("Check for updates now"): update ChatRite first, then Dictate.
- The updaters run whatever is published, so keep the repository's write access tight.
- Give the owner a clickable link for the update check and say what he should see.

## Rules for the code

- Keep the update markers and version lines intact, or self-update stops working.
- AutoHotkey v2 pitfalls: `" ;"` inside a string is a comment; wrap `cmd /c "..."` in an extra pair of quotes when the first token is quoted; do not use implicit concatenation like `var (expr)`; check for local variables shadowing global function names.
- Dictate must never press plain Enter for "new line" (use Shift+Enter) because that sends chat messages.
- Never log the user's text. Logs hold timings and events only.
- Nothing may leave the PC except Ollama on 127.0.0.1, GitHub Pages update checks, and one-off model downloads.
- Allow every hotkey to be changed in `dictate.ini`. Claude's desktop app owns Ctrl+Alt+Space.

## Current state and first jobs

Both programs are at version 10. Read `HANDOVER.md` sections 4 and 11. In short: verify everything on this machine first (spoken "polish", dictation with `smart_stops = no`, speed), then fix defaults (hotkey, `smart_stops`, the misleading "first time it downloads" log line), then move the project to its own repository with the careful update-address migration in section 12, then try the 14b model, then the Surface Pro engine.
