# JARVIS AI

A standalone desktop AI assistant inspired by the *capabilities and feel*
of a fictional AI assistant like JARVIS. Original design, original
dialogue, original code.

> **Status: PHASE 37 complete.** Evening pack. `einstein` shares a daily
> quote or fact, `lighting_ideas` suggests a lighting setup for any mood,
> `bedtime_mode` dims the screen + goes quiet (text-only replies, with
> optional scheduled quiet hours), and `print_document` sends a file to the
> default Windows printer (approval-gated).
> Phase 36 also remains: natural voice & continuous conversation.
> `edge-tts` replaces the robotic system voice with natural neural voices
> (Microsoft's online TTS; set `TTS_ENGINE=edge` and pick a voice) and a
> hands-free **continuous conversation** mode keeps the mic open after each
> reply so you can just keep talking - end a session by saying "stop".
> Phase 35 also remains: the capabilities pack. `screen_ocr` reads text
> off the screen (Gemini vision), `screen_time` tracks which apps you use,
> `media_control` presses play/pause/volume keys, and `export_pdf` renders
> reports to real PDFs - all with no new dependencies.
> Phase 34 also remains: ethical hacking & security lab. Six
> tools scoped to authorised testing: `network_scan` (connect-only
> ping + port scan), `web_recon` (headers, missing security headers,
> robots.txt, TLS), `cve_lookup` (public CVE data), `hash_identify`
> (local hash recognition), `password_audit` (strength + private HIBP
> breach check), and `learn_security` (a persistent security knowledge
> bank seeded with OWASP and injected into every conversation). Scanning
> and audit tools are approval-gated; exploitation of third parties is
> explicitly out of scope.
> Phase 33 also remains: smart glasses & wearables. The `glasses`
> tool scans for paired Bluetooth devices, selects your glasses, and
> delivers notifications - shown as a native Windows toast and spoken
> aloud on audio-capable glasses. `GLASSES_MIRROR_REPLIES=true` pushes
> every JARVIS reply to the glasses. It is honest by design: JARVIS
> interfaces with paired hardware, it cannot embed itself into the
> glasses (that needs vendor SDKs and firmware).
> Phase 32 also remains: a contacts address book ("message Mummy" just
> works), multitasking apps (`manage_window`), and upload/paste
> attachments (images + documents analysed before the reply).
> Phase 31 remains: always-on camera fall detection with an emergency
> alert + call.
> Earlier: tone-of-voice emotion detection, threat scan + Security
> Dashboard, in-app research, code scaffolding and Unrestricted mode.

---

## Requirements

* Windows 10/11 (macOS/Linux support planned)
* Python 3.12+ (tested with 3.14)
* Internet on first run (Flet downloads its desktop runtime once)

## Dependencies & what you need to download

Everything installs with `pip install -r requirements.txt` (see Setup
below), but here is exactly what is downloaded and why, split into
**required** (installed automatically) and **optional** (feature-gated —
install only if you want that feature).

### Required packages (auto-installed via `requirements.txt`)

| Package           | Needed for                                                        |
|-------------------|-------------------------------------------------------------------|
| `flet`            | The desktop GUI framework (window, widgets) — downloads its Flutter runtime once on first run |
| `python-dotenv`   | Loading your `.env` configuration file                            |
| `openai`          | OpenAI + OpenRouter + `AI_PROVIDER=auto` fallback chain           |
| `anthropic`       | Anthropic Claude provider (optional even for auto)                |
| `pyttsx3`         | Text-to-speech so JARVIS reads replies aloud (Windows SAPI5 voices) |
| `SpeechRecognition` | Microphone → text (speech recognition)                          |
| `sounddevice`     | Capturing microphone audio for speech recognition                 |
| `numpy`           | Audio processing + emotion detection (voice-tone analysis)        |
| `psutil`          | Real-time system monitoring (CPU / RAM / network panel)           |
| `requests`        | Web search, weather, and update checks                            |
| `pypdf`           | Reading PDF files (`read_document`)                               |
| `python-docx`     | Reading Word `.docx` files                                        |
| `openpyxl`        | Reading Excel `.xlsx` files                                       |
| `python-pptx`     | Reading PowerPoint `.pptx` files                                  |
| `Pillow`          | Image handling, thumbnails, screenshot capture, graphic design    |

### Optional packages (install only for the extra features)

| Package            | Install command                    | Enables                                                                 |
|--------------------|------------------------------------|-------------------------------------------------------------------------|
| `keyboard`         | `pip install keyboard`             | Push-to-talk hotkey (`PTT_ENABLED=true`)                                |
| `opencv-python`    | `pip install opencv-python mediapipe` | Camera fall detection (Phase 31) — the pose model downloads once to `camera/models/` |
| `mediapipe`        | *(same command as above)*          | Pose model used by camera fall detection                                |
| `openai-whisper`   | `pip install openai-whisper`       | Fully offline/local speech recognition (`STT_PROVIDER=whisper`)         |
| `pywin32`          | `pip install pywin32`              | Pasting files from the clipboard (Phase 32)                             |

> The camera and push-to-talk features detect missing libraries and tell
> you exactly which command to run, instead of crashing.

### External downloads (not pip)

* **Ollama** (optional) — run a fully local model with no API key. Install
  from https://ollama.com, then `ollama pull llama3.1` and
  `ollama serve`, and set `AI_PROVIDER=localllm` in `.env`.
* **A webcam driver** (optional) — only needed for camera fall detection.

### API keys (free options available)

JARVIS runs in offline mode with no keys, but full AI conversations need
at least one key. Free tiers exist for all of the following
(see `.env.example` for details):

| Provider    | Where to get a key                          | Cost        |
|-------------|---------------------------------------------|-------------|
| OpenRouter  | https://openrouter.ai (free `:free` models) | free        |
| Google      | https://aistudio.google.com/apikey          | free tier   |
| Groq        | https://console.groq.com/keys               | free tier   |
| HuggingFace | https://huggingface.co/settings/tokens      | free tier   |
| Tavily      | https://tavily.com (web search)             | free tier   |
| OpenWeather | https://openweathermap.org/api (weather)    | free tier   |

With `AI_PROVIDER=auto`, JARVIS chains every free key you add and
automatically falls back to the next one on rate limits.

## Setup

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install the required dependencies
pip install -r requirements.txt

# 3. (Optional) install extra feature packages, e.g.:
pip install keyboard                     # push-to-talk
pip install opencv-python mediapipe      # camera fall detection
pip install openai-whisper               # fully local speech-to-text

# 4. Copy the example env file and add your API keys
Copy-Item .env.example .env
#    then edit .env and add at least one API key (see table above)
```

## Run

```powershell
python main.py
```

A dark futuristic window should open with:
* an animated AI core (top centre)
* a chat area (centre) — type a message and press Enter or click send
* a system-monitor panel (right, placeholders for now)
* text input, microphone button and send button (bottom)
* an AI status indicator and settings button (top bar)

### Enabling full AI conversations

Without any configuration the app runs in **offline mode**: it answers
basic local requests (clock, calculations) and explains that the full AI
is not connected. To enable real conversations:

1. Copy `.env.example` to `.env`.
2. Set `AI_PROVIDER=auto` (recommended) or pick one provider below.
3. Add at least one API key (free options exist, see below).
4. Restart the app.

Supported providers (more can be added in `ai/providers/`):

| Provider    | Env key                | Model env          | Cost        |
|-------------|------------------------|--------------------|-------------|
| **auto**    | *(any of the keys)*    | *(any)*            | free tier   |
| OpenRouter  | `OPENAI_API_KEY`       | `OPENAI_MODEL`     | free models |
| Google      | `GOOGLE_API_KEY`       | `GOOGLE_MODEL`     | free tier   |
| Groq        | `GROQ_API_KEY`         | `GROQ_MODEL`       | free tier   |
| HuggingFace | `HUGGINGFACE_API_KEY`  | `HUGGINGFACE_MODEL`| free tier   |
| OpenAI      | `OPENAI_API_KEY`       | `OPENAI_MODEL`     | paid        |
| Anthropic   | `ANTHROPIC_API_KEY`    | `ANTHROPIC_MODEL`  | paid        |
| Local LLM   | *(no key)*             | `LOCAL_LLM_MODEL`  | you own it  |
| Offline     | *(no key needed)*      | —                  | —           |

If a provider is selected but its key is missing, the app warns and
falls back to offline mode instead of crashing.

### Free providers & automatic failover

`AI_PROVIDER=auto` (the default in `.env.example`) chains every free
provider that has a key, in priority order:

1. **OpenRouter free models** (`OPENROUTER_MODELS`, using your `sk-or-v1-`
   key) - rotate across several `:free` models. No credits needed, but the
   shared pool allows only **50 free requests per day** (resets at
   midnight UTC).
2. **Google Gemini** - the most generous free tier. Get a key at
   https://aistudio.google.com/apikey (no credit card).
3. **Groq** - very fast Llama models. Key at https://console.groq.com/keys.
4. **HuggingFace** - community router. Token at
   https://huggingface.co/settings/tokens.

When one provider is rate-limited, JARVIS automatically tries the next
one, so a single exhausted quota no longer kills the conversation. If
every provider is down, the app explains how to fix it instead of just
showing a raw error. Adding more than one key gives you a much larger
combined free allowance.

### Your own local model (no filters except the ones you pick)

If you want JARVIS to run entirely on a model you own - no API key, no
internet, and no provider-side content filters - point it at a local
OpenAI-compatible server. Two easy options:

* **Ollama** (recommended): install from https://ollama.com, then
  ```powershell
  ollama pull <model>     # e.g. ollama pull llama3.1 or dolphin-llama3
  ollama serve            # keeps the server running
  ```
* **LM Studio** or **llama.cpp** also expose an OpenAI-compatible endpoint.

Then tell JARVIS to use it:

```
AI_PROVIDER=localllm
LOCAL_LLM_URL=http://localhost:11434/v1
LOCAL_LLM_MODEL=llama3.1
```

*No internet and no API key are used.* Because the model runs on your
machine, **you** choose which model to install and therefore what it will
and won't answer - it is your model and your decision, not a remote
provider's policy. Local processing also means your conversation never
leaves your computer.

## Environment variables

See `.env.example` for the full list. Never commit your real `.env`.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest
```

## Project structure

```
jarvis_ai/
├── main.py              # entry point
├── config.py            # central configuration (reads .env)
├── requirements.txt
├── .env.example
├── ai/                  # the brain
│   ├── brain.py         # single interface the app uses for AI
│   ├── conversation.py  # chat history with context trimming
│   └── providers/       # base, openai, openai-compat (google/groq/hf),
│                        # fallback (auto), anthropic, local (offline)
├── tools/               # capabilities JARVIS can call (Phase 6)
│   ├── base.py          # the Tool interface + ToolError
│   ├── registry.py      # ToolRegistry + streaming tool-call parser
│   ├── builtin.py       # clock, date, calculator, list_tools
│   ├── system_control.py # Phase 7: apps, files, URLs, system info
│   ├── filesystem.py    # Phase 8: list/read/search/write files
│   ├── web.py           # Phase 10: web search (Tavily) + weather
│   ├── notes.py         # Phase 11: notes + reminders (SQLite backed)
│   ├── documents.py     # Phase 12: PDF/Word/Excel/PPT text extraction
│   ├── vision.py        # Phase 13: screenshot + Gemini image analysis
│   ├── memory.py        # Phase 14: long-term memory (remember/recall)
│   ├── scripts.py       # Phase 15: task scripts (advanced automation)
│   ├── rag.py           # Phase 30: local document index + query (RAG)
│   ├── email.py         # Phase 30: check/read/send email (IMAP + SMTP)
│   ├── scheduler.py     # Phase 30: recurring reminders
│   ├── chat_search.py   # Phase 30: full chat-history search
│   ├── export.py        # Phase 30: JSON + CSV data export
│   ├── mood.py          # Phase 30: mood memory + mood_report
│   ├── briefing.py      # Phase 30: morning briefing
│   ├── plugins.py       # Phase 30: plugin loader + list_plugins
│   └── voice_confirm.py # Phase 30: spoken yes/no confirmation
├── ai/
│   └── summaries.py     # Phase 30: long-chat summarization
├── memory/
│   ├── database.py      # SQLite persistence (convos, messages, notes, reminders)
│   └── reminders.py     # Phase 11: background reminder scheduler
├── system/
│   ├── monitor.py       # Phase 9: live CPU/RAM/disk/battery/network/uptime
│   ├── folder_watcher.py# Phase 30: watch a folder for changed files
│   ├── focus_recap.py   # Phase 30: idle-time focus nudge
│   └── scripts.py       # Phase 15: deterministic task-script runner
│   └── security.py      # Phase 16: audit log + sensitive-tool approval gate
├── security/            # Phase 28: threat monitoring & detection
│   ├── threats.py       # ThreatAlert model + honest status wording
│   ├── collectors.py    # defensive indicator collectors (processes, CPU/
│   │                    # RAM, network, startup, firewall, logons, files)
│   └── monitor.py       # ThreatMonitor: periodic scan loop + alert buffer
├── voice/
│   ├── text_to_speech.py # offline speech output (SAPI5, lazy init)
│   ├── speech_to_text.py # microphone capture + recognition (+whisper, lang)
│   ├── emotion.py        # Phase 29: tone-of-voice emotion detection
│   ├── ptt.py            # Phase 30: push-to-talk global hotkey
│   └── wake_word.py      # "Hey JARVIS" background listener
├── plugins/             # Phase 30: user drop-in tool plugins
├── ui/                  # Flet interface
│   ├── app.py           # page setup + launch
│   ├── dashboard.py     # main screen layout + wiring to the brain
│   ├── chat_view.py     # conversation bubbles (supports streaming)
│   ├── system_panel.py  # monitoring cards (placeholders in Phase 1)
│   ├── settings_view.py # settings dialog
│   └── components/      # orb, status indicator
├── utils/               # logger, helpers
├── data/                # created at runtime (logs, database)
└── tests/               # pytest suite
```

Modules for the AI brain, voice, tools, memory, computer control,
productivity, vision, security, updates and plugins are added phase by
phase. The architecture is designed so each capability is its own module.

## Roadmap (phases)

1. **DONE** — Project architecture + futuristic Flet interface
2. **DONE** — Chat interface + AI brain (provider abstraction, streaming,
   conversation history, SQLite persistence, offline fallback)
3. **DONE** — Text-to-speech (offline SAPI5, mute toggle, voice/speed
   settings)
4. **DONE** — Speech recognition (free Google STT; needs internet; clean
   messages when mic/internet missing)
5. **DONE** — Wake word (offline VAD + transcription gating; visible
   toggle, off by default for privacy)
6. **DONE** — Tool architecture: a tool registry, a streaming tool-call
   parser, and an agent loop in the Brain. Built-in offline-safe tools
   (clock, date, calculator, list tools). The AI requests a tool with a
   single-line `TOOL: {...}` marker; the Brain executes it, returns the
   result, and repeats until the model answers.
7. **DONE** — Computer control: launch applications, open files/folders
   and web pages, and report system info - all as safe, visible tools.
8. **DONE** — File intelligence: list directories, read text files,
   search by filename, get file info, and write text files - all safe,
   size-limited tools.
9. **DONE** — System monitoring: real CPU, memory, storage, battery,
   network rate and uptime, refreshed every 2 seconds in the side panel.
10. **DONE** — Web search and current information: `web_search` (Tavily)
    and `get_weather` (OpenWeatherMap) tools. Both are free-tier API keys
    in `.env`, and both fail with a clear message if unconfigured.
11. **DONE** — Notes and reminders: persistent notes (`create_note`,
    `list_notes`, `get_note`, `delete_note`) and scheduled reminders
    (`set_reminder`, `list_reminders`, `cancel_reminder`). A background
    scheduler announces due reminders in the chat and out loud.
12. **DONE** — Document intelligence: a `read_document` tool extracts
    text from PDF, Word, Excel, PowerPoint, CSV and text files so JARVIS
    can read and summarize real documents.
13. **DONE** — Screenshot and vision: `take_screenshot` captures the
    screen or a region to a PNG, and `analyze_image` sends it to the
    Gemini vision model so JARVIS can tell you what it shows.
14. **DONE** — Memory and personalization: `remember` / `list_memories` /
    `forget_memory` tools persist facts to SQLite and inject them into the
    system prompt, and voice/wake settings now survive restarts.
15. **DONE** — Advanced automation and multi-step tasks: persistent task
    scripts (`create_script` / `run_script` / `list_scripts` /
    `delete_script`) execute ordered tool-call steps deterministically,
    stopping at the first failure.
16. **DONE** — Security hardening + monitor: approval-gated sensitive
    tools, a full audit log (ring buffer + SQLite), and a live security
    feed on the side panel.
17. **DONE** — UI/UX polishing and animations: activity-reactive orb,
    streaming caret, animated "generating..." indicator, button hover
    feedback, status robustness.
18. **DONE** — Testing: 283 tests, all passing; ~90% coverage across
    config, AI, tools, system, memory and utils via `pytest --cov`
    (dev deps in `requirements-dev.txt`).
19. **DONE** — Packaging: PyInstaller spec + `scripts/build.ps1` produce a
    standalone single-file `dist\JARVIS AI.exe`; packaged builds keep data
    in `%USERPROFILE%\.jarvis-ai` and load `.env` from next to the exe.
20. **DONE** — Performance optimization and final cleanup: lazy brain and
    voice imports (~10x faster cold start, < 1s), graceful window-close
    shutdown, dependency + artifact hygiene.
21. **DONE** — Self-update: checks a remote manifest
    (`UPDATE_MANIFEST_URL`), downloads the new exe with SHA-256
    verification, installs it on restart, and exposes the `check_for_updates`
    tool.
22. **DONE** — Chat history + memory: conversations are persisted and the
    most recent one is resumed on launch; a history browser reopens old
    chats, conversations get auto-titled from the first message, and a
    Memory Store panel (in Settings) lists and deletes remembered facts.
23. **DONE** — Graphic design: a local Pillow renderer draws posters and
    banners (`create_poster`), fashion suit prototypes on a silhouette
    (`design_suit`), and app/website wireframe mockups (`create_wireframe`),
    all saved as PNG files under the data folder - no API keys needed.
24. **DONE** — Code security audit: `audit_code` scans the user's own
    software for common weakness patterns, `suggest_patch` extracts the
    exact weak lines for a fix, and `apply_patch` applies it to the
    (backed-up) file after user approval.
25. **DONE** — Unrestricted mode: a user-controlled "no boundaries" mode
    (Settings -> Permissions, or `UNRESTRICTED_MODE=true` in `.env`).
    When it is on, JARVIS runs approval-gated tools (screenshots, files,
    apps, URLs, patches) without pausing for confirmation and drops the
    ask-permission rules from its instructions. Off by default; persisted
    between sessions; can be switched on and off at any time.
26. **DONE** — In-app research: `research_topic` searches the web (Tavily
    when configured, otherwise DuckDuckGo with no key), reads the top
    result pages, and returns a digest so JARVIS answers you with real,
    current, sourced information instead of guessing or answering from
    stale memory.
27. **DONE** — Code scaffolding: `create_folder` makes directories and
    `write_project` writes a whole project (root folder + any number of
    files, creating every parent folder) in a single tool call, so you can
    simply ask JARVIS to build or code something and it creates the files
    on your PC. Both are approval-gated (unless Unrestricted mode is on).
28. **DONE** — Security monitoring & threat detection: a background
    `ThreatMonitor` periodically inspects processes, CPU/RAM, outbound
    connections, startup apps, firewall state, failed logons and recently
    dropped executables, and reports indicators with a severity and a
    recommended action. A Security Dashboard (`🟢 NORMAL` / `🟡
    SUSPICIOUS` / `🔴 HIGH RISK`) shows every alert. It only observes and
    reports - it never deletes, kills, disables or changes anything, and
    it never claims the machine is definitely safe.
29. **DONE** — Tone-of-voice emotion detection: when you use the
    microphone, JARVIS analyses the *sound* of what you said (loudness,
    pitch, rhythm, harshness) and can tell if you sound happy, sad or
    angry - then answers with matching empathy. It is local and free
    (numpy only, no API keys, no audio uploads), reports `neutral` when
    unsure, and never treats the guess as a certainty.
30. **DONE** — The "build all of these" drop: local document RAG,
    recurring scheduler, email assistant, chat-history search, data export,
    plugins, mood memory + report, morning briefing, conversation
    summaries, mood-adapted voice, multi-language + offline STT,
    push-to-talk, voice confirmation, folder watcher and focus-aware
    recap (see "Phase 30" below).

## Security notes

* API keys live in `.env` (never hard-coded).
* No hidden microphone/webcam/screen activity is performed.
* Confirmation is required before destructive actions (later phases).
* Unrestricted mode (Phase 25) opts out of that confirmation for gated
  tools at your own discretion; it stays on your machine, is persisted
  per session, and is never auto-enabled.

## Voice settings

Text-to-speech uses the Windows system voices (no internet, no API key).
You can:
* mute/unmute spoken replies with the speaker button in the input bar
* pick a voice, speech speed, and turn speech on/off in Settings
* control it via `.env`: `TTS_ENABLED`, `TTS_VOICE`, `TTS_SPEED`

## Speech recognition

The microphone button (`MIC`) listens for one phrase, then sends the
transcribed text to JARVIS. It uses free Google recognition
(`STT_PROVIDER=google`), which requires an internet connection. If there
is no microphone or no internet, JARVIS says so clearly instead of
failing silently.

## Wake word

The wake button (next to the mic) enables hands-free activation. While
active, JARVIS listens for the phrase set in `WAKE_WORD` (default
"hey jarvis") and then starts listening for your command.

* **Privacy first:** the listener is OFF by default. Enabling it is an
  explicit action (the button lights up) or requires
  `WAKE_WORD_ENABLED=true` in `.env`.
* It uses offline voice-activity detection and only calls the speech
  recognizer when it actually hears speech, so the network is not used
  continuously.
* The listener pauses automatically while JARVIS is speaking, so it
  does not wake itself up through the speakers.
* Detecting the actual phrase still uses Google recognition, so wake
  word needs internet when you speak near the microphone.

## Tools (Phase 6)

JARVIS can call tools while answering. Each capability is a class in
`tools/` that implements `Tool` (name, description, parameters, and an
`execute()` method). Tools currently built in:

* `get_time` - current local time
* `get_date` - today's date
* `calculate` - safe arithmetic (no code execution)
* `list_tools` - lets the model discover what it can do

**How it works:** the system prompt lists the tools and instructs the
model to request one with a single-line marker:

    TOOL: {"name": "get_time", "arguments": {}}

The Brain streams the model's reply, runs any tools it asked for, feeds
the results back, and asks again until a final answer is produced (capped
by `TOOL_MAX_ITERATIONS`). Tool-call lines are hidden from the chat;
only the tool activity and the final answer are shown.

To add a capability later (web search, notes, files...), register a new
`Tool` on the registry - no other code needs to change.

Settings: `TOOLS_ENABLED=true`, `TOOL_MAX_ITERATIONS=4` in `.env`.

## Computer control (Phase 7)

JARVIS can act on this computer through safe, visible tools:

* `open_app` - launch a known app (notepad, calculator, explorer...) or
  any executable on PATH
* `open_path` - open a file or folder with its default app
* `open_url` - open a web page in the default browser (http/https only)
* `computer_info` - OS, version, architecture, hostname, current user
* `list_apps` - show the app catalog

Security rules baked into the tools: applications launch with argument
lists (never a shell string, so no command injection), URLs must be
http(s), and paths are validated to exist first. Destructive actions
(shutdown, killing processes, deleting files) are intentionally excluded
until a confirmation flow exists.

## File intelligence (Phase 8)

JARVIS can work with files through safe tools:

* `list_directory` - list a folder's contents with sizes
* `read_file` - read the start of a text file (default max 4,000 chars)
* `search_files` - find files by name inside a folder (recursive)
* `file_info` - size, dates and type of a file or folder
* `write_file` - create or overwrite a text file (max 100,000 chars)
* `create_folder` - create a folder (and any missing parents)
* `write_project` - write a whole project: a root folder + any number of
  files (every parent folder is created automatically) in one call

Safety: reads are size-limited, binary files are detected and refused,
paths are validated, and nothing is ever deleted. Destructive file
operations wait for the confirmation flow in a later phase.

Example: *"Read data/notes.txt and summarize it"* - JARVIS calls
`read_file`, gets the text, and summarizes it.

## Code scaffolding (Phase 27)

To have JARVIS actually **build code for you** and put it on your PC,
describe what you want and it will create the files:

* *"Create a folder called myapp in Documents"* - calls `create_folder`.
* *"Code me a Python calculator app in Documents/DemoCalc"* - calls
  `write_project`, creating the folder and every file (e.g. `main.py`,
  `requirements.txt`, `README.md`) in one go.

Both actions are approval-gated by default (JARVIS asks once), and run
directly when Unrestricted mode is on. Files are capped at 100,000 chars
each and nothing existing is ever deleted or overwritten silently across
the whole project.

## System monitoring (Phase 9)

The right-hand panel shows live data, refreshed every 2 seconds:

* **CPU load** - current processor usage %
* **Memory** - used/total GB plus usage %
* **Storage** - free space on the system drive
* **Battery** - charge % and charging state (shows "AC" on desktops)
* **Network** - current up/down transfer rate
* **Uptime** - how long the system has been running

Powered by `psutil` (cross-platform, no admin rights needed). Every
sensor is isolated: if one fails or is missing, the card just shows "--"
and the rest keep updating.

## Web info (Phase 10)

JARVIS can look up things it does not already know:

* `web_search` - live web results via **Tavily** (title, URL, snippet)
* `get_weather` - current conditions (temp, conditions, humidity, wind)
  via **OpenWeatherMap**

Both use free-tier API keys (no credit card needed):

```
TAVILY_API_KEY=your_tavily_key        # https://tavily.com           ~1000 searches/mo
OPENWEATHERMAP_API_KEY=your_owm_key   # https://openweathermap.org/api  ~1000 calls/day
```

Keys go in `.env`. If a key is missing, the tool returns a clear message
instead of pretending, so the AI never invents search results or weather.
Example: *"What's the weather in Accra?"* - JARVIS calls `get_weather`,
gets real data, and reads the answer aloud.

## Research (Phase 26)

If you want JARVIS to *learn a topic and then answer you properly*, say
something like: *"Research the 2026 Ghana State of the Nation address and
tell me the highlights."* JARVIS calls `research_topic`, which:

1. searches the web (**Tavily** if `TAVILY_API_KEY` is set, otherwise the
   free **DuckDuckGo** endpoint - so it works with no key at all),
2. fetches the top result pages and extracts their readable text,
3. returns a compact digest of the best sources, which JARVIS turns into
   a real, current, sourced answer instead of guessing.

It is read-only (it never writes anything), respects sensible page-size
limits, and if the network is unavailable it says so clearly.

## Notes & reminders (Phase 11)

JARVIS can remember things across sessions (stored in the local SQLite
database):

* `create_note` - save or overwrite a note by title
* `list_notes` - show every note with a short preview
* `get_note` - read a note's full content
* `delete_note` - remove a note
* `set_reminder` - schedule a reminder; times like *"in 5 minutes"*,
  *"in 2 hours"* or *"2026-08-12 15:30"* are accepted
* `list_reminders` - show pending reminders
* `cancel_reminder` - cancel one by its id

A background `ReminderService` checks every two seconds for reminders
whose time has passed and fires them: JARVIS posts **REMINDER: ...** to
the chat and speaks it aloud (respecting the mute toggle and wake-word
privacy pause). Notes and reminders survive app restarts.

Example: *"Remind me to call mum in 10 minutes"* - JARVIS schedules it,
confirms the time, and calls out when it's due.

## Document intelligence (Phase 12)

JARVIS can read real documents with one tool, `read_document`:

* **PDF** - text layer extraction (`pypdf`; scanned/image PDFs need OCR,
  which is planned)
* **Word** - `.docx` paragraphs and tables (`python-docx`)
* **Excel** - `.xlsx` sheet values row by row (`openpyxl`)
* **PowerPoint** - `.pptx` slide titles and body text (`python-pptx`)
* **Plain text** - `.txt`, `.md`, `.csv`, `.json`, `.log`, and more

Extraction is size-limited so huge files cannot flood the chat, and if a
format's library is missing the tool says exactly which `pip install`
command fixes it. Example: *"Summarize data/report.pdf"* - JARVIS reads
the document and gives you the highlights.

## Screenshot & vision (Phase 13)

JARVIS can see your screen with two tools:

* `take_screenshot` - captures the whole screen or a region
  (`"0,0,800,600"`) and saves it to `data/screenshots/` (path shown in
  the chat)
* `analyze_image` - sends an image file to the **Gemini** vision model
  (your `GOOGLE_API_KEY`) and returns its answer

Example: *"look at my screen and tell me what's open"* - JARVIS takes a
screenshot, analyzes it, and reads the answer aloud. Captures happen only
when you ask - there is no hidden or background screen activity. Images
are downscaled before being sent to keep them fast and small.

## Memory & personalization (Phase 14)

JARVIS can remember you across sessions:

* `remember` - save a fact, e.g. *"My name is Jones"* or *"I prefer dark
  mode"*
* `list_memories` - show everything JARVIS remembers
* `forget_memory` - remove a memory by id or by text

Remembered facts are stored in SQLite and injected into the system prompt
on every reply, so JARVIS naturally uses them in later conversations
(even after a restart). Ask it *"what do you remember about me?"* to see.

Voice settings are also persisted now: voice, speed, and the mute and
wake-word toggles are saved when you change them and restored on the next
launch - no more resetting preferences every start.

## Task scripts (Phase 15)

For jobs JARVIS repeats, you can build a **task script** once and replay
it whenever you like:

* `create_script` - save (or overwrite) a named script: an ordered list of
  tool calls, e.g.
  `[{"name": "get_date"}, {"name": "get_weather", "arguments": {"city": "Accra"}}]`
* `run_script` - execute its steps in order, deterministically (no LLM in
  the middle), returning a step-by-step summary
* `list_scripts` - show saved scripts
* `delete_script` - remove one

Scripts are validated when saved, run to the *first* failing step (so a
bad script stops safely), are capped by `SCRIPT_MAX_STEPS` (default 30),
and cannot nest inside one another (no recursive runs). Everything they
do is visible in the chat. Example: *"create a morning briefing script
that gives the date, time and Accra weather"*, then later *"run my
morning briefing"*.

## Security (Phase 16)

**Approval gate:** tools that touch the screen, the filesystem, launch
programs/URLs, or delete data now require your explicit permission:

`take_screenshot`, `write_file`, `delete_note`, `delete_script`,
`forget_memory`, `cancel_reminder`, `open_app`, `open_url`, `open_path`

If JARVIS asks for one without you saying yes, it returns *"requires your
approval"* and asks you to confirm. A simple *"yes"*, *"go ahead"* or
*"okay"* on the next message unlocks it for that turn. Non-sensitive
tools (clock, math, web search, notes, reminders...) run freely.

**Audit log:** every tool call and every approval-gated request is
recorded (in-memory ring buffer + the local `security_events` SQLite
table) and surfaced in the new **Security** card on the side panel - a
live feed plus event / sensitive / approval counters. There is no hidden
or background activity: screenshots, file writes and launches only happen
when you approve them, and every one is logged and shown in the chat.

## Security monitoring & threat detection (Phase 28)

JARVIS watches for observable indicators of suspicious activity. The
**shield** button in the top bar (or the **THREAT MONITOR** tile in the
side panel) opens the Security Dashboard, which shows an overall posture
and every alert:

| Status            | Meaning                                    |
|-------------------|--------------------------------------------|
| 🟢 **NORMAL**    | no obvious indicators of compromise found  |
| 🟡 **SUSPICIOUS**| medium indicators need review              |
| 🔴 **HIGH RISK** | serious indicators - investigate promptly  |

Each alert reports:

* **what** was detected
* **why** it is suspicious
* **which** process / application is involved
* **when** it occurred
* **severity** (low / medium / high)
* **recommended action**

Areas monitored: unexpected or known-malware process names, processes
running from temp/downloads, near-total CPU usage, outbound connections to
suspicious ports, very high connection counts, startup apps launching from
low-trust locations, firewall profiles switched off, repeated failed logon
events (Security log 4625), and executables recently dropped in
temp/startup folders.

**Honesty:** a clean scan reports *"No obvious indicators of compromise
were detected."* JARVIS never claims the machine is definitely safe, never
invents findings, and stays silent about data sources it cannot read.

**No automatic actions:** the monitor only observes and reports. It never
deletes files, kills processes, disables security software, edits firewall
rules, changes passwords, disconnects the network or alters system
settings. Anything beyond detection is left to you, and any high-risk
remediation is only considered after you explicitly confirm it. Scans run
every `THREAT_SCAN_INTERVAL` seconds (default 60, minimum 5).

## Tone-of-voice emotion detection (Phase 29)

Speak to JARVIS with the microphone and it will look beyond the words: it
analyses the *acoustics* of your voice - loudness, pitch (fundamental
frequency), rhythm and harshness - and estimates whether you sounded
HAPPY, SAD, ANGRY or NEUTRAL. The detected mood is shown as a small hint
under your spoken words and passed to the AI so JARVIS answers with
matching empathy (e.g. calmer and more reassuring when you sound upset).

How it works (local and free - numpy only):

* every frame of the utterance is measured for energy, zero-crossing
  rate, autocorrelation pitch and spectral brightness
* these roll up into speech-level cues: how loud, how animated, how
  high/low, how bright/harsh
* a documented heuristic maps those cues onto emotions (angry voices are
  loud, harsh and low; happy voices bright, high and lively; sad voices
  quiet and low)

Honest limits (by design):

* it reads the **tone**, not the words - the meaning of what you say still
  comes from the transcription
* when features are ambiguous it reports **neutral** instead of
  inventing a mood, and it never uploads your audio anywhere
* happy/angry/sad are common, but it is a lightweight heuristic, not a
  trained neural model - treat it as a hint, not a verdict

Toggle it with `TONE_EMOTION_ENABLED=false` in `.env` (default: true).

## Phase 30 - the "build-all" feature drop

One combined phase that landed the local knowledge, productivity and
proactive side of JARVIS:

* **Local document memory (RAG)** - "index the folder <path>" builds a
  local TF-IDF search index of your documents; ask "query_documents" to
  make JARVIS answer questions from them. Everything runs on-device, no
  API keys. `forget_index` clears it. Index lives in `rag_index/` under
  the data folder.
* **Recurring reminders / scheduler** - "remind me to stretch every 2
  hours" or "remind me daily at 9am". Repeating reminders never expire:
  each time one fires it is pushed forward to the next occurrence.
* **Email assistant** - when `EMAIL_IMAP_HOST` / `EMAIL_SMTP_HOST` /
  `EMAIL_USER` / `EMAIL_PASSWORD` are set, JARVIS can check, read and send
  email from the chat ("check my email", "send an email to X saying ...").
  All standard-library (imaplib + smtplib), no third-party dependencies.
* **Chat history search** - "search our chats for <phrase>" finds any past
  conversation, even from previous sessions.
* **Data export / backup** - the `export_data` tool dumps notes, memories,
  reminders and chat history to timestamped JSON + CSV files so your data
  is never held hostage. (Approval-gated and logged, like other sensitive
  tools.)
* **Plugin system** - drop a `.py` file that subclasses `PluginTool` into
  the project `plugins/` folder (or a folder named by `PLUGINS_DIR`) and
  JARVIS loads it on startup without touching core code. `list_plugins`
  shows what is loaded. A bad plugin is reported but never crashes JARVIS.
* **Mood memory & report** - every detected voice-tone read is logged to
  the database. `mood_report` summarises recent trends ("you've sounded
  stressed this week") so JARVIS notices patterns over time.
* **Morning briefing** - `BRIEFING_ON_START=true` greets you on launch
  with the time, weather, pending reminders and a recent mood read.
* **Conversation summaries** - once a chat grows past `SUMMARY_THRESHOLD`
  turns, the older turns are compressed into a summary by the model so
  context survives past the window instead of being dropped.
* **Mood-adapted voice** - with `TTS_MOOD_EMPHASIS=true`, spoken replies
  slow down for a gentle "sad" tone and brighten for "happy", so the
  voice matches the mood detected in your speech.
* **Multi-language + offline speech recognition** - `STT_LANGUAGE` sets
  the recognition language; `STT_PROVIDER=whisper` uses a fully local
  OpenAI-Whisper model (`pip install openai-whisper`) so transcription
  works with no internet connection.
* **Push-to-talk** - with `PTT_ENABLED=true` and `pip install keyboard`,
  hold `PTT_HOTKEY` (default `ctrl+space`) to talk instead of clicking the
  mic button.
* **Voice confirmation** - JARVIS can ask for a spoken "yes or no" before
  important actions via the `confirm_by_voice` tool (falls back to typed
  confirmation when no microphone is available).
* **Folder watcher** - set `WATCH_FOLDER` to an absolute path and JARVIS
  surfaces new/changed files in chat; `WATCH_INDEX_CHANGES=true` also
  feeds them into the local RAG index automatically.
* **Focus-aware recap** - with `FOCUS_RECAP_ENABLED=true`, JARVIS notices
  when the machine has been idle for `FOCUS_RECAP_IDLE_MINUTES` (Windows
  idle detection) and gently nudges you back into focus.

* **Camera fall detection** - with `CAMERA_FALL_ENABLED=true` (default),
  the webcam runs an always-on pose monitor that recognises a fall. When
  one is detected JARVIS starts a `FALL_COUNTDOWN_SECONDS` countdown and
  speaks/prints a cancel prompt; unless you say "I'm ok" (or press the
  camera tile, which toggles it off) it alerts your emergency contact via
  `FALL_ALERT_MESSAGE` through `send_message` (email/WhatsApp) and starts
  a call via `make_call` (Phone Link / `tel:`). Set `FALL_EMERGENCY_NUMBER`
  and/or `FALL_EMERGENCY_EMAIL` in `.env` to enable the alerting half.
  The pose model downloads on first run to `camera/models/`; requires
  `pip install opencv-python mediapipe`.
* **Messaging & calling tools** - `send_message` drafts a message for you:
  email through the configured mail account, or WhatsApp via the official
  `wa.me` compose link (you tap send - JARVIS never automates your chat).
  `make_call` opens the system dialer with a number pre-dialled. Both are
  honest about what happened and are approval-gated + logged sensitive
  tools.

## Phase 32 - multitasking, upload & paste

* **Contacts address book** - tell JARVIS once ("save Mummy's number as
  +233..."), and later "message Mummy" just works. `save_contact` /
  `list_contacts` / `forget_contact` store names in
  `<data_dir>/contacts.json`; `send_message` and the fall detector resolve
  names to numbers automatically.
* **Multitasking apps** - `open_app` never closes what is already open: a
  later launch simply adds another window, so Notepad, Calculator and Paint
  can all run side by side. Pass several names at once - `"notepad,
  calculator"` - to open them together. The new `manage_window` tool brings
  one to the front (`focus`), snaps it to a screen half
  (`snap-left/right/top/bottom`), or `maximize`/`minimize`s it, so you can
  arrange a whole workspace and JARVIS keeps the layout.
* **Upload images & documents** - click the paperclip in the input bar to
  pick files from disk. They are copied into `<data_dir>/uploads` and shown
  as chips above the box. When you send, each attachment is analysed
  *before* the reply: images go to the vision model (`analyze_image`), and
  documents are read with `read_document` and their text is folded into
  the message, so JARVIS answers about the files in the same turn.
* **Paste images & documents** - click the paste icon (or copy then press
  it) and whatever is on the clipboard - a screenshot, a copied image, or
  a copied set of files - is imported as an attachment the same way.

  Images need `GOOGLE_API_KEY` set (Gemini vision) to be *described*;
  without it the file is still attached and JARVIS says so. Documents are
  read fully locally. `UPLOADS_DIR` overrides where imports are stored.

## Phase 33 - smart glasses & wearables

* **Universal glasses link** - the `glasses` tool talks to whatever
  Bluetooth/Windows wearable is paired, with no extra dependencies.
  `glasses` actions: `scan` (list Bluetooth devices), `connect <fragment>`
  (select your glasses), `notify <text>` (deliver a message), `status`
  (what is selected).
* **What it really does** - a message is delivered as a native Windows
  toast (*works for any paired wearable*) and, when the glasses are a
  Bluetooth **audio** output, spoken aloud through them. Vendor HUD
  displays (Meta Ray-Ban screen, XREAL HUD) need their own SDKs, which
  JARVIS cannot reach - and it says so honestly instead of pretending.
* **Mirror replies** - with `GLASSES_MIRROR_REPLIES=true` (or Settings ->
  Glasses) every JARVIS reply is also pushed to the glasses automatically.
* **Honest by design** - JARVIS is desktop software and cannot embed
  itself into glasses hardware; it interfaces with what is paired.

Everything above is additive and optional - set the `.env` flags you want
and JARVIS picks them up.

## Phase 34 - ethical hacking & security lab

A built-in security lab scoped to **authorised testing** (your own machines,
networks and accounts, or anything you have written permission to assess):

* `network_scan` - connect-only scan: ping check + TCP port check on a host
  or CIDR subnet (sends no payloads). Approval-gated.
* `web_recon` - passive recon on a web target: HTTP status, server header,
  which security headers are missing, `robots.txt`, TLS certificate info.
  Approval-gated.
* `cve_lookup` - look up a product/version against public CVE data (free,
  no API key).
* `hash_identify` - recognise hash algorithms locally (MD5/SHA-1/SHA-2,
  bcrypt, SHA-crypt, argon2, WordPress/Drupal...). Nothing leaves the PC.
* `password_audit` - local strength estimate + HaveIBeenPwned check using
  k-anonymity: only the first 5 characters of the SHA-1 hash ever leave the
  machine, and the password is never shown back. Approval-gated.
* `learn_security` - save notes into a persistent security knowledge bank
  (with an OWASP Top 10 baseline) that is injected into every conversation,
  so JARVIS *learns* as you teach it.

The tool descriptions make the ethics explicit: they analyse and test, they
never attack; exploitation of third parties is out of scope.

## Phase 35 - capabilities pack

Everyday power tools with **no new dependencies**:

* `screen_ocr` - read the text currently on screen (or a screen region) via
  the Gemini vision model (needs `GOOGLE_API_KEY`).
* `screen_time` - a small local sampler tracks which apps are in the
  foreground; ask JARVIS what you have been using (top apps + share of time).
* `media_control` - press standard media keys (play/pause/next/previous/stop,
  volume up/down/mute) for whatever music or video is playing (Windows).
  Approval-gated.
* `export_pdf` - render text into a real PDF under `data/exports/` using a
  pure-Python writer (no external PDF libraries). Approval-gated.

## Phase 36 - natural voice & continuous conversation

Two upgrades to how you *talk* to JARVIS:

* **Natural neural voice (edge-tts).** The default system voice (SAPI5 via
  pyttsx3) is robotic; `edge-tts` streams Microsoft's neural voices instead.
  Enable it in `.env`: `TTS_ENGINE=edge`, then set `TTS_VOICE` to a voice
  from `voice/text_to_speech.py::EDGE_VOICES` (e.g. `en-US-EmmaNeural`,
  `en-US-GuyNeural`, `en-GB-SoniaNeural`); the Settings > Voice picker lists
  them too. New deps: `pip install edge-tts soundfile`. Needs internet. If
  they are missing, JARVIS logs why and carries on speaking (or text-only) -
  it never crashes. Mood-adapted rate (happy/sad/angry) still applies.
* **Continuous conversation.** Turn it on with the button next to the mic
  (or Settings > Voice > "Continuous conversation", or
  `CONTINUOUS_CONVERSATION=true` in `.env`). Click the mic and keep talking -
  after each reply JARVIS waits until it has finished speaking, then listens
  again, hands-free. End a session by saying **"stop"** (or "goodbye",
  "that's all", "exit", ...) or by staying silent. The mode is saved between
  restarts.

## Phase 37 - evening pack

Things to say as the day winds down (all local + free, no new dependencies):

* **`einstein`** - *"give me an Einstein quote"*, *"a daily Einstein"*, or
  *"an Einstein fact"*. A curated, deterministic quote/fact of the day.
* **`lighting_ideas`** - *"lighting ideas for focus"* (or reading, relax,
  movie, bedtime, energy). Suggests a colour temperature + brightness; it
  cannot control physical bulbs, but can dim the screen to match.
* **`bedtime_mode`** - *"goodnight, JARVIS"* dims the screen and makes
  replies **quiet (text-only)** so nothing interrupts your sleep. Set
  scheduled quiet hours via `BEDTIME_SCHEDULE_ENABLED` + `BEDTIME_START` /
  `BEDTIME_END` in `.env`, or the Settings > Bedtime tab. Say *"good
  morning"* / *"bedtime mode off"* to restore.
* **`print_document`** - *"print this file"* sends a local `.txt`/`.md`/
  `.pdf`/`.docx`/image to the default Windows printer. Approval-gated.

## Unrestricted mode (Phase 25)

All of the above gates now have an opt-out for the machine's owner. Open
**Settings -> Permissions** and flick on **Unrestricted mode**, or set
`UNRESTRICTED_MODE=true` in `.env`.

When it is on:

* approval-gated tools (`take_screenshot`, `write_file`, `delete_note`,
  `open_app`, `open_url`, `open_path`, `apply_patch`, ...) run directly
  without JARVIS pausing to ask,
* the "ask the user for yes/no" instruction block is removed from the
  system prompt.

The mode is off by default, is saved between sessions, and can be switched
on and off at any time from Settings. Every action is still logged to the
audit log - the boundaries are relaxed, not hidden.

For questions, the matching "you own it" option is the local LLM provider
(see "Your own local model" above): `AI_PROVIDER=localllm` runs your own
model locally, where you control which model - and therefore which
behaviour - is installed.

## UI polish (Phase 17)

Small touches that make JARVIS feel alive:

* **Activity-reactive orb** - the AI core pulses different colours and
  speeds depending on what JARVIS is doing: calm purple when idle, amber
  while thinking, cyan while speaking, red while listening.
* **Blinking caret** - streaming replies type out with a blinking `▌`.
* **"Generating..." indicator** - animated dots appear while JARVIS
  prepares a reply, replaced by the real text when it starts streaming.
* **Button hover feedback** - mic, wake, send, speaker and settings
  buttons glow softly on hover, and the status indicator now ignores
  invalid states gracefully.

## Testing (Phase 18)

The test suite runs with `pytest` and uses a fake/offline provider and
temporary SQLite databases - no API keys, microphone or internet needed.

```powershell
pip install -r requirements-dev.txt
pytest -q                         # run everything
pytest --cov=config --cov=ai --cov=tools --cov=system --cov=memory --cov=utils
pytest tests/test_security.py -q  # a single area
```

Coverage is ~90% across config, the AI brain and providers, the tool
registry, the system monitor/scripts/security layers, memory, note and
reminder tools, and shared utils. Untested lines are almost entirely
network-error branches in the live OpenAI/Anthropic providers. The keys
to the suite:

- `tests/test_tools.py` - registry, streaming parser, and the Brain's
  tool agent loop (including iteration caps).
- `tests/test_security.py` - approval gate, sensitive-tool list, audit
  feed, and the "yes/go ahead" unlock.
- `tests/test_wake_word.py` - voice-wake matching with a fake clock and
  synthetic audio (no microphone).
- `tests/test_config.py` - env parsing: booleans, ints, model lists, and
  the data-dir override.
- `tests/test_logger.py` - logging to file with rotation over a temp dir.
- Every other `test_*.py` matches its module (notes, documents, vision,
  scripts, filesystem, web, memory, system control, UI polish).

## Packaging (Phase 19)

A standalone Windows executable can be built in one command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build.ps1
```

or directly with `pyinstaller jarvis.spec`. Either way the output is a
single file, `dist\JARVIS AI.exe` (~80 MB), which bundles Python, Flet and
every library - nothing else needs to be installed on the target machine.

How the packaged app behaves differently from `python main.py`:

* **Data** is kept out of the bundle: `%USERPROFILE%\.jarvis-ai`
  (`database\jarvis.db`, `logs\jarvis.log`). Source runs keep using the
  local `data\` folder.
* **.env** is looked up next to the executable, so API keys can be
  configured per install (`dist\.env`) - the `.env.example` template is
  bundled inside the exe for reference.
* **No console window** - it launches as a normal GUI app.

Notes:

* First launch may briefly show the Flet desktop client being unpacked
  from the user cache (`~/.flet`); it only happens once.
* Windows SmartScreen may warn about an unsigned executable the first
  time - click "More info" then "Run anyway".

## Performance & cleanup (Phase 20)

Start-up speed was the last big polish target. Measured results:

* `import main` (the whole UI, voice and brain chain) went from ~8.2s to
  ~0.9s - roughly a **10x faster cold start**.
* **Lazy brain**: `ai/brain.py` no longer builds the shared `Brain` (and
  with it the full provider + tool registry) at import time. The first
  `from ai.brain import brain` still works, but constructing the instance
  now happens on first use.
* **Lazy voice stack**: importing `voice.speech_to_text` / `voice.wake_word`
  no longer pulls in numpy, sounddevice and SpeechRecognition. Those load
  only when the microphone is actually used.
* **Graceful shutdown**: pressing the window close button now falls
  through `Dashboard.shutdown()` (`ui/dashboard.py`), which stops the
  wake/mic listener, reminder poller, orb animation and system-monitor
  thread, then destroys the window - no background work left running.
* Background loops were reviewed: reminders poll every 2s (event-wakeable)
  and the monitor repaints every 2s; the orb/caret animations are
  event-driven and already low-frequency, so no change was needed.
* All dependencies in `requirements.txt` are used by the code; the
  packaging artifacts (`build/`, `dist/`) stay git-ignored while
  `jarvis.spec` remains tracked as the build recipe.

## Self-update (Phase 21)

JARVIS can update itself to a newer build, entirely from the Settings
dialog (or by asking it: the `check_for_updates` tool answers).

How to enable it:

1. Host the packaged `JARVIS AI.exe` anywhere with an HTTPS URL.
2. Publish alongside it a JSON manifest, e.g. `jarvis-updates.json`:

   ```json
   {
     "version": "1.1.0",
     "url": "https://example.com/JARVIS AI.exe",
     "sha256": "<hex SHA-256 of the exe - optional but recommended>",
     "notes": "Fix for XYZ"
   }
   ```

   The SHA-256 can be computed with
   `Get-FileHash "dist\JARVIS AI.exe" -Algorithm SHA256`.

3. Put the manifest URL in the `.env` next to the exe:

   ```
   UPDATE_MANIFEST_URL=https://example.com/jarvis-updates.json
   ```

Then:

* **Settings > Software Updates > Check for updates** compares the remote
  version with the running one and shows the release notes.
* **Download & install** fetches the new executable next to the running
  one, verifies its SHA-256 (when the manifest provides one), and asks
  the app to restart. A tiny helper script waits for JARVIS to exit,
  swaps the executable, and relaunches - no manual steps.

Design notes:

* The update never installs without an explicit user action.
* The download is only trusted if its SHA-256 matches the manifest.
* Development runs (`python main.py`) cannot self-update (there is no
  executable to replace); the settings dialog reports this.
* A leftover `JARVIS AI.old.exe` backup is removed automatically on the
  next launch.

## Chat history & memory (Phase 22)

Before this phase JARVIS held every conversation in memory only - close
the window and it was gone. Now everything is saved and restored:

* **Conversations are persisted.** Every message is written to the local
  SQLite database (`memory/database.py`), and on launch JARVIS resumes the
  most recent conversation - chat history, notes, reminders and long-term
  memories all survive a restart.
* **History browser.** The clock icon in the top bar opens a dialog listing
  every saved conversation (title, date, message count) with *open* and
  *delete* buttons. Opening an old chat loads its full context back into
  the assistant.
* **New conversation.** The "+" icon starts a blank chat while keeping old
  ones in the database.
* **Auto-titles.** A conversation is renamed from the first thing you say
  to it (e.g. "what time is sunset today"), so the history list stays
  readable. Saved titles use the same SQLite database.
* **Memory Store.** Settings now has a **MEMORY STORE** panel that lists
  everything JARVIS has been asked to remember, with a delete button per
  entry, and a Refresh button. These same facts are still injected into
  every reply's system prompt via the `remember` / `list_memories` /
  `forget_memory` tools (from Phase 14).

Design notes:

* Only `user` and `assistant` turns are persisted and restored; internal
  agent-loop steps (tool-call lines and tool results) are context-only.
* Conversations restore into a moderately-sized context window (`max_messages`)
  so long histories do not exceed the model's limit; the database keeps the
  full record regardless.
* Deleting the active conversation switches to the most recent one.

## Graphic design (Phase 23)

JARVIS can produce real image files for design requests using **only the
local Pillow library** - nothing is uploaded, no image-gen API key is
needed, and it works fully offline. Ask for things like:

* "make a neon poster for my coffee shop grand opening"
* "design a navy suit prototype with a peak lapel and three buttons"
* "draft a mobile app wireframe for a fashion store"

Three tools power this:

* **`create_poster`** - poster / banner / social-card graphics with five
  styles (`minimal`, `bold`, `gradient`, `grid`, `neon`) and named palettes
  (`ocean`, `sunset`, `forest`, `midnight`, `crimson`) or custom hex
  colours. Title, subtitle, and canvas size are configurable.
* **`design_suit`** - a fashion **suit prototype**: a suit drawn on a
  front-facing silhouette with configurable suit colour, lapel style
  (`notch` / `peak` / `shawl`), number of buttons (1-3), optional tie
  colour, and background. The result includes a colour swatch + spec label.
* **`create_wireframe`** - UI **suite** mockups: clean grey-box wireframes
  for a mobile app (1-3 phone screens with header/search/cards/bottom nav)
  or a desktop website (nav, hero, content blocks, footer).

Design notes:

* Everything is saved as a PNG under `settings.data_dir / "designs"`
  (source runs: `data\designs`), and the saved file path is returned so
  JARVIS can tell you where to find it.
* Because these tools write files, they are approval-gated like
  `write_file`/`take_screenshot`: JARVIS will ask for your go-ahead
  ("yes", "go ahead"...) the first time before rendering.
* No internet connection or API key is required for any of it.

## Code security review (Phase 24)

JARVIS can review software you have built for common security weaknesses,
propose fixes, and apply them - all locally. It is a defensive code
reviewer (like a lightweight Bandit/Semgrep), not an offensive tool: it
only reads and writes paths you point it at. Ask things like:

* "hack into my project in C:\src\myapp and tell me the weaknesses"
* "scan my code for hardcoded secrets"
* "fix that sql injection you found"

Three tools work together:

* **`audit_code`** - scans a file or folder (recursively, skipping
  `.venv`, `node_modules`, `__pycache__`...) and reports potential issues
  with severity, line numbers, a code snippet, and fix advice. Patterns
  include hardcoded secrets/API keys, SQL injection (f-strings / `%s` /
  concatenation), shell/command injection, unsafe `eval`/`exec` and
  `pickle`, path traversal, weak crypto (MD5/SHA-1), plaintext password
  handling, disabled TLS verification, debug mode left on, and broad
  exception handlers.
* **`suggest_patch`** - extract the exact lines around a finding so the
  fix is written against the real, current source.
* **`apply_patch`** - apply an exact `old` -> `new` text replacement.
  It backs the file up to `<file>.bak` first and refuses ambiguous or
  non-matching patches.

Security & safety notes:

* Everything is local - no code is uploaded anywhere.
* `apply_patch` is approval-gated (like `write_file`): JARVIS asks for
  your go-ahead before touching a file.
* A `.bak` copy is always created before a patch is written, so changes
  can be rolled back instantly.
* The scan is heuristic (regex-based) - flags should be treated as "worth
  a look", not guaranteed vulnerabilities. The fix advice and patches come
  from the LLM, so review them before relying on them.
* JARVIS will not patch files for projects it is not explicitly pointed
  at; it is designed for reviewing code you built.
