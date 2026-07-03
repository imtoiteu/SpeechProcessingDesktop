# STTLive Desktop App

A **native desktop launcher/wrapper** (Tauri v2) around the existing STTLive stack.
It changes nothing about how STT or TTS work — it only *supervises* them and shows
the existing web UI inside an app window.

## What was added (scope of this work)

The desktop layer was added **without touching the STT/TTS engines or the web UI**.
Deleting `desktop/` and the new `scripts/*` reverts to the exact web-only setup.

- **`desktop/`** — a self-contained Tauri v2 app: a Rust supervisor
  (`src-tauri/src/main.rs`) that health-checks STT (`:8000/health`) and TTS
  (`:8011/tts/health`), starts each server only if it isn't already up, embeds the
  existing `:8000` UI in an iframe (`ui/index.html`), and on exit stops **only** the
  processes it started (never an externally-launched server).
- **`scripts/launch.config.json`** — an OS-aware command map (macOS/Windows/Linux → how
  to start STT and TTS). The launcher reads it at startup, so backend commands change
  without recompiling; a built-in fallback keeps it working if the file is absent.
- **Per-OS sidecar scripts** — `run_stt_server.sh`/`run_tts_server.sh` (macOS),
  `run_stt_linux.sh`/`run_tts_linux.sh` (Linux), `run_stt_windows.ps1`/
  `run_tts_windows.ps1` (Windows). macOS keeps the original `mlx-whisper` + Metal
  commands; Windows/Linux use the cross-platform `faster-whisper` STT backend and
  CPU/CUDA `llama-cpp-python` for TTS.
- **`tauri.conf.json`** — `bundle.targets: "all"`, so each OS produces its native
  installers (macOS `.app`/`.dmg`, Windows NSIS `.exe`/`.msi`, Linux AppImage/`.deb`/`.rpm`).
- **Docs** — this file (per-OS prerequisites, run/build, limitations, test checklists)
  plus a README quick-reference.

> **Runtime status:** macOS Apple Silicon is the primary, tested runtime. Windows and
> Linux are **structurally prepared but pending validation on real hardware** — nothing
> about them was faked or claimed as tested. See the Windows/Linux sections below.

## What it does

1. Locates the repo (via `STTLIVE_REPO`, the working directory, or the executable path).
2. Checks whether **STT** is already serving `http://localhost:8000/health`.
   * If not, it starts STT via the platform launch command (see
     [OS-aware launch configuration](#os-aware-launch-configuration) — macOS uses
     [`scripts/run_stt_server.sh`](../scripts/run_stt_server.sh)).
   * If an STT server is **already running**, it leaves it alone.
3. Opens the existing STT web UI (`:8000`) inside the desktop window (embedded in an
   iframe, so the web version is untouched).
4. Checks **TTS** at `http://localhost:8011/tts/health` and shows its status.
5. Starts **TTS on demand** — click **"Start Text-to-Speech"** — via the platform TTS
   command (macOS: [`scripts/run_tts_server.sh`](../scripts/run_tts_server.sh)). It
   never starts a second copy if one is already up.
6. Shows live **STT/TTS status badges** in the top bar.
7. On exit, stops **only** the child processes it started itself. A server that was
   already running before the app launched is **never** killed.

### Design (why it's low-risk)

- The native layer only spawns the **existing launch scripts** and does HTTP health
  checks. No STT/TTS engine code is touched, moved, or rewritten.
- On macOS/Linux the scripts `exec` their servers, so the child PID *is* the server —
  stopping the child stops the server cleanly (no orphaned `uvicorn`). (Windows caveat
  below.)
- Everything lives in a self-contained `desktop/` folder plus a handful of `scripts/`;
  the rest of the repo is unchanged. Deleting `desktop/` fully reverts to the web-only
  setup.

```
desktop/
├─ package.json            # npm scripts: dev / build / icon
├─ app-icon.png            # (you generate this — see "Icons")
├─ ui/
│  └─ index.html           # thin status bar + iframe of the :8000 STT UI
└─ src-tauri/
   ├─ Cargo.toml
   ├─ build.rs
   ├─ tauri.conf.json       # bundle.targets = "all" (per-OS installers)
   ├─ capabilities/default.json
   ├─ icons/               # placeholder PNGs (regenerate with `npm run icon`)
   └─ src/main.rs          # process supervisor + health checks + lifecycle

scripts/
├─ launch.config.json       # OS -> {stt, tts} launch command map (edit, no recompile)
├─ run_stt_server.sh        # macOS STT (mlx-whisper / Metal)
├─ run_tts_server.sh        # macOS TTS (llama-cpp-python Metal)
├─ run_stt_linux.sh         # Linux STT (faster-whisper)
├─ run_tts_linux.sh         # Linux TTS (llama-cpp-python CPU/CUDA)
├─ run_stt_windows.ps1      # Windows STT (faster-whisper)
└─ run_tts_windows.ps1      # Windows TTS (llama-cpp-python CPU/CUDA)
```

## OS-aware launch configuration

The launcher never hard-codes platform commands. It reads
[`scripts/launch.config.json`](../scripts/launch.config.json), which maps each OS to
the exact program + args used to start STT and TTS:

```jsonc
{
  "macos":   { "stt": {"program": "bash",       "args": ["scripts/run_stt_server.sh"]},
               "tts": {"program": "bash",       "args": ["scripts/run_tts_server.sh"]} },
  "linux":   { "stt": {"program": "bash",       "args": ["scripts/run_stt_linux.sh"]},
               "tts": {"program": "bash",       "args": ["scripts/run_tts_linux.sh"]} },
  "windows": { "stt": {"program": "powershell", "args": ["-NoProfile","-ExecutionPolicy","Bypass","-File","scripts/run_stt_windows.ps1"]},
               "tts": {"program": "powershell", "args": ["-NoProfile","-ExecutionPolicy","Bypass","-File","scripts/run_tts_windows.ps1"]} }
}
```

- Relative paths resolve against the repo root (the app spawns with the repo as CWD).
- To change a backend command (e.g. switch STT to `--backend whisper`, or point at a
  different venv), **edit this file — no recompile needed**. Or edit the script it
  points to. Or set the per-server env vars each script honours (see the table below).
- Override the config file location with `STTLIVE_LAUNCH_CONFIG`.
- If the file is missing or malformed, the app falls back to built-in defaults that are
  identical to the values above, so it still works out of the box.

## Prerequisites (MacBook, Apple Silicon)

The desktop app is **Mac-only** to build and run. On the Mac you need:

- **The STT stack already set up** (`.venv` with `whisperlivekit-server`) and, for TTS,
  the `VieNeu-TTS/.venv` — see the root [README](../README.md#setup). The desktop app
  launches these; it does not install them.
- **Rust** (stable): `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`
- **Xcode Command Line Tools**: `xcode-select --install`
- **Node.js 18+** (for the Tauri CLI): `brew install node`
- Tauri's macOS system webview (WKWebView) ships with macOS — nothing to install.

## Install & run

```bash
cd desktop
npm install            # installs the @tauri-apps/cli dev dependency

# Dev mode — hot-reloads the Rust supervisor + UI. STT auto-starts if :8000 is down.
npm run dev

# Release build — produces STTLive.app and a .dmg under
# desktop/src-tauri/target/release/bundle/
npm run build
```

If you run the **built** `.app` from outside the repo, tell it where the repo is:

```bash
STTLIVE_REPO="$HOME/Desktop/Speech2Text" open -a STTLive
```

(When launched from within the repo, or in `npm run dev`, the repo root is found
automatically.)

## Icons

The committed `src-tauri/icons/*.png` are flat placeholder icons so `dev`/`build`
don't fail, and `desktop/app-icon.png` is a placeholder source (a copy of the 512px
icon). **Before packaging** (especially for Windows `.ico` / macOS `.icns`), regenerate
all platform icon formats from a real square PNG:

```bash
cd desktop && npm run icon    # tauri icon ./app-icon.png -> all sizes incl. .icns/.ico
```

Replace `desktop/app-icon.png` with your own 512×512+ PNG first to brand the app.

## Configuration (env vars)

The scripts the app launches accept the same env vars as manual use:

| Server | Vars |
|---|---|
| STT | `STT_MODEL`, `STT_BACKEND`, `STT_BACKEND_POLICY`, `STT_LANGUAGE`, `STT_HOST`, `STT_PORT`, `STT_PYTHON` |
| TTS | `TTS_BACKBONE`, `TTS_CODEC`, `TTS_DEVICE`, `TTS_PORT`, `TTS_EAGER_LOAD`, `TTS_VENV`, `TTS_PYTHON` |

Set them in the environment before launching the app. The desktop app itself reads
only `STTLIVE_REPO` (optional repo-root override).

## What cannot be tested on the Linux VPS

Everything Apple-specific:

- MLX-Whisper / Metal STT inference.
- Microphone capture & streaming.
- The real VieNeu-TTS model (Metal `llama-cpp-python` wheels).
- The Tauri build itself (needs macOS WKWebView + Xcode toolchain).

The VPS is for editing the launcher, scripts, and docs only. **All runtime behavior
must be verified on the MacBook.**

## Desktop runtime behavior: STT mic / WebSocket / TTS startup

These fixes address issues seen only in the embedded desktop webview (the web
version at `http://localhost:8000` was unaffected). All changes are guarded so the
plain web page behaves exactly as before.

### STT — blank dropdowns + "WebSocket or mic aborted" (root cause)

The STT frontend had an **unguarded top-level** call,
`navigator.mediaDevices.addEventListener('devicechange', …)`. In the desktop
webview, `navigator.mediaDevices` is `undefined` (restricted/embedded context), so
that line threw a `TypeError` and **aborted the rest of the script** — which is why
the **language/model selectors were empty** (they are populated further down the
file) while the record button (wired earlier) still "worked" enough to hit a generic
error. Fixes in `WhisperLiveKit/whisperlivekit/web/live_transcription.js`:

- **Feature-detect `navigator.mediaDevices`** before adding the `devicechange`
  listener → the script no longer aborts → **selectors populate** (Auto/Vietnamese/
  English, and `large-v3-turbo` etc.). This is the core fix.
- **Health checked separately from the socket:** on a live-mic start, a WebSocket
  failure now triggers a quick `GET /health` probe to distinguish *server down* from
  *server up but socket failed*.
- **The one generic error was split into three** distinct, actionable messages:
  - *STT server not reachable* (WebSocket/health failed),
  - *WebSocket connection failed* (server up, socket not),
  - *microphone unavailable / permission denied* — with a friendly macOS hint
    (System Settings › Privacy & Security › Microphone). Mic success is **not**
    faked: if the webview exposes no mic API, the UI says so plainly.
- File/batch STT is untouched and is restored by the same guard.

### macOS microphone permission (Tauri config added)

- `desktop/src-tauri/Info.plist` → `NSMicrophoneUsageDescription` (required for
  WKWebView to prompt for the mic).
- `desktop/src-tauri/entitlements.plist` → `com.apple.security.device.audio-input`,
  referenced from `tauri.conf.json` → `bundle.macOS.entitlements` (hardened-runtime
  builds).

> **Must verify on Mac:** with these in place the built `.app` should prompt for and
> use the mic. If `navigator.mediaDevices` is still `undefined` inside the embedded
> iframe (a WebKit secure-context limitation for cross-origin frames), the guard keeps
> the whole UI working and shows the clear mic message; the fallback is to open
> `http://localhost:8000` in a browser (full web version) for live mic. The dropdown
> fix does **not** depend on any of this — it works regardless.

### TTS — no terminal needed

The wrapper passes `?desktop=1` to the embedded UI. In desktop mode the TTS tab now:

- shows an **inline "Start TTS Server"** button when the sidecar is down (the old
  message told users to run `scripts/run_tts_server.sh` by hand — gone in desktop
  mode);
- keeps **"Generate speech" disabled** and the **Model/Voice selects showing
  "Start TTS server first"** until `:8011/tts/health` is ready;
- on click, asks the wrapper (via `postMessage`) to run the OS-aware `start_tts`
  sidecar command, **polls `/tts/health` up to 90 s**, then loads models/voices and
  enables Generate; the top-bar badge flips to **TTS running** via normal polling;
- on timeout, shows a clear error pointing at the TTS dependency setup.

The top-right **"Start Text-to-Speech"** button still works; the tab button is an
additional contextual entry point. On the plain web page (no `?desktop=1`) the tab
falls back to the original "run the script" hint — web behavior is preserved.

## MacBook test checklist

Run these on the Mac after pulling the branch and doing `cd desktop && npm install`.
**Rebuild** after pulling (`npm run build`) — the mic Info.plist/entitlement only
take effect in a built `.app`, and dev mode may not prompt for the mic.

- [ ] **STT launch** — start the app with nothing on :8000; STT auto-starts and the
      UI appears once `/health` is ready. (First run downloads/loads the MLX model.)
- [ ] **Dropdowns populate** — the language selector shows Auto/Vietnamese/English and
      the model selector shows `large-v3-turbo` (this was the blank-dropdown bug).
- [ ] **No double-start** — start `whisperlivekit-server` manually first, then launch
      the app; it should attach to the running server and **not** spawn a second one.
- [ ] **Microphone / streaming STT** — in the *Speech → Text* tab, run live mic
      transcription; accept the macOS mic prompt. If denied, verify the message names
      the mic (not a generic "WebSocket or mic" error) and points to System Settings.
- [ ] **Error clarity** — stop the STT server and click record: the message should say
      the *server is not reachable*, distinct from a mic-permission message.
- [ ] **File / batch STT** — upload an audio/video file, pick a model, transcribe.
- [ ] **TTS in-tab start** — with TTS down, open the *Text → Speech* tab: Generate is
      disabled, selects read "Start TTS server first", and an **inline "Start TTS
      Server"** button appears. Click it (no terminal); badge/tab flip to ready and
      Model/Voice populate.
- [ ] **TTS top-right button** — the header **Start Text-to-Speech** still starts TTS.
- [ ] **Text-to-Speech tab** — pick a model + voice, synthesize/stream audio.
- [ ] **App-close cleanup** — quit the app (Cmd-Q). Servers the app started stop
      (`lsof -i :8000` / `lsof -i :8011` show nothing). A server you started manually
      **before** the app keeps running.
- [ ] **Desktop build** — `npm run build` produces `STTLive.app` / `.dmg`; launch the
      bundle (with `STTLIVE_REPO` set if outside the repo) and repeat the STT/TTS checks.

---

# Windows

> **Status: structurally prepared, runtime pending validation on real Windows.**
> The Tauri desktop shell, the OS-aware launch map, and the Windows PowerShell
> launch scripts are all in place. The STT/TTS *backends* have not been run on
> Windows from this repo yet — they must be validated on an actual Windows machine.
> Nothing about Windows was faked or claimed as tested.

### Why STT/TTS need different backends on Windows

- **STT**: the macOS command uses `--backend mlx-whisper`, which is Apple-Silicon
  only. `scripts/run_stt_windows.ps1` defaults to `--backend faster-whisper` instead —
  the cross-platform backend that WhisperLiveKit's own CLI auto-selects on non-Apple
  hosts (CPU by default; CUDA if a GPU build of faster-whisper/ctranslate2 is installed).
  This is the upstream-supported Windows path, but accuracy/latency on Windows is
  **unverified** here.
- **TTS**: the macOS setup installs the **Metal** `llama-cpp-python` wheel. Windows has
  no Metal, so `scripts/run_tts_windows.ps1` expects a **CPU** (or CUDA) wheel. TTS is
  torch-free (llama.cpp + ONNX codec), so CPU is the safe default, but this has **not**
  been run on Windows.

### Prerequisites (Windows)

- **Rust** (stable, MSVC toolchain): <https://rustup.rs>
- **Microsoft C++ Build Tools** (Desktop C++ workload).
- **WebView2 runtime** — preinstalled on Windows 10/11; otherwise install the Evergreen
  runtime from Microsoft.
- **Node.js 18+**: <https://nodejs.org>
- **Python 3.12 + `uv`**, plus the STT and TTS venvs (see backend setup below).

### Windows backend setup (pending validation)

```powershell
# STT venv (faster-whisper — CPU; add a CUDA build for GPU)
uv venv --python 3.12 .venv
uv pip install --python .venv -e .\WhisperLiveKit
uv pip install --python .venv faster-whisper

# TTS venv (VieNeu-TTS core + CPU llama-cpp-python wheel)
cd VieNeu-TTS; uv sync; cd ..
uv pip install --python VieNeu-TTS\.venv "llama-cpp-python==0.3.16" `
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/ `
    --index-strategy unsafe-best-match
uv pip install --python VieNeu-TTS\.venv "trafilatura>=2.0.0"
```

### Windows dev / build

```powershell
cd desktop
npm install
npm run dev      # dev shell (STT auto-start requires the STT venv above)
npm run build    # -> NSIS .exe + .msi under desktop\src-tauri\target\release\bundle\
```

### Windows runtime limitations

- **Backends unverified** — treat STT/TTS on Windows as experimental until run on real
  hardware.
- **Process cleanup caveat** — PowerShell cannot `exec`-replace itself, so the launcher's
  child is the `powershell` process, and killing it may **not** kill the Python server it
  spawned (possible orphaned `python.exe`). macOS/Linux don't have this problem (bash
  `exec`). If you hit orphans, stop the server manually
  (`Get-Process python | Stop-Process`) — a job-object based tree-kill can be added later.
- **No MLX/Metal** — do not expect Apple-Silicon-class speed.

### Windows test checklist

- [ ] **Tauri app launch** — `npm run dev` opens the STTLive window.
- [ ] **STT backend available** — `powershell -File scripts\run_stt_windows.ps1` starts
      `whisperlivekit-server` with `faster-whisper` and serves `:8000/health`.
- [ ] **TTS backend available** — `powershell -File scripts\run_tts_windows.ps1` serves
      `:8011/tts/health` (CPU llama-cpp-python wheel installed).
- [ ] **Health checks** — both status badges turn green in the app.
- [ ] **Packaging output** — `npm run build` produces `.exe` (NSIS) and/or `.msi`.
- [ ] **Cleanup** — after quitting, confirm no orphaned `python.exe` (see caveat above).

---

# Linux

> **Status: structurally prepared, runtime pending validation on real Linux.**
> The Tauri shell, launch map, and Linux shell scripts exist. The STT `faster-whisper`
> path is upstream-supported on Linux; TTS runs via a CPU/CUDA `llama-cpp-python` wheel.
> Neither has been run on Linux from this repo — validate on a real Linux machine.
> (This VPS can edit the code but cannot run the webview build or the ML backends.)

### Prerequisites (Linux, Debian/Ubuntu example)

```bash
# Tauri system deps (WebKitGTK)
sudo apt update
sudo apt install -y libwebkit2gtk-4.1-dev build-essential curl wget file \
    libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
# Rust + Node
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
# Node.js 18+ via your distro or nvm
```

### Linux backend setup (pending validation)

```bash
# STT venv (faster-whisper — CPU; add a CUDA build for GPU)
uv venv --python 3.12 .venv
uv pip install --python .venv -e ./WhisperLiveKit
uv pip install --python .venv faster-whisper

# TTS venv (VieNeu-TTS core + CPU llama-cpp-python wheel)
cd VieNeu-TTS && uv sync && cd ..
uv pip install --python VieNeu-TTS/.venv "llama-cpp-python==0.3.16" \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu/ \
    --index-strategy unsafe-best-match
uv pip install --python VieNeu-TTS/.venv "trafilatura>=2.0.0"
```

### Linux dev / build

```bash
cd desktop
npm install
npm run dev      # dev shell (STT auto-start requires the STT venv above)
npm run build    # -> AppImage + .deb + .rpm under desktop/src-tauri/target/release/bundle/
```

### Linux runtime limitations

- **Backends unverified** — STT/TTS on Linux is experimental until run on real hardware.
- **No MLX/Metal** — CPU (or CUDA) only; do not expect Apple-Silicon speed.
- **WebKitGTK required** — the app window needs `libwebkit2gtk-4.1` at runtime.

### Linux test checklist

- [ ] **Tauri app launch** — `npm run dev` opens the STTLive window.
- [ ] **STT backend available** — `bash scripts/run_stt_linux.sh` starts
      `whisperlivekit-server` with `faster-whisper` and serves `:8000/health`.
- [ ] **TTS backend available** — `bash scripts/run_tts_linux.sh` serves
      `:8011/tts/health` (CPU llama-cpp-python wheel installed).
- [ ] **Health checks** — both status badges turn green in the app.
- [ ] **Packaging output** — `npm run build` produces an AppImage / `.deb` / `.rpm`.
- [ ] **App-close cleanup** — servers the app started stop; a pre-existing server is left
      running (bash `exec` gives clean single-PID kill, same as macOS).
