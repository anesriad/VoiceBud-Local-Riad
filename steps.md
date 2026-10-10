# VoiceBud — the prompts that built it

A local, fully offline Wispr Flow clone (push-to-talk dictation with local Whisper + Ollama cleanup) for macOS, built entirely by prompting Claude Code.

**How this was done:** the first prompt was planned in a separate session with **Opus 4.8** (research on how Wispr Flow works, choosing the stack, and writing an efficient build prompt). That main prompt was then given to **Fable 5**, which built the app and handled every adjustment below.

Give these prompts to Claude Code in order. Each one was a real step in the build.

---

## Prompt 1 — the main build prompt (give this to Fable 5, keep as is)

**Why `/goal`?** In Claude Code, `/goal` doesn't just send a prompt — it sets a persistent objective the agent is held to. The agent isn't allowed to stop until the stated condition is actually met (here: a *working, proven* app). If it tries to finish early with code that hasn't been demonstrated end-to-end, it gets pushed back to keep working. For a "build this and prove it works" task, that's exactly the behavior you want — no half-finished handoffs.

```
/goal Build a working local WhisperFlow (Wispr Flow) clone as a Python app on macOS (Apple Silicon, M4 Pro), fully offline, then prove it works.

EFFICIENCY RULES (follow strictly to conserve tokens):

- Do NOT re-research the stack — it is locked below. Do not fetch web pages or explore the reference repos beyond a single glance at their file layout.
- Ask me at most ONE round of clarifying questions, then build.
- Write the code directly; do not narrate your reasoning or restate the plan back to me.
- Keep it to ~4–6 small modules + one config file. No test suite, no CI, no README beyond a 5-line setup block.
- Prove it works with ONE end-to-end run, not a battery of tests.

TARGET: press-and-hold global hotkey (default: right ⌥/Option) starts dictation; on release, a local Whisper-family model transcribes the mic audio; a local LLM served by Ollama cleans the transcript (strip fillers, fix casing/punctuation); cleaned text is injected at the cursor in whatever app is focused.

STACK (locked, macOS Apple Silicon — do not substitute):

STT: faster-whisper (CTranslate2) with vad_filter=True (Silero VAD) to gate silence; default model tiny.en or base for latency, config-selectable up to large-v3. (Optional faster path: allow mlx-whisper / Parakeet-MLX behind a config flag for Neural-Engine speed — do not block on this.)
Cleanup: Ollama, default qwen3:4b-instruct (pull it first: ollama pull qwen3:4b-instruct). WARNING: do NOT use the plain qwen3:4b tag — that is the "thinking" variant which reasons for minutes instead of cleaning, and think:false does not stop it. Config-selectable alternatives: qwen2.5:1.5b (roughly half the size, for slower machines) / llama3.2:3b / phi3:mini.
Hotkey: pynput for the system-wide press-and-hold push-to-talk key.
Audio: sounddevice, 16kHz mono, with a 500ms pre-roll ring buffer so the first word isn't clipped.
Text injection: clipboard + synthesized ⌘V via Quartz CGEvent (pyobjc), with a per-character CGEvent Unicode keystroke fallback, chosen by a config flag. Save and restore the user's existing clipboard around the paste.
LLM CONFIG (make model-swapping trivial):

All Ollama settings live in config.yaml under a single llm: block: model, base_url (default http://localhost:11434), temperature, system_prompt, and an enabled flag.
The cleanup module must read the model name ONLY from config — never hardcode it anywhere. Changing one line (llm.model: <name>) must be the only edit needed to switch models.
On startup, if the configured model isn't found in ollama list, print a clear one-line warning (Model X not installed — run: ollama pull X) and fall back to skipping cleanup (raw transcript) rather than crashing.
Add a # to change the LLM: edit llm.model below, then restart comment right above that line in config.yaml.
CLEANUP PROMPT BEHAVIOR: the system prompt must instruct the model to ONLY fix fillers/casing/punctuation and NEVER rewrite, translate, answer, or add content. Small models are prone to over-editing or answering the transcript instead of cleaning it — keep the instruction strict and the temperature low, ~0.1. Also pass "think": false in the Ollama request as protection against thinking models.

macOS REQUIREMENTS: the app needs Microphone, Accessibility, and Input Monitoring permissions (System Settings → Privacy). Print a clear one-time setup message if any are missing.

LATENCY RULE: utterances under 10 words skip the Ollama step entirely.

REFERENCE (glance only, do not port Windows code): github.com/drajb/whisper-local (has a macOS Quartz injection path already) and github.com/bubnyukab/whisperflow-windows (architecture only — its pywin32/SendInput code is Windows-only, ignore it).

STRUCTURE: simple modules — hotkey.py, audio.py, transcribe.py, cleanup.py, inject.py, config.yaml, main.py.
```

> Note: if the cleanup model ever answers the transcript instead of cleaning it (common with very small models like qwen2.5:0.5b or 1.5b), the agent will need one or two prompt-hardening iterations in cleanup.py — that's normal.

---

## Prompt 2 — run it like an app, not a terminal command

```
Two things:
1. I don't want to start this from a terminal. Make it start automatically at login and run in the background system-wide (any app: browser, Notes, Slack). Use a macOS LaunchAgent that runs the venv python, logs to ~/Library/Logs, and survives reboots. Install and load it.
2. Change the hotkey to a two-key chord: ctrl+alt (left Control + left Option). Add chord support to the hotkey module so any combo from config works. Note: I originally wanted fn+ctrl — fn is NOT possible (macOS doesn't expose the fn key to apps), so don't try.
```

> Gotcha you'll hit here: macOS permission grants. The python binary must be added to **Accessibility** and **Input Monitoring** in System Settings → Privacy & Security. The `.venv/bin/python` is a hidden path — either drag the real binary from Finder into the settings list (ask the agent to reveal it with `open -R`), or press ⌘⇧G in the file picker and paste the path. Microphone permission pops up on first recording.

---

## Prompt 3 — recording indicator + app identity

```
1. When recording, show a small floating panel with a live waveform (like Wispr Flow's pill) so I know it's recording. Bottom-center of screen, always on top, driven by the real mic level, disappears when recording stops. Use AppKit via pyobjc, no extra dependencies.
2. Name the app VoiceBud instead of "Python" wherever possible (process name, bundle name). Also confirm: does this keep running when I close my editor? (It should — it's a login service.)
3. Add a menu bar icon (🎙️) with the hotkey reminder and a Quit option so it feels like a real app.
```

> Caveat the agent should tell you: the Control Center mic widget may still show "Python" because the attribution follows the Python.framework bundle. A full fix needs a real .app bundle (and re-granting permissions once).

---

## Prompt 4 — toggle mode instead of hold-to-talk

```
Change the hotkey behavior: instead of holding the chord while I speak, I want to press it once to start recording and press it again to stop (toggle mode). Keep hold mode available behind a config option (hotkey.mode: hold | toggle). Also tune the LLM cleanup prompt: keep my exact wording and meaning, only remove fillers (um, uh, ah), fix punctuation/capitalization, and fix small grammar slips — never rephrase or summarize.
```

---

## Prompt 5 — change the hotkey if it clashes

```
The ctrl+alt chord clashes with another tool I use. Switch it to ctrl+shift. (Avoid anything with F5 — that's Apple's dictation key on modern MacBooks.) Restart the service.
```

---

## Prompt 6 — when it stops capturing audio

```
There's an issue with VoiceBud. It doesn't capture any audio and nothing is transcribed. I press ctrl+shift as usual, the UI appears, I speak but nothing is captured. I haven't changed anything. Find out what the issue is.
```
Then:
```
Yes, fix it permanently, because I sometimes speak from AirPods, sometimes in loud places, sometimes just from the Mac.
```

> What it found: the mic stream was opened once at startup and silently died when the audio device changed (CoreAudio error -10863). The fix makes `audio.py` follow the macOS default input, reopen dead streams with backoff, and open Bluetooth mics only while recording (keeping the AirPods mic open all the time forces them into low-quality call audio).

---

## Prompt 7 — punctuation and paragraphs without AI rewording

```
I notice the messages often look clunky: no punctuation, no new paragraphs. Is this because the LLM isn't good enough or because the cleanup prompt isn't? I want to keep the essence of my words (no AI-style rewording) but I want good punctuation and paragraphs. How can we fix this?
```

> What it found: cleanup was **off**. VoiceBud started at login before Ollama and disabled cleanup until restart. The fix: re-check Ollama lazily, a chat prompt with one worked example (small models copy a format better than they follow rules), paragraph rules, stripping em dashes and curly quotes, and a guard that falls back to the raw transcript if the LLM changes too many words. The LLM stayed `qwen3:4b-instruct`.

---

## Prompt 8 — better speech recognition + your own jargon

```
This is what VoiceBud transcribed in a silent room: "in tax" for "intact", "voicebot" for "VoiceBud", "Obama" for "Ollama". Imagine in a coffee shop. Improve the transcription quality.
```
Then:
```
Add a bunch of keywords I use as a data scientist, AI engineer and AI consultant (API, RAG, retrieval, Claude Code, Codex, etc.) so it recognizes them. Maybe a list of ~50 keywords and tools.
```

> What it found: the mistakes came from speech-to-text, not the LLM. Switching to Whisper large-v3-turbo on the Apple GPU (mlx-whisper) fixed them and is *faster* than small.en on the CPU. The vocabulary goes into Whisper's initial prompt, which only holds ~220 tokens, so the list is capped (~57 terms) with your most-used terms last. A `replacements` map handles words it still mishears, and the cleanup step restores vocabulary words the LLM respells.

---

## Final result

- Press `ctrl+shift` anywhere → waveform pill appears → speak (any length) → press again → clean, punctuated text with paragraphs lands at your cursor in ~2-3s.
- 100% offline: Whisper large-v3-turbo on the Apple GPU (mlx-whisper) with a custom vocabulary for STT, `qwen3:4b-instruct` via Ollama for cleanup.
- Follows your mic (AirPods, built-in, external) and recovers by itself.
- Runs at login, menu bar 🎙️, zero subscription.
