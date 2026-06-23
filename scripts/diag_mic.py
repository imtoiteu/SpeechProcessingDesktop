"""NON-INVASIVE microphone-pipeline diagnostic harness.

Investigation only — does NOT modify the pipeline. It subclasses StreamingTranscriber
to *observe* (never alter) every step, monkeypatches the UI to use that observer, and
drives the REAL ui.mic_start/mic_stream/mic_stop handlers with simulated browser-mic
chunks (the live browser mic can't be exercised headless, but the entire server-side
path — _to_mono16k, chunking, buffering, VAD, LocalAgreement, ASR, commit, display —
is the real code).

Outputs: per-session B-metrics, the exact processed WAV (16 kHz), a state-reset proof,
and quality/loss measurements. Run: .venv/bin/python scripts/diag_mic.py
"""
from __future__ import annotations

import time
import wave

import numpy as np

from vnstt import ui
from vnstt.audio import SAMPLE_RATE, decode_audio
from vnstt.streaming import StreamingTranscriber
from vnstt.transcribe import transcribe_file
from vnstt.engine import create_engine

GGML = "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin"
MULTI = "tests/fixtures/multi.wav"
REF = ("xin chào tôi tên là lan hôm nay trời rất đẹp tôi đang thử nghiệm hệ thống "
       "nhận dạng giọng nói cảm ơn bạn đã lắng nghe")


def wer(ref: str, hyp: str) -> float:
    r, h = ref.split(), hyp.lower().replace(".", "").split()
    d = list(range(len(h) + 1))
    for i, rr in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hh in enumerate(h, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (rr != hh))
    return d[len(h)] / max(1, len(r))


class Observer(StreamingTranscriber):
    """Records every transformation step without changing behavior."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.ev: list[tuple] = []
        self.fed: list[np.ndarray] = []   # the exact 16 kHz samples handed to feed()
        self.n_chunks = 0
        self.total_fed = 0
        self.discarded = 0
        self._n_final = 0
        self._t0 = time.time()

    def feed(self, chunk):
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        self.n_chunks += 1
        self.total_fed += chunk.size
        self.fed.append(chunk.copy())
        off0, nf0 = self._offset_s, self._n_final
        self.ev.append(("CHUNK", self.n_chunks, chunk.size, round(chunk.size / SAMPLE_RATE, 3)))
        super().feed(chunk)
        # A trim (the `not ts` 1s-tail branch) advances _offset_s WITHOUT a finalize:
        if self._n_final == nf0 and self._offset_s > off0 + 1e-9:
            disc = round((self._offset_s - off0) * SAMPLE_RATE)
            self.discarded += disc
            self.ev.append(("TRIM_DISCARD", disc, round(disc / SAMPLE_RATE, 3)))

    def _vad(self, audio):
        ts = super()._vad(audio)
        speech = sum(t["end"] - t["start"] for t in ts) / SAMPLE_RATE if ts else 0.0
        self.ev.append(("VAD", round(audio.size / SAMPLE_RATE, 2), len(ts), round(speech, 2)))
        return ts

    def _hypothesis(self):
        self.ev.append(("DECODE_ASR", round(self.buffer.size / SAMPLE_RATE, 2)))
        return super()._hypothesis()

    def _emit(self, words):
        out = super()._emit(words)
        if out:
            self.ev.append(("COMMIT", list(out)))
        return out

    def _finalize(self, *, speech_end_s):
        self._n_final += 1
        self.ev.append(("FINALIZE", round(self.buffer.size / SAMPLE_RATE, 2), list(self._utt_words)))
        super()._finalize(speech_end_s=speech_end_s)


def state_snapshot(sess) -> dict:
    st = sess.st
    return {
        "buffer_samples": int(st.buffer.size),
        "hyp.committed": list(st.hyp.committed),
        "hyp._prev": list(st.hyp._prev),
        "_since_decode": st._since_decode,
        "_offset_s": round(st._offset_s, 3),
        "_utt_words": list(st._utt_words),
        "final_words": list(st.final_words),
        "total_decode_s": round(st.total_decode_s, 3),
        "session.committed": list(sess.committed),
        "session.snapshot": sess.snapshot(),
        "session.stopped": sess.stopped,
    }


def to_chunks(audio16k: np.ndarray, sr_in: int, chunk_s: float = 0.5):
    """Yield (sr_in, chunk) browser-style chunks. If sr_in != 16k, upsample to int16."""
    if sr_in != SAMPLE_RATE:
        n = int(round(audio16k.size * sr_in / SAMPLE_RATE))
        a = np.interp(np.linspace(0, audio16k.size - 1, n), np.arange(audio16k.size), audio16k)
        a = (np.clip(a, -1, 1) * 32767).astype(np.int16)
    else:
        a = audio16k.astype(np.float32)
    step = int(chunk_s * sr_in)
    return [(sr_in, a[i:i + step]) for i in range(0, len(a), step)]


def run_session(audio16k, sr_in, *, drop=None, reorder=False, label=""):
    """Drive the REAL ui handlers (background-worker path) with an Observer
    transcriber. mic_stop drains+joins the worker, so events are complete after."""
    ui.StreamingTranscriber = Observer  # MicSession will build an Observer
    chunks = to_chunks(audio16k, sr_in)
    if reorder and len(chunks) >= 4:           # swap chunks 2 and 3 (arrive out of order)
        chunks[2], chunks[3] = chunks[3], chunks[2]
    sid, final, partial = ui.mic_start(None, "whisper.cpp", "vi")
    sess = ui._MIC_SESSIONS[sid]
    fresh = state_snapshot(sess)               # fresh state BEFORE any audio
    delivered = 0
    for i, ch in enumerate(chunks):
        if drop and i in drop:                  # simulate a transport-dropped chunk
            continue
        delivered += 1
        sid, final, partial = ui.mic_stream(ch, sid, "whisper.cpp", "vi")
    sid, final, partial, wav = ui.mic_stop(sid, "whisper.cpp", "vi")
    return sid, sess, fresh, final, partial, len(chunks), delivered


def report_session(sid, sess, final, n_chunks, delivered):
    st: Observer = sess.st
    decodes = [e for e in st.ev if e[0] == "DECODE_ASR"]
    finals = [e for e in st.ev if e[0] == "FINALIZE"]
    commits = [e for e in st.ev if e[0] == "COMMIT"]
    trims = [e for e in st.ev if e[0] == "TRIM_DISCARD"]
    n_commit_tokens = sum(len(e[1]) for e in commits)
    print(f"  session id          : {sid}")
    print(f"  recorded duration   : {st.total_fed / SAMPLE_RATE:.2f}s ({st.total_fed} samples @ {SAMPLE_RATE}Hz)")
    print(f"  chunks generated    : {n_chunks}")
    print(f"  chunks delivered    : {delivered}  (feed() calls: {st.n_chunks})")
    print(f"  chunk durations     : {sorted(set(round(e[3],3) for e in st.ev if e[0]=='CHUNK'))} s")
    print(f"  ASR decodes         : {len(decodes)}  buffer durations into ASR: {[e[1] for e in decodes]}")
    print(f"  finalize events     : {len(finals)}  buf@finalize: {[e[1] for e in finals]}")
    print(f"  committed tokens    : {n_commit_tokens}")
    print(f"  partial tokens (end): {len(sess.snapshot()[1].split()) if sess.snapshot()[1] else 0}")
    print(f"  TRIM discards (loss): {len(trims)} events, {st.discarded} samples "
          f"({st.discarded / SAMPLE_RATE:.2f}s of audio DISCARDED before ASR)")
    print(f"  final transcript    : {final}")
    print(f"  WER vs reference    : {wer(REF, final):.1%}")
    return st


def save_wav(st: Observer, path: str):
    audio = np.concatenate(st.fed) if st.fed else np.zeros(0, np.float32)
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    print(f"  processed WAV saved : {path}  ({audio.size / SAMPLE_RATE:.2f}s, {SAMPLE_RATE}Hz, mono)")


def main():
    audio = decode_audio(MULTI)
    print(f"# fixture multi.wav: {audio.size/SAMPLE_RATE:.2f}s, peak {np.abs(audio).max():.3f}\n")

    # ---- A) BATCH baseline (full-context, the 'file pipeline' the user trusts) ----
    eng = create_engine("whisper.cpp", model_path=GGML)
    batch = " ".join(s.text.strip() for s in transcribe_file(MULTI, eng)).strip()
    print("== BATCH (file pipeline) ==")
    print(f"  {batch}\n  WER vs reference: {wer(REF, batch):.1%}\n")

    # ---- B/D) Normal mic session @48kHz (browser-like) ----
    print("== MIC SESSION 1: 48kHz int16 (browser-like), no drops ==")
    sid, sess, fresh, final, partial, nc, dl = run_session(audio, 48000, label="s1")
    st1 = report_session(sid, sess, final, nc, dl)
    save_wav(st1, "/tmp/diag_mic_session1.wav")
    print()

    # ---- C) STATE RESET PROOF across consecutive sessions ----
    print("== STATE RESET: fresh-session snapshot BEFORE any audio (session 2) ==")
    sid2, sess2, fresh2, final2, partial2, nc2, dl2 = run_session(audio, 48000, label="s2")
    nonempty = {k: v for k, v in fresh2.items() if v not in ([], "", 0, 0.0, None, False, ("", ""))}
    print(f"  fresh session-2 state (only non-empty fields shown): {nonempty or 'ALL CLEAR'}")
    print(f"  engine object reused across sessions: {sess.st.engine is sess2.st.engine}")
    print(f"  session-2 final: {final2}  | WER {wer(REF, final2):.1%}\n")

    # ---- E) Quantify resampling effect: 16k-direct vs 48k-resampled ----
    print("== RESAMPLING EFFECT: same audio, 16kHz-direct vs 48kHz->16k linear ==")
    _, h16, _, f16, _, _, _ = run_session(audio, SAMPLE_RATE, label="16k")
    print(f"  16kHz-direct  final: {f16}  | WER {wer(REF, f16):.1%}")
    print(f"  48kHz-resamp  final: {final} | WER {wer(REF, final):.1%}\n")

    # ---- Failure-mode signatures ----
    print("== FAILURE SIGNATURES (what each transport fault looks like) ==")
    _, hd, _, fd, _, ncd, dld = run_session(audio, 48000, drop={2, 5}, label="drop")
    print(f"  DROPPED chunks {{2,5}} ({ncd-dld} lost): {fd}  | WER {wer(REF, fd):.1%}")
    _, hr, _, fr, _, _, _ = run_session(audio, 48000, reorder=True, label="reorder")
    print(f"  REORDERED chunks 2<->3            : {fr}  | WER {wer(REF, fr):.1%}\n")

    # ---- full event trace of session 1 (the documented step-by-step) ----
    print("== SESSION 1 FULL EVENT TRACE (every transformation) ==")
    for e in st1.ev:
        print("   ", e)


if __name__ == "__main__":
    main()
