# Vietnamese Local-First STT — Planning Deliverables

> Status: **Research & Planning (pre-implementation).** No production code yet.
> Workflow gate: we are at SPECIFY → PLAN. Implementation is **not** authorized until these are reviewed and approved.

This folder holds the planning deliverables mandated by `CLAUDE.md`. Each document distinguishes
**[VERIFIED]** facts (with source URL), **[ASSUMPTION]** / **[HYPOTHESIS]**, and **[UNKNOWN]** items, per the
project's evidence-first policy. No benchmark numbers have been invented.

| # | Deliverable | File |
|---|-------------|------|
| 1 | Problem Analysis | [01-problem-analysis.md](01-problem-analysis.md) |
| 2 | Assumption Audit | [02-assumption-audit.md](02-assumption-audit.md) |
| 3 | Repository & Model Research Plan | [03-research-plan.md](03-research-plan.md) |
| 4 | Architecture Review | [04-architecture-review.md](04-architecture-review.md) |
| 5 | Benchmark Methodology | [05-benchmark-methodology.md](05-benchmark-methodology.md) |
| 6 | Technology Recommendations | [06-technology-recommendations.md](06-technology-recommendations.md) |
| 7 | Phased Roadmap | [07-roadmap.md](07-roadmap.md) |
| 8 | Open Questions | [08-open-questions.md](08-open-questions.md) |
| 9 | Candidate Evaluation Matrix (pre-Phase-0 triage) | [09-candidate-evaluation-matrix.md](09-candidate-evaluation-matrix.md) |
| 10 | Implementation Path Decision (primary + fallback) | [10-implementation-decision.md](10-implementation-decision.md) |
| 11 | Implementation Plan — Phase 1 Audio MVP | [11-implementation-plan.md](11-implementation-plan.md) |
| 12 | Phase 1 Build Status (MVP complete + perf finding) | [12-phase1-status.md](12-phase1-status.md) |
| 13 | whisper.cpp / Metal validation + engine decision | [13-whisper-cpp-metal.md](13-whisper-cpp-metal.md) |
| 14 | Phase 2 — Video support | [14-phase2-video.md](14-phase2-video.md) |
| 15 | Phase 3 — Real-time mic streaming | [15-phase3-streaming.md](15-phase3-streaming.md) |
| 16 | Phase 3 — Streaming polish (latency/RTF/defaults) | [16-phase3-streaming-polish.md](16-phase3-streaming-polish.md) |
| 17 | Quality pass — onset loss fixed + engine accuracy A/B | [17-quality-pass.md](17-quality-pass.md) |
| 18 | Local testing UI (Gradio) — usage + sample collection | [18-testing-ui.md](18-testing-ui.md) |
| 19 | Microphone pipeline — diagnosis report (root causes, no fixes) | [19-mic-diagnosis.md](19-mic-diagnosis.md) |
| 20 | Microphone pipeline — fixes applied (gain-norm, ASR worker, race, WAV) | [20-mic-fixes.md](20-mic-fixes.md) |

## Evidence labels used throughout

- **[VERIFIED]** — backed by an official/primary source, URL cited.
- **[ASSUMPTION]** — a working belief we have NOT confirmed; carries a validation plan.
- **[HYPOTHESIS]** — a claim to be proven or disproven by our own benchmark.
- **[UNKNOWN]** — no evidence found; must be measured.

## Doubt-review reconciliation log (2026-06-23)

Per `doubt-driven-development`, the architecture + technology recommendations were submitted to a
fresh-context adversarial reviewer (artifact + contract only). Outcome:

- **Refuted by primary source (NOISE):** the reviewer's most severe claim — that PhoWhisper large-vs-medium
  WER gap is ~1.4 (medium 10.2 / large 8.8) — was **false**. The paper's Table 2 and the GitHub README (two
  independent renderings) both show **8.14 vs 8.27 on CMV-Vi (gap 0.13)**. The medium-default recommendation
  stands. *(This is why the reconcile step re-reads the source instead of rubber-stamping the reviewer.)*
- **Valid, actioned:** TEN VAD relabeled "Apache-2.0 + non-compete rider"; SimulStreaming/AlignAtt license
  marked contested (default to permissive LocalAgreement-2); ChunkFormer elevated from "control" to a
  first-class, license-flagged benchmark entry; Whisper word-timestamp fragility added as a benchmark metric
  + risk; PhoWhisper→GGML/MLX conversion elevated to a Phase-1 gating spike; input edge-cases and a
  partial/final commit contract added to the architecture; "one pipeline" clarified as a shared core + thin
  mode-policy layer.
- **Cross-model second opinion:** **offered and skipped by the user** (2026-06-23). Proceeding on the
  single-model adversarial review + primary-source verification.

## Product decision recorded (2026-06-23)

- **Commercial intent = NON-COMMERCIAL ONLY.** Consequence: CC-BY-NC / gated / non-compete components are now
  **usable in the product**, not benchmark-only. **ChunkFormer-Large-Vie (110M, CC-BY-NC) is promoted from
  "control" to a co-primary ASR candidate** alongside PhoWhisper-medium — it leads on size, native streaming,
  and CTC-timestamp reliability (accuracy claim still to be validated under identical eval). License is no
  longer a binding constraint; **portability to Windows/Linux/servers still is.** Docs 01/02/03/06/08 updated.

## Research provenance

These documents synthesize four source-grounded research passes (2026-06-23) covering: PhoWhisper & the
Vietnamese ASR model landscape; Apple-Silicon Whisper runtimes & portability; VAD & streaming-ASR
techniques; and Vietnamese benchmark datasets & LLM post-correction evidence. Citations are inline.
