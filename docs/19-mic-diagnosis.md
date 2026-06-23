# 19. Microphone pipeline — diagnosis report (no fixes yet)

> Investigation only, per request: trace the path, instrument it, prove/disprove state
> reset, capture the processed audio, and rank root causes by confidence **before**
> changing any pipeline logic. Evidence gathered with two non-invasive harnesses that
> *observe* the real handlers without altering them: `scripts/diag_mic.py`,
> `scripts/diag_mic2.py`. Measured on M3 / 16 GB with PhoWhisper-medium GGML (f16).
>
> **Environment caveat:** a live browser mic can't run headless here, so chunks are
> *simulated* (fixture audio → 48 kHz int16 → 0.5 s chunks). The entire **server-side**
> path is the real code; the **transport** layer (browser → websocket → Gradio) is
> reasoned about from its measured timing, not directly observed. Flagged per claim.

## A. The complete path, every transformation

| # | Stage | What happens | Code |
|---|---|---|---|
| 1 | Browser mic | Captures at the device rate (typically **48 kHz / int16**, mono or stereo) | browser |
| 2 | Gradio `stream` | Every `stream_every=0.5 s` delivers the **new** chunk `(sr, int16 ndarray)` to the handler; state is the `gr.State` holder | `ui.build_ui` |
| 3 | `mic_stream` | Guards None/stopped holder; pulls `(sr, y)` | `ui.py:134` |
| 4 | `_to_mono16k` | int→float `/iinfo.max`, mean to mono, **linear** resample sr→16 kHz, clip [-1,1] | `ui.py:52` |
| 5 | `feed()` | Appends to `self.buffer`; `_since_decode += n` | `streaming.py:122` |
| 6 | VAD | `get_speech_timestamps(buffer, threshold=0.5, min_silence=400 ms)` over the **whole buffer** | `streaming.py:151` |
| 7a | no speech | keep last 1 s, advance `_offset_s`, **discard the rest**, return | `streaming.py:128` |
| 7b | trailing silence ≥0.4 s & speech ≥0.25 s | `_finalize()` | `streaming.py:137` |
| 7c | buffer ≥15 s | `_finalize()` (safety) | `streaming.py:139` |
| 7d | else every 1 s | `_decode_partial()` | `streaming.py:141` |
| 8 | ASR | `engine.transcribe(self.buffer)` — **re-decodes the whole growing buffer** each time | `streaming.py:167` |
| 9 | `_clean_tokens` | strip onset `.`/`…`, drop punct-only (the doc-17 onset fix) | `streaming.py:172` |
| 10 | LocalAgreement-2 | commit the longest prefix two consecutive hypotheses agree on | `HypothesisBuffer.insert` |
| 11 | commit / finalize | `_emit` appends to `final_words`, fires `on_commit`; `_finalize` flushes remainder then **zeroes buffer + new HypothesisBuffer** | `streaming.py:174,189` |
| 12 | UI display | `on_commit` → `holder["committed"]`; partial read live from `hyp.pending()` | `ui._display` |

Verified end-to-end on a clean session: 27 chunks → 13 ASR decodes (buffer 1→2→3 s sawtooth) → 4 finalizes → 27 committed tokens → `0.0%` WER. The full event trace is in `scripts/diag_mic.py` output.

## B. Instrumentation (captured per session)

`scripts/diag_mic.py` records: session id, recorded duration, total samples, total/delivered
chunks, chunk order + durations, **buffer duration handed to each ASR decode**, finalize
events, committed-token count, partial-token count, VAD events (per call: buffer dur,
regions, speech seconds), **TRIM-discarded samples**, and the final transcript.

## C. State-reset proof — CLEAN (a suspected cause, DISPROVEN)

Snapshot of a **fresh** session 2 before any audio:

```
buffer_samples=0, hyp.committed=[], hyp._prev=[], _since_decode=0, _offset_s=0.0,
_utt_words=[], final_words=[], total_decode_s=0.0, holder.committed=[], partial="",
stopped=False   →  ALL CLEAR
```

Every per-session field is recreated by `_new_session` (new `StreamingTranscriber`, new
`HypothesisBuffer`, fresh `committed` list). Consecutive sessions both scored 0.0% on clean
audio. The ASR **engine object is shared** across sessions (cached), but pywhispercpp runs
with `no_context=True` (default) so no decode text carries over. **There is no state leak.**
The reported "later recordings less reliable" is far better explained by **thermal
throttling** (§D-RC2) than by state — decode slows 3–5× as the machine heats, which worsens
the real-time deficit.

## D. Root causes, ranked by confidence

### RC-1 — Short-segment streaming decode hallucinates on real audio (HIGH) — the main cause
The **same** audio, batch vs streaming:

| audio | BATCH (file pipeline) | STREAMING (mic path) |
|---|---|---|
| clean | 4% WER | 0% WER |
| low-gain 0.30× | **4% WER** | **89% WER** — `…a little hot and a little hot and a little hot…` |
| noisy + low-gain | **4% WER** | **26% WER** — `italia …`, `it is a sunny day …` |

Batch hands Whisper the whole 13 s with context and is **robust** to low level/noise.
Streaming hands it isolated 1–4 s segments, and on degraded audio Whisper **hallucinates**
— repetition loops and English injection. Real mic audio is exactly this: quieter and
noisier than a clean file. This is the core of *"mic significantly worse than file."*
Explains **symptoms 1 and 2**. Note the streaming decode uses none of the batch
anti-hallucination guards (`condition_on_previous_text`, `hallucination_silence_threshold`,
temperature fallback), and there is no input gain normalization.

### RC-2 — Real-time decode deficit → transport drops/coalesces/reorders chunks (HIGH for the deficit; MEDIUM-HIGH that it reaches the user)
Per-0.5 s-chunk processing time, **warm**:
```
[1, 896, 9, 1022, 12, 921, 1, 799, 8, 920, 12, 913, 2, 973, 6, 1125, 12, 1081, 7, 1094, 3, 800, 8, 938, 11, 933, 2] ms
max 1125 ms · 13 of 27 chunks exceed the 500 ms budget
```
Every chunk that triggers a decode takes **0.8–1.1 s warm (3–5× under thermal load)** — well
over the 0.5 s `stream_every` cadence, while holding `_MODEL_LOCK`. The handler cannot keep
up, so Gradio must **drop or coalesce** incoming mic chunks (transport behaviour, reasoned
from timing — not directly observed headless). Injecting that fault reproduces the user's
symptoms exactly:
```
dropped chunks {2,5} → "italia xin chào là lan …"           (11% WER, mangled onset)
reordered 2↔3        → "my xin chào là la tôi tên anh …"    (18% WER, scrambled phrase)
```
Explains **symptoms 2, 3, 4** and the "not processed exactly once" suspicion — *in-process*
every chunk is processed exactly once (feed-calls == chunks, samples conserved), but the
**transport layer upstream of the handler** is where audio is lost.

### RC-3 — start_recording / stream race discards the onset chunk (MEDIUM-HIGH)
If the first `stream` chunk arrives before `start_recording`'s output commits the new holder,
`mic_stream` lazily builds session **A**, then `mic_start` overwrites `m_state` with session
**B** — and A's audio is orphaned:
```
orphan session A got 8000 samples (0.50 s) → DISCARDED
race final: "hôm nay trời rất đẹp …"   (22% WER — entire "xin chào tôi tên là lan" LOST)
```
Explains **symptoms 3 and 5** (unstable onset; first/early recording unreliable). Confidence
medium-high: the code path provably allows it; live Gradio event ordering isn't observable
here.

### RC-4 — Inherent streaming-vs-batch gap (MEDIUM, baseline)
Per-utterance buffer reset (`_finalize` zeroes buffer + hypothesis) means each utterance is
decoded with **no cross-utterance context** and on short audio. Even clean, streaming is
structurally below batch; it compounds RC-1. Contributes to **symptom 1**.

## Symptom → root-cause map

| Observed symptom | Primary cause(s) | Also |
|---|---|---|
| 1. Mic quality ≪ file | **RC-1** | RC-4, RC-2 |
| 2. Missing words / dropped phrases | **RC-2** (transport) | RC-1 (corruption) |
| 3. Onset loss ("Xin chào") | **RC-3** (race), **RC-2** (dropped 1st chunk) | — |
| 4. Lost / duplicated / reordered chunks | **RC-2** | — (in-process logic is correct) |
| 5. Later recordings less reliable | **RC-2 via thermal throttling** | RC-3 |
| 6. Can't hear processed audio | tooling gap (see §E) | — |

## Disproven hypotheses (tested, with evidence)

- **State / session leak** — fresh state ALL CLEAR; consecutive sessions 0%. Not a cause.
- **VAD cutting speech / the `not ts` trim discarding audio** — `0.00 s` discarded in every
  acoustic condition tested. Latent risk only; not a current cause.
- **48 kHz→16 kHz resampling** — 16 kHz-direct vs 48 kHz-resampled both 0% WER. Not a cause.
- **LocalAgreement committing wrong / chunks duplicated in the buffer** — in-process every
  chunk is fed exactly once and samples are conserved; commits are monotonic. The losses are
  upstream (transport), not in the buffer/LA logic.

## E. The missing artifact (symptom 6) — captured

The harness now saves the **exact 16 kHz audio the pipeline processed** and reports duration
+ rate: `/tmp/diag_mic_session1.wav (13.23 s, 16000 Hz, mono)`. This is the file-feed
simulation; for live mic the same capture belongs in the UI (proposed below).

## Proposed fixes — NOT applied (for discussion)

Ranked to match the root causes; each is a hypothesis to validate, not yet implemented:

1. **RC-2 (biggest usability win):** decouple capture from decode — feed chunks into a
   thread-safe queue immediately and run ASR in a single background worker, so the Gradio
   handler returns in ms and never drops audio. Alternatively raise `stream_every` and cap
   buffer growth. *Validates by: zero dropped chunks under real-time pacing.*
2. **RC-1:** apply the batch anti-hallucination guards to the streaming decode
   (`condition_on_previous_text`, `hallucination_silence_threshold`, temperature fallback),
   add **input gain normalization** before ASR, and consider longer minimum decode windows.
   *Validates by: low-gain/noisy streaming WER dropping from 26–89% toward the 4% batch floor.*
3. **RC-3:** make session creation single-owner — create the session lazily in `stream`
   only, have `start_recording` just reset, so no overwrite can orphan the first chunk.
   *Validates by: onset retained under a start/stream race.*
4. **Symptom 6 / D:** add a `gr.Audio` output to the mic tab, have `mic_stop` write the
   accumulated processed audio to a WAV and return its path for in-UI playback + duration/SR.
5. **RC-4:** carry a short audio/text primer across utterance boundaries instead of a hard
   buffer reset (larger change; evaluate after 1–3).

No code beyond the two read-only diagnostic harnesses has been changed.
