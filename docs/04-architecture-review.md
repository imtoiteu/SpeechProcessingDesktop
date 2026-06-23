# 4. Architecture Review

> Not a final architecture. This reviews the candidate from `CLAUDE.md` and proposes revisions to test.

## Candidate (from brief)
```
Audio/Video/Mic → Audio Source Layer → Normalization → Silero VAD → Segment Queue
  → ASR Engine → Streaming Transcript → (Optional Correction) → Final Transcript
```

## Strengths
- **Shared pipeline + Audio Source abstraction** is the right backbone and matches proven multi-source designs (WhisperLive: file/mic/RTSP through one path). [VERIFIED](https://github.com/collabora/WhisperLive)
- **VAD-based segmentation** before ASR is documented best practice (reduces hallucination, enables batching/streaming). [VERIFIED](https://github.com/m-bain/whisperX)
- **Correction layer marked optional** — correct posture given the mixed evidence ([02 A6](02-assumption-audit.md)).
- Linear and easy to reason about.

## Weaknesses & gaps (the load-bearing critique)

1. **It collapses two different execution modes into one line.** File/video transcription is *incremental batch* (process segments, emit as you go, latency not critical). Mic is *real-time streaming* (latency-critical, output must stay stable). They share components but need different control. The diagram hides this. → **Add an explicit "execution mode" concept** (incremental-batch vs real-time) over the shared components.
   - *Does this violate the "one shared pipeline" contract?* No — the shared core (decode → VAD → segmenter → engine abstraction → timestamping → assembler → exporters) is **identical across all three inputs**. The execution-mode controller is a **thin policy layer** selecting buffering/commit behavior; it is not a second pipeline. This must be stated explicitly in the design so "one pipeline" is satisfied in substance, not just on a diagram.

2. **No stabilization/commit stage for real-time.** "Segment Queue → ASR → Streaming Transcript" implies one-shot decode per segment. But Whisper is a 30 s batch model; naive chunking splits words and yields flickering output. Real streaming requires **overlapping re-decode + a commit policy** (LocalAgreement-2 or AlignAtt). This is the single biggest missing piece. [VERIFIED](https://arxiv.org/html/2307.14743)

3. **Audio decode/resample is implicit.** Needs an explicit decode stage (ffmpeg) producing 16 kHz mono PCM — required by both Silero VAD and Whisper. Video audio extraction is a special case of the *same* decode stage, not a separate pipeline.

4. **Timestamp & export stage is missing — and word timestamps are not free.** SRT/VTT need word/segment timestamps via faster-whisper `word_timestamps=True` or WhisperX alignment. But Whisper-family word timestamps are **known to be fragile** (DTW/cross-attention, can desync on music/jingles) and PhoWhisper inherits this — so timestamp accuracy must be **benchmarked explicitly**, not assumed. Export formatters (TXT/SRT/VTT) are a real component, not an afterthought.

5. **ASR Engine is drawn as one fixed box** — but engine choice is the highest-risk portability decision (MLX=Apple-only; faster-whisper=CPU-on-Mac; whisper.cpp=portable+Metal). → **Engine must be an abstraction with ≥2 interchangeable backends**, also required for the Phase-1 benchmark. **It must also span two model *families*: emulated-streaming Whisper models (PhoWhisper, needing LocalAgreement/AlignAtt) and natively-streaming CTC models (ChunkFormer, which is now a co-primary candidate — non-commercial decision, 2026-06-23). If ChunkFormer wins, the real-time path simplifies (no re-decode commit policy) and timestamps come from CTC rather than fragile cross-attention.** The abstraction should expose "supports native streaming?" so the mode controller adapts.

6. **VAD is drawn as a fixed "Silero" box.** Should be a VAD abstraction (Silero default; TEN/WebRTC swappable) — claims about Silero's transition delay are unverified and VN-untested.

7. **Correction placement risk.** If kept, correction must run on the **final** transcript only, never on streaming partials (latency + instability + hallucination risk). And it stays behind a benchmark gate.

8. **Missing operational components:** model loading/caching & download; hallucination handling on silence/non-speech; long-file memory management; error/cancel handling; progress reporting for the streaming UX.

9. **No input-validation / failure-mode handling.** The "16 kHz mono PCM" assumption ignores: multichannel audio (downmix policy), variable sample rates, empty/silent files, corrupt/DRM media, **video with no audio track**, and very long files that exceed memory in batch mode. The decode stage must define explicit behavior for each.

10. **No partial/final reconciliation contract.** With LocalAgreement re-decoding from a buffer, already-emitted partials can change before they're committed. The Transcript Assembler must define a consumer contract: **finals are append-only; partials are replaceable and carry a stability marker.** This matters for any downstream consumer, including SmartDocs.

## Complexity risks
- **Apple lock-in via MLX** — highest. Mitigated by the engine abstraction.
- **Two models in memory** (ASR + correction LLM) — memory pressure on 16 GB Macs; another reason correction must prove its worth first.
- **Build-vs-buy for streaming** — rebuilding LocalAgreement/AlignAtt from scratch is avoidable; WhisperLiveKit (Apache-2.0) already integrates both. Evaluate adopting it behind our abstraction.

## Proposed revised architecture (to validate, not to finalize)
```
            ┌──────────── Audio Sources ────────────┐
            │ File   Video   Mic   (future: stream)  │
            └───────────────────┬────────────────────┘
                                │
                    Decode & Resample (ffmpeg → 16 kHz mono PCM)   [explicit]
                                │
                         VAD (abstraction; Silero default)
                                │
                         Segmenter / Buffer
                                │
        ┌───────────────────────┴───────────────────────┐
        │           Execution Mode controller            │
        │  • incremental-batch (file/video)              │
        │  • real-time (mic): overlap + commit policy     │  ← LocalAgreement-2 / AlignAtt  [NEW]
        └───────────────────────┬───────────────────────┘
                                │
                ASR Engine (abstraction: faster-whisper | whisper.cpp | mlx)  [swappable]
                                │
                Timestamping (word/segment)               [explicit]
                                │
            Transcript Assembler  →  partial (live) + final
                                │
            (Optional) Correction — final-only, benchmark-gated   [conditional]
                                │
            Exporters: TXT | SRT | VTT
```
Key changes vs candidate: explicit decode/resample, VAD & ASR as abstractions, an **execution-mode controller with a streaming commit policy**, explicit timestamping & exporters, correction demoted to final-only/conditional.

## Alternatives considered
- **Adopt WhisperLiveKit (Apache-2.0)** for the real-time path instead of building the commit policy ourselves; wrap it behind our Audio Source + engine abstraction. Trade-off: external dependency vs much less streaming code to own & debug. → Evaluate in Phase 4.
- **whisper.cpp as the single engine everywhere** (one C/C++ codebase, GPU on Mac+NVIDIA). Trade-off: simplest portability story, but C++ binding ergonomics and the PhoWhisper GGML conversion must be proven. → Keep as a top engine candidate in Phase 1.
