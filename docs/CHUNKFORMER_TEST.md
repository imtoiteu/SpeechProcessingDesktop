# ChunkFormer (Vietnamese ASR) — temporary test tool

A standalone way to transcribe files with
[`khanhld/chunkformer-large-vie`](https://huggingface.co/khanhld/chunkformer-large-vie)
(ChunkFormer CTC-Conformer, ~110M) to evaluate it against the project's
Whisper-based STT. **Temporary and fully isolated** — it lives in its own venv
(`.venv-chunkformer`), uses only the `chunkformer` package, and changes **nothing**
in the WhisperLiveKit STT stack. Remove it anytime with `rm -rf .venv-chunkformer`.

> ChunkFormer's API is **file/batch-based** (`endless_decode(audio_path=...)`), so
> this is a file transcriber, not a real-time mic backend. It runs on **Apple GPU
> (MPS)** here (≈3 s to decode ~10 s of audio), falling back to CPU automatically.

## Setup (one time)

```bash
uv venv --python 3.12 .venv-chunkformer
uv pip install --python .venv-chunkformer -r requirements-chunkformer.txt
```

The model (~110M) downloads from Hugging Face on first run to the default HF
cache. (Optional: `export HF_TOKEN=...` for higher download rate limits.)

## Usage

```bash
# human-readable segments with timestamps (default)
.venv-chunkformer/bin/python scripts/chunkformer_transcribe.py path/to/audio.wav

# plain text
.venv-chunkformer/bin/python scripts/chunkformer_transcribe.py meeting.m4a --format text

# SRT subtitles from a video, written to a file
.venv-chunkformer/bin/python scripts/chunkformer_transcribe.py talk.mp4 --format srt -o talk.srt

# force CPU (default is auto: MPS → CPU)
.venv-chunkformer/bin/python scripts/chunkformer_transcribe.py audio.wav --device cpu
```

Input may be any ffmpeg-decodable **audio or video** (it's transcoded to 16 kHz
mono WAV first). Output formats: `segments` (default), `text`, `srt`, `vtt`, `json`.

Decode tuning (defaults match the library): `--chunk-size 64`, `--left 128`,
`--right 128`, `--batch-duration 1800` (raise for very long files), `--max-silence 0.5`,
`--model <hf-id>` (default `khanhld/chunkformer-large-vie`).

## Benchmarking models in the app (Batch mode)

Batch mode lets you transcribe the **same uploaded file** with different engines to
compare accuracy, speed and memory. The streaming/mic workflow is unchanged and always
uses the Whisper model loaded at startup.

In the toolbar:

1. Switch the mode toggle from **Streaming** to **Batch**.
2. The model dropdown then offers, in order:
   **ChunkFormer (Vietnamese)** (default), **tiny**, **base**, **small**, **medium**,
   **large-v3-turbo**. Pick one *before* clicking Start.
3. Choose a file and click **Start Transcription**. The transcript renders with
   clickable timestamps for every backend.

**Whisper sizes run the model you pick.** Unlike before (when the batch Whisper path
reused the startup singleton regardless of the name), each Whisper size now runs that
*exact* MLX model via `mlx_whisper.transcribe` — so the comparison is real.
`large-v3` is intentionally **excluded** (too heavy for testing).

| Size | MLX repo | Approx. download |
|---|---|---|
| tiny | `mlx-community/whisper-tiny-mlx` | ~75 MB |
| base | `mlx-community/whisper-base-mlx` | ~137 MB |
| small | `mlx-community/whisper-small-mlx` | ~459 MB |
| medium | `mlx-community/whisper-medium-mlx` | ~1.4 GB |
| large-v3-turbo | `mlx-community/whisper-large-v3-turbo` | ~1.5 GB |

Models download **lazily on first use** (nothing at server startup). mlx_whisper keeps
the *last* size loaded warm (a 1-slot cache), so repeated runs of the same size don't
re-load; switching size reloads. Whisper batch models require **Apple Silicon +
`mlx_whisper`**; if unavailable, `/health` reports them unavailable, the dropdown shows
them disabled, and the batch endpoint falls back to the in-process singleton.

**How it works (isolation preserved):** the server does *not* import ChunkFormer.
The batch endpoint (`POST /v1/audio/transcriptions`, `model=chunkformer`) runs this
same `scripts/chunkformer_transcribe.py` **out-of-process** in `.venv-chunkformer`,
so the STT `.venv` gains no dependencies and the streaming pipeline is untouched.
The routing lives in
[`batch_backends.py`](../WhisperLiveKit/whisperlivekit/batch_backends.py).

The model loads on each batch request (subprocess cold start, ~20–40s the first time).
This is fine for evaluation; a long-lived warm worker is a possible future optimization.

Configure without code changes via env vars (defaults shown):

| Env var | Default |
|---|---|
| `CHUNKFORMER_PYTHON` | `<repo>/.venv-chunkformer/bin/python` |
| `CHUNKFORMER_SCRIPT` | `<repo>/scripts/chunkformer_transcribe.py` |
| `CHUNKFORMER_MODEL` | `khanhld/chunkformer-large-vie` |
| `CHUNKFORMER_DEVICE` | `auto` |
| `CHUNKFORMER_TIMEOUT` | `1800` (seconds) |

If `.venv-chunkformer` is missing, `/health` reports ChunkFormer as unavailable and the
dropdown shows it disabled; selecting it via the API returns a clear 503, not a stack trace.

The CLI form (curl) also works:

```bash
# Batch via ChunkFormer (SRT subtitles)
curl -s http://localhost:8000/v1/audio/transcriptions \
  -F file=@clip.wav -F model=chunkformer -F response_format=srt
# Batch via a specific Whisper size (runs that exact MLX model)
curl -s http://localhost:8000/v1/audio/transcriptions \
  -F file=@clip.wav -F model=small -F response_format=verbose_json
# OpenAI-compatible default (empty/'whisper-1' -> in-process singleton)
curl -s http://localhost:8000/v1/audio/transcriptions \
  -F file=@clip.wav -F response_format=verbose_json
```

> Note: **Streaming** mode still uses the model loaded at startup (a singleton, no
> hot-swap). To stream with a different size, restart with `--model <size>`. This
> caveat no longer applies to **Batch** Whisper sizes — they load the requested model.

## Notes / limitations

- Output is **lowercase Vietnamese without punctuation** (CTC model).
- The standalone CLI does **not** replace STT — it's a separate evaluation tool. (The
  Batch-mode integration above *does* let you transcribe with it inside the app.)
- Keep `chunkformer` out of the STT `.venv` and the TTS `.venv-tts` (it brings its
  own torch/torchaudio/transformers).

## Verified

`scripts/chunkformer_transcribe.py tests/fixtures/sample.wav` →
`xin chào` / `hôm nay là một ngày đẹp trời ở hà nội` /
`tôi đang thử nghiệm hệ thống nhận dạng giọng nói tiếng việt ...` (MPS, ~3 s).
