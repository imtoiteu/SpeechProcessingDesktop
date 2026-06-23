# 18. Local testing UI (Gradio) — usage + sample collection

> A lightweight **local** Gradio UI to drive the existing pipeline by hand: upload
> audio/video, transcribe, download TXT/SRT/VTT, and do live-mic transcription with
> partial + final text. Purpose: **rapid real-world testing and Vietnamese sample
> collection** — not a production app. No accounts, no database, no cloud.
> It reuses the pipeline unchanged ([src/vnstt/ui.py](../src/vnstt/ui.py)); **no core
> modules were modified.** 30 tests pass.

## Install & run

```bash
uv pip install -e '.[ui]'      # installs gradio (the only new dependency, optional)
python -m vnstt.ui             # or: vnstt-ui
# opens http://127.0.0.1:7860  (local only; not exposed to the network)
```

Top of the page: **Engine** (default `whisper.cpp` / Metal; `faster-whisper` available
as the cross-check) and **Language** (default `vi`). These apply to all three tabs.

## Tabs

| Tab | Do | Get |
|---|---|---|
| **Audio** | upload `wav/mp3/m4a/flac` → **Transcribe** | transcript + **TXT / SRT / VTT** download boxes |
| **Video** | upload `mp4/mov/mkv` → **Transcribe** | same (audio is extracted via ffmpeg — same pipeline) |
| **Microphone** | **Record** → speak → **Stop** | **Final** (committed, stable) + **Partial** (live estimate) |

Mic notes: *Final* text only grows and never rewrites; *Partial* is the current
still-changing guess. Press **Stop** to flush the last sentence into Final. **Clear**
starts a new session.

## Collecting representative Vietnamese samples

The goal is to move past the clean/likely-TTS fixtures and get the **real-world,
dialectal, noisy** audio that doc 17 flagged as the missing evidence for a definitive
accuracy verdict. Drop collected clips into `tests/fixtures/eval/` (gitignored area is
fine) and keep a short note of the reference text where you know it.

Aim for a small spread across the categories from `CLAUDE.md`'s benchmark policy:

- **Dialect:** Northern (Hà Nội), Central (Huế/Đà Nẵng — the hardest), Southern (HCMC).
- **Condition:** clean, then noisy (café/street/fan), and far-field (phone on a table).
- **Content:** conversational, a lecture/monologue, a meeting (overlapping speakers),
  and one with **technical terminology / code-switching** (English product names).
- **Length:** a few 10–30 s clips per category is enough — this is a sanity set, not a
  full benchmark.

Quick ways to capture: the **Microphone** tab directly; phone voice memos exported as
`m4a`; or short clips from Vietnamese YouTube/podcasts (for personal evaluation only).

## How to evaluate

1. **Engine A/B:** transcribe the same clip with `whisper.cpp` then `faster-whisper`
   (switch the Engine dropdown) and compare. Watch for whisper.cpp's `máy tiếng`-class
   slips vs faster-whisper's **trailing-silence fabrications** (doc 17).
2. **Per dialect/condition:** note where accuracy drops (Central dialect, noise,
   far-field, technical terms are the expected weak spots).
3. **Streaming feel (mic):** judge latency and whether partial→final stabilises cleanly;
   confirm onset words survive (the doc-17 fix).
4. Save the transcript (Copy button or the TXT download) next to the audio so the sample
   set doubles as a tiny labelled eval set for later.

## Known UI limitations (from the adversarial review)

- **One tab at a time.** All ASR inference is serialized under a single lock (the models
  aren't thread-safe) and events are `concurrency_limit=1`. Running a file transcription
  while the mic streams will make them wait on each other.
- **Mic latency tracks the engine.** Under sustained load on a fanless Mac, thermal
  throttling pushes streaming RTF toward 1 and finalize latency to ~1.4 s (doc 16). Use
  `PhoWhisper-small` GGML or a fan-equipped Mac for longer sessions.
- **Live-mic audio is resampled in-process** with a lightweight linear resampler (browser
  mic ≠ 16 kHz); fine for testing. For archival-grade decoding, prefer **file upload**
  (ffmpeg path). Mic streaming output is **TXT-equivalent only** (no SRT/VTT timestamps).
- A first-chunk race at *Record* start can rarely drop ~0.5 s of the very first word;
  re-record if the opening word is missing.

## Troubleshooting: "model not found" (previously a segfault)

The default model paths are **relative** (`models/...`). Earlier, launching the UI from
a directory other than the repo root meant pywhispercpp couldn't find the file; it
resolved the path to `None`, loaded a **NULL** whisper context, and **segfaulted on the
first transcription** (an uncatchable native crash). Fixed two ways:

1. **Robust resolution** — `resolve_model_arg` (in `cli.py`) now tries the path against
   the current directory **and** the repo root, so the UI works launched from anywhere.
2. **Validation before the native call** — the engine constructors validate the path and
   raise a clear `ModelLoadError` (caught by the UI → shown in the transcript box) instead
   of handing a bad value to pywhispercpp. A startup pre-flight also prints a warning.

If you see a `⚠️ Model could not be loaded` message, point at the real weights:
```bash
# pass an ABSOLUTE path; or run from the repo root
transcribe --model /abs/path/to/ggml-PhoWhisper-medium.bin <file>
```
Regression coverage: `tests/test_model_path.py` (a bad path must raise, never crash).
