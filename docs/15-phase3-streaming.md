# 15. Phase 3 — Real-time microphone streaming

> Exit criterion (doc 10): *stable (non-flickering) incremental partial+final within an agreed latency.*
> **Core delivered and validated via simulated streaming; live-mic content is unverifiable in this
> environment (no way to speak into the mic), but the capture path is wired.**

## Approach
Whisper is a 30s batch model, so streaming is emulated:
- **LocalAgreement-2** (`streaming.HypothesisBuffer`): re-decode the growing audio buffer each ~1s; a word
  becomes **committed/final** only once two consecutive hypotheses agree on it. Unstable tail = **partial**.
- **Silero VAD** (reused from `faster_whisper.vad` — *no new dependency*) detects end-of-utterance silence to
  finalize and reset the buffer, keeping it small.
- Engine: **whisper.cpp/Metal** (the CPU path is far too slow to re-decode in real time).

## Built
- `src/vnstt/streaming.py` — `HypothesisBuffer` (LocalAgreement-2), `StreamingTranscriber` (feed/close,
  partial+commit callbacks, VAD finalization), `stream_file` (simulated), `stream_microphone` (sounddevice).
- CLI: `transcribe <file> --stream` (simulated real-time) and `transcribe --mic` (live).

## Validated
- `stream_file` on the VN sample → correct final transcript; **LocalAgreement-2 correctly rejected an early
  English hallucination** (`is a sunny day.`) — it appeared as a partial but never committed because the next
  hypothesis disagreed. This is the policy working as intended.
- **20 tests pass** (4 new): pure LocalAgreement-2 unit tests (commit-on-agreement, no-commit-on-disagreement,
  committed-words-never-revoked) + an end-to-end convergence test (committed transcript contains `việt`,
  commits are monotonic).
- Mic devices are present (`MacBook Air Microphone`); `sounddevice` capture path is wired.

## Honest caveats / limitations
1. **Live mic content unverified here** — I cannot speak into the mic in this environment. The streaming logic
   is proven via file-fed chunks; real-mic field testing is still needed.
2. **Streaming RTF ≈ 1.5** for a single continuous 10s utterance (repeated full-buffer re-decode) — slightly
   *slower* than real-time. Real speech has pauses → VAD finalizes → buffers stay short → keeps up better.
   For guaranteed real-time on long continuous speech, tune `decode_interval_s`, use a smaller model, or trim
   the buffer with timestamps.
3. **Minor artifacts** — an early hallucinated `.` got committed (leading-token guard is a future polish); the
   terminal partial/final display is functional but rough.
4. **Streaming outputs TXT only** — no SRT/VTT in streaming mode yet (needs word-level timestamps from the
   streaming engine).

## Deferred
Real-time SRT/VTT, partial-display polish, real-mic field validation, faster/lower-latency streaming tuning,
leading-punctuation guard, whisper.cpp-vs-faster-whisper accuracy A/B (still open).
