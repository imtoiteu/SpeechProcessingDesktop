# 8. Open Questions

Unresolved items needing a human decision or an experiment. Grouped by who can resolve them.

## Needs a decision from you (product/requirements)
1. **Primary user & top use case?** (Meetings vs lectures vs media vs dictation.) This reorders dialect/noise priorities and the meeting-data investment.
2. **Accuracy target?** A concrete WER/CER ceiling on the clean tier (and an acceptable per-dialect gap). Without a number, "high accuracy" isn't testable.
3. **Streaming latency budget?** Proposed ≤ ~3–5 s commit latency (matches documented LocalAgreement ranges) — acceptable, or do you need lower?
4. ~~**Commercial intent / SmartDocs path?**~~ **RESOLVED 2026-06-23: NON-COMMERCIAL ONLY.** CC-BY-NC / gated / non-compete components are usable in the product; ChunkFormer-Large-Vie promoted to co-primary ASR candidate. License is no longer a binding filter — **portability is.** (Re-open only if commercial intent changes.)
5. **Implementation language/runtime?** Python is the natural fit for this ecosystem; confirm, or state constraints (e.g., must embed in a specific app/runtime).
6. **Delivery form for v1?** CLI, minimal desktop UI, or library? Affects Phase-2 deliverable shape.
7. **Meeting/lecture data gap:** record our own small VN eval set, license a commercial one, or descope meeting/lecture accuracy for v1?

## Needs an experiment (we resolve via benchmark)
8. PhoWhisper **medium vs large vs small** on our VN audio — is large's marginal gain worth 2× cost? ([05](05-benchmark-methodology.md) #1)
9. **Engine on Apple Silicon:** is faster-whisper-CPU fast enough, or do we need whisper.cpp-Metal / mlx? (#2)
10. **Quantization:** how much WER does Q4/Q8 cost vs fp16 on Vietnamese? (#3)
11. **ChunkFormer-Large-Vie (now co-primary):** does its accuracy claim hold under identical eval vs PhoWhisper, and does it run cleanly cross-platform (Win/Linux/servers + Apple Silicon)? Portability is the gating question now that license is cleared.
12. **Does the correction layer help at all** on PhoWhisper output, or hurt it? (#6) — could remove an entire subsystem.
13. **Streaming policy:** LocalAgreement-2 vs AlignAtt latency/quality on VN + Apple Silicon; **build vs adopt WhisperLiveKit**. (#5)
14. **VAD:** does TEN VAD actually beat Silero on noisy/dialect VN, or is Silero's transition delay a non-issue for us? (#4)

## Needs verification (read primary source before relying)
15. Exact Silero VAD window/sample-rate constraints (wiki/FAQ).
16. Common Voice-vi validated hours (confirm on download).
17. ChunkFormer / Bud500 / VLSP / Regional Voice exact license terms.
18. Qwen3-1.7B/4B Vietnamese capability (no small-model VN benchmark found — must test if correction is pursued).
19. PhoWhisper→GGML and →MLX conversion parity (no pre-built artifacts found).
