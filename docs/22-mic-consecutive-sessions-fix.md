# 22. Consecutive microphone sessions — fix applied

> Fixes the bug diagnosed in [doc 21](21-mic-consecutive-sessions.md): session 2 (no page
> reload) lost almost all audio because a stale `m_state` id (pointing at the previous,
> stopped session) caused `mic_stream` to drop chunks and stick `m_state` on the stopped
> session. Verified with `scripts/diag_mic_sessions.py`; regression tests added.

## Root cause (recap)
Audio routing depended on the per-event `gr.State` session id (`m_state`). After Stop,
`m_state` points at a **stopped** session; during the next take, stream events that read
`m_state` before `start_recording` committed the new id carried the stopped id. `mic_stream`
then hit `if sess.stopped: return sid, …` — dropping the chunk **and** echoing the stopped id
back into `m_state`, which made it sticky. The asymmetry (`m_state=None` on session 1 *created*
a session and kept audio; a stopped id on session 2 *dropped* it) is why session 1 worked and
session 2 failed.

## The fix — route by a single "armed session", not by `m_state`
A module-level pointer `ui._ACTIVE_SID` is now the **only** authority for which session
receives audio:

- **`mic_start`** (Record pressed) opens a fresh session and sets `_ACTIVE_SID`. It also
  finalizes any still-open previous take (Record without Stop) so no worker leaks.
- **`mic_stream`** routes the chunk to `_ACTIVE_SID` **regardless of the `m_state` sid it was
  handed**. A stale/None/bogus id can no longer drop the chunk or stick `m_state`. If no
  session is armed (a trailing chunk after Stop, or audio before the first Record), it neither
  captures nor blanks — it echoes the last session's final.
- **`mic_stop`** finalizes and disarms `_ACTIVE_SID` (so trailing chunks are ignored).
- **`mic_clear`** finalizes any open session and disarms.

The previous "reuse a racing session" hack (doc 20 RC-3) is **removed** — it relied on
`m_state` and was the source of this bug. The narrow pre-Record onset race it tried to cover
(a stream chunk arriving before `start_recording`) now simply ignores that first ~0.5 s chunk
rather than risk the whole session; in practice `start_recording` fires on the click before
audio is captured, so this is rarely hit.

## Verification (`scripts/diag_mic_sessions.py`)
```
1) armed routing ignores a stale/None/bogus m_state sid : returns armed id = True; 3 chunks kept
2) consecutive sessions, normal order                   : session 1 = 13.23s, session 2 = 13.23s
3) session 2 with a STALE stopped id (the reported bug) : captured 13.23s (was ~0 pre-fix);
                                                          finalized the NEW session = True
```

Regression tests (`tests/test_ui.py`):
- `test_stale_stopped_sid_routes_to_armed_session` — a stream carrying the stopped id after a
  Stop must feed the armed new session and return its id (never stick to the stopped one).
- `test_consecutive_sessions_capture_full_audio` — session 2 (with a stale first stream)
  captures > 80 % of the spoken duration and produces a complete transcript.
- `test_mic_session_background_worker_flow` — single-session worker flow + WAV (unchanged).

Full suite: all tests pass.

## Notes / scope
- `_ACTIVE_SID` is a module global: correct for this **single-user, one-tab-at-a-time** local
  testing tool. Concurrent recordings from two browser tabs would share it (out of scope).
- This does not touch the ASR/streaming pipeline — only the mic-tab session lifecycle in
  `ui.py`. The doc-20 fixes (gain-norm, background worker, processed-WAV playback) are intact.
- If the live symptom persists after this, the remaining suspect is RC-S2 (Gradio streaming
  Audio not re-arming after Stop) — distinguishable with the per-chunk logging proposed in
  doc 21.
