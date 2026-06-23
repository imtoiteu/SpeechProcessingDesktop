"""ASR engine abstraction.

Everything downstream (orchestrator, exporters, CLI) depends only on `ASREngine`
and `Segment`/`Word`. Swapping faster-whisper for whisper.cpp later is a new class,
not a rewrite.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Protocol, Union, runtime_checkable

import numpy as np


class ModelLoadError(RuntimeError):
    """An ASR model could not be located or loaded.

    Raised BEFORE a bad path reaches a native backend. pywhispercpp resolves an
    unknown model name/path to ``None`` and then segfaults when that NULL context
    is first used; we validate up front and raise this catchable error instead.
    """


def validate_whispercpp_model_path(model_path: str) -> str:
    """Validate a whisper.cpp model arg, returning a value safe to hand pywhispercpp.

    Returns the absolute path of an existing GGML file, or a bare known model name
    (which pywhispercpp can download safely). Raises ``ModelLoadError`` for anything
    else — never returns ``None`` — so a NULL model can never reach the native layer.
    """
    if not model_path or not isinstance(model_path, str):
        raise ModelLoadError(f"whisper.cpp model path must be a non-empty string, got {model_path!r}")
    p = Path(model_path)
    if p.is_file():
        return str(p.resolve())
    try:
        from pywhispercpp.constants import AVAILABLE_MODELS
    except Exception:
        AVAILABLE_MODELS = ()
    looks_like_path = (os.sep in model_path) or ("/" in model_path) or model_path.endswith(".bin")
    if not looks_like_path and model_path in AVAILABLE_MODELS:
        return model_path  # a known model name — pywhispercpp will fetch it safely
    known = ", ".join(sorted(AVAILABLE_MODELS)[:6])
    raise ModelLoadError(
        f"whisper.cpp model not found: {model_path!r}\n"
        f"  current dir: {os.getcwd()}\n"
        f"  Provide an existing GGML .bin file (an absolute path is safest) via "
        f"--model, or a known model name ({known}, …).\n"
        f"  (An invalid path makes pywhispercpp load a NULL model and segfault on "
        f"first use, so loading is stopped here.)"
    )


def validate_faster_whisper_model(model_path: str) -> str:
    """Validate a faster-whisper model arg (a CT2 directory or a Hugging Face id)."""
    if not model_path or not isinstance(model_path, str):
        raise ModelLoadError(f"faster-whisper model must be a non-empty string, got {model_path!r}")
    p = Path(model_path)
    if p.exists():
        return str(p.resolve())
    looks_like_path = (os.sep in model_path) or model_path.startswith(".")
    if looks_like_path:
        raise ModelLoadError(
            f"faster-whisper model not found: {model_path!r}\n"
            f"  current dir: {os.getcwd()}\n"
            f"  Provide an existing CT2 model directory via --model, or a Hugging Face id."
        )
    return model_path  # a bare HF id — faster-whisper will fetch it


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)


@runtime_checkable
class ASREngine(Protocol):
    def transcribe(
        self, audio: Union[str, np.ndarray], *, language: str = "vi"
    ) -> Iterator[Segment]:
        """Yield transcript Segments. May be a generator (incremental)."""
        ...


def create_engine(name: str = "whisper.cpp", **kwargs) -> ASREngine:
    """Factory for ASR engines.

    - "whisper.cpp": Metal/CoreML fast path on Apple Silicon (GGML weights).
    - "faster-whisper": CTranslate2 path (CPU on macOS), CT2 weights.
    """
    if name in ("whisper.cpp", "whisper-cpp", "whispercpp"):
        from .whisper_cpp import WhisperCppEngine

        return WhisperCppEngine(**kwargs)
    if name == "faster-whisper":
        from .faster_whisper import FasterWhisperEngine

        return FasterWhisperEngine(**kwargs)
    raise ValueError(f"unknown engine: {name!r}")
