# 13. whisper.cpp / Metal validation (Phase-4 fallback, brought forward)

> Triggered by the Phase-1 finding that faster-whisper on CPU misses RTF<1 on the M3. Goal: does
> whisper.cpp on Metal fix the speed wall? **Yes — decisively.** Details + the resulting engine decision below.

## Setup
- `pywhispercpp 1.5.0` installed from a **prebuilt wheel** (no cmake/build needed — good portability signal), Python 3.12.
- Metal confirmed engaged at runtime: `use gpu = 1`, `GPU family: MTLGPUFamilyApple9` (M3).

## Speed results (9.85 s VN sample, dev M3 / 16 GB)

| Engine | Model | Backend | RTF (cold / warm) |
|---|---|---|---|
| **whisper.cpp** | standard whisper-medium (size proxy) | **Metal** | **0.21 / 0.16** |
| **whisper.cpp** | **PhoWhisper-medium GGML** (`dongxiat/ggml-PhoWhisper-medium`, 1.5 GB fp16) | **Metal** | **0.21 / 0.16** |
| faster-whisper | PhoWhisper-medium CT2 int8 | CPU | 2.3 – 6.9 (thermal variance) |

**whisper.cpp/Metal is ~10–40× faster than the CPU path and clears RTF<1 by ~5×.** A 1 h file ≈ ~10 min.

## Accuracy note (NOT a benchmark — one synthetic TTS sample)
- faster-whisper CT2: **perfect** — `...trên máy tính apple silicon.`
- whisper.cpp GGML: **2 errors** — spurious leading `my`, and `máy tiếng` (vs `máy tính`).
- Beam search (`beam_size=5`) did **not** change the GGML output → the errors are **not** a greedy-vs-beam issue;
  they're inherent to this GGML/whisper.cpp path. Likely causes: third-party GGML conversion quality, and/or
  whisper.cpp processing the lead-in without VAD. **Must be resolved by Stage-1 accuracy benchmarking**, not by
  this one clip. (Standard whisper-medium made the same `máy tiếng` error, so it may be model/decoding, not unique to the conversion.)

## Stage-0 risk retired
Stage 0 flagged "no pre-built PhoWhisper GGML artifact." One now exists (`dongxiat/ggml-PhoWhisper-medium`,
1.5 GB fp16), so no self-conversion was needed. A clean self-conversion remains an option if its accuracy disappoints.

## Engine decision (revised)
- **Primary on Apple Silicon: `whisper.cpp` (Metal).** Now the **CLI default** — speed makes the product usable.
- **Kept in the abstraction: `faster-whisper` (CT2).** Accuracy reference on this sample, and the cross-platform
  CUDA path for future servers. Selectable via `--engine faster-whisper`.
- Both implement the same `ASREngine` interface; the chars/sec hallucination filter applies to both via the orchestrator.

## Residual items (for Stage 1 / later)
1. **Accuracy A/B** whisper.cpp-GGML vs faster-whisper-CT2 on real VN data (the `máy tiếng`/`my` regression must be characterized).
2. **Word-level timestamps** are not yet surfaced from whisper.cpp (segment-level only) — fine for SRT/VTT now; add later if needed.
3. **whisper.cpp VAD / lead-in trimming** to remove artifacts like the leading `my`.
4. Consider a **self-converted or quantized** PhoWhisper GGML (q5_0 ≈ 0.5 GB) if accuracy/size needs it.

## Engine footprint
- `models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin` — 1.5 GB (whisper.cpp/Metal)
- `models/PhoWhisper-medium-ct2-fasterWhisper/` — 1.4 GB (faster-whisper reference)
