"""Lightweight whisper.cpp (default) vs faster-whisper (reference) accuracy A/B.

Decodes each clip with BOTH engines in batch mode (no streaming, so this measures
engine fidelity, not streaming policy) and reports:
  - both transcripts, side by side
  - WER between the engines (agreement; neither is treated as ground truth)
  - WER vs an optional reference transcript, when one is provided

NOTE on precision: the GGML weights are f16 (no quantization loss); faster-whisper
loads CT2 weights and quantizes to int8 at runtime. So whisper.cpp is the
*higher-precision* path here, and faster-whisper is a cross-implementation control.

Usage: .venv/bin/python scripts/ab_engines.py
"""
from __future__ import annotations

import re
import sys
import time

from vnstt.audio import decode_audio
from vnstt.engine import create_engine

GGML = "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin"
CT2 = "models/PhoWhisper-medium-ct2-fasterWhisper"

# Clips + best-effort reference text. The references are clean, unambiguous
# Vietnamese; they are NOT authoritative ground truth (the clips are scripted/
# likely-TTS), so treat reference-WER as indicative, not a benchmark result.
CLIPS = [
    (
        "tests/fixtures/multi.wav",
        "xin chào tôi tên là lan hôm nay trời rất đẹp tôi đang thử nghiệm "
        "hệ thống nhận dạng giọng nói cảm ơn bạn đã lắng nghe",
    ),
    ("tests/fixtures/sample.wav", None),  # no trusted reference
]

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def norm(text: str) -> list[str]:
    return _PUNCT.sub(" ", text.lower()).split()


def wer(ref: list[str], hyp: list[str]) -> float:
    # Levenshtein over word lists.
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev = cur
    return d[len(hyp)] / max(1, len(ref))


def transcribe(engine, path: str) -> tuple[str, float]:
    audio = decode_audio(path)
    t = time.perf_counter()
    segs = list(engine.transcribe(audio, language="vi"))
    dt = time.perf_counter() - t
    return " ".join(s.text.strip() for s in segs), dt


def main() -> int:
    print("loading engines…")
    wcpp = create_engine("whisper.cpp", model_path=GGML)
    fw = create_engine("faster-whisper", model_path=CT2, device="cpu", compute_type="int8")

    for path, ref in CLIPS:
        print(f"\n================ {path} ================")
        w_txt, w_dt = transcribe(wcpp, path)
        f_txt, f_dt = transcribe(fw, path)
        print(f"whisper.cpp  (f16, {w_dt:5.2f}s): {w_txt}")
        print(f"faster-whisp (int8,{f_dt:5.2f}s): {f_txt}")

        wn, fn = norm(w_txt), norm(f_txt)
        print(f"\n  engine-vs-engine WER (agreement): {wer(fn, wn):.1%}  "
              f"[{len(wn)} vs {len(fn)} words]")
        if ref:
            rn = norm(ref)
            print(f"  whisper.cpp  vs reference WER:    {wer(rn, wn):.1%}")
            print(f"  faster-whisper vs reference WER:  {wer(rn, fn):.1%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
