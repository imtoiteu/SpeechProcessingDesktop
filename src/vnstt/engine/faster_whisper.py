"""faster-whisper (CTranslate2) engine — the Phase 1 primary.

Wraps faster_whisper.WhisperModel and adapts its output to our Segment/Word types.
`condition_on_previous_text=False` suppresses the trailing-silence repetition
hallucination observed during Stage 0 validation.
"""
from __future__ import annotations

from typing import Iterator, Union

import numpy as np

from . import Segment, Word


class FasterWhisperEngine:
    def __init__(
        self,
        model_path: str,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        vad_filter: bool = True,
    ) -> None:
        from . import validate_faster_whisper_model

        model_path = validate_faster_whisper_model(model_path)
        from faster_whisper import WhisperModel

        self._model = WhisperModel(
            model_path, device=device, compute_type=compute_type, cpu_threads=cpu_threads
        )
        self._vad_filter = vad_filter

    def transcribe(
        self, audio: Union[str, np.ndarray], *, language: str = "vi"
    ) -> Iterator[Segment]:
        segments, _info = self._model.transcribe(
            audio,
            language=language,
            vad_filter=self._vad_filter,
            word_timestamps=True,
            # Anti-hallucination defaults (Stage-0 finding: Whisper fabricates
            # text on trailing silence/noise). condition_on_previous_text=False
            # stops error propagation; hallucination_silence_threshold skips
            # suspected hallucinations over silent gaps (requires word timestamps).
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
        )
        for s in segments:  # generator — yields as decoded (incremental)
            yield Segment(
                start=s.start,
                end=s.end,
                text=s.text.strip(),
                words=[Word(w.start, w.end, w.word) for w in (s.words or [])],
            )
