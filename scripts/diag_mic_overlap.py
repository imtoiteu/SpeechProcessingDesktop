"""Reproduce the FINALIZE/START OVERLAP hypothesis (doc 23) with real threads.

The user's simpler explanation: can session 2 start before session 1 has fully
finalized and cleaned up? Gradio 5.50 schedules `mic_stop`, `mic_start` and
`mic_stream` on INDEPENDENT per-function concurrency queues (verified from
gradio/queueing.py), so session 1's blocking `mic_stop -> MicSession.finish()`
(drain + worker.join) can run CONCURRENTLY with session 2's `mic_start`/`mic_stream`.

Crucial detail in the code: `MicSession.stopped` flips to True only AFTER the worker
join completes. So DURING finalization the previous session looks "not stopped", and
`mic_start`/`mic_stream` (routing by the per-event m_state id, which is still the old
sid because mic_stop has not returned yet) REUSE / feed the session that is being torn
down. Chunks enqueued after the worker's None-sentinel are never processed -> session 2
loses its audio. This matches "saved audio only ~1-2s" and "reload fixes it".

This harness forces the overlap deterministically by holding `_MODEL_LOCK` so session
1's worker is stuck mid-decode while session 2 starts. It uses the REAL ui handlers and
real threads. It is NOT a browser; browser logs (VNSTT_MIC_DEBUG=1) remain the
confirmation that this is the path actually hit in production.

Run: .venv/bin/python scripts/diag_mic_overlap.py
"""
import threading
import time

from vnstt import ui
from vnstt.audio import decode_audio, SAMPLE_RATE

AUDIO = decode_audio("tests/fixtures/multi.wav")
STEP = int(0.5 * SAMPLE_RATE)
CHUNKS = [(SAMPLE_RATE, AUDIO[i:i + STEP]) for i in range(0, AUDIO.size, STEP)]


def reset():
    for s in list(ui._MIC_SESSIONS.values()):
        try:
            s.finish()
        except Exception:
            pass
    ui._MIC_SESSIONS.clear()


def captured_s(sid):
    sess = ui._MIC_SESSIONS.get(sid)
    if sess is None:
        return 0.0
    with sess._lock:
        return sum(a.size for a in sess._audio) / SAMPLE_RATE


print(f"# multi.wav: {AUDIO.size / SAMPLE_RATE:.2f}s spoken; {len(CHUNKS)} chunks\n")

# ---------------------------------------------------------------------------
# A) BASELINE (serial, what the synthetic harness and the browser-with-reload do):
#    fully stop session 1, THEN start session 2.  -> both fine.
# ---------------------------------------------------------------------------
print("== A) serial: stop session 1 fully, then start session 2 ==")
reset()
sidA, _, _ = ui.mic_start(None, "whisper.cpp", "vi")
for c in CHUNKS:
    ui.mic_stream(c, sidA, "whisper.cpp", "vi")
ui.mic_stop(sidA, "whisper.cpp", "vi")               # blocks until fully finalized
sidB, _, _ = ui.mic_start(sidA, "whisper.cpp", "vi")  # sidA now really stopped -> new B
for c in CHUNKS:
    ui.mic_stream(c, sidB, "whisper.cpp", "vi")
ui._MIC_SESSIONS[sidB]._q.join()
print(f"   session 1 = {captured_s(sidA):.2f}s   session 2(new {sidB[:6]}) = {captured_s(sidB):.2f}s")
print(f"   distinct sessions: {sidA != sidB}\n")

# ---------------------------------------------------------------------------
# B) OVERLAP (real browser timing): user clicks Record again while session 1's
#    mic_stop -> finish() is still draining.  m_state is still sidA (mic_stop has
#    not returned).  We force the drain to hang by holding _MODEL_LOCK so the
#    session-1 worker is stuck, exactly like a slow/thermal-throttled decode.
# ---------------------------------------------------------------------------
print("== B) overlap: Record (session 2) fires while session 1 is still finalizing ==")
reset()
sidA, _, _ = ui.mic_start(None, "whisper.cpp", "vi")
# Pin session 1's worker so its queue cannot drain: every feed needs _MODEL_LOCK,
# which we hold. This stands in for a slow / thermally-throttled decode where finish()
# has a real backlog to drain and its worker.join() blocks for seconds.
ui._MODEL_LOCK.acquire()
for c in CHUNKS:
    ui.mic_stream(c, sidA, "whisper.cpp", "vi")       # all queue up, unprocessed

stop_done = threading.Event()

def do_stop():
    ui.mic_stop(sidA, "whisper.cpp", "vi")            # finish(): put(None) sentinel, join() -> blocks
    stop_done.set()

t = threading.Thread(target=do_stop, name="gradio-stop")
t.start()
time.sleep(0.3)                                       # let the stop thread reach join()

a_stopped_during = ui._MIC_SESSIONS[sidA].stopped     # <-- the bug: still False mid-finalize
sidB, _, _ = ui.mic_start(sidA, "whisper.cpp", "vi")  # Record again: m_state is still sidA
for c in CHUNKS:                                      # session 2 audio streams in (after the sentinel)
    ui.mic_stream(c, sidB, "whisper.cpp", "vi")
streamed2 = len(CHUNKS) * STEP / SAMPLE_RATE

ui._MODEL_LOCK.release()                              # let session 1 finish draining
stop_done.wait(timeout=60)
t.join(timeout=60)

# Session 2's chunks were enqueued AFTER session 1's None-sentinel, so the worker
# exits before reaching them: they are stranded in the now-dead session's queue.
stranded = ui._MIC_SESSIONS[sidA]._q.qsize()
stranded_s = stranded * STEP / SAMPLE_RATE
print(f"   session 1 .stopped DURING session-2 start : {a_stopped_during}   (False = window open)")
print(f"   session 2 got its OWN session             : {sidB != sidA}   (False = reused the dying one)")
print(f"   session 2 streamed                        : {streamed2:.2f}s ({len(CHUNKS)} chunks)")
print(f"   session 2 STRANDED unprocessed in dead q   : {stranded_s:.2f}s ({stranded} chunks)")
reused = (sidB == sidA)
lost = stranded >= 0.8 * len(CHUNKS)
verdict = "REPRODUCED — session 2 reused the finalizing session and lost its audio" \
    if (reused and lost) else "not reproduced under this timing"
print(f"   -> {verdict}\n")

reset()
print("Note: browser logs (VNSTT_MIC_DEBUG=1) are the confirmation; see doc 23.")
