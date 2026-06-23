# 10. Implementation Path Decision

> Decision made on the weighting you set: **fastest path to a usable product + low implementation risk**,
> with Vietnamese accuracy, streaming, and maintainability as the next priorities. Not optimized for
> exhaustive benchmarking. One primary path, one fallback. Grounded in Stage 0 evidence + docs 01–09.

## The decision

**Primary:** **PhoWhisper-medium** running on **faster-whisper (CTranslate2)** with **Silero VAD** (built in),
**ffmpeg** decode, behind a thin **engine abstraction**, on **pinned Python 3.12**. Files transcribe as an
incremental segment stream; real-time mic (a later phase) wraps the same engine with **WhisperLiveKit /
LocalAgreement-2** rather than building a streaming policy from scratch.

**Fallback:** **same model + pipeline, engine swapped to whisper.cpp (Metal/CoreML)** with PhoWhisper converted
to GGML — used only if CPU-only faster-whisper misses the latency budget on Apple Silicon, or if CT2 proves
problematic on a target platform. Because only the engine box changes, this is a config switch, not a rewrite.

> Held constant across primary/fallback: **the model (PhoWhisper) and the pipeline.** Only the *engine* varies.
> That is the lowest-risk way to keep Vietnamese accuracy fixed while de-risking platform performance.

## Why this path (justification against your priorities)

| Priority | Why PhoWhisper + faster-whisper wins |
|---|---|
| **Fastest path to product** | faster-whisper gives **VAD + word timestamps + segment streaming out of the box** → minimal glue code. **Pre-converted PhoWhisper CT2 weights already exist** ([quocphu/PhoWhisper-ct2-FasterWhisper](https://huggingface.co/quocphu/PhoWhisper-ct2-FasterWhisper)) so there's no conversion step to write. File-transcription MVP is a thin wrapper. |
| **Vietnamese accuracy** | PhoWhisper is the **peer-reviewed, verified VN strong-tier** model (medium CMV-Vi 8.27 — re-verified against the paper), **BSD-3** (no license drama). Alternatives' accuracy edges are unproven: ChunkFormer's lead is on *normalized* WER (cross-paper, not apples-to-apples); the VN-turbo fine-tune's accuracy is unpublished. |
| **Streaming** | Two modes, both covered: **files** stream as faster-whisper yields segments (incremental output, native); **mic** uses the mature **LocalAgreement-2** policy via WhisperLiveKit (Apache-2.0) over the *same* faster-whisper backend. No bespoke streaming engine to maintain. |
| **Maintainability** | One dominant, battle-tested dependency; an **engine abstraction** keeps faster-whisper / whisper.cpp / transformers interchangeable; portable to CUDA servers for the future SmartDocs path. |
| **Low implementation risk** | The single most widely-used Whisper runtime + existing VN weights + a verified-working escape hatch (transformers+MPS, proven on this exact Mac in Stage 0). The one unknown (CT2 on the dev Python) is **eliminated by pinning Python 3.12**, where CT2 wheels are well-supported. |

## What Stage 0 actually verified (evidence behind the call)

- **[VERIFIED on this M3/16 GB Mac]** A Whisper-family model (VN turbo fine-tune) loads and transcribes Vietnamese **correctly on both MPS and CPU** via the installed torch 2.11 + transformers 5.6 → the Whisper runtime path works here. This is the proven escape hatch.
- **[VERIFIED]** Disk is the binding local constraint (≈12–17 GB free, volatile via APFS purgeable; hit 100% once after one 3 GB model). Drives the "medium not large by default" choice and one-model-at-a-time handling.
- **[VERIFIED]** PhoWhisper repos are BSD-3, single `pytorch_model.bin` (medium 2.8 GB / large 5.7 GB, no safetensors). ChunkFormer 586 MB, CC-BY-NC.
- **[UNVERIFIED → mitigated]** faster-whisper/CT2 on the *dev* Python (3.14) untested → **mitigate by pinning 3.12**. ChunkFormer install (deepspeed) untested → **deferred, not on the critical path**.

## Why not the alternatives (briefly)

- **ChunkFormer as primary** — too much unproven risk for a "fastest/lowest-risk" mandate: unvalidated `deepspeed` install, single-author ecosystem, Apple-Silicon GPU unverified, and its accuracy advantage is a normalized-WER cross-paper artifact. **Deferred** as a future native-streaming option, not dropped.
- **VN-turbo fine-tune as primary** — attractive for decode latency, but the available checkpoint has **no published WER and no stated license** → unacceptable as the accuracy-bearing core today. Kept as a **latency lever** to A/B later.
- **transformers+MPS as primary** — proven to run, but weaker for production streaming/exports and slower than CT2 int8. Demoted to **bring-up escape hatch**, not the product engine.
- **PhoWhisper-large by default** — 5.7 GB barely fits 16 GB RAM + scarce disk, for a sub-0.3 WER gain that vanishes on noisy speech. **Deferred** to an optional accuracy-ceiling check.

## Recommended stack

| Layer | Choice | Notes |
|---|---|---|
| Runtime | **Python 3.12** (via `uv`) | **NOT 3.14** — ecosystem wheels. Single most important stack decision. |
| Model | **PhoWhisper-medium** (BSD-3); small as mic-latency fallback | from `quocphu/PhoWhisper-ct2-FasterWhisper` (CT2) or convert `vinai/PhoWhisper-medium` |
| Engine (primary) | **faster-whisper** (CTranslate2), `int8` on Mac CPU | built-in Silero VAD, word timestamps, segment generator |
| Engine (fallback) | **whisper.cpp** (Metal/CoreML) + PhoWhisper-GGML | swap behind the engine abstraction |
| VAD | **Silero** (`vad_filter=True`) | no separate dependency |
| Decode | **ffmpeg** (installed) | audio + video audio-extraction, → 16 kHz mono |
| Mic streaming (later) | **WhisperLiveKit / whisper_streaming** (LocalAgreement-2) | wraps faster-whisper; don't build from scratch |
| Timestamps | faster-whisper `word_timestamps=True` | benchmark timing accuracy before trusting SRT/VTT sync |
| Exports | hand-written TXT / SRT / VTT formatters | tiny, no dependency |
| Packaging | library core + CLI (typer or argparse) | UI deferred |

## Architecture diagram (concrete)

```
   Audio file (wav/mp3/m4a/flac)   Video file (mp4/mov/mkv)        Microphone  [Phase 3]
            │                              │                            │
            └──────────────┬───────────────┘                           │
                           ▼                                           ▼
                 ffmpeg decode/extract                        mic capture (16kHz)
                 → 16 kHz mono PCM                                     │
                           │                                          ▼
                           ▼                                   Silero VAD segmenter
                 ┌─────────────────────────────────────┐              │
                 │  ASREngine (abstraction)             │              ▼
                 │   • PRIMARY: faster-whisper (CT2)    │      WhisperLiveKit /
                 │     - Silero VAD (vad_filter)        │      LocalAgreement-2
                 │     - PhoWhisper-medium int8         │      over faster-whisper
                 │     - word timestamps                │              │
                 │     - SEGMENT GENERATOR (streaming)  │              │
                 │   • FALLBACK: whisper.cpp (Metal)    │              │
                 └─────────────────────────────────────┘              │
                           │                                          │
                           ▼                                          ▼
                 Transcript assembler  ◄───────────── partial + committed-final
                           │
                           ▼
                 Exporters:  TXT  |  SRT  |  VTT
```
The shared core (decode → VAD → engine → assembler → exporters) is identical for all inputs; video adds only
an ffmpeg extraction front-step; mic adds capture + the streaming-commit policy. One pipeline, thin per-mode policy.

## Implementation phases

| Phase | Objective | Exit criteria |
|---|---|---|
| **1 — Audio MVP** | File → VN transcript + TXT/SRT/VTT, incremental output, CLI | transcribe wav/mp3/m4a/flac with word timestamps; valid SRT/VTT; RTF < 1.0 on the dev Mac at PhoWhisper-medium int8 |
| **2 — Video** | mp4/mov/mkv via ffmpeg extraction, reuse Phase-1 core | video → subtitles through the identical path; no pipeline duplication |
| **3 — Mic streaming** | Real-time incremental transcript via WhisperLiveKit/LocalAgreement-2 | stable (non-flickering) partial+final within agreed latency; fall to small-model/turbo/whisper.cpp if latency insufficient |
| **4 — Perf fallback (conditional)** | whisper.cpp-Metal engine + quantization tuning, only if Mac latency demands it | latency/throughput target met without accuracy regression beyond tolerance |

## MVP scope (Phase 1 only)

**In:** local audio files (wav/mp3/m4a/flac); Vietnamese transcript; word/segment timestamps; **TXT + SRT + VTT**
export; incremental console output as segments decode; CLI (`transcribe <file> --format srt,vtt,txt`);
PhoWhisper-medium via faster-whisper + Silero VAD (int8); engine abstraction with one implementation.

**Out of MVP:** video, microphone, any UI, correction LLM, diarization, accuracy tuning, multi-model benchmarking.

## Deferred items (explicitly not now)

Video (Phase 2, soon) · real-time mic (Phase 3) · whisper.cpp fallback (Phase 4, conditional) · LLM correction
layer (only if a future A/B proves net WER gain) · **ChunkFormer evaluation** (native-streaming option to revisit
in Phase 3 if PhoWhisper streaming is painful) · PhoWhisper-large accuracy-ceiling check · speaker diarization ·
YouTube/network-stream sources · SmartDocs-Agent integration · MLX/Apple-only engines · exhaustive Stage-1 benchmarking.

## Residual risks (honest)

1. **faster-whisper/CT2 not yet run on this project** — mitigated by Python 3.12 pin + transformers+MPS escape hatch (proven). First Phase-1 task validates it.
2. **CPU-only faster-whisper latency on Mac for real-time mic** — addressed by Phase 3 model/engine levers (small model, turbo, whisper.cpp-Metal). File MVP (batch) is unaffected.
3. **Whisper word-timestamp fragility** → SRT/VTT sync — measure timing accuracy in Phase 1, not just WER.
4. **PhoWhisper frozen since Dec 2023** — acceptable; it's a stable artifact, and the engine abstraction allows model swaps.
