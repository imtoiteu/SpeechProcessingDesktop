# 2. Assumption Audit

Each candidate-architecture / candidate-technology assumption from `CLAUDE.md`, audited as:
**supporting evidence → missing evidence → validation plan**. Status is one of
[VERIFIED] / [PARTLY VERIFIED] / [HYPOTHESIS] / [UNKNOWN].

---

### A1. "Silero VAD is the right VAD." — [PARTLY VERIFIED]
- **Supporting:** MIT license, ~2 MB, <1 ms/chunk on one CPU thread, ONNX, actively maintained (v6.2.1, Feb 2026), language-agnostic, has a CoreML port. [VERIFIED](https://github.com/snakers4/silero-vad)
- **Missing:** No Vietnamese-specific VAD accuracy data. A competitor (TEN VAD, Apache-2.0) *claims* better precision/recall and that "Silero VAD suffers from a delay of several hundred ms" on speech→non-speech transitions — but that is a **vendor self-benchmark**, not independent or VN-tested. [VERIFIED claim exists](https://github.com/TEN-framework/ten-vad)
- **Validation plan:** In Phase 1, benchmark Silero vs TEN VAD vs WebRTC on our noisy/dialect VN clips for segmentation accuracy and transition latency. Default to Silero; switch only on evidence.

### A2. "ASR = PhoWhisper (and bigger = better)." — [HYPOTHESIS on size]
- **Supporting:** PhoWhisper is a Whisper fine-tune on 844h Vietnamese; paper reports SOTA on CMV-Vi/VIVOS/VLSP; BSD-3 (commercial-safe). [VERIFIED](https://ar5iv.labs.arxiv.org/html/2406.02555)
- **Missing / doubt:** "Largest is best" is **not** supported — large beats medium by only ~0.13 WER (8.14 vs 8.27 CMV-Vi) at ~2× the parameters (769M → 1.55B). A 110M alternative (ChunkFormer-Large-Vie) *claims* to match/beat PhoWhisper-large with 14× fewer params — but CC-BY-NC and on the author's own recomputed comparison. [VERIFIED](https://huggingface.co/khanhld/chunkformer-large-vie)
- **Validation plan:** Phase 1 benchmark PhoWhisper {small, medium, large} **head-to-head with ChunkFormer-Large-Vie** (promoted to co-primary candidate now that the project is non-commercial, 2026-06-23 — its CC-BY-NC license no longer disqualifies it) on our VN sets, measuring WER **and** RTF/memory **and** cross-platform runtime support. Pick the smallest model meeting the accuracy target; validate ChunkFormer's accuracy claim under identical eval (cross-paper splits differ).

### A3. "PhoWhisper will run on our chosen engine on Apple Silicon." — [PARTLY VERIFIED]
- **Supporting:** PhoWhisper is pure Whisper weights → loads in HF Transformers directly; **pre-converted CTranslate2 (faster-whisper) repos already exist** (`quocphu/PhoWhisper-ct2-FasterWhisper`, all 5 sizes). [VERIFIED](https://huggingface.co/quocphu/PhoWhisper-ct2-FasterWhisper)
- **Missing:** **No pre-built PhoWhisper GGUF (whisper.cpp) or MLX artifact was found.** Conversion is mechanically standard (`convert-h5-to-ggml.py` / `mlx convert.py`) but unproven for this checkpoint, and quantization quality on Vietnamese is unmeasured. [VERIFIED conversion paths exist](https://github.com/ggml-org/whisper.cpp/blob/master/models/README.md)
- **Validation plan:** Phase 1 — convert PhoWhisper to GGML and MLX, verify numeric parity vs HF/CT2 fp16, and measure WER under Q4/Q8 quantization vs fp16.

### A4. "faster-whisper is the engine." — [HYPOTHESIS — portability tension]
- **Supporting:** ~4× faster than openai-whisper, word timestamps, built-in Silero VAD, easiest PhoWhisper path. [VERIFIED](https://github.com/SYSTRAN/faster-whisper)
- **Missing / doubt:** **CPU-only on macOS** (CTranslate2 has no Metal). On the dev Mac it was the *slowest* option in a third-party M4 test. `whisper.cpp` (Metal/CoreML, portable to CUDA) and `mlx-whisper` (Apple-only) are the Mac-acceleration alternatives. [VERIFIED](https://opennmt.net/CTranslate2/hardware_support.html)
- **Validation plan:** Benchmark faster-whisper-CPU vs whisper.cpp-Metal vs mlx-whisper on identical PhoWhisper weights; decide per evidence, behind an engine abstraction. Do not hard-commit.

### A5. "VAD-segmented chunks → ASR → streaming transcript" is sufficient for real-time. — [HYPOTHESIS — likely insufficient as drawn]
- **Supporting:** VAD-based segmentation is documented best practice.
- **Missing / doubt:** Whisper is a 30 s batch model; naive chunking "can split a word in the middle" and gives unstable output. Real "streaming" needs a **stabilization policy** — LocalAgreement-2 (commit longest common prefix of 2 decodes) or AlignAtt — over **overlapping re-decoded** windows. The candidate diagram hides this. [VERIFIED](https://arxiv.org/html/2307.14743), [WhisperLiveKit warns vs naive small segments](https://github.com/QuentinFuxa/WhisperLiveKit)
- **Validation plan:** Architecture must add an explicit stabilization/commit stage for the mic path (see [04](04-architecture-review.md)). Prototype LocalAgreement-2 first; evaluate AlignAtt.

### A6. "An LLM correction layer (Qwen3) improves the transcript." — [HYPOTHESIS — evidence is mixed/negative for strong baselines]
- **Supporting:** GER literature (HyPoradise NeurIPS'23; Whispering-LLaMA 37.66% rel. WER gain) shows LLM correction *can* help. Qwen3 (Apache-2.0, 1.7B/4B) runs cheaply at Q4 on Apple Silicon (40–80+ tok/s). [VERIFIED](https://arxiv.org/pdf/2309.15701), [VERIFIED](https://arxiv.org/abs/2310.06434)
- **Missing / doubt:** Gains are largely on **weak** baselines/diverse N-best. Surveys report "minimal or no improvement, and sometimes slight degradation, for fine-tuned Whisper outputs" and hallucination/over-correction risk. PhoWhisper is a *strong* fine-tuned baseline → expected ROI is low or negative. Qwen3 Vietnamese ability at 1.7B/4B specifically is **[UNKNOWN]** (only large-model VN scores published). [VERIFIED](https://arxiv.org/pdf/2508.07285), [VERIFIED hallucination](https://arxiv.org/abs/2505.24347)
- **Validation plan:** A/B benchmark PhoWhisper WER **with vs without** Qwen3 correction on held-out VN (incl. technical terms). Build only if net WER improves beyond a threshold without breaking latency. **Default: defer, do not ship in v1.**

### A7. "One shared pipeline + Audio Source abstraction." — [VERIFIED as sound]
- **Supporting:** Matches proven designs (WhisperLive handles file/mic/RTSP through one server; faster-whisper backend reused). [VERIFIED](https://github.com/collabora/WhisperLive)
- **Caveat:** "Streaming while processing a file" (incremental batch) is a *different* mode from real-time mic streaming; they share components but have different latency/stabilization needs. The abstraction must model both modes. (See [04](04-architecture-review.md).)
- **Validation plan:** Define the Audio Source interface + two execution modes (incremental-batch, real-time) in Phase 1 design.

### A8. "Apple Silicon is the dev target but the system stays portable." — [VERIFIED as a real constraint with teeth]
- **Supporting:** Brief mandates portability to Windows/Linux/servers + SmartDocs.
- **Doubt:** This *directly constrains engine choice.* MLX would break it. The only single-codebase-GPU-everywhere option is whisper.cpp; faster-whisper is portable but CPU-on-Mac.
- **Validation plan:** Treat portability as a first-class acceptance criterion; the engine abstraction is the mitigation. Verify on one non-Apple target in the roadmap.

---

## Highest-leverage things to validate first (ranked)
1. **PhoWhisper size × engine × quantization** on real VN audio (settles A2, A3, A4 at once).
2. **Whether the correction layer helps at all** (settles A6 — could remove an entire subsystem).
3. **Streaming latency on Apple Silicon** with LocalAgreement-2 (settles A5 feasibility).
4. **VAD comparison on noisy/dialect VN** (settles A1).
