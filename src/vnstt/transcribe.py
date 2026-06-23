"""Transcription orchestrator: decode -> engine -> Segment stream.

Keeps the streaming nature of the engine: segments are surfaced via `on_segment`
as they are decoded, while also being collected and returned.
"""
from __future__ import annotations

from typing import Callable, Optional

from .audio import SAMPLE_RATE, decode_audio
from .engine import ASREngine, Segment, Word

# Whisper fabricates text on trailing silence/noise (Stage-0 + Phase-1 finding).
# Such segments share a physical impossibility: far more characters than the
# segment's duration could contain (e.g. 47 chars in 0.08s ≈ 590 chars/s, vs
# ~13 chars/s for real Vietnamese speech). This is an engine-agnostic guard.
_MAX_CHARS_PER_SEC = 30.0
_MIN_TEXT_LEN_TO_JUDGE = 15  # don't penalize short legit utterances ("Vâng.")


def is_likely_hallucination(seg: Segment) -> bool:
    text = seg.text.strip()
    if not text:
        return True
    dur = seg.end - seg.start
    if dur <= 0:
        return True  # nonzero text in ~zero time
    if len(text) <= _MIN_TEXT_LEN_TO_JUDGE:
        return False
    return (len(text) / dur) > _MAX_CHARS_PER_SEC


def _clamp_to_duration(seg: Segment, duration: float) -> Segment:
    """Clamp segment/word times to [0, duration].

    Some engines (whisper.cpp) inflate a short segment's end to the 30s decode
    window; clamping keeps SRT/VTT cues sane.
    """
    start = min(max(seg.start, 0.0), duration)
    end = min(max(seg.end, start), duration)
    words = [
        Word(min(max(w.start, 0.0), duration), min(max(w.end, 0.0), duration), w.text)
        for w in seg.words
    ]
    return Segment(start=start, end=end, text=seg.text, words=words)


def transcribe_file(
    path: str,
    engine: ASREngine,
    *,
    language: str = "vi",
    drop_hallucinations: bool = True,
    on_segment: Optional[Callable[[Segment], None]] = None,
) -> list[Segment]:
    """Decode `path` (audio or video) and transcribe it, emitting each kept Segment."""
    audio = decode_audio(path)
    duration = len(audio) / SAMPLE_RATE
    collected: list[Segment] = []
    for seg in engine.transcribe(audio, language=language):
        seg = _clamp_to_duration(seg, duration)
        if drop_hallucinations and is_likely_hallucination(seg):
            continue
        collected.append(seg)
        if on_segment is not None:
            on_segment(seg)
    return collected
