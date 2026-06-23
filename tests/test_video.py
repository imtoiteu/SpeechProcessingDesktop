"""Phase 2: video support is the *same* pipeline (ffmpeg extracts the audio)."""
import os
import subprocess

import pytest

from vnstt.audio import SAMPLE_RATE, AudioDecodeError, decode_audio
from vnstt.engine import create_engine
from vnstt.transcribe import transcribe_file

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
GGML = "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin"


@pytest.mark.parametrize("ext", ["mp4", "mov", "mkv"])
def test_decode_video_extracts_audio(ext):
    audio = decode_audio(os.path.join(FIX, f"sample.{ext}"))
    assert audio.ndim == 1 and audio.size > 0
    assert 9.0 < audio.size / SAMPLE_RATE < 11.0  # ~10s clip


def test_no_audio_track_raises(tmp_path):
    vid = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "color=c=black:s=160x120:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(vid)],
        check=True,
    )
    with pytest.raises(AudioDecodeError):
        decode_audio(str(vid))


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_transcribe_video_end_to_end():
    engine = create_engine("whisper.cpp", model_path=GGML)
    segs = transcribe_file(os.path.join(FIX, "sample.mp4"), engine, language="vi")
    assert segs
    assert "việt" in " ".join(s.text for s in segs).lower()
    # timestamps clamped to the real ~10s duration, not the 30s decode window
    assert max(s.end for s in segs) <= 11.0
