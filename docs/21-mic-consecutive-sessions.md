# 21. Consecutive microphone sessions fail — diagnosis (no fix yet)

> Investigation only. Session 1 works; session 2 (no page reload) yields an empty
> transcript and a saved WAV of only ~1–2 s. Reload restores normal behaviour.
> Evidence: `scripts/diag_mic_sessions.py` drives the **real** ui handlers (no pipeline
> change), modelling `m_state` as Gradio does (each event reads it and its return
> overwrites it).

## The lifecycle (what `m_state` holds across a take)

`gr.State m_state` holds a **session-id string**. Three events all read AND write it:
`start_recording → mic_start`, `stream → mic_stream`, `stop_recording → mic_stop`.

```
fresh page         : m_state = None
session 1 start    : mic_start(None)      -> creates A, m_state = "A"
session 1 streams  : mic_stream(c, "A")   -> enqueue into A
session 1 stop     : mic_stop("A")        -> A.stopped = True ;  m_state stays "A"
                     ^ after Stop, m_state points to a STOPPED session
session 2 start    : mic_start("A")       -> A is stopped, so creates B, m_state = "B"
session 2 streams  : mic_stream(c, "B")   -> enqueue into B        (intended)
```

The intended path is fine. The failure is what happens to **stream events that read
`m_state` before `mic_start` commits "B"** — i.e. they still carry the stopped id "A".

## Evidence

### (1) The stale-`m_state` asymmetry — the smoking gun
```
m_state = None      -> chunk KEPT   (mic_stream lazily creates a session)   captured 0.50s
m_state = stopped   -> chunk DROPPED (mic_stream hits `if sess.stopped: return`) captured 0.00s
                       and the returned m_state STAYS the stopped id (True)
```
`mic_stream` (ui.py:208-225) has two branches for an unusable session:
- `sess is None` → **create a new session and keep the audio** (this is session 1, m=None).
- `sess.stopped` → **ignore the chunk and return the stopped id** (this is session 2, m="A").

So the *same* racing chunk is preserved in session 1 but discarded in session 2. That is
exactly "session 1 good, session 2 broken."

### (2) Without a race, consecutive sessions are fine
```
session 1 captured = 13.23s    session 2 captured = 13.23s
```
In strict `start → streams → stop` order the code works — confirming the trigger is the
event race, not the steady-state logic.

### (3) One stale stream gets `m_state` permanently STUCK on the stopped session
```
after 1 stale stream, m_state == stopped session 1 : True
session 2's NEW session B captured                 : 0.00s   (expected ~13s)
mic_stop then re-finalized the stopped session 1 instead of B
```
Because `mic_stream` **returns the stopped id** when it drops a chunk, a single stale
in-flight stream overwrites `m_state` back to "A". `start_recording` fires **once**;
`stream` fires **continuously** — so the stopped id wins and every subsequent chunk is
dropped. The new session B is orphaned with little/no audio.

## Root causes, ranked

### RC-S1 — `m_state` routing: stopped-session chunks are dropped AND re-assert the stopped id (HIGH — proven code bug)
`mic_stream`'s `if sess.stopped:` branch cannot tell a **trailing post-Stop chunk** (which
*should* be ignored) from the **first chunks of a new recording that arrived before
start_recording committed** (which should open/feed a new session). It ignores both, and by
returning the stopped id it makes `m_state` sticky. This single behaviour explains every
symptom (table below). It is independent of Gradio internals and reproduces deterministically
given the race.

**Why ~1–2 s and not 0 s / full:** the saved length is whatever reached a live session before
`m_state` got stuck. Depending on the exact interleave the outcome ranges from *empty*, to
*~1–2 s in B* (the user's case: a few chunks land in B, then it's orphaned), to *re-finalising
session 1's full audio*. All three are the same bug at different timings; my harness shows the
0 s / re-finalise extreme.

### RC-S2 — Gradio streaming-Audio re-arm (POSSIBLE co-factor — not verifiable headless)
It is also possible the browser/Gradio streaming component does not fully re-arm after Stop
without reload and simply streams ~1–2 s on the next take. This would match the symptoms too,
and reload would also fix it. I **cannot rule this out** without a live mic. It is *distinct*
from RC-S1 and, if present, is additive. The discriminator below tells them apart.

### Disproven / not the cause
- **State leak between sessions** — each `MicSession` is independent; "normal order" gives a
  full, correct session 2. Not a leak.
- **The background worker / ASR / engine** — the saved WAV is built from the audio *fed*, before
  ASR; a short WAV means few chunks were *routed in*, not an ASR fault.
- **Resampling / `_to_mono16k`** — stateless; identical across sessions.

## Symptom → cause map

| Observed | Cause |
|---|---|
| Session 1 transcript good | m_state=None path keeps audio (RC-S1 asymmetry, good side) |
| Session 2 transcript empty | session-2 chunks dropped to the stopped session (RC-S1) |
| Saved audio only ~1–2 s | only the chunks that reached a live session before m_state stuck (RC-S1) |
| Duration ≠ spoken | dropped chunks never enter the saved session (RC-S1); possibly less streamed (RC-S2) |
| ASR gets almost nothing | same — the worker only ever receives the few routed chunks |
| Reload restores normal | reload resets m_state→None → the session-1 (working) path |

## Decisive next evidence (to split RC-S1 vs RC-S2 in a *live* session)
Temporary opt-in logging in `mic_stream`/`mic_stop` capturing per call: the incoming `sid`,
whether the session was `stopped`, and a running count of (chunks **received** vs chunks
**enqueued**). Then do one real session-1→session-2 run:
- **RC-S1**: session 2 shows **many** mic_stream calls, the **stopped id recurring**, and
  enqueued ≪ received.
- **RC-S2**: session 2 shows **few** mic_stream calls total (the browser sent little).

This is logging, not a fix; happy to add it on request.

## Fix direction (NOT applied — for the later fix discussion)
Make recording lifecycle explicit instead of inferring it from a stopped flag: have
`start_recording` be the single authority that opens/arms the session and clears the stopped
state, and make `mic_stream` **never resurrect or stick to a stopped session** — a chunk for a
stopped/None session should open (or wait for) the current armed session rather than be
dropped while echoing the stopped id back into `m_state`. (Detail to be designed with tests
once we agree on the root cause.)
