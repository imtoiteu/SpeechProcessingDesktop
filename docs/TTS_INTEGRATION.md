# TTS Integration — VieNeu-TTS Text-to-Speech

This document describes how Text-to-Speech (TTS) is integrated into STTLive using
[VieNeu-TTS](https://github.com/pnnbao97/VieNeu-TTS), **without changing any
Speech-to-Text (STT) backend logic**.

> Backward compatibility is the highest priority. The STT stack
> (WhisperLiveKit + MLX Whisper) is unchanged. TTS runs in a **separate process
> and a separate virtual environment** and is reached over HTTP.

The "Text → Speech" tab mirrors VieNeu-TTS's own streaming app
(`apps/web_stream.py` + `client/client.html`): **model selection + runtime
switching**, **all built-in voices**, **Text/URL input**, and **low-latency
streaming playback with a live spectrum**.

### Runtime decisions (validated on this MacBook Air)

- **Engine: VieNeu-TTS, `standard` mode**, integrated directly via the SDK
  (`from vieneu import Vieneu`) — no Fish-Speech compatibility layer.
- **Models (selectable, mirrors web_stream `AVAILABLE_MODELS`):**
  - `q4` — `pnnbao-ump/VieNeu-TTS-0.3B-q4-gguf` (Fast/Light)
  - `q8` — `pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf` (High Quality, **default**)
  - `ngochuyen` — `pnnbao-ump/VieNeu-TTS-0.3B-ngoc-huyen-gguf-Q4_0` (Ngoc Huyen LoRA)
  - plus any custom GGUF repo id. Switching reloads the backbone at runtime.
- **Codec: `neuphonic/neucodec-onnx-decoder-int8`** (ONNX Runtime, CPU).
- **Fully torch-free** — GGUF backbone via llama.cpp+Metal + ONNX codec. Measured:
  ~4 s load+warmup, **first streamed audio ~0.3 s**.
- **Built-in voices:** q4/q8 ship **6 Vietnamese voices** (Northern/Southern,
  male/female): Vĩnh, Bình, Tuyên, Đoan, Ly, Ngọc; ngochuyen ships 1. All are
  exposed in the voice dropdown and refresh when the model changes.
- **No voice cloning.** A decode-only ONNX codec can't *encode* new reference
  audio, and the original streaming app has no cloning either. The cloning UI was
  removed (no disabled/non-functional controls). Cloning would require the full
  PyTorch codec (`vieneu[gpu]`) and is out of scope for this torch-free build.

### Dependencies (important)

The sidecar reuses **`VieNeu-TTS/.venv`**. A plain `uv sync` installs the
torch-free *core* but **not** `llama-cpp-python` or `trafilatura` — they live only
in the heavy `gpu` group. Install them separately (the launcher preflights this):

```bash
cd VieNeu-TTS && uv sync
uv pip install --python .venv "llama-cpp-python==0.3.16" \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal/ \
    --index-strategy unsafe-best-match        # GGUF backbone (REQUIRED)
uv pip install --python .venv "trafilatura>=2.0.0"   # URL extraction (optional)
```

> A later bare `uv sync` re-prunes `llama-cpp-python`; `scripts/run_tts_server.sh`
> detects this and prints the fix.

---

## 1. Architecture

```
Browser — STTLive web UI
   ├─ "Speech → Text" tab  ── existing STT (UNCHANGED) ──▶ WhisperLiveKit server  (:8000)
   └─ "Text → Speech" tab  ── HTTP (JSON / WAV stream) ──▶ TTS sidecar           (:8011)
                                                              │
                                                   src/tts/server.py   (FastAPI, /tts/*)
                                                              │
                                                   src/tts/service.py  (lifecycle, model switch,
                                                                        streaming, URL extract, encode)
                                                              │
                                                   src/tts/vieneu_engine.py  (direct VieNeu SDK adapter)
                                                              │
                                                   vieneu.Vieneu  (GGUF + ONNX codec, VieNeu-TTS/.venv)
```

### Files

| Path | Role |
|---|---|
| `src/tts/config.py` | `TtsConfig` + `AVAILABLE_MODELS` + `resolve_model` (all `TTS_*` env) |
| `src/tts/vieneu_engine.py` | VieNeu SDK adapter: load/switch model, voices, synth, `infer_stream` |
| `src/tts/service.py` | Lifecycle, request serialization, streaming WAV, URL extract, audio encode |
| `src/tts/server.py` | FastAPI sidecar exposing `/tts/*` |
| `src/tts/models.py` | Pydantic request/response schemas |

---

## 2. HTTP API

| Method & path | Purpose |
|---|---|
| `GET /tts/health` | readiness + active model/device/voices |
| `GET /tts/models` | selectable models (q4/q8/ngochuyen) + active flag |
| `POST /tts/model` | switch the active model (reloads backbone) → new voices |
| `GET /tts/voices` | built-in preset voices for the active model |
| `POST /tts/synthesize` | one-shot `{text, voice?, format?, temperature?}` → audio |
| `GET/POST /tts/stream` | low-latency streaming WAV (`?text=&voice=&temperature=`) |
| `POST /tts/extract_url` | extract article text from a URL (trafilatura) |

`format` (one-shot only): `wav`, `flac`, `ogg` (libsndfile) and `mp3`, `opus`
(pydub+ffmpeg). VieNeu's standard inference honours `temperature` (with a fixed
`top_k` + model-baked repetition penalty) and `normalize`. Streaming is WAV/PCM16.

---

## 3. Setup & run

```bash
# one-time (see "Dependencies" above for the two uv pip install lines)
cd VieNeu-TTS && uv sync && uv pip install ...   # llama-cpp-python + trafilatura
cd ..
./scripts/download_tts_model.sh   # OPTIONAL: warm the HF cache
./scripts/run_tts_server.sh       # sidecar on :8011 (preflights deps)
```

Open the STT UI → **"Text → Speech"** tab. The model loads lazily on first use
(or set `TTS_EAGER_LOAD=1`).

### Configuration (`TTS_*` env vars)

| Var | Default | Meaning |
|---|---|---|
| `TTS_BACKBONE` | `pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf` | initial GGUF backbone |
| `TTS_CODEC` | `neuphonic/neucodec-onnx-decoder-int8` | codec repo |
| `TTS_DEVICE` | `cpu` | backbone device |
| `TTS_PORT` | `8011` | sidecar port |
| `TTS_TEMPERATURE` | `0.7` | default sampling temperature |
| `TTS_EAGER_LOAD` | `0` | load the model at startup instead of lazily |
| `TTS_VENV` / `TTS_PYTHON` | `VieNeu-TTS/.venv` | interpreter for the sidecar |

---

## 4. Notes / limitations

- **Streaming** is wired end-to-end (server `infer_stream` → WAV/PCM16 →
  browser Web Audio + live spectrum + first-audio latency). A non-streaming
  `/tts/synthesize` is kept as a fallback + for the API.
- **Voice cloning / custom presets** are not available with the torch-free ONNX
  decoder and have been removed from the UI (they were never in the upstream
  streaming app).
- **STT is untouched** — this subsystem shares no code, process or venv with
  WhisperLiveKit.
