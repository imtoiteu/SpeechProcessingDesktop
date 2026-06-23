# 16. Phase 3 — Streaming polish results

> Goal: make mic mode production-ready and pleasant. Measured on a **realistic 4-utterance VN sample with
> ~0.5s pauses** (`tests/fixtures/multi.wav`, 13.2s) on the dev **M3 / 16 GB (fanless)**.

## What changed
| Area | Change |
|---|---|
| **VAD segmentation** | Tuned Silero `min_silence_duration_ms=400` (default 2000 merged everything) → clean per-sentence finalization; pure-silence buffers are skipped (never decoded); 1s onset tail kept. |
| **LocalAgreement** | `decode_interval_s` default **0.5 → 1.0** (partials ~1/s) to hold RTF in budget; 2-way agreement kept (it correctly rejects hallucinations). |
| **Punctuation** | Standalone punctuation tokens dropped; leading punctuation stripped off an utterance's first word (`.chào` → `chào`). |
| **Terminal UX** | Committed text solid + live partial **dimmed**, refreshing in place on a TTY; clean one-line-per-utterance on non-TTY/pipe. |
| **Latency instrumentation** | `total_decode_s` (RTF) + per-utterance finalization decode time. |
| **audio_ctx** | Tried (to cut whisper.cpp's 30s-window cost) — **reverted**: reducing it produces garbage (`.`) on short buffers. Full ctx is fast enough *when not throttled* (~0.2s/3s-buffer warm). |

## Measured results

| Metric | Warm / steady | Under sustained load (thermally throttled) |
|---|---|---|
| **Avg per-utterance latency**¹ | ~0.6–0.9 s | **~1.4 s** (measured) |
| **Streaming RTF** (decode ÷ audio) | ~0.3–0.5 | **~0.95** (measured) |
| Finalization decode (3s buffer) | ~0.2 s (micro-bench) | ~1.0 s |

¹ latency = `min_finalize_silence` (0.4s) + one finalization decode — i.e. "how long after you stop speaking
the final text appears." (PortAudio buffers during decode, so this is the real perceived latency as long as RTF<1.)

**The dominant variable is thermal state.** A controlled micro-benchmark showed a 3s buffer decodes in **0.19s
warm**; after sustained back-to-back streaming the *same* decode took ~1s (≈5× slower). On a fanless M3, heavy
continuous streaming throttles and pushes RTF toward 1 and latency toward ~1.4s.

## Known limitations
1. **Thermal throttling (fanless M3)** — the biggest limiter. Sustained streaming slows decode 3–5×; RTF can
   reach ~1 and latency drift up. Mitigations: PhoWhisper-**small** GGML (faster), sparser partials
   (`decode_interval_s` 1.5), or a fan-equipped/desktop Mac.
2. **Onset word loss** — the first word of an utterance is occasionally dropped (`xin`, `cảm`, `giọng` seen).
   ~~Inherent to chunked-Whisper streaming.~~ **FIXED in [doc 17](17-quality-pass.md):** it was a
   phantom-`.` LocalAgreement index bug, not a model limitation. `_clean_tokens` resolves it (4/4 onsets
   preserved).
3. **whisper.cpp GGML accuracy quirks** (`máy tiếng`) — unchanged; pending the deferred accuracy A/B.
4. **Live mic content unverified here** — can't speak into the mic in this environment; logic validated via
   real-time-paced file feed; `sounddevice` capture path wired (mic devices present).
5. **Streaming outputs TXT only** — no SRT/VTT (needs streaming word timestamps).

## Recommended default settings (now the code defaults)
```
engine            = whisper.cpp / Metal, PhoWhisper-medium GGML, full audio_ctx
decode_interval_s = 1.0      # partials ~1/s
min_finalize_silence_s = 0.4 # clean sentence segmentation, ~1.4s finalize latency
vad_threshold     = 0.5
min_speech_s      = 0.25     # ignore sub-250ms blips (anti-hallucination)
max_utterance_s   = 15       # force-finalize safety for pauseless speech
chunk_s           = 0.5      # mic block size
```
For long/continuous sessions where throttling bites: switch to **PhoWhisper-small** or raise
`decode_interval_s` to ~1.5 (trades partial responsiveness for headroom).

## Verdict
Mic mode is **usable and pleasant for conversational speech with natural pauses** (latency ~1.4s, RTF <1) when
the machine isn't thermally saturated. The two things keeping it from "fully production-ready" are **thermal
throttling on fanless hardware** and **occasional onset word loss** — both characterized above with concrete
mitigations. 20 tests pass.
