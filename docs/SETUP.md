# SETUP — reproducible clone → run → build

*Language: **English** · [Tiếng Việt](SETUP.vi.md)*

This is the single reference for getting a **clean clone** running without depending on
any local machine state (old venvs, stray folders, global Python). Everything is driven
by scripts under [`scripts/`](../scripts).

macOS Apple Silicon is the **primary, validated** platform. Windows/Linux status is at
the end.

---

## A. Clean-clone quick start (macOS)

```bash
git clone https://github.com/imtoiteu/SpeechProcessingDesktop.git
cd SpeechProcessingDesktop
./scripts/bootstrap_macos.sh
./scripts/build_desktop_macos.sh
./scripts/open_desktop_macos.sh
```

`bootstrap_macos.sh` is idempotent (safe to re-run). It:

1. Checks the OS + prerequisites (`uv`, `ffmpeg`, `node`/`npm`, `cargo`) and prints
   install hints for anything missing.
2. Creates the **root `.venv`** (STT): `whisperlivekit` (editable) + `mlx-whisper`, and
   verifies `.venv/bin/whisperlivekit-server` exists.
3. Sets up **`VieNeu-TTS/.venv`** (TTS): `uv sync`, then reinstalls the Metal
   `llama-cpp-python==0.3.16` wheel + `trafilatura`, and verifies `import vieneu`,
   `import llama_cpp`, `import trafilatura`.
4. Installs desktop deps (`npm install`) and generates icons (`npm run icon`).

It does **not** download model weights (they lazy-download on first use). To prefetch the
TTS model:

```bash
./scripts/bootstrap_macos.sh --warm-tts     # runs scripts/download_tts_model.sh
```

> **Why the TTS wheel is reinstalled every run:** a bare `uv sync` inside `VieNeu-TTS`
> installs the torch-free core but can *prune* `llama-cpp-python` (it lives only in the
> heavy optional group). The bootstrap reinstalls the Metal wheel each time so the GGUF
> backbone always works.

## B. Daily use

```bash
./scripts/open_desktop_macos.sh
```

If the app isn't built yet, this prints: *"Please run ./scripts/build_desktop_macos.sh first."*

## C. Manual / debug (run the servers directly, no desktop app)

```bash
./scripts/run_web_macos.sh      # STT web UI + API  → http://localhost:8000  (alias of run_stt_server.sh)
./scripts/run_stt_server.sh     # STT server: streaming (/asr) + batch (/v1/audio/transcriptions)
./scripts/run_tts_server.sh     # TTS sidecar        → http://localhost:8011  (health: /tts/health)
```

`run_stt_server.sh` env overrides (defaults preserve the validated macOS command):

| Variable | Default | Meaning |
|---|---|---|
| `STTLIVE_STT_MODEL` | `large-v3-turbo` | Streaming model size |
| `STTLIVE_STT_LANGUAGE` | `auto` | Language (`auto` = detect) |
| `STTLIVE_STT_HOST` | `localhost` | Bind host |
| `STTLIVE_STT_PORT` | `8000` | Bind port |

(The older `STT_MODEL` / `STT_LANGUAGE` / `STT_HOST` / `STT_PORT` names still work as
fallbacks. Backend/policy stay `mlx-whisper` / `simulstreaming`.)

Dev mode (hot-reload wrapper): `./scripts/dev_desktop_macos.sh`.

## D. The two-venv model

Standardize around exactly these two primary environments:

| Environment | Subsystem | Key executable |
|---|---|---|
| **root `.venv`** | STT — WhisperLiveKit + mlx-whisper | `.venv/bin/whisperlivekit-server` |
| **`VieNeu-TTS/.venv`** | TTS — vieneu + llama-cpp-python + trafilatura | `VieNeu-TTS/.venv/bin/vieneu-stream` |

Optional third venv:

| Environment | Subsystem | Set up with |
|---|---|---|
| **`.venv-chunkformer`** | Batch **ChunkFormer (Vietnamese)** only | `./scripts/setup_chunkformer.sh` |

`.venv-stage0` and `.venv-tts` are **legacy/experimental** — no current UI feature uses
them. `./scripts/diagnose_env.sh` reports which venvs exist and whether the critical
imports resolve, so you can tell the current ones from the old ones at a glance.

> **Do not copy `.venv` folders between machines.** Virtual environments hard-code
> absolute paths and platform-specific binary wheels (mlx-whisper, llama-cpp-python's
> Metal build, torch). Always recreate them on each machine with
> `./scripts/bootstrap_macos.sh` (and `./scripts/setup_chunkformer.sh` if needed). All
> `.venv*` folders are git-ignored for the same reason.

## E. UI feature → backend mapping

| UI feature | Endpoint / backend |
|---|---|
| **Streaming mic** | WebSocket `ws://<stt>/asr` — MLX-Whisper `large-v3-turbo` (in-process singleton) on macOS Apple Silicon |
| **Microphone playback** | the desktop WebView recording is re-encoded to **WAV/PCM** so it replays reliably in the app (Safari/WKWebView can't replay its raw MediaRecorder blob) |
| **Batch file/video** | `POST <stt>/v1/audio/transcriptions` |
| **Batch + ChunkFormer (Vietnamese)** | same endpoint → routed to the ChunkFormer subprocess (`.venv-chunkformer`) |
| **Batch + tiny/base/small/medium/large-v3-turbo** | same endpoint → per-model MLX-Whisper |
| **TTS** | `http://<tts>/tts/*` on `:8011` (or the configured TTS URL); health `GET /tts/health`; models `q4` / `q8` / `ngochuyen` + a voice dropdown |
| **Desktop Settings** | selects **Local Managed** vs **Remote Server** mode, STT URL, TTS URL, auto-start STT, auto-start TTS, timeout |

The server logs the routing decision for every batch request (requested model, selected
backend, ChunkFormer/mlx-whisper/fallback, elapsed time) and logs the streaming
backend/model once per `/asr` session — so you can confirm which engine ran.

> **ChunkFormer warm-up:** the **first** ChunkFormer batch run is slower because the
> model loads/warms up on demand; **subsequent** runs are faster as long as the STT
> server process stays alive (it caches the loaded model).

## F. Local Managed Mode

- STT and TTS run on the **same machine** as the app.
- The app may **auto-start STT** on `:8000` if it isn't already running.
- **TTS lazy-starts** on `:8011` when you first open the Text→Speech tab / press *Start TTS Server*.
- On exit the app stops **only** the processes it started itself (never external ones).

## G. Remote Server Mode

- The app does **not** start any local servers.
- You enter the STT/TTS **URL by IP or domain** (e.g. `http://192.168.1.20:8000`).
- Intended for LAN/company deployments and Windows/Linux clients pointing at a validated
  (e.g. macOS) backend host.

Switch modes any time via the **⚙ Settings** button in the app's top bar.

## H. Config file location

First launch (if no config exists) shows a setup dialog; after that it's skipped and the
saved config is reused. The config lives **outside the repo**:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/STTLive/config.json` |
| Windows | `%APPDATA%\STTLive\config.json` |
| Linux | `~/.config/STTLive/config.json` |

Fields: `mode` (`local`/`remote`), `stt_url`, `tts_url`, `auto_start_stt`,
`auto_start_tts`, `timeout_seconds`.

## I. Reset config

```bash
# macOS
rm "$HOME/Library/Application Support/STTLive/config.json"

# Linux
rm "$HOME/.config/STTLive/config.json"

# Windows (PowerShell)
Remove-Item "$env:APPDATA\STTLive\config.json"
```

The next launch will show the first-run setup dialog again.

## J. Windows / Linux status & limitations

**The desktop client (Tauri app) builds and runs on all three OSes.** The *local
backend* story differs:

- There is **no MLX/Metal** off macOS — the macOS `mlx-whisper` STT and the macOS Metal
  `llama-cpp-python` TTS wheel are **macOS-only**.
- **Local STT on Windows/Linux** uses `faster-whisper` (`run_stt_windows.ps1` /
  `run_stt_linux.sh`), the upstream cross-platform backend (CPU, or CUDA with a GPU
  ctranslate2 build). This path is **not validated by this project** — verify it on real
  hardware before relying on it.
- **Local TTS on Windows/Linux** needs a **CPU or CUDA** `llama-cpp-python` wheel (NOT
  the macOS Metal wheel). Also unvalidated here.
- **ChunkFormer** on Windows/Linux can run on CPU/CUDA via `.venv-chunkformer`, but only
  the macOS (MPS/CPU) path has been exercised.
- **Recommended on Windows/Linux:** run the app in **Remote Server Mode** against a
  validated STT/TTS host (e.g. a Mac) on your LAN.

Bootstrap/build/run scripts:

```bash
# Linux
./scripts/bootstrap_linux.sh            # desktop client deps (add --with-stt for a local faster-whisper venv)
./scripts/build_desktop_linux.sh
./scripts/open_desktop_linux.sh

# Windows (PowerShell, from the repo root)
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\bootstrap_windows.ps1   # add -WithStt for a local venv
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_desktop_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\open_desktop_windows.ps1
```

Tauri does not cross-compile: each installer is produced on its own OS. Linux also needs
system libs (`webkit2gtk`, `libsoup`, …); Windows needs the MSVC C++ Build Tools + the
WebView2 runtime. See [`DESKTOP_APP.md`](DESKTOP_APP.md) for the full prerequisite lists.

---

## Diagnostics

```bash
./scripts/diagnose_env.sh
```

Prints OS/arch, Python/uv/ffmpeg/node/cargo versions, whether each venv and its key
executable exist, whether the TTS-critical imports (`vieneu`, `llama_cpp`, `trafilatura`)
resolve, whether the required Silero VAD asset is present, desktop config presence, and
the config-file path — so you never confuse a current venv with an old one.

### Required runtime asset: Silero VAD

STT loads `WhisperLiveKit/whisperlivekit/silero_vad_models/silero_vad.onnx` (~2.3 MB,
opset-16) at startup. It ships **committed** in the repo (a `.gitignore` exception to the
general `*.onnx` rule), so a clean clone already has it. If it is ever missing,
`bootstrap_macos.sh` and `run_stt_server.sh` restore it automatically from the pinned
upstream WhisperLiveKit tag before STT starts, and `run_stt_server.sh` fails with a clear
message if the restore can't complete.
