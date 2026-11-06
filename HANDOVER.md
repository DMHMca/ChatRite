# ChatRite: handover for the new project

Written on 5 November 2026 at the end of the first phase, when ChatRite was split out of the Get a grip project. The aim: a new Claude Code session, started on the owner's RTX 4080 laptop, can read this file and `CLAUDE.md` and carry on without asking the owner to repeat anything.

## 1. What ChatRite is

ChatRite is the owner's name for a small toolset that makes dictation usable in any Windows window. Everything runs on his own PC. Nothing is sent anywhere except the one-off model downloads and a check for updates on GitHub Pages.

It has three running parts:

1. **ChatRite** (`cleanup/cleanup.ahk`, AutoHotkey v2). A tray program with two hotkeys.
   - Ctrl+Shift+Space, "fix words": copies the selected text (or the whole box), asks the local model for a short list of corrections (homophones, misheard names, wrong real words, stray capitals), applies them, pastes the result back. About 0.7 seconds for a sentence.
   - Ctrl+Shift+Alt+Space, "polish": sends the whole passage to the model with a "punctuation only" instruction. It adds full stops, commas and capitals and fixes obvious recognition errors without rewording. The result is pasted only if at least 90% of the original words survive.
   - It also installs and starts ChatRite Dictate, and updates itself.
2. **ChatRite Dictate** (`dictate/dictate.py`, Python). A tray program that listens continuously through the microphone, recognises each phrase with Whisper (`large-v3-turbo`) on the NVIDIA GPU, and types it into whichever window has focus. A hotkey switches it on and off. Spoken commands: "new line", "new paragraph", "stop dictation", "polish", and spoken punctuation ("full stop", "comma", "question mark", "exclamation mark").
3. **Ollama** (not ours). Runs the language model (`qwen2.5:7b`; `qwen2.5:14b` is the upgrade). ChatRite and Dictate talk to it at `http://127.0.0.1:11434`.

Why it exists: the owner dictates a great deal. Voice In (a Chrome extension) works well inside Chrome but not in the Claude or ChatGPT desktop apps. Windows voice typing (Win+H) and apps such as Murmur are push to talk, which he rejected. Commercial tools such as Wispr Flow insert text only after the speaker stops and cost $100 to $200 a year. He has a 4080 and wants it local, live and free.

## 2. The owner and how to work with him

The owner has very little coding experience and often dictates messages, so speech-to-text errors are common (for example Ollama, Murmur, Soniox and ChatRite are often misheard). Quote back what you think was meant when a message looks garbled.

Standing rules (also in `CLAUDE.md`):

- British English. Short, plain, practical prose. Avoid bullet lists where prose will do. No jargon without explanation.
- Always give web addresses as clickable markdown links with a few words on what they open. He is tired of copying addresses on the phone and has said so repeatedly.
- Give step-by-step instructions for anything he must do himself and say exactly what he should see on screen.
- Never ask him to paste secrets into chat. API keys go through the tool's own dialog or Windows Credential Manager.
- Restate what you understand before building when the request is ambiguous, and wait for a yes. When he says "build X" or "yes, go ahead", just do it.
- "Get something operational and let real use be the test." He does not want elaborate test suites. He does want honest statements about what was and was not tested.
- He gets frustrated by long fragmented sessions and by being asked things he has already answered. Keep sessions focused. Tell him what changed after each piece of work.
- Tray icons use grey, blue and amber, never red or green. Keep that.
- Name: the tool is **ChatRite**. Earlier I invented "Get a grip tidy"; he corrected it. Do not rename things he has not asked to rename.

## 3. Hardware and where things run

- **RTX 4080 G14 laptop, Windows.** Home machine and the primary target. Runs Ollama, ChatRite and ChatRite Dictate, all local. The new Claude Code session should run on this machine, so it can start AutoHotkey, Ollama and Python and test for real. Until now every line was written in a Linux container with no way to run AutoHotkey, Ollama, the microphone or the GPU, so the owner's PC was the only real test.
- **Surface Pro 11 (Snapdragon X, ARM, no NVIDIA).** For travel. It cannot run the CUDA Whisper build. Plan: a cloud engine (Soniox) for Dictate, and either a small local model or a cloud model for the clean-up. Not started. Do the 4080 first.

## 4. Current state (versions and what is confirmed)

Both programs are at **version 12** (6 Nov 2026). Version 12 added spoken "press enter", "carriage return", "CR", "paste that", "colon" and "semicolon", a capital after a full stop or new line, and a spoken "period" at the end of a phrase. Installed copies now check `https://dmhmca.github.io/ChatRite/cleanup/version.txt` and `.../dictate/version.txt` (the new repository). The old `get-a-grip` address still serves version 12 too, for copies that have not yet moved; keep it for a few weeks. Not yet proved: an update that travels only through the new address (needs a version 13). GitHub Actions must stay enabled (GitHub-owned actions only) on the ChatRite repository, or Pages cannot build.

Confirmed working on the 4080 by the owner:
- Ctrl+Shift+Space word fixing: "Magic!", about 0.7 s on the second request, fixes homophones and capitals.
- ChatRite Dictate installs through the ChatRite tray item, loads the model on the GPU (first start about 10 minutes for the download, afterwards 2 to 4 seconds), types live into the ChatGPT desktop app, recognises each phrase in 0.15 to 0.6 s.
- Self-updating of both programs, including the restart after an update (v5 fixed a handle bug).
- The Polish hotkey (Ctrl+Shift+Alt+Space) gave "a reasonable job" on a dictated paragraph.

Not yet confirmed, or reported but unresolved:
- **Spoken "polish"** (Dictate writes `%APPDATA%\ChatRite\polish.now`, ChatRite checks for it every 300 ms and runs Polish). The first version (v8) pressed the hotkey from Python and nothing happened; v10 uses the signal file. After updating to v10 the owner said "ChatRite not work as far as I can see" without detail, so this is untested.
- The owner's latest messages: "ChatRite is working but is putting in full stops for pauses. Also very slow." Cause believed to be the live sentence check (`smart_stops`, see 6.2), which calls Ollama after every pause. He set `smart_stops = no` and `hotkey = ctrl+alt+M`. The result was not reported. Verify first.
- **Hotkey clash:** the Claude desktop app uses Ctrl+Alt+Space for its quick-entry bar, which takes priority over Dictate's default. The owner moved Dictate to Ctrl+Alt+M. Consider making a different default.
- Ollama's newer app shows a sign-in prompt. No account is needed; closing the prompt is fine.

## 5. File map

```
CLAUDE.md                      project brief for Claude Code (read first)
HANDOVER.md                    this file
README.md                      short public description
cleanup/cleanup.ahk            ChatRite (AutoHotkey v2), about 760 lines
cleanup/version.txt            newest ChatRite version number (the updater reads this)
cleanup/index.html             the owner's set-up page (download and install steps)
cleanup/README.md              short note on the updater
dictate/dictate.py             ChatRite Dictate (Python), about 735 lines
dictate/requirements.txt       pip packages for the Dictate virtual environment
dictate/version.txt            newest Dictate version number
tests/dict_test.py             25 checks of the pure logic (run: python tests/dict_test.py)
docs/chatrite-start-sheet.html the owner's start-up and fix sheet (also published as an artifact)
examples/dictate.ini.example   every Dictate setting with comments
examples/vocabulary.example.txt  vocabulary file format
```

On the PC:
- Programs: `%LOCALAPPDATA%\ChatRite\` (`cleanup.ahk`, `cleanup.previous.ahk`, `dictate\` with `dictate.py`, `venv\`).
- Data: `%APPDATA%\ChatRite\` (`settings.ini` with `[Tidy] Model`, `vocabulary.txt`, `dictate.ini`, `dictate-log.txt`, `dictate-console.txt`, `tidy-log.txt`, `polish.now` when a polish is requested).
- Startup shortcuts: `shell:startup` holds `ChatRite.lnk` and `ChatRite Dictate.lnk`.

## 6. How it works

### 6.1 ChatRite (`cleanup.ahk`)

- `#SingleInstance Force`, `Persistent()`. First run from any other folder copies itself to `%LOCALAPPDATA%\ChatRite` and relaunches from there.
- `VERSION := 10`. `AutoUpdate()` runs at start and every six hours. `CheckUpdate()` fetches `cleanup/version.txt`, then `cleanup.ahk`, checks it contains the same version number and ends with `; CHATRITE-END`, keeps the old file as `cleanup.previous.ahk`, writes the new one and reloads. The updater runs whatever is published at `UpdateUrl`, so only trusted people may change that location.
- `Tidy()` (Ctrl+Shift+Space): waits for the keys to be released, saves the clipboard, sends Ctrl+C (Ctrl+A first if nothing was selected), builds a JSON request and runs `curl.exe` through `cmd /c` against `http://127.0.0.1:11434/api/chat` with a `format` JSON schema, so the model returns only `{"fixes":[{"wrong":"...","right":"..."}]}`. `ApplyFixes` validates that each `wrong` occurs in the text and applies them. Model options: temperature 0, `num_ctx` 4096, `keep_alive` 24h. The prompt is `BuildPrompt()` plus vocabulary notes (`VocabNotes()`). Limit 6000 characters. The log in `tidy-log.txt` holds timings only, never text.
- `Polish()` (Ctrl+Shift+Alt+Space): same capture, but `AskPolish` asks for the whole text back with the owner's Voice In "Punctuation only" wording (see 10). `WordsKept(orig, out)` accepts the result only if at least 90% of the original words (case-insensitive, multiset) appear in it and the output has no more than about 10% extra words. Limit 8000 characters; `num_predict` is half the text length plus 256.
- `CheckSignal()` runs on a 300 ms timer: if `%APPDATA%\ChatRite\polish.now` exists it deletes it and runs `Polish()`. This is how Dictate triggers a polish when the owner says "polish".
- Tray menu: version, polish hint, sample test, edit vocabulary, copy last original text, change model, set up Dictate, start Dictate, check for updates, open log folder, start with Windows, exit.
- `InstallDictate()`: finds Python 3.12 (looks in `%LOCALAPPDATA%\Programs\Python\Python312` and Program Files, else `py -3.12`) or installs it with winget, creates `%LOCALAPPDATA%\ChatRite\dictate\venv`, downloads `requirements.txt`, pip installs it, downloads `dictate.py`, adds the Startup shortcut and launches it. It shows a window with each step.
- `EnsureModel()` / `Warm()` pull the Ollama model if missing and load it into memory.

### 6.2 ChatRite Dictate (`dictate.py`)

- `Endpointer`: 20 ms blocks at 16 kHz mono, an adaptive noise floor and a pause (`silence_ms`, default 600) end a phrase. Long speech is cut at 25 s.
- `Engine`: `faster_whisper.WhisperModel("large-v3-turbo", device="cuda", compute_type="float16")`, warmed with one second of silence. If that fails it falls back to `small.en` on the CPU with int8. `add_cuda_dlls()` adds the `nvidia-cublas-cu12` and `nvidia-cudnn-cu12` DLL folders to the DLL search path. The prompt given to Whisper is "British English spelling.", the vocabulary names, and the last 120 characters typed.
- `Output.prepare(text)` decides what to type:
  - trims Whisper's `...` at the start and end of phrases, turns a mid-phrase `...` into a comma;
  - unless `auto_stops = yes`, strips trailing `. , ; : ?` (a pause is not a sentence end);
  - converts spoken "full stop", "comma", "question mark", "exclamation mark/point" to punctuation;
  - drops coughs and fillers ("ahem", "hmm", "um", "[coughs]" and so on) and a small list of Whisper hallucinations;
  - lowercases the first letter of a phrase that continues a sentence, unless the word is "I", all capitals, in the vocabulary, or a day or month;
  - if `smart_stops = yes`, asks Ollama (`/api/generate`, the `BOUNDARY_PROMPT` few-shot prompt, `num_predict` 4, 4 s timeout) whether a new sentence begins at this join, with the first letter of PART B lowercased so Whisper's capital is not a cue. YES or QUESTION adds a full stop and a capital. A question mark is never added by itself. If Ollama is unreachable it stops asking for 30 s and logs once.
- Spoken commands (whole phrase only, `parse_command`): "new line" and "new paragraph" press **Shift+Enter, never plain Enter** (plain Enter would send a chat message); "stop dictation"; "polish" (and "polish that", "polish it", ...) writes `polish.now` and then waits `polish_wait_s` (5 s) in the worker thread. Speech heard meanwhile waits in the queue, so nothing is lost.
- Typing uses `SendInput` with Unicode key events (`type_text`).
- Tray (pystray): grey ring = off, blue disc = listening, amber square = working. No red or green. Beeps on start and stop. Switches itself off after `idle_timeout_s` (90) of quiet.
- Hotkey via the `keyboard` package (`keyboard.add_hotkey`), default `ctrl+alt+space`.
- Single instance via a named mutex. `already_running()` closes its own handle when the mutex exists, otherwise a restart after an update would see its own earlier attempts and never start (fixed in v5).
- Self-update: `check_update()` every six hours and from the tray: fetches `dictate/version.txt` and `dictate.py`, checks `VERSION = n` and the final `# CHATRITE-DICTATE-END` line, keeps `dictate.previous.py`, replaces itself, starts the new copy and exits.
- Settings (all optional): see `examples/dictate.ini.example`. Defaults are in `DEFAULTS` at the top of the file.

## 7. Decisions made and why

- **Local, not cloud.** Privacy, no running cost, the 4080 can do it. Cloud is accepted only for the Surface (no NVIDIA).
- **AutoHotkey for clean-up.** The owner knows AutoHotkey and wanted a hotkey he can trust in every window. Chrome extensions were rejected for the non-Chrome case.
- **JSON "fixes" for word fixing, not "rewrite the text".** Small models over-edit. A fix list the script validates cannot silently reword a sentence. Polish accepts a full rewrite only behind the 90% word-survival check for the same reason.
- **No punctuation added at pauses.** The owner pauses mid-thought, so pause length says nothing about sentence ends, and Whisper only sees one phrase at a time. Default behaviour adds none; punctuate by voice or with polish. `smart_stops` tries to judge from grammar at each join. It was unreliable with the 7b model and adds latency per phrase, and the owner then turned it off. Whisper's trailing question marks are removed because they were wrong too often.
- **Polish as a spoken word.** The owner prefers saying "polish" to pressing keys. First attempt (Python sends the hotkey with the `keyboard` package) did nothing on his PC, so the hand-over is a small signal file.
- **curl.exe through cmd for Ollama calls.** AutoHotkey v2 has no good HTTP client without COM; this keeps one dependency (curl ships with Windows).
- **Install Dictate from the ChatRite tray item** so the owner never touches Python.
- **Self-update from GitHub Pages**, same pattern as his web apps: bump the version number in the program and in `version.txt`.

## 8. Gotchas learned the hard way

- AutoHotkey v2: `" ;"` inside a string is read as a comment start. `cmd /c "..."` with a quoted first token needs the whole command wrapped in an extra pair of quotes. Do not write `var (expr)` implicit concatenation. A local `var` can shadow a global function name.
- Sending a hotkey from Python (`keyboard.send("ctrl+shift+alt+space")`) did not trigger the AutoHotkey hotkey on the owner's PC (the v8 "polish" failure). The cause was never established. Use a file or another channel instead.
- Claude's desktop app owns Ctrl+Alt+Space. Other apps may own other combinations; always allow the hotkey to be changed in the ini.
- GitHub Pages can take up to about ten minutes to publish a change, so "Check for updates now" may say "you have the newest version" right after a release. The version.txt link shows the truth.
- The first Dictate start downloads about 1.6 GB (Whisper turbo). The log line "the first time it downloads about 1.6 GB" prints on every start and is misleading. Fix the wording.
- The Windows 11 notification box cannot be moved. The owner finds Claude's toasts in the way; not our problem.
- Ollama may show a sign-in prompt. It is optional and unrelated to ChatRite.

## 9. What is tested and what is not

Tested in the Linux container: `tests/dict_test.py` (25 checks of endpointing with synthetic audio, commands, spacing, vocabulary, the punctuation rules, the sentence-check plumbing against a pretend Ollama). Syntax of `dictate.py` is checked by importing it.

Never run anywhere except the owner's PC: all AutoHotkey code, clipboard capture and paste, the tray icons, SendInput typing, the microphone and GPU path, the installer window, and the real model's judgement. A session on the 4080 can finally run all of these. Do that first, before changing behaviour.

## 10. Source wording

The owner's Voice In "Custom Polish" instruction, used as the basis for `AskPolish` (his edited "Punctuation only" style):

> Polish the text: fix speech-recognition errors, grammar, punctuation, and capitalisation; make it clearer and more concise. Keep the author's voice, meaning, and paragraph breaks. Do not add new information.
> Also follow these rules. Where they conflict with anything above, these rules win:
> - Do not reword anything: only add or fix punctuation, capitalisation, and obvious speech-recognition errors. Keep every other word, in the same order.
> - Keep every word the author wrote in ALL CAPS exactly as written, in capitals.

Voice In's own Polish worked very well on the owner's test paragraph, so it is the quality benchmark. It is Chrome only and needs a Plus subscription (he has one). ChatRite's polish exists for the apps Voice In cannot reach.

## 11. Next steps, in order

1. **Verify on the 4080.** Run the tests. Start Ollama, ChatRite, Dictate. Check: fix words, polish by hotkey, spoken "polish" (the signal file route), dictation with `smart_stops = no`, speed. Read the logs. Fix what is broken before adding anything.
2. **Defaults.** Choose a default Dictate hotkey that does not clash with Claude (the owner now uses Ctrl+Alt+M). Consider `smart_stops = no` as the default. Fix the misleading "first time it downloads" log line.
3. **Move to its own home.** See 12.
4. **14b model trial** for fix and polish quality (`ollama pull qwen2.5:14b`, tray "Change the model...").
5. **Surface Pro 11.** Optional Soniox engine in `dictate.py`: real-time WebSocket streaming, context terms from the vocabulary file, API key stored in Windows Credential Manager through the `keyring` package and typed once into the program's own dialog, never in chat. Decide the clean-up engine for the Surface (small local model or cloud). Python on ARM may need x64 emulation; check `sounddevice` and `pystray` wheels. A later experiment: Whisper on the Qualcomm NPU.
6. Ideas not asked for yet: a spoken trigger for fix words, live correction while speaking (the owner said not planned).

## 12. Moving it into its own repository

The old private repository `DMHMca/ChatRite` already uses the obvious name. It holds ChatGPT's first attempt (a Chrome extension with a Windows installer, branch `chatrite/milestone-1`, including a `CHATRITE_VOICE_IN_FEATURE_AUDIT.md`). It is parked; either rename it (for example `ChatRite-old`) or choose a new name such as `chatrite-app`.

Plan for a safe move, because both programs update themselves from a fixed address:

1. Create the new public repository, copy this folder's contents to its root, keep the folder names `cleanup/` and `dictate/`, and turn on GitHub Pages for the main branch root. The new update addresses will be `https://dmhmca.github.io/<repo>/cleanup/` and `.../dictate/`.
2. In `cleanup.ahk` change `UpdateUrl`; in `dictate.py` change `UPDATE_URL`; also the set-up page links and `InstallDictate()`'s download addresses. Raise both versions to 11.
3. **Publish version 11 at the OLD address first** (`get-a-grip/cleanup` and `get-a-grip/dictate`), because that is where the installed copies look. When they update they start looking at the new address. Publish the same files at the new address.
4. Test on the 4080: each program updates once from old to 11, then update to a trivial version 12 published only at the new address to prove the new route works.
5. Leave the old folders in place for a few weeks, then replace them with a pointer file.
6. Remove the ChatRite sections from the Get a grip `CLAUDE.md` and leave a link to the new repository.

## 13. Links

- Set-up page: https://dmhmca.github.io/get-a-grip/cleanup/
- Current code: https://github.com/DMHMca/get-a-grip/tree/main/cleanup and https://github.com/DMHMca/get-a-grip/tree/main/dictate