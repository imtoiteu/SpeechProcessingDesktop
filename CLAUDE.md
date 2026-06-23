# CLAUDE.md

## Project Context

This project aims to build a local-first Vietnamese Speech-to-Text (STT) system optimized for Apple Silicon.

Primary goals:

1. High Vietnamese transcription accuracy.
2. Streaming transcription experience.
3. Support for:

   * Audio files
   * Video files
   * Real-time microphone transcription
4. Open-source stack.
5. Future integration into SmartDocs-Agent.

Current stage:

Research, architecture design, repository evaluation, benchmarking strategy, and implementation planning.

This project is NOT yet in the implementation phase.

---

## Required Skills

Always prioritize these skills:

1. .claude/skills/spec-driven-development
2. .claude/skills/source-driven-development
3. .claude/skills/doubt-driven-development

Use them together rather than independently.

---

## Mandatory Workflow

Before proposing implementation:

### Step 1 — Specification

Use spec-driven-development.

Define:

* Goals
* Scope
* Non-goals
* Constraints
* Assumptions
* Success criteria
* Risks

Do not begin coding before these are clear.

---

### Step 2 — Evidence Gathering

Use source-driven-development.

For every repository, model, framework, or technical claim:

* Inspect source repositories.
* Read documentation.
* Identify maintenance status.
* Verify compatibility.
* Verify hardware requirements.
* Verify deployment complexity.

Prefer evidence over assumptions.

Do not invent benchmark results.

---

### Step 3 — Challenge Assumptions

Use doubt-driven-development.

Actively question:

* Whether the largest model is actually the best choice.
* Whether additional complexity creates measurable value.
* Whether proposed features belong in the current milestone.
* Whether architecture decisions are supported by evidence.

Treat all recommendations as hypotheses until validated.

---

## Current Candidate Architecture

This architecture is a starting point, not a final decision.

Audio File
Video File
Microphone
↓
Audio Source Layer
↓
Audio Normalization
↓
Silero VAD
↓
Segment Queue
↓
ASR Engine
↓
Streaming Transcript
↓
(Optional Correction Layer)
↓
Final Transcript

The architecture must remain open to revision if evidence suggests a better approach.

---

## Candidate Technologies

Evaluate rather than assume.

VAD:

* Silero VAD

ASR:

* PhoWhisper Small
* PhoWhisper Medium
* PhoWhisper Large
* Faster-Whisper
* Other justified alternatives

Correction Layer:

* Qwen3 1.7B Q4
* Qwen3 4B Q4

Do not assume correction is required.

Validate its actual benefit through benchmarks.

---

## Benchmark-First Policy

Before implementation:

Create a benchmark plan.

Evaluate:

* Vietnamese accuracy
* Processing speed
* Memory usage
* Streaming latency
* Apple Silicon performance

Test categories should include:

* Northern Vietnamese
* Central Vietnamese
* Southern Vietnamese
* Noisy recordings
* Lectures
* Meetings
* Technical terminology

No model or architecture decision should be finalized before benchmark planning.

---

## Implementation Policy

Do not build the entire system at once.

Prefer:

Research
→ Specification
→ Architecture Review
→ Benchmark Design
→ Roadmap
→ Implementation

Avoid premature optimization.

Avoid feature creep.

Prefer the smallest architecture that satisfies current requirements.

---

## Decision-Making Principles

When multiple options exist:

1. Prefer evidence over intuition.
2. Prefer measured results over assumptions.
3. Prefer maintainability over novelty.
4. Prefer incremental progress over large rewrites.
5. Prefer architecture flexibility over hard-coded decisions.

If uncertainty exists, explicitly state:

* What is known
* What is assumed
* What must be validated

Never present assumptions as facts.
