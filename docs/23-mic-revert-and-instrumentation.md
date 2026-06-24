# 23. Microphone — revert doc-22, instrument, and re-diagnose from real timing

> **Status: investigation + instrumentation. No new routing fix applied.**
> doc-22's `_ACTIVE_SID` "armed session" routing was reverted because it regressed
> first-recording quality and did **not** fix the real-world consecutive-session
> failure. We re-baselined on doc-20, added opt-in live diagnostics, and found a
> **simpler, source-verified mechanism** — session 2 starting *before* session 1 has
> finished finalizing — that reproduces the exact symptoms. The next step is to confirm
> it from a **real browser** log before changing any routing.

## 1. Why doc-22 was reverted

doc-22 introduced a module-global `_ACTIVE_SID` ("armed session") and routed all audio
by it instead of the per-event `m_state` id. It was verified **only** with a synthetic
harness that calls `mic_start → mic_stream* → mic_stop` **in strict sequence**. Real
testing showed:

- First-recording quality got **worse** (doc-22 dropped the pre-`start_recording` onset
  chunk instead of capturing it — it removed the doc-20 "reuse the racing session" path).
- Second recording **still failed**; reload **still required**.

So `_ACTIVE_SID` (RC-S1 from doc 21) was **not** the primary root cause. Reverted to the
doc-20 baseline: route by `m_state`; `mic_start` reuses a non-stopped racing session;
`mic_stream` lazily opens a session when `m_state` is `None`. `MicSession` (background
worker, gain-norm, processed-WAV) is unchanged. **41 tests pass.**

> Note: this repo is not under git, so the "revert" is a faithful reconstruction of the
> doc-20 routing semantics (verified against the doc-21 behavioural description), not a
> `git revert`.

## 2. The flaw in the previous diagnoses (doc 21/22)

Both the doc-21 harness and the doc-22 tests **call `finish()` to completion before
session 2 starts**. That erases the one interval where the bug lives. The real browser
does **not** serialize these events — see §3. By serializing them, every synthetic test
silently assumed the thing that is actually false.

## 3. Source-verified: Gradio does **not** serialize start/stream/stop

The whole overlap question hinges on one framework fact, so it was verified against the
installed version rather than assumed (Gradio **5.50.0**):

- Each event listener gets its **own** `concurrency_id` derived from the function object:
  `self.concurrency_id = concurrency_id or str(id(fn))`
  — [`gradio/block_function.py:74`]. `mic_start`, `mic_stream`, `mic_stop` are three
  different functions → **three different concurrency ids**.
- The queue keeps a **separate `EventQueue` per concurrency id**
  ([`gradio/queueing.py:126`]) and the scheduler shuffles the ids and pulls from each one
  whose `current_concurrency < concurrency_limit` independently
  ([`gradio/queueing.py:413-436`]), against a 40-thread pool (`max_threads` default).
- `default_concurrency_limit` defaults to **1** — but that is **per id**, so it only
  serializes *repeats of the same handler*, not *different* handlers.

**Conclusion:** session 1's `stop_recording → mic_stop → MicSession.finish()` (which
**blocks**, draining the queue + `worker.join(timeout=60)`) can run **concurrently** with
session 2's `start_recording → mic_start` and `stream → mic_stream`. The user's "simpler
explanation" is mechanically possible at the framework level.

## 4. Root cause candidate — RC-OVERLAP (finalize/start overlap)

```
MicSession.finish():
    self._q.put(None)              # exit sentinel
    self._worker.join(timeout=60)  # <-- BLOCKS here while the backlog drains
    ...
    self.stopped = True            # <-- .stopped flips True ONLY AFTER the join
```

`stopped` is set **at the end** of `finish()`. So for the entire (possibly multi-second,
thermally-throttled) drain, the previous session still looks **not stopped**. Meanwhile
`m_state` is still the old sid, because `mic_stop` has not returned yet. Therefore, when
the user clicks **Record** again during that window:

- `mic_start(oldSid)` sees the old session "not stopped" → **reuses the dying session**.
- `mic_stream(chunk, oldSid)` enqueues session-2 audio into it — **after** the `None`
  sentinel that `finish()` already queued. The worker hits the sentinel and exits, so
  those chunks are **never processed** → session 2's audio is lost.

This explains **every** reported symptom, and crucially differs from doc-21's RC-S1
(which assumed the old session was already *stopped*; here it is *mid-finalize*):

| Observed | RC-OVERLAP explanation |
|---|---|
| Session 1 fine | no overlap on the first take |
| Session 2 transcript empty | session-2 chunks stranded after the sentinel, never decoded |
| Saved WAV only ~1–2 s | only the few chunks that slipped in *before* the sentinel were processed |
| Duration ≠ spoken | most chunks never reach `_audio` |
| Reload restores normal | reload resets `m_state→None`, so session 2 takes the lazy-create path — no reuse |

### Reproduced with real threads — `scripts/diag_mic_overlap.py`
```
A) serial: stop session 1 fully, then start session 2
   session 1 = 13.23s   session 2(new) = 13.23s      distinct sessions: True   # fine

B) overlap: Record (session 2) fires while session 1 is still finalizing
   session 1 .stopped DURING session-2 start : False   (window open)
   session 2 got its OWN session             : False   (reused the dying one)
   session 2 streamed                        : 13.50s (27 chunks)
   session 2 STRANDED unprocessed in dead q  : 13.50s (27 chunks)
   -> REPRODUCED — session 2 reused the finalizing session and lost its audio
```
The harness forces the drain to block by holding `_MODEL_LOCK` (standing in for a slow /
throttled decode). It uses the **real** ui handlers and real threads. It is **not** a
browser — so it proves the mechanism is *real in the code*, not that it is *the* path hit
in production. That last step needs browser logs (§6).

## 5. Live diagnostics added (opt-in, temporary)

Set before launching the UI:

```bash
VNSTT_MIC_DEBUG=1 VNSTT_MIC_LOG=/tmp/mic.log .venv/bin/python -m vnstt.ui
```

`VNSTT_MIC_DEBUG=1` logs every mic lifecycle event to **stderr** (and to `VNSTT_MIC_LOG`
if set), each line stamped with `elapsed seconds` + `thread name` so overlap is visible:

| event | fields | what it tells you |
|---|---|---|
| `mic_start.enter/.reuse/.new` | `sid_in`, `sid_out` | did Record reuse a session or open a new one? |
| `session.create` / `session.prune` | `sid`, `n_sessions` | session creation/destruction |
| `worker.start` / `worker.sentinel` / `worker.exit` | `sid`, `processed`, `exported_s` | worker lifecycle |
| `worker.enqueue` | `sid`, `qsize`, `recv_s` | **queue size** + **audio seconds received** |
| `mic_stream.feed` / `.drop_stopped` / `.lazy_create` | `sid`, `qsize`, `samples16k` | per-chunk routing decision |
| `finish.enter` / `finish.done` | `qsize`, `recv_s`, `exported_s`, `join_s`, `timed_out` | drain time + whether `join` timed out |
| `mic_stop.done` | `wav`, `wav_s`, `final_chars` | **audio seconds exported** to the WAV |

When `VNSTT_MIC_DEBUG` is unset the logger is a no-op (hot paths are guarded), so this is
safe to leave in until the live diagnosis is closed, then remove.

## 6. The decisive next evidence — one real browser session

Run the UI with logging (above), then in the browser do **one** session-1 → **Stop** →
quickly **Record** session-2 (no reload) → **Stop**. The `thread` + `elapsed` columns
make the three competing hypotheses fall out immediately:

- **RC-OVERLAP (this doc):** session-2 `mic_start.reuse` / `mic_stream.feed` lines appear
  **between** session-1's `finish.enter` and `finish.done` (overlapping threads); session-2
  chunks go to the **old sid**; `finish` may show `timed_out=True`.
- **RC-S2 (Gradio streaming-Audio not re-arming after Stop):** session 2 shows only a
  **handful** of `mic_stream` calls total / low `recv_s` — the **browser sent little**. No
  server fix helps; this is a client/Gradio issue (candidate: recreate the `gr.Audio`
  component, or upgrade/downgrade Gradio).
- **RC-S1 (doc 21 stale-stopped id):** session-2 shows `mic_stream.drop_stopped` lines
  with the **stopped** old sid recurring (only possible *after* `finish` completed).

Paste the `session 2` portion of the log and the diagnosis is decidable.

## 7. Conservative UX fix — evaluation (NOT yet applied)

The user's proposal — *disable Record while finalization runs; show "Processing previous
recording…"; only allow a new recording after cleanup completes* — is a **direct and
correct** remedy **if** RC-OVERLAP is confirmed: it removes the overlap window entirely,
so session 2 can never start against a finalizing session. It adds no routing abstraction.

**Feasibility in Gradio 5.50 (verified API shapes):**

- Make `mic_stop` a **generator**: first `yield` a "⏳ Processing previous recording…"
  status and `gr.update(interactive=False)` on the mic component, *then* run the blocking
  `finish()`, *then* `yield` the final transcript + WAV + `gr.update(interactive=True)`.
  Gradio streams successive `yield`s of an event to the UI, so the disable lands **before**
  the blocking drain. (Generator/streaming outputs are a documented Gradio feature.)
- A small `gr.Markdown` status box reflects "Processing…" / "Ready".

**Trade-offs / honest caveats:**

- It is a **UX serialization**, not a fix to the underlying `stopped`-flips-late defect.
  A minimal *code* fix (mark the session finalizing at the **start** of `finish()`, and
  have `mic_start` always open a fresh session rather than reuse a finalizing one) would
  also close the window — but that touches routing, which we are deliberately **not** doing
  until the browser log confirms RC-OVERLAP. The UX gate is the safer first move.
- It does **nothing** for RC-S2. If the log shows the browser simply stops streaming after
  Stop, the gate won't help and the fix belongs on the client/Gradio side.
- Disabling the component mid-`stop` must re-enable reliably (re-enable in a `finally`/last
  `yield`) or a failed finalize could leave Record stuck disabled.

**Recommendation:** capture the one browser log first (§6). If it shows the overlap, apply
the generator-based UX gate (smallest safe change). I have **not** implemented it — per the
instruction to stop changing behaviour until real logs identify the failure path.

## 8. Client-side (browser) diagnostics — added after the first live log

The first browser log (§ recap below) **refuted RC-OVERLAP** and pointed at the client:
session 2 opened a clean new server session (`mic_start.new`, `finish` instant with
`join_s=0.0`, **no** overlap) yet the browser delivered only **1.0 s / 2 chunks**, 11 s
after Record and bunched 5 ms apart → empty transcript, 1.0 s WAV (the exact reported
symptom). So the remaining question is strictly client-side:

> **On recording #2, is the browser still capturing and sending audio, or does capture
> stop before the server ever receives it?**

To answer it definitively, `ui.py` injects a **read-only** diagnostics script into
`<head>` **only when `VNSTT_MIC_DEBUG` is set** (default launch is byte-for-byte
unchanged). It wraps, at the prototype level (robust to Gradio's minified bundle), the
browser audio-capture APIs the streaming mic uses — verified present in the 5.50.0
frontend (`AudioContext`/`audioWorklet`/`createMediaStreamSource`, plus `MediaRecorder`):

| client event | what it tells us |
|---|---|
| `getUserMedia.request` / `.granted` / `.ERROR` | did the browser (re)acquire the mic on take 2? |
| `track.acquired {readyState,muted}` | is the captured audio track live or already dead/muted? |
| `track.ENDED` / `track.MUTE` / `track.stop()` | did the app tear the mic track down on Stop and not re-acquire it? |
| `AudioContext.suspend()/resume()/state` | did the audio graph go suspended and fail to resume on take 2? |
| `createMediaStreamSource {ctxState}` | was the mic re-wired into the graph for take 2? |
| `worklet.msg {n}` / `scriptProcessor.audioprocess {n}` | **PCM frames the mic actually produced** on take 2 (the decisive count) |
| `MediaRecorder.start` / `.data {size}` / `.stop` | if this build records-then-uploads, did it restart and emit blobs? |

Each line is `[mic-client <elapsed>s] <event> <json>` and is both `console.log`-ed and
buffered; running **`__micDump()`** in the DevTools Console copies the whole buffer.

### How to capture (one run)
```bash
VNSTT_MIC_DEBUG=1 VNSTT_MIC_LOG=/tmp/mic.log .venv/bin/python -m vnstt.ui
```
1. Open `http://127.0.0.1:7860`, open **DevTools → Console**.
2. Record → speak ~8–10 s → Stop.  **Immediately** Record → speak ~8–10 s → Stop (no reload).
3. In the Console run `__micDump()` (copies all `[mic-client …]` lines), and also keep
   `/tmp/mic.log` (server side). Paste the **take-2** portion of both.

### How the client log decides it
- **Capture stopped (browser side):** take 2 shows `track.stop()`/`track.ENDED` on the
  first Stop and **no** `getUserMedia.request` (or a dead `track.acquired readyState:"ended"`)
  for take 2 — i.e. the mic was never re-armed. Few/zero `worklet.msg`. → fix is to make the
  component re-acquire/reset on Stop (client/Gradio-side).
- **Graph suspended:** `AudioContext.suspend()` on Stop with **no** `resume()` on take 2;
  context `state:"suspended"`. → fix is to resume/recreate the context.
- **Capturing but not delivered:** healthy `worklet.msg` count climbing on take 2 **but**
  the server log still shows almost no `mic_stream.feed` → the loss is in the
  websocket/stream transport, not capture. → different fix entirely.

This isolates the failure to one of {re-arm, resume, transport} with a single run, before
any client-side change is proposed.

## 9. Status
- `src/vnstt/ui.py` — reverted to doc-20 routing; opt-in SERVER instrumentation; opt-in
  CLIENT (`<head>`) diagnostics, both gated on `VNSTT_MIC_DEBUG` (default UI unchanged).
- `tests/test_ui.py` — doc-22 regression tests removed; doc-20 reuse test restored;
  `test_consecutive_sessions_normal_order_capture_full_audio` documents the serial baseline.
- `scripts/diag_mic_overlap.py` — new; reproduces the (latent) RC-OVERLAP mechanism.
  `diag_mic_sessions.py` (verified the reverted doc-22 fix) removed.
- **First live log: RC-OVERLAP refuted; cause is client-side** (browser sent only ~1 s on
  take 2 into a clean server session). The UX gate would not fix this.
- **Second live log (client+server, §10): DEFINITIVE — capture is healthy; the loss is in
  the Gradio streaming front-end's send/dispatch on take 2.** The browser's MediaRecorder
  emits ~96 chunks / ~10 s normally; the server receives ~1 s. Not capture, not routing.
- **Fix applied (§12): per-take remount of the streaming mic via `@gr.render`** (option 1,
  user's choice — keep streaming). Routing/worker/session code untouched. **41 tests pass**
  (build-only check); needs a one-run browser verification (§12) — front-end behaviour can't
  be verified headless.

## 10. Second live log — capture works, transport is the locus (Chrome 149, macOS)

This build streams the mic via **`MediaRecorder`** (`audio/webm;codecs=pcm`), one blob
~every 100 ms. Aligning the client console log with the server's run (consistent ~5.9 s
client→server offset):

| | take 1 (works) | take 2 (fails) |
|---|---|---|
| client `MediaRecorder.data` | 106 chunks, ~10.6 s | **96 chunks, ~9.6 s, +2.0 MB — normal cadence** |
| client track / context | live / running | **live / running** (no `track.ENDED`, no `suspend`) |
| **server `recv_s`** | climbs 0.5 → 12.0 | **stuck: 10.4 s silence, then 2 chunks (1.0 s) at the very end** |
| server result | `final_chars=112`, `wav_s=12.0` | `final_chars=0`, `wav_s=1.0` |

The browser captured ~10 s of audio on take 2 and the track stayed live the whole time;
the server got none of it until a ~1 s tail flush. So the audio is dropped **client-side,
in Gradio's streaming dispatch, before the websocket** — the streaming `gr.Audio`
component does not re-arm its *send* pipeline on the second take without a page reload.
(Capture re-arms fine; only the per-tick `stream` dispatch does not.) This is a Gradio
front-end bug, not our routing/worker/session code, and not audio capture.

Notable client detail: on take 2 `MediaRecorder.start` fired with **no** `MediaRecorder.new`
and the data counter continued (n=110→205) — the front-end re-`start()`ed the *old*
recorder instance rather than building a fresh streaming pipeline, which is consistent with
the dispatch machinery not being re-initialised.

## 11. Smallest-fix options (proposed, NOT applied — pick before any change)

The defect is in Gradio's front-end streaming dispatch, which we can only influence
indirectly. In rough order of size/risk:

1. **Recreate/reset the mic component on Stop** so the front-end rebuilds its stream
   pipeline for the next take (mimicking the reload that we know fixes it). Smallest *if* it
   works — but a value reset may not re-initialise the underlying dispatch; **needs
   source/empirical verification** before trusting it.
2. **Switch the mic tab to non-streaming: record → on Stop, run the existing batch
   `transcribe_file`.** Sidesteps the entire streaming-dispatch/re-arm bug class and reuses
   the *proven, more accurate* file pipeline (doc 17/19). Cost: no live "partial" box.
   For a **testing/sample-collection UI**, this is likely the most robust and is arguably
   the smallest *reliable* change. Live streaming remains available via the CLI `--mic`.
3. **Gradio version change** if 5.50.0 has a known streaming-restart bug fixed elsewhere —
   needs a changelog/issue check.

Recommendation pending your call: **(2)** for reliability given the UI's purpose, unless a
live partial transcript is a hard requirement — in which case verify **(1)**/**(3)** first.
No implementation until you choose.

## 12. Fix applied — per-take remount of the streaming mic (option 1)

**Decision:** keep live streaming, fix the re-arm.

**Source basis (why a remount, verified):** the symptom is upstream Gradio bug
[#10486](https://github.com/gradio-app/gradio/issues/10486) ("Real Time Speech Recognition
not working after first stop", reported on 5.x, **closed "not planned"** — no upstream fix);
6.x is not a safe escape ([#12827](https://github.com/gradio-app/gradio/issues/12827) is a
*new* streaming-mic infinite-loop in 6.4.0). The only reliable reset is what a page reload
does: destroy and recreate the mic component so the browser builds a fresh MediaRecorder/
stream pipeline. Gradio's documented mechanism for that is `@gr.render`: components created
in a render function **without a `key=`** are destroyed and recreated on each re-render
(per the render-decorator guide — "Without a key, components are destroyed and recreated on
each render, resetting their state").

**Change (mic tab only; routing/worker/session code untouched):**
- A `m_take = gr.State(0)` counter. The streaming `gr.Audio` (and its three listeners) now
  live inside `@gr.render(inputs=[m_take])`, with **no `key=`** → each re-render mounts a
  fresh mic component.
- `stop_recording` now calls `mic_stop_and_remount`, which runs the unchanged `mic_stop`
  finalize **and** bumps `m_take`, triggering the re-render → the *next* take starts on a
  freshly-mounted mic. (Bounded: the counter changes once per Stop, so no render loop.)
- Outputs (`m_final`, `m_partial`, `m_wav`) stay **outside** the render so the transcript
  persists across remounts.

**What is verified vs not:** `build_ui()` constructs and all **41 tests pass** — but those
only confirm it *builds*. The fix targets browser front-end behaviour that **cannot be
verified headless**. The live diagnostics from §5/§8 are the proof.

### Verify in one browser run
```bash
VNSTT_MIC_DEBUG=1 VNSTT_MIC_LOG=/tmp/mic.log .venv/bin/python -m vnstt.ui
```
Record → speak ~8–10 s → Stop → **immediately** Record → speak ~8–10 s → Stop (no reload).
- **Fixed:** server `/tmp/mic.log` shows take-2 `recv_s` climbing steadily again (not stuck
  at ~1 s), `final_chars > 0`, `wav_s ≈ spoken`. Client shows a **new** `MediaRecorder.new`
  for take 2 (a fresh recorder), not a re-`start()` of the old one.
- **Still broken:** take-2 `recv_s` stuck at ~1 s ⇒ the remount didn't re-arm dispatch;
  fall back to option 2 (non-streaming record→`transcribe_file`), which avoids the bug class.

This is cleanly revertible (restore the plain mic tab + drop `m_take`/`mic_stop_and_remount`).

### Live verification result (Chrome 149) — partial: re-arm works, but a remount-latency race remains
Client log of Record → Stop → *immediate* Record → … :
- The remount **fires**: a later take shows a fresh `MediaRecorder.new` (chunk counter resets
  to n=1) and the old component logs `AudioContext.close()`. A take on the freshly-mounted
  component streams cleanly (~13 s, normal cadence). **Re-arm without page reload is achieved.**
- **But** the *immediate* retry ran on the **old** component (`MediaRecorder.start` with **no**
  `MediaRecorder.new`, counter continued) and was **truncated ~1.7 s in by `AudioContext.close()`**
  (an unmount, not a user `track.stop()`) — i.e. the remount tore the component down underneath
  the user.
- **Root of the race:** `mic_stop_and_remount` bumps `m_take` only **after** the blocking
  `mic_stop`→`finish()` drain (measured ~3.8 s here; worse under thermal load). The remount is
  therefore delayed by the drain, and during that window the stale mic is live and accepts a take.

**Completion APPLIED — generator `mic_stop_and_remount` (v2).** Rather than yielding the
remount first (which would destroy the in-flight trigger component mid-event and risk losing the
results yield), the safe shape is **disable-first / remount-last**:
1. First `yield` (emitted *before* the blocking `finish()` drain): `gr.update(interactive=False)`
   on the mic + a "⏳ Finalizing…" status, with `gr.skip()` for the other outputs. The stale mic
   is disabled within ms of Stop, so an immediate retry can't land on it.
2. `mic_stop()` runs the drain (unchanged).
3. Final `yield`: the transcript + WAV **and** the `m_take` bump together — outputs apply first,
   then `m_take.change` remounts a fresh, enabled mic. Being the last yield, destroying the old
   trigger component here is safe.

`gr.skip()` (verified: skips a single output position) keeps the previous transcript visible
during finalize. Trade-off: the user waits out the `finish()` drain (mic disabled, status shown)
before the fresh mic appears — correct over silent truncation. **Still requires a browser run to
confirm** `interactive=False` actually greys the record control and the two-yield sequence behaves
(headless can only confirm it builds + 41 tests pass). If `interactive=False` does **not** block
the record button, swap it for `gr.update(visible=False)` (guaranteed to prevent the click).

### Verify v2 in one browser run
Same recipe as above. Expected on take 2 (immediate retry):
- On Stop: the mic greys out / shows "⏳ Finalizing…" and **cannot** be clicked until it resets.
- After the brief finalize, a fresh mic appears; recording then streams normally — server take-2
  `recv_s` climbs to ~spoken seconds, `final_chars > 0`, and the client logs a new
  `MediaRecorder.new`. No `AudioContext.close()` truncating a take the user started.
