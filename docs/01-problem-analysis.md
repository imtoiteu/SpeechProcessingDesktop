# 1. Problem Analysis

## Objective

Build a **local-first** (offline-capable, privacy-preserving) Vietnamese Speech-to-Text application that
transcribes **audio files**, **video files**, and **real-time microphone** input with high Vietnamese
accuracy and a streaming experience. The current dev machine is an Apple-Silicon Mac, but the system must
remain portable to Windows/Linux/servers. Future reuse inside **SmartDocs-Agent** must stay possible.

**Who is the user?** (To confirm — see Open Questions.) Working assumption: Vietnamese-speaking knowledge
workers transcribing meetings, lectures, and media on their own machine, who value privacy and accuracy
over raw speed.

## Scope (in scope)

- Audio file transcription: `wav`, `mp3`, `m4a`, `flac` — with timestamps and TXT/SRT/VTT export.
- Video file transcription: `mp4`, `mov`, `mkv` — automatic audio extraction, reuse of the same pipeline, subtitle export.
- Real-time microphone mode: continuous capture, VAD segmentation, near-real-time incremental transcript.
- A **single shared pipeline** built around an Audio Source abstraction (no separate pipelines per input type).
- A reproducible **benchmark harness** for Vietnamese accuracy, speed, memory, and streaming latency.

## Non-goals (explicitly out of scope for now)

- A polished video player or frame-accurate synchronized playback UI (transcript quality > playback per the brief).
- Speaker diarization, translation, summarization (candidate *future* additions; not v1).
- Cloud/server transcription service, multi-user accounts, or a hosted API.
- Maximum accuracy at any cost — we optimize the **balance** of accuracy / latency / resource / maintainability / complexity.
- Training or fine-tuning new ASR models (we evaluate existing ones).
- The LLM correction layer as a committed feature (it is a hypothesis to be tested — see [02](02-assumption-audit.md)).

## Constraints

- **Local-first / offline:** all inference runs on-device; no audio leaves the machine by default. **[constraint from brief]**
- **Portability:** avoid platform lock-in. Engine choice has real portability consequences — `mlx`-based runtimes are **Apple-only**; `faster-whisper`/CTranslate2 is portable but **CPU-only on macOS**; `whisper.cpp` is the only runtime with GPU on both Apple (Metal) and NVIDIA (CUDA). [VERIFIED — CTranslate2 hardware support is CUDA-only](https://opennmt.net/CTranslate2/hardware_support.html); [whisper.cpp Metal+CUDA](https://github.com/ggml-org/whisper.cpp); [MLX is Apple Silicon-targeted](https://pypi.org/project/mlx-whisper/)
- **Open-source stack** required. License matters for the SmartDocs future: PhoWhisper is **BSD-3** (commercial-safe); several strong alternatives (ChunkFormer, nguyenvulebinh wav2vec2, VIVOS dataset) are **CC-BY-NC** (non-commercial). [VERIFIED PhoWhisper BSD-3](https://huggingface.co/vinai/PhoWhisper-large)
- **Apple Silicon dev reality:** the most popular Python ASR runtime (`faster-whisper`) does **not** use the Apple GPU. Mac acceleration requires `whisper.cpp` (Metal/CoreML) or `mlx-whisper`. [VERIFIED](https://github.com/SYSTRAN/faster-whisper/issues/515)
- **Streaming is emulated, not native:** Whisper is a 30-second batch model "not designed for real time transcription"; low latency requires a chunking + re-decode + stabilization policy. [VERIFIED — UFAL paper](https://arxiv.org/html/2307.14743)

## Risks

| Risk | Severity | Note / mitigation |
|------|----------|-------------------|
| No public Vietnamese WER or RTF numbers exist for our exact model×engine×chip combos | High | Must run our own benchmarks (Phase 0–1); cannot shortcut. **[UNKNOWN]** |
| Picking an Apple-only engine (MLX) creates lock-in, breaking portability + SmartDocs goal | High | Mandate an **engine abstraction**; keep MLX as an optional fast path only. |
| "Biggest model is best" leads to over-heavy PhoWhisper-large when -medium may suffice | Medium | PhoWhisper-large beats -medium by only ~0.13 WER on CMV-Vi (8.14 vs 8.27) at 2× params — [VERIFIED paper table](https://ar5iv.labs.arxiv.org/html/2406.02555). Benchmark before committing. |
| LLM correction layer adds a second model + latency but may *degrade* a strong PhoWhisper baseline | Medium | Literature shows GER can hurt strong fine-tuned Whisper via hallucination/over-correction — [VERIFIED survey](https://arxiv.org/pdf/2508.07285). Gate behind A/B benchmark; not in v1. |
| Best dialect-labeled & meeting/lecture VN corpora are paywalled, gated, or non-existent as open data | Medium | Free options (Bud500, VietMed, FLEURS, CommonVoice) cover some cases; meeting/lecture data is a **gap** — may need to record our own. |
| Real-time latency target unmet on Apple Silicon | Medium | English LocalAgreement-2 latency is ~3.3s on a datacenter GPU; Apple-Silicon VN latency is **[UNKNOWN]** — measure early. |
| Best-accuracy alternative (ChunkFormer-Large-Vie, 110M) is CC-BY-NC | Low/Med | Usable for research/benchmark; flag license before any commercial path. |
| Whisper word-level timestamps are fragile (can desync) → bad SRT/VTT timing | Medium | Benchmark timestamp accuracy explicitly (not just WER); WhisperX forced-alignment as fallback. **[surfaced in doubt-review]** |
| Mac-acceleration fallback (whisper.cpp/MLX) depends on a PhoWhisper conversion with **no pre-built artifact** | High | Make HF→GGML/MLX conversion + numeric-parity check a Phase-1 **gating spike**, not a late assumption. **[surfaced in doubt-review]** |
| Streaming/AlignAtt path (SimulStreaming) has a **contested license**; TEN VAD carries a non-compete rider | Medium | Default to LocalAgreement-2 (permissive); verify any encumbered component before commercial use. **[surfaced in doubt-review]** |

## Success criteria (reframed, testable — targets to confirm with user)

These are proposed targets, not yet agreed. See Open Questions for the values needing confirmation.

1. **Accuracy:** Vietnamese WER on a held-out clean read-speech set (FLEURS-vi / CommonVoice-vi) ≤ a target to be agreed (PhoWhisper paper reports 8.14–8.27 WER on CMV-Vi for large/medium — our number must be *measured on our pipeline*, not assumed). **[HYPOTHESIS until measured]**
2. **Per-dialect:** WER measured and reported separately for Northern / Central / Southern; no dialect catastrophically worse (gap target to agree).
3. **Batch speed:** real-time factor (RTF) < 1.0 (faster than real-time) for file transcription on the dev Mac, at the chosen model size. **[HYPOTHESIS]**
4. **Streaming latency:** mic mode commit latency under an agreed budget (proposed ≤ ~3–5 s, matching documented LocalAgreement ranges — to confirm).
5. **Exports:** correct TXT, SRT, VTT with word/segment timestamps that pass a subtitle validator.
6. **Portability:** the same core runs on at least one non-Apple target (Linux/NVIDIA or Linux/CPU) without architectural change.
7. **Maintainability:** ASR engine and VAD are swappable behind abstractions; adding a new Audio Source requires no pipeline rewrite.

## Spec scaffold (provisional — finalized at the implementation gate)

Per `spec-driven-development`, the following are recorded as **provisional** and will be locked only when we
enter implementation:

- **Tech stack:** language/runtime **[UNDECIDED]** (Python is the obvious fit for the ASR ecosystem; to confirm). Key libs depend on engine selection in Phase 1.
- **Commands / Project Structure / Code Style / Testing Strategy:** deferred to the implementation gate; not meaningful before engine selection.
- **Boundaries:**
  - *Always:* cite sources for framework/model claims; benchmark before finalizing a model/engine; keep audio on-device by default; report WER/RTF honestly.
  - *Ask first:* adding the correction-LLM dependency; adopting an Apple-only runtime as default; adding any dataset with a non-commercial/gated license to the shipped product.
  - *Never:* invent benchmark numbers; hard-code a single ASR backend; ship a non-commercial-licensed model/dataset into a commercial SmartDocs path without sign-off.
