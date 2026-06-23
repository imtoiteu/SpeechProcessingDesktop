# 9. Candidate Evaluation Matrix (pre-Phase-0 triage)

> Goal: **minimize unnecessary benchmark work** by ranking ASR-model candidates *before* spending GPU/CPU time.
> Scope = ASR models (engines, VAD, streaming policy, correction LLM are evaluated elsewhere). Ratings:
> ✅ strong · ◑ partial / conditional / unverified · ❌ weak. "Expected benchmark value" = how likely this
> candidate is to **change the final decision** (High / Med / Low), given priorities: VN accuracy > streaming >
> maintainability > performance > reusability > open-source; project is **non-commercial** and must stay **portable**.

> ⚠️ **Number-comparability warning (load-bearing).** Author-reported WERs are **not comparable across models**:
> ChunkFormer's card numbers are computed on **manually normalized** text (numbers/casing/punctuation handled),
> while a CTC model with no LM scores far worse on **orthographic** WER. So "ChunkFormer 6.66 beats PhoWhisper
> 8.27" is **not a real finding** until both are re-scored under one normalization spec. No author number may gate a
> model in or out. An independent same-test-set re-evaluation exists and should be read in Phase 0 — *Vietnamese
> ASR: A Revisit*, Vu/Nguyen/Nguyen (the PhoWhisper group), [EACL 2026 Findings, arXiv 2603.14779](https://arxiv.org/abs/2603.14779)
> — which also ships a 500h aggregated VN dataset; it may **pre-answer the accuracy ranking and cut our Stage-1 work.**

## Candidate list

Whisper-family (fine-tuned): PhoWhisper-{tiny, base, small, medium, large}. CTC / alt-architecture:
ChunkFormer-Large-Vie, nguyenvulebinh wav2vec2-{base, large}. Controls/baselines: OpenAI Whisper large-v3
(zero-shot), Whisper large-v3-turbo. Research/emerging: VietASR, TSPC, gipformer.

## Matrix A — capability ratings

| Candidate (params) | Runtime maturity | Cross-platform | Streaming | Timestamp quality | Ecosystem | Exp. benchmark value |
|---|---|---|---|---|---|---|
| **PhoWhisper-medium** (769M) | ✅ CT2 pre-converted exists | ✅ all Whisper runtimes (CPU-on-Mac caveat) | ◑ emulated (LocalAgreement) | ◑ Whisper word-ts fragile | ✅ huge | **High** — co-primary |
| **PhoWhisper-large** (1.55B) | ✅ | ✅ (heaviest) | ◑ emulated | ◑ fragile | ✅ | **High** — accuracy ceiling anchor |
| **ChunkFormer-Large-Vie** (110M) | ◑ real PyPI pkg + ICASSP'25, but newer/smaller community | ◑ PyTorch→Linux/Win/CUDA ✅; **Apple-Silicon GPU unverified** | ◑ **streaming OFF by default** (`use_dynamic_chunk:false`, ~1.28s min lookahead); 16h is batch | ✅ **CTC frame-level** | ◑ single-author, packaged | **High** — co-primary; must verify *streaming-mode* WER |
| PhoWhisper-small (244M) | ✅ | ✅ | ◑ emulated | ◑ fragile | ✅ | **Med** — latency fallback only |
| Whisper large-v3 (1.55B, zero-shot) | ✅ | ✅ | ◑ emulated | ◑ fragile | ✅ | **Med** — control (fine-tuning value) |
| wav2vec2-large-vi-vlsp2020 (317M) | ◑ HF, needs LM for best | ✅ PyTorch | ◑ CTC streamable, not packaged | ◑ CTC frame-level | ◑ | **Med** — distinct CTC+LM profile |
| PhoWhisper-tiny/base (39/74M) | ✅ | ✅ | ◑ emulated | ◑ fragile | ✅ | **Low** — WER too high (19.05 / 16.19 CMV-Vi) |
| **VN Whisper-large-v3-turbo** fine-tune (~809M) | ✅ same `transformers`/CT2 path | ✅ (CPU-on-Mac caveat) | ◑ emulated, **but 4 decoder layers → much faster** | ◑ fragile | ✅ Whisper | **Med-High** — Whisper-family streaming/latency option; accuracy unknown |
| wav2vec2-base (95M) | ◑ | ✅ | ◑ | ◑ | ◑ | **Low** — dominated by the large variant |
| VietASR / TSPC / gipformer | ❌ no readily-usable released checkpoint verified | ? | ? | ? | ❌ nascent | **Low** — unverified; watch-list (track VietASR's 500h set) |

Sources: [PhoWhisper paper Table 2](https://ar5iv.labs.arxiv.org/html/2406.02555) · [PhoWhisper repo](https://github.com/VinAIResearch/PhoWhisper) · [ChunkFormer HF card](https://huggingface.co/khanhld/chunkformer-large-vie) · [ChunkFormer repo](https://github.com/khanld/chunkformer) · [chunkformer PyPI](https://libraries.io/pypi/chunkformer) · [nguyenvulebinh wav2vec2](https://huggingface.co/nguyenvulebinh/wav2vec2-large-vi-vlsp2020) · [Whisper large-v3](https://huggingface.co/openai/whisper-large-v3) · [faster-whisper macOS = CPU](https://opennmt.net/CTranslate2/hardware_support.html)

## Matrix B — strengths & weaknesses (the prose dimensions)

**PhoWhisper-medium (769M)** — *Strengths:* verified VN strong-tier on **clean read speech** (CMV-Vi 8.27, VIVOS 4.97); BSD-3; pre-converted CT2 weights; mature tooling; word timestamps via faster-whisper. *Weaknesses:* **degrades sharply on spontaneous/noisy speech — VLSP-2020 Task-2 WER 26.85** (the closest public proxy to the meetings/noisy use cases), i.e. ~3× the clean number; emulated streaming only; word-ts fragile; CPU-only on Mac under faster-whisper; weights frozen since Dec 2023.

**PhoWhisper-large (1.55B)** — *Strengths:* best published VN WER on clean sets (8.14 CMV-Vi). *Weaknesses:* only ~0.13–0.37 WER better than medium at 2× compute/memory — **and on spontaneous speech the gap nearly vanishes (VLSP-T2 26.68 vs 26.85)**; heaviest for streaming + 16 GB Macs; same fragile-ts / emulated-streaming limits.

**ChunkFormer-Large-Vie (110M)** — *Strengths:* tiny (≈14× smaller than PhoWhisper-large); long-form (16h) on low-memory GPUs; supports streaming (dynamic chunking); **CTC frame-level timestamps** (structurally more reliable than Whisper's cross-attention word-ts → directly helps SRT/VTT); could **simplify the architecture** (no LocalAgreement commit layer). *Weaknesses:* its headline CMV-Vi 6.66 / VIVOS 4.18 are **manually normalized** (numbers/casing/punctuation stripped) and **not comparable** to PhoWhisper's numbers — the "ChunkFormer beats PhoWhisper" claim is unproven until re-scored under one normalization; **streaming is OFF by default** (`use_dynamic_chunk:false`, ~1.28s min lookahead) and the headline number was likely measured in full-context (non-streaming) mode → streaming WER unknown; **Apple-Silicon GPU support unverified**; CTC-no-LM may trail on rare/technical terms and on orthographic (un-normalized) scoring.

**VN Whisper-large-v3-turbo fine-tune (~809M)** — *Strengths:* 4 decoder layers vs 32 → the **Whisper-family low-latency/streaming candidate** at near-large accuracy potential; reuses the exact PhoWhisper harness (near-zero marginal cost); Vietnamese fine-tunes exist ([suzii/vi-whisper-large-v3-turbo](https://huggingface.co/suzii/vi-whisper-large-v3-turbo), ~240h). *Weaknesses:* the available community checkpoint has **no published WER and no stated license** (89 downloads/mo) → quality/usability unverified; accuracy genuinely unknown (which is a reason to benchmark, not to exclude).

**PhoWhisper-small (244M)** — *Strengths:* much lighter than medium; viable real-time latency. *Weaknesses:* CMV-Vi WER 11.08 — a real step down from medium (8.27); likely below accuracy target unless both turbo and ChunkFormer also fail on latency.

**Whisper large-v3 zero-shot** — *Strengths:* Apache-2.0; the canonical "did fine-tuning actually help us" control. *Weaknesses:* on in-domain VN sets it trails PhoWhisper; 1.55B with no VN specialization.

**wav2vec2-large-vi-vlsp2020 (317M)** — *Strengths:* strong VLSP-T1 with 5-gram LM (5.32, and 15.18 without); a genuinely **different CTC+LM latency/streaming profile** from both Whisper and ChunkFormer. *Weaknesses:* poor on Common Voice without LM (the >100% figure reflects no-LM + domain mismatch, a CTC eval caveat, not a fixed quality verdict); needs an LM pipeline; no punctuation/casing; CC-BY-NC; 2020-era data.

**PhoWhisper-tiny/base, wav2vec2-base, VietASR/TSPC/gipformer** — see triage below; none expected to change the decision.

## Triage

> **Before any of this:** read *Vietnamese ASR: A Revisit* ([arXiv 2603.14779](https://arxiv.org/abs/2603.14779)) in full — it is an independent same-test-set comparison from the PhoWhisper authors and may already settle the PhoWhisper-vs-ChunkFormer accuracy ranking, cutting Stage-1 work. Its 500h aggregated dataset (license TBD) may also fill the eval gap.

### 1. Must benchmark — the minimal decision-set (3 + 1 anchor)
- **PhoWhisper-medium** — the Whisper-family batch-accuracy co-primary.
- **ChunkFormer-Large-Vie** — the CTC co-primary; if it wins it simplifies streaming *and* timestamps. Highest information-per-run — **but its WER must be measured in the actual streaming chunk config it would deploy in**, not full-context mode, and under the shared normalization spec.
- **VN Whisper-large-v3-turbo fine-tune** — the Whisper-family *low-latency* candidate (4 decoder layers); near-zero marginal harness cost. **Prerequisite:** pick a license-clear, usable checkpoint (the available `suzii` one has no stated license/WER — vet it, or drop turbo to NICE if none qualifies).
- **PhoWhisper-large** *(anchor, minimal scope)* — **one clean-tier run only** to confirm the accuracy ceiling is flat vs medium. Do **not** run it through the full dataset/engine grid unless medium misses the target. *(Revised down from a full must-run — the medium→large gain is sub-0.3 WER and vanishes on noisy speech.)*

> These answer the questions that gate the architecture: *Whisper vs CTC-native*, *batch-accuracy vs low-latency within the Whisper family*, and *does extra size buy enough accuracy*.

### 2. Nice-to-benchmark — run only if the must-set leaves a gap
- **Whisper large-v3 (zero-shot)** — one cheap control run to quantify the value of VN fine-tuning.
- **wav2vec2-large-vi-vlsp2020** — the non-Whisper, non-ChunkFormer CTC+LM reference; a genuinely different latency profile. Decide LM inclusion in Stage 2.
- **PhoWhisper-small** — *trigger:* the must-set's accuracy winners all miss the streaming latency budget. Then test whether small's accuracy is acceptable.

### 3. Exclude before benchmarking (with reason)
- **PhoWhisper-tiny / base** — WER 19.05 / 16.19 on CMV-Vi; far below any plausible target. *(Keep tiny only as a fast CI/smoke-test fixture.)*
- **wav2vec2-base (95M)** — dominated by the large variant on the same architecture; no distinct value.
- **VietASR, TSPC, gipformer** — no readily-usable, verified released checkpoint found; TSPC targets code-switching (not the core use case). Watch-list — but **do read VietASR/Revisit for their datasets.**

> *Correction vs the first draft (after adversarial review): Whisper-large-v3-turbo was moved out of "exclude" — the "redundant with PhoWhisper" reasoning was wrong (turbo is a distinct latency tradeoff, and accuracy-unknown is a reason to test, not skip).*

## Minimized benchmark plan (the actionable output)

Run a **staged funnel**, not the full model × engine × quantization × dataset grid:

0. **Stage 0 — runtime/viability smoke check (gating, cheap):** for each architecture (Whisper-via-CT2/whisper.cpp/MLX, ChunkFormer-via-PyTorch), confirm it *runs* on the targets and capture a rough CPU/MPS RTF. fp16 may not be viable on every backend (MPS op gaps; CTC may need fp32). **A model that can't run acceptably on Apple Silicon dies here, before any accuracy run** — portability is a hard constraint, not a tuning detail.
1. **Stage 1 — accuracy screen, one normalization spec, report both O-WER and N-WER:** must-set models on the *clean tier* (FLEURS-vi + Common Voice-vi) **+ a spontaneous/noisy set (e.g. VLSP-T2) as a first-class tier** (it is the closest proxy to meetings/lectures) + one dialect set. Do **not** rank on author-reported or normalized-only numbers.
2. **Stage 2 — engine/latency + full dialect coverage, survivors only:** the 1–2 models that clear the accuracy target → engine comparison (faster-whisper-CPU vs whisper.cpp-Metal vs mlx; ChunkFormer native) + streaming latency + **all three dialects (N/C/S)** (a model can win overall yet lose Central).
3. **Stage 3 — quantization, finalist only:** Q4/Q8 vs fp16. Note quantization can **reorder** candidates separated by <0.3 WER, so re-check if Stage 1 was close.

This tests **3 models up front** (+1 cheap anchor run), gates on *runnability* before accuracy, scores all models on **comparable** metrics, and defers engine/quant/full-dialect sweeps to survivors.
