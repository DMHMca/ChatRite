# ChatRite on the Surface Pro 11: brief for Claude Code running natively on it

Read `CLAUDE.md` and `HANDOVER.md` first (same owner, same rules: plain English, British English, clickable links, no secrets in chat, never release or change update addresses without their yes). This file is only about the Surface.

## Goal
Get ChatRite Dictate (voice typing into any window) and ChatRite (fix words, polish) working on this Surface Pro 11 (Snapdragon X, ARM64, no NVIDIA), local and free if at all possible. Get something operational and let real use be the test.

## What was learned on the 4080 laptop (6 Nov 2026)
- `dictate.py` uses `faster-whisper` with CUDA, so it cannot use this machine's hardware as it stands. It falls back to `small.en` on the CPU if the GPU fails, which may be a usable first step.
- Ollama calls: keep `num_ctx` the same (8192) in every request, or Ollama reloads the model (about 3 seconds each time). Already fixed in the project files.
- Hotkeys sent by one AutoHotkey script do not trigger another script's hotkeys unless the sender uses `SendLevel 1`. Use that when testing.
- Do not test by injecting keystrokes while the owner is typing. Use a test window of your own.

## Decision (6 Nov 2026): the built-in Windows engine first, then Soniox
The owner has been using Windows voice typing (the dictation button on the on-screen keyboard, same as Win+H) on the Surface and finds it good, but it stops whenever focus moves to another text box. He accepts that audio goes to Microsoft (free, same as the button) and wants ChatRite's extras on top (always listening whatever has focus, spoken commands, fix words, polish, vocabulary).

**First experiment:** a `windows` engine in Dictate using Windows' own recogniser, `Windows.Media.SpeechRecognition.SpeechRecognizer` with the dictation topic constraint and `ContinuousRecognitionSession`, which is not tied to the focused window. Open questions to test, not assume: do the Python WinRT projection packages (for example `winrt-Windows.Media.SpeechRecognition`) install and run on ARM64 native Python; does "Online speech recognition" need switching on in Windows privacy settings; is it usable unpackaged with microphone permission; does it add its own punctuation (if so, avoid doubling it with Dictate's rules); latency per phrase. Keep it as `engine = windows` on the `surface` branch. Fallbacks if it cannot be made to work: Windows "Voice access", or an AutoHotkey helper that presses Win+H again when voice typing stops.

**Second option, Soniox.** The owner has used Soniox before (the old Chrome extension prototype used it, see `surface/` notes) and accepts the small cost and that audio goes to Soniox on that machine only. Build it if the Windows engine is not good enough (real-time WebSocket streaming, vocabulary as context terms, API key in Windows Credential Manager via `keyring`, typed once into the program's own dialog, never in chat). Local NPU or CPU engines are optional experiments afterwards. The "nothing leaves the PC" rule in `CLAUDE.md` has this one agreed exception: the Surface Soniox engine, only when `engine = soniox` is set. The 4080 default stays local.

## Keeping the two machines apart
Work on the `surface` branch of the repository, never on `main` (the 4080 version, the only one installed copies self-update from). The Surface engine is an option (`engine = soniox` or `npu`), the 4080 CUDA engine stays the default, and Surface-only code lives in its own file. Merge to `main` only with the owner's yes, after the tests and a hotkey, fix and polish check on the 4080.

## Plan (steps 1 to 3 below are now optional; start from the Soniox engine)
1. Check the chip (X Plus or X Elite matters, the NPU models are chip-specific), whether Python is native ARM64 (x64 emulation cannot reach the NPU), and which packages install: `numpy`, `sounddevice`, `pystray`, `keyboard`, `onnxruntime-qnn`, `faster-whisper`/`ctranslate2`. `surface/surface-check.ps1` does this and writes a report to the Desktop; or just do it yourself.
2. Easiest first: run Dictate unchanged on the CPU with a small model. Measure time per phrase from `%APPDATA%\ChatRite\dictate-log.txt`.
3. NPU experiment: Qualcomm's precompiled Whisper-Large-V3-Turbo (https://huggingface.co/qualcomm/Whisper-Large-V3-Turbo) through ONNX Runtime's QNN provider. Reported about 0.8 s for the encoder on X Elite. One community report had the NPU idle and the CPU doing the work at 5 to 7 s per phrase, so check the NPU is actually in use (Task Manager, Performance, NPU). Add it to `dictate.py` as an optional `engine = npu` setting, keeping the CUDA engine as it is.
4. Clean-up model: Ollama has a Windows ARM build; try a small model (for example `qwen2.5:3b` or `7b`) and time fix and polish. Otherwise decide with the owner about a cloud model.
5. Fallback if local is too slow or too inaccurate: Soniox cloud engine (see `HANDOVER.md` section 11, step 5). It sends audio off the PC, so ask the owner first.

## Cloud engine for fix and polish (7 Nov 2026, built on the `surface` branch)
The local 3b model on the Surface CPU is slow and weak at homophones, and the NPU route failed (Foundry Local: the 1.5b NPU model was too weak, the 7b one crashed the NPU on a 16 GB machine). The owner accepts text leaving this one machine for a pay-per-use cloud model. Agreed exception to "nothing leaves the PC": the Surface only, only while `Engine=cloud` is set in `settings.ini` (tray: "Use the cloud engine (OpenRouter)"). Default stays `local`, so the 4080 is unchanged.
- ChatRite sends the same prompts to OpenRouter (`anthropic/claude-haiku-5.5`, about $0.10 in and $0.50 out per million tokens, so a polish costs a hundredth of a cent). If the call fails it falls back to the local model. The model can be changed with `CloudModel` in `settings.ini`.
- The key is typed once into a masked box (tray: "Cloud engine: enter or change my OpenRouter key...") and kept in the Windows credential store (target name `ChatRite OpenRouter`). Never in a file, the repository or chat.
- A published ChatRite update with a higher version number would replace the Surface's installed copy and drop this code until it is merged to `main`.

## Rules specific to this work
- Work in a copy of the project on the Surface. Do not publish or bump versions without the owner's yes.
- Report honestly what was and was not tested, with timings.
