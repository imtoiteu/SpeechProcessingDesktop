"""Audio + misc helpers for the TTS subsystem.

Generic, engine-agnostic helpers. Heavy/optional imports (``soundfile``,
``numpy``) are done lazily inside the functions so that :mod:`tts.config`,
:mod:`tts.models` and the FastAPI app in :mod:`tts.server` remain importable in
environments without the VieNeu runtime (e.g. the STT venv running smoke tests).

The primary audio encoder used by the service is
:meth:`tts.service.TtsService._encode_audio` (soundfile for wav/flac/ogg,
pydub+ffmpeg for mp3/opus); :func:`encode_audio` here is a libsndfile-only
fallback kept for reuse/testing.
"""

from __future__ import annotations

import io
import re
import unicodedata

# Output formats we expose -> (libsndfile format, subtype, mime type).
# WAV and FLAC are always available with libsndfile; MP3/OGG-OPUS require a
# recent libsndfile (>=1.1) and are best-effort.
_FORMATS = {
    "wav": ("WAV", "PCM_16", "audio/wav"),
    "flac": ("FLAC", None, "audio/flac"),
    "mp3": ("MP3", None, "audio/mpeg"),
    "opus": ("OGG", "OPUS", "audio/ogg"),
    "ogg": ("OGG", "VORBIS", "audio/ogg"),
}

SUPPORTED_FORMATS = tuple(_FORMATS.keys())


def mime_for(fmt: str) -> str:
    fmt = fmt.lower()
    if fmt not in _FORMATS:
        raise ValueError(f"Unsupported audio format: {fmt!r}")
    return _FORMATS[fmt][2]


def encode_audio(samples, sample_rate: int, fmt: str = "wav") -> bytes:
    """Encode a mono float32 numpy waveform to container bytes.

    Parameters
    ----------
    samples : np.ndarray
        1-D float32 array in [-1, 1] (Fish-Speech's native output).
    sample_rate : int
        Sample rate in Hz (Fish-Speech S2-Pro produces 44100).
    fmt : str
        One of :data:`SUPPORTED_FORMATS`.
    """
    import numpy as np
    import soundfile as sf

    fmt = fmt.lower()
    if fmt not in _FORMATS:
        raise ValueError(f"Unsupported audio format: {fmt!r}")
    sf_format, subtype, _mime = _FORMATS[fmt]

    audio = np.asarray(samples, dtype=np.float32)
    audio = np.squeeze(audio)
    if audio.ndim > 1:
        # Collapse any accidental channel dim to mono.
        audio = audio.reshape(audio.shape[0], -1).mean(axis=1)

    buffer = io.BytesIO()
    write_kwargs = {"format": sf_format}
    if subtype is not None:
        write_kwargs["subtype"] = subtype
    try:
        sf.write(buffer, audio, sample_rate, **write_kwargs)
    except Exception as exc:  # pragma: no cover - depends on libsndfile build
        raise RuntimeError(
            f"Failed to encode audio as {fmt!r} (libsndfile may lack support for "
            f"this format): {exc}"
        ) from exc
    buffer.seek(0)
    return buffer.read()


def slugify(value: str, *, fallback: str = "voice") -> str:
    """Filesystem-safe slug for voice preset ids."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = value.replace("'", "")  # drop apostrophes rather than split words on them
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-._").lower()
    return value or fallback


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
