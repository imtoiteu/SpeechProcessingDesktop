"""Audio decoding via ffmpeg.

Decodes any ffmpeg-readable audio (and, for free, video) file to mono float32 PCM
at 16 kHz. Using the ffmpeg binary directly keeps us dependency-light and means
video audio-extraction (Phase 2) is the same code path.
"""
from __future__ import annotations

import shutil
import subprocess

import numpy as np

SAMPLE_RATE = 16000


class AudioDecodeError(RuntimeError):
    """Raised when a file cannot be decoded to usable audio."""


def decode_audio(path: str, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode `path` to a mono float32 numpy array in [-1, 1] at `sample_rate`.

    Raises AudioDecodeError on missing ffmpeg, decode failure, or no audio stream.
    """
    if shutil.which("ffmpeg") is None:
        raise AudioDecodeError("ffmpeg not found on PATH")

    cmd = [
        "ffmpeg", "-nostdin", "-threads", "0",
        "-i", path,
        "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le",
        "-ar", str(sample_rate), "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        msg = proc.stderr.decode("utf-8", "ignore").strip().splitlines()
        tail = msg[-1] if msg else "unknown ffmpeg error"
        raise AudioDecodeError(f"ffmpeg failed to decode {path!r}: {tail}")

    audio = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size == 0:
        raise AudioDecodeError(f"no audio decoded from {path!r} (no audio stream?)")
    return audio
