# vnstt — Local-first Vietnamese Speech-to-Text

Phase 1 (MVP): transcribe a local **audio** file to Vietnamese text with timestamps and
export **TXT / SRT / VTT**. Architecture, decisions, and roadmap are in [`docs/`](docs/).

- **Model:** PhoWhisper-medium (VinAI, BSD-3-Clause)
- **Engine (Apple Silicon default):** **whisper.cpp / Metal** via `pywhispercpp` — RTF ~0.16 on M3
- **Engine (alt / cross-platform):** faster-whisper (CTranslate2), `int8` on CPU — accuracy reference, CUDA servers
- Both behind a swappable `ASREngine` abstraction; pick with `--engine`
- **VAD:** Silero (faster-whisper path) · **Decode:** ffmpeg

> Status: Phase 1. Video, real-time microphone, a UI, and an optional correction LLM are deferred
> (see [docs/10-implementation-decision.md](docs/10-implementation-decision.md)).

## Setup

Requires **Python 3.12** (not 3.14 — ASR runtimes lag new releases), `ffmpeg`, and [`uv`](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv -e .

# Default engine: whisper.cpp / Metal — GGML weights (~1.5 GB)
.venv/bin/python -c "from huggingface_hub import snapshot_download; \
snapshot_download('dongxiat/ggml-PhoWhisper-medium', local_dir='models/ggml-phowhisper-medium')"

# Optional alt engine: faster-whisper — CT2 weights (~1.4 GB)
.venv/bin/python -c "from huggingface_hub import snapshot_download; \
snapshot_download('quocphu/PhoWhisper-ct2-FasterWhisper', \
allow_patterns=['PhoWhisper-medium-ct2-fasterWhisper/*'], local_dir='models')"
```

## Usage

```bash
# whisper.cpp / Metal (default, fast on Apple Silicon)
.venv/bin/transcribe path/to/audio.mp3 --format txt,srt,vtt
# writes audio.txt, audio.srt, audio.vtt next to the input

# faster-whisper (CPU; accuracy reference / CUDA servers)
.venv/bin/transcribe path/to/audio.mp3 --engine faster-whisper --format srt

# video works through the same pipeline (ffmpeg extracts the audio)
.venv/bin/transcribe path/to/video.mp4 --format srt,vtt

# near-real-time streaming
.venv/bin/transcribe --mic                       # live microphone (Ctrl-C to stop)
.venv/bin/transcribe path/to/audio.wav --stream  # simulated real-time from a file
```

Options: `--engine whisper.cpp|faster-whisper`, `--model <path>` (defaults per engine),
`--language vi`, `--format txt,srt,vtt`, `--output-base <prefix>` (faster-whisper: `--device`, `--compute-type`).

## Tests

```bash
uv pip install --python .venv pytest
.venv/bin/pytest -q          # export tests run anywhere; smoke test needs the model
```

## License

Code: see repository. Model: PhoWhisper is BSD-3-Clause (VinAI Research).
