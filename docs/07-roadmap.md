# 7. Phased Roadmap

Smallest useful milestone first. Each phase has objectives, deliverables, and **exit criteria** (a gate).
No phase starts before the prior gate passes. Implementation begins only after this plan is approved.

---

### Phase 0 — Foundations & benchmark harness *(no product features yet)*
- **Objectives:** Lock the spec; build the reproducible benchmark harness; acquire & license datasets; define text-normalization spec.
- **Deliverables:** WER/CER/RTF/memory harness; downloaded license-clean datasets (FLEURS-vi, CommonVoice-vi) + as many dialect/noisy sets as licensing allows; normalization spec (versioned).
- **Exit criteria:** Harness reproduces a WER number for a reference model on a reference set, twice, deterministically; dataset license status documented; meeting/lecture data gap has a decision (record vs license vs skip).

### Phase 1 — Model & engine selection *(decision phase)*
- **Objectives:** Run benchmark comparisons #1–#4 from [05](05-benchmark-methodology.md). Define the **engine abstraction** and **VAD abstraction** interfaces.
- **Deliverables:** Populated comparison table (PhoWhisper small/medium/large × faster-whisper/whisper.cpp/mlx × fp16/Q8/Q4, **ChunkFormer-Large-Vie as co-primary** + whisper-large-v3 control; Silero/TEN/WebRTC VAD); PhoWhisper→GGML & →MLX conversion validated for parity; **ChunkFormer cross-platform runtime confirmed**.
- **Exit criteria:** A chosen default **model + engine + quantization** justified by measured WER/RTF/memory on VN audio; portability confirmed (runs on ≥1 non-Apple target); abstractions specified.

### Phase 2 — Audio-file transcription (the smallest useful product)
- **Objectives:** End-to-end batch transcription of `wav/mp3/m4a/flac` with incremental ("streaming-while-processing") output, word/segment timestamps, and TXT/SRT/VTT export.
- **Deliverables:** Decode→VAD→ASR→timestamp→export path; CLI or minimal UI; exporters validated.
- **Exit criteria:** Transcribes the four formats; SRT/VTT pass a subtitle validator; measured WER within the agreed target on the clean tier; RTF < 1.0 on the dev Mac at the chosen model.

### Phase 3 — Video support
- **Objectives:** Add `mp4/mov/mkv` via ffmpeg audio extraction, reusing the Phase-2 pipeline (extraction = a case of the decode stage, not a new pipeline).
- **Deliverables:** Video→audio extraction; subtitle export for video.
- **Exit criteria:** Video files produce correct subtitles through the identical core path; no pipeline duplication.

### Phase 4 — Real-time microphone streaming
- **Objectives:** Continuous capture + VAD segmentation + a **stabilization/commit policy** (LocalAgreement-2 baseline; evaluate AlignAtt / adopting WhisperLiveKit). Run benchmark comparison #5.
- **Deliverables:** Mic mode with incremental partial + committed-final transcript; latency measured on Apple Silicon.
- **Exit criteria:** Stable (non-flickering) incremental transcript within the agreed latency budget; streaming-vs-offline WER delta within tolerance.

### Phase 5 — Correction layer *(conditional — runs only if justified)*
- **Objectives:** Execute the correction A/B (comparison #6). Implement only if it earns its place.
- **Deliverables:** A/B report; if positive, a final-only, optional Qwen3 correction stage.
- **Exit criteria:** Net WER improvement beyond an agreed threshold **with** acceptable added latency and **no** increase in hallucination/over-correction. If not met → **drop the layer** and record why.

### Future (post-v1, not scheduled)
- Speaker diarization (meetings, via WhisperX), YouTube/network-stream sources, live-meeting capture, SmartDocs-Agent integration. Each should slot in via the Audio Source / engine abstractions without architectural change.

---

## Critical path & parallelism
- Phase 0 gates everything. Phases 2→3 are sequential (video reuses audio). Phase 4 can begin design in parallel with Phase 2 but needs the Phase-1 engine decision. Phase 5 is independent and conditional.
- Highest-risk/highest-info work is front-loaded into Phase 0–1 by design (resolves the model/engine/correction unknowns before any UI investment).
