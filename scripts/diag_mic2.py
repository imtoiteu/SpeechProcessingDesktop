"""Adverse-condition probes for the mic pipeline (real-mic-like inputs + timing).

Tests the three things clean synthetic file-simulation can't show:
  1. VAD behaviour on noisy / low-gain audio -> the `not ts` 1s-tail TRIM that
     silently DISCARDS buffered audio before ASR (candidate for dropped words).
  2. Real-time budget: wall-clock to process each 0.5s chunk vs the 0.5s
     stream_every cadence -> whether Gradio would have to drop/coalesce chunks.
  3. The start_recording / stream race -> first-chunk (onset) loss.

Run: .venv/bin/python scripts/diag_mic2.py
"""
import sys
import time

import numpy as np

sys.path.insert(0, "scripts")
from diag_mic import Observer, REF, to_chunks, wer  # noqa: E402

from vnstt import ui  # noqa: E402
from vnstt.audio import SAMPLE_RATE, decode_audio  # noqa: E402

AUDIO = decode_audio("tests/fixtures/multi.wav")


def drive(audio16k, sr_in, label):
    ui.StreamingTranscriber = Observer
    chunks = to_chunks(audio16k, sr_in)
    sid, *_ = ui.mic_start(None, "whisper.cpp", "vi")
    per_chunk_ms = []
    for ch in chunks:
        t = time.perf_counter()
        sid, final, partial = ui.mic_stream(ch, sid, "whisper.cpp", "vi")
        per_chunk_ms.append((time.perf_counter() - t) * 1000)
    sid, final, partial, wav = ui.mic_stop(sid, "whisper.cpp", "vi")
    st: Observer = ui._MIC_SESSIONS[sid].st
    vad_speech = [e[3] for e in st.ev if e[0] == "VAD"]
    detected_any = sum(1 for e in st.ev if e[0] == "VAD" and e[2] > 0)
    n_vad = sum(1 for e in st.ev if e[0] == "VAD")
    return dict(
        label=label, final=final, wer=wer(REF, final),
        discarded_s=st.discarded / SAMPLE_RATE,
        vad_hit_rate=f"{detected_any}/{n_vad}",
        peak=float(np.abs(np.concatenate(st.fed)).max()),
        per_chunk_ms=per_chunk_ms,
    )


def main():
    print(f"# multi.wav: {AUDIO.size/SAMPLE_RATE:.2f}s peak {np.abs(AUDIO).max():.3f}\n")

    # ---- 1) acoustic conditions: clean vs low-gain vs noisy+low-gain ----
    rng = np.random.default_rng(0)
    noisy = np.clip(AUDIO * 0.35 + rng.normal(0, 0.01, AUDIO.size).astype(np.float32), -1, 1)
    cases = [
        ("clean 48k", AUDIO, 48000),
        ("low-gain 0.30x 48k", AUDIO * 0.30, 48000),
        ("noisy+low-gain 48k", noisy, 48000),
    ]
    print("== ACOUSTIC CONDITIONS (VAD trim-loss + accuracy) ==")
    for label, aud, sr in cases:
        r = drive(aud, sr, label)
        print(f"  {label:22s} peak={r['peak']:.3f} VADhit={r['vad_hit_rate']:>6s} "
              f"discarded={r['discarded_s']:.2f}s WER={r['wer']:.0%}")
        print(f"     -> {r['final']}")
    print()

    # ---- 2) real-time budget: per-chunk processing time vs 0.5s cadence ----
    print("== REAL-TIME BUDGET (process time per 0.5s chunk; >500ms => Gradio must drop/coalesce) ==")
    r = drive(AUDIO, 48000, "clean")
    ms = r["per_chunk_ms"]
    over = [i for i, m in enumerate(ms, 1) if m > 500]
    print(f"  STREAM-HANDLER times (ms): {[round(m) for m in ms]}")
    print(f"  max={max(ms):.0f}ms  mean={sum(ms)/len(ms):.0f}ms  chunks over 500ms budget: {len(over)} -> {over}")
    print(f"  (post-RC-2: handler only ENQUEUES; the background worker runs the slow ASR)\n")

    # ---- 3) start/stream race: first chunk arrives before mic_start (RC-3 fixed) ----
    print("== START/STREAM RACE (first chunk before Record; mic_start must REUSE it) ==")
    ui.StreamingTranscriber = Observer
    chunks = to_chunks(AUDIO, 48000)
    sidA, _, _ = ui.mic_stream(chunks[0], None, "whisper.cpp", "vi")  # stream races ahead -> session A
    sidB, _, _ = ui.mic_start(sidA, "whisper.cpp", "vi")              # Record pressed -> must reuse A
    for ch in chunks[1:]:
        sidB, f, p = ui.mic_stream(ch, sidB, "whisper.cpp", "vi")
    sidB, f, p, wav = ui.mic_stop(sidB, "whisper.cpp", "vi")
    print(f"  session reused (no orphan): {sidA == sidB}")
    print(f"  race final: {f}  | WER {wer(REF, f):.0%}")
    print(f"  normal final: {r['final']}  | WER {r['wer']:.0%}")


if __name__ == "__main__":
    main()
