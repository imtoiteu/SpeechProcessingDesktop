"""whisper.cpp (Metal/CoreML) engine via pywhispercpp — the Apple-Silicon fast path.

Stage-0/Phase-1 finding: on M3, this runs PhoWhisper-medium-sized models at RTF ~0.16
(GPU/Metal) vs RTF 2.3-6.9 for faster-whisper on CPU. Needs GGML weights (e.g.
`dongxiat/ggml-PhoWhisper-medium`). Accuracy vs the CT2 path is still to be confirmed
in Stage-1 benchmarking. Word timestamps are not emitted here (segment-level only).
"""
from __future__ import annotations

from typing import Iterator, Union

import numpy as np

from . import Segment


class WhisperCppEngine:
    def __init__(
        self, model_path: str, n_threads: int = 4, dynamic_audio_ctx: bool = False
    ) -> None:
        from . import validate_whispercpp_model_path

        # Validate BEFORE importing/constructing pywhispercpp: an unknown path makes
        # it load a NULL model and segfault on first use (uncatchable). Fail loud here.
        model_path = validate_whispercpp_model_path(model_path)
        from pywhispercpp.model import Model

        self._model = Model(
            model_path,
            n_threads=n_threads,
            print_progress=False,
            print_realtime=False,
            redirect_whispercpp_logs_to=False,  # silence verbose Metal init logs
        )
        # whisper.cpp pads every decode to its 30s window; for streaming, sizing the
        # encoder context to the actual buffer length (`audio_ctx`) cuts per-call cost
        # ~proportionally — the difference between RTF>1 and real-time.
        self._dynamic_audio_ctx = dynamic_audio_ctx

    def transcribe(
        self, audio: Union[str, np.ndarray], *, language: str = "vi"
    ) -> Iterator[Segment]:
        params: dict = {"language": language}
        if self._dynamic_audio_ctx and isinstance(audio, np.ndarray):
            secs = len(audio) / 16000
            params["audio_ctx"] = min(1500, max(256, int(secs * 50) + 64))
        # pywhispercpp accepts a file path or a float32 16 kHz numpy array.
        # Its segment timestamps (t0/t1) are in centiseconds.
        for s in self._model.transcribe(audio, **params):
            yield Segment(
                start=s.t0 / 100.0,
                end=s.t1 / 100.0,
                text=s.text.strip(),
                words=[],  # word-level timestamps not surfaced by this engine yet
            )
