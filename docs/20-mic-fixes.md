# 20. Microphone pipeline — fixes applied

> Implements the fixes proposed in [doc 19](19-mic-diagnosis.md), each validated with
> the same non-invasive harnesses (`scripts/diag_mic.py`, `diag_mic2.py`). 40 tests pass.
> Measured on M3 / 16 GB, PhoWhisper-medium GGML (f16).

## What changed (and the measured before → after)

### RC-1 — gain-normalize the streaming decode buffer
`StreamingTranscriber._hypothesis` now peak-normalizes a **copy** of the decode buffer to
~0.95 before ASR (`normalize_gain=True`, cap 12×, silence skipped). Quiet/low-level mic
audio was making Whisper hallucinate on short segments; full gain fixes it.

| same audio | before | after |
|---|---|---|
| clean | 0% | 0% |
| low-gain 0.30× | **89% WER** (repetition loops) | **0% WER** |
| low-gain 0.15× | 22% | **0%** |

`self.buffer` is never mutated (offsets/finalize math unchanged). Applies to file-stream too
(harmless on clean: clean stays 0%).

### RC-2 — background ASR worker so the stream handler never blocks
The Gradio mic handler used to run the ~0.8–1.1 s decode **inline**, overrunning the 0.5 s
chunk cadence and forcing Gradio to drop/coalesce audio. Now `mic_stream` only **enqueues**
the chunk and returns; one `MicSession` worker thread drains the queue, runs the (globally
serialized) ASR, and publishes committed/partial snapshots the handler reads instantly.

| stream-handler latency per 0.5 s chunk | before | after |
|---|---|---|
| max | **1125 ms** | **12 ms** |
| mean | 463 ms | **1 ms** |
| chunks over the 500 ms budget | **13 / 27** | **0 / 27** |

No audio is dropped: everything is queued and processed; `mic_stop` drains the queue and
joins the worker before returning, so the final transcript is complete (0% WER on the
fixture). Sessions live in a module registry keyed by a string id (`gr.State` holds only the
id — Gradio never has to copy the Thread/Queue).

### RC-3 — single-owner session creation (no orphaned onset)
`mic_start` now takes the current session id and **reuses** a non-stopped session that a
racing `stream` chunk already opened, instead of overwriting it. The first chunk (the onset)
is never orphaned.

| start/stream race | before | after |
|---|---|---|
| onset | `xin chào tôi tên là lan` **lost** (22% WER) | preserved (**0% WER**); session reused |

### Symptom 6 — the processed audio is now visible
`MicSession` accumulates the exact 16 kHz samples fed to ASR; `mic_stop` writes them to a WAV
and the mic tab shows a `gr.Audio` player (playback + download). You can now listen to
exactly what the system processed.

## Residual limitation (honest)
The synthetic **AWGN + low-gain** case stays at **26% WER** (foreign-text injection like
`italia`, `it is a sunny day` on short low-SNR segments). No available lever moved it: VAD
threshold (0.5→0.8), `suppress_nst`, `no_speech_thold`, `logprob_thold`, and disabling the
temperature fallback were all swept — all 26%. Additive white noise is also not representative
of real room noise (HVAC/room tone differ spectrally). The batch pipeline handles the same
audio at 4%, so a future option is short-utterance batching or a correction pass; deferred.

## State / engine notes (unchanged, still clean)
State reset remains **ALL CLEAR** between sessions (each `MicSession` builds a fresh
`StreamingTranscriber`); the ASR engine is shared but runs `no_context=True`. RC-4 (the
inherent per-utterance buffer reset / no cross-utterance context) is **not** addressed here —
it's the larger primer-carryover change deferred in doc 19.

## Verification
- `tests/test_streaming.py` — gain-norm default on; onset + convergence still pass.
- `tests/test_ui.py` — `test_mic_session_background_worker_flow` (worker drains, complete
  final, WAV saved), `test_mic_start_reuses_racing_session_no_onset_loss` (RC-3).
- `scripts/diag_mic.py` / `diag_mic2.py` — updated to the worker API; reproduce all numbers above.
- Full suite: **40 passed**.
