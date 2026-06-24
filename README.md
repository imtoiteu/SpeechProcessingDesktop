# STTLive — Local-first Vietnamese Speech-to-Text + Text-to-Speech

A local-first Vietnamese **STT + TTS** workbench optimized for Apple Silicon, built on
[WhisperLiveKit](WhisperLiveKit/) (streaming/batch ASR) with an integrated
[VieNeu-TTS](VieNeu-TTS/) text-to-speech sidecar. Everything runs on-device; nothing is
sent to a cloud API. Research, architecture decisions, and the benchmark plan live in
[`docs/`](docs/).

## Features

- **Real-time microphone transcription** — streaming Vietnamese ASR via MLX-Whisper
  (`large-v3-turbo`), with a live web UI.
- **Batch file / video transcription with model benchmarking** — transcribe the *same*
  file with **ChunkFormer** (Vietnamese CTC, default) or **Whisper** `tiny` / `base` /
  `small` / `medium` / `large-v3-turbo`, each running its real model, to compare
  accuracy / speed / memory.
- **Text-to-Speech** — VieNeu-TTS with selectable models, built-in Vietnamese voices
  (Northern/Southern, male/female), Text **or** URL input, and low-latency streaming
  playback.
- **One web UI, two tabs** — *Speech → Text* and *Text → Speech*.

## Architecture

Three isolated runtimes, each in its own virtual environment, talking over HTTP:

```
Browser — STTLive web UI (http://localhost:8000)
   ├─ "Speech → Text" tab ─▶ WhisperLiveKit server (:8000)            [.venv]
   │                            ├─ Streaming: MLX-Whisper (in-process singleton)
   │                            └─ Batch:     ChunkFormer subprocess  [.venv-chunkformer]
   │                                          or MLX-Whisper (per-model)
   └─ "Text → Speech" tab ─▶ VieNeu-TTS sidecar (:8011)               [VieNeu-TTS/.venv]
```

| Environment | Used by | Notes |
|---|---|---|
| `.venv` | STT (WhisperLiveKit + MLX-Whisper) | torch + `mlx_whisper`; serves the web UI |
| `VieNeu-TTS/.venv` | TTS sidecar | **torch-free** (GGUF via llama.cpp + ONNX codec) |
| `.venv-chunkformer` | ChunkFormer batch backend | isolated torch/torchaudio; subprocess only |

The STT and TTS subsystems share **no code, process, or venv** — TTS is an optional
add-on and the streaming hot path is never touched by it.

## Setup

Requires **Python 3.12** (ASR/TTS runtimes lag newer releases), `ffmpeg`, and
[`uv`](https://docs.astral.sh/uv/). Apple Silicon recommended (MLX).

### 1. STT server (required)

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -e ./WhisperLiveKit   # installs the whisperlivekit-server CLI
uv pip install --python .venv mlx-whisper            # Apple-Silicon ASR backend
```

Models download lazily from the Hugging Face hub on first use — nothing to pre-fetch.

### 2. TTS sidecar (optional)

Reuses `VieNeu-TTS/.venv` (torch-free). See [docs/TTS_INTEGRATION.md](docs/TTS_INTEGRATION.md)
for details; the short version:

```bash
cd VieNeu-TTS && uv sync
# `uv sync` does NOT install these two (they live only in the heavy gpu group):
uv pip install --python .venv "llama-cpp-python==0.3.16" \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal/ \
    --index-strategy unsafe-best-match      # GGUF backbone (required)
uv pip install --python .venv "trafilatura>=2.0.0"   # URL extraction (optional)
cd ..
```

### 3. ChunkFormer batch backend (optional)

For Vietnamese batch transcription / benchmarking. Fully isolated — see
[docs/CHUNKFORMER_TEST.md](docs/CHUNKFORMER_TEST.md):

```bash
uv venv --python 3.12 .venv-chunkformer
uv pip install --python .venv-chunkformer -r requirements-chunkformer.txt
```

## Run

```bash
# STT server + web UI on :8000
whisperlivekit-server \
  --model large-v3-turbo \
  --backend mlx-whisper \
  --backend-policy simulstreaming \
  --language auto \
  --host localhost --port 8000

# (optional) TTS sidecar on :8011 — preflights deps, powers the "Text → Speech" tab
./scripts/run_tts_server.sh
```

Then open **http://localhost:8000**:

- **Speech → Text** — choose **Streaming** (live mic) or **Batch** (upload audio/video),
  pick a model, and transcribe. Results show clickable timestamps; export is available.
- **Text → Speech** — pick a model + voice, type text or paste a URL, and stream the audio.

> Exact run/stop commands and environment variables are in [`run.md`](run.md).

## Models

| Mode | Default | Alternatives |
|---|---|---|
| **Streaming** (mic) | `large-v3-turbo` | `tiny` · `base` · `small` · `medium` — switching requires a server restart (`--model <size>`; the engine is a startup singleton) |
| **Batch** (file/video) | **ChunkFormer** (Vietnamese) | `tiny` · `base` · `small` · `medium` · `large-v3-turbo` — each runs its real MLX model. `large-v3` is intentionally excluded (too heavy for testing). |
| **TTS** | `q8` (High Quality) | `q4` (Fast/Light) · `ngochuyen` (LoRA) — 6 built-in Vietnamese voices (q4/q8); voice cloning is not available in the torch-free build. |

Batch Whisper sizes download lazily on first use (~75 MB tiny → ~1.5 GB turbo) and the
last-used size stays warm in memory. `/health` reports which backends are available and
the UI disables any that aren't.

## Tests

```bash
# STT + batch-backend + UI/export tests
.venv/bin/python -m pytest tests/ --ignore=tests/tts -q

# TTS tests (skip automatically unless the `vieneu` SDK is importable)
VieNeu-TTS/.venv/bin/python -m pytest tests/tts -q
```

## Legacy CLI (Phase-1 MVP)

The original offline file transcriber (`vnstt` package, PhoWhisper-medium) is still
available via the `transcribe` console script — useful as an accuracy reference:

```bash
.venv/bin/transcribe path/to/audio.mp3 --format txt,srt,vtt
.venv/bin/transcribe path/to/audio.mp3 --engine faster-whisper --format srt
```

See the project history in [`docs/`](docs/) (e.g.
[docs/10-implementation-decision.md](docs/10-implementation-decision.md)) for how the
project evolved from this CLI to the current streaming app.

## License

This repository vendors third-party components, each under its own license:
[WhisperLiveKit/](WhisperLiveKit/), [VieNeu-TTS/LICENSE](VieNeu-TTS/LICENSE). Model
weights (PhoWhisper, Whisper, ChunkFormer, VieNeu-TTS) are governed by their respective
model cards. Use is intended for local, non-commercial research.
