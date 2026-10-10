# Run VoiceBud on your MacBook

VoiceBud is a fully offline dictation app for **macOS on Apple Silicon** (M1–M4).
Press `ctrl+shift` anywhere → speak → press again → clean text appears at your cursor.
No cloud, no subscription. Everything runs on your machine.

## 1. Prerequisites

```bash
# Install Homebrew if you don't have it (macOS package manager)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Python 3.12 (the version this project uses)
brew install python@3.12

# Install Ollama (runs the local LLM that cleans up your transcripts)
brew install ollama

# Start the Ollama server. Easiest: open Ollama.app once and enable "launch at login".
# (VoiceBud re-checks every 30s, so it's fine if Ollama starts after VoiceBud.)
ollama serve &

# Download the LLM used for transcript cleanup (~2.5 GB, one time)
ollama pull qwen3:4b-instruct
```

## 2. Set up the project

```bash
# Clone the repository from GitHub and enter it
git clone https://github.com/anesriad/VoiceBud-Local-Riad.git
cd VoiceBud-Local-Riad

# Create an isolated Python environment inside the project
python3.12 -m venv .venv

# Activate it (your terminal now uses the project's own Python)
source .venv/bin/activate

# Install all Python libraries the app needs
pip install -r requirements.txt
```

## 3. Run it

```bash
# Start the app (first run downloads the ~1.5 GB Whisper large-v3-turbo model automatically)
python main.py
```

## 4. Grant permissions (one time)

macOS will block the app until you allow it. In **System Settings → Privacy & Security**, add your Python binary to:

- **Input Monitoring** — lets the app see the global hotkey
- **Accessibility** — lets it paste text into other apps
- **Microphone** — macOS asks automatically on your first recording; click Allow

Tip: the settings file picker hides dot-folders. Press `⌘⇧G` in the picker and paste the path printed by `readlink -f .venv/bin/python`, or reveal it with `open -R "$(readlink -f .venv/bin/python)"` and drag the file into the list. Restart the app after granting.

## 5. Use it

Click into any text field (Notes, browser, Slack, anywhere):

1. Press `ctrl+shift` → a small waveform pill appears (recording)
2. Speak naturally — ums and uhs are fine, they get removed
3. Press `ctrl+shift` again → your cleaned text is pasted at the cursor

## Customize (edit `config.yaml`, then restart)

- **Hotkey**: `hotkey.key` (e.g. `alt_r`, `ctrl+alt`) — `fn` is not possible on macOS
- **Hold vs toggle**: `hotkey.mode: hold | toggle`
- **LLM**: `llm.model` — one line to swap (avoid plain `qwen3:4b`: it's the slow "thinking" variant; use `qwen3:4b-instruct`)
- **Speech model**: default is `stt.engine: mlx-whisper` with `mlx-community/whisper-large-v3-turbo` (Apple GPU, ~1s for a 30s dictation, robust to background noise). On slower Macs, set `stt.engine: faster-whisper` and `stt.model: small.en` (CPU).
- **Your jargon**: add names and terms to `stt.vocabulary` (comes with ~57 data science / AI terms like RAG, pgvector, LangChain, Claude Code). Whisper only reads ~220 tokens of it, so skip words it already knows (Python, SQL) and put your most-used terms **last**. VoiceBud warns in the log if the list is too long.
- **Words it keeps mishearing**: add `wrong: right` pairs under `stt.replacements` (e.g. `Alima: Ollama`).
- **Formatting**: `llm.system_prompt` and the `example_input` / `example_output` pair control punctuation and paragraphs. Edit the example to change the style. If the LLM changes too many of your words (`llm.min_similarity`, default 0.8), VoiceBud pastes your raw transcript instead.

## Microphones

VoiceBud always uses the current macOS default input and switches automatically (AirPods in/out, external mic, sleep/wake). Bluetooth mics are only opened while you record, so your AirPods don't drop to low-quality "call" audio all day. With AirPods, pause half a second after pressing the hotkey before you speak.

## Troubleshooting

- **Text has no punctuation/paragraphs**: Ollama isn't running (`curl localhost:11434/api/tags`). Start Ollama.app. VoiceBud picks it up within 30s, no restart needed.
- **Wrong words**: check the log. Each dictation prints `raw:` (what Whisper heard) and `→` (after cleanup), so you can see which step made the mistake. Fix Whisper errors with `stt.vocabulary` / `stt.replacements`.
- **Your last recording** is kept at `~/Library/Caches/VoiceBud/last.wav` (overwritten each time, never leaves your Mac), useful to replay a bad transcription.
- **Nothing is captured**: the log shows `[audio] mic: ...` whenever the mic changes. Restart with `launchctl kickstart -k gui/$(id -u)/com.riadanas.whisperflow`.

## Optional: start automatically at login

```bash
# Edit com.riadanas.whisperflow.plist first: replace the two absolute paths with YOUR project path.
# Then install and load it — VoiceBud now starts at every login, no terminal needed.
cp com.riadanas.whisperflow.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.riadanas.whisperflow.plist

# Logs live here if something misbehaves:
tail -f ~/Library/Logs/whisperflow.log
```
