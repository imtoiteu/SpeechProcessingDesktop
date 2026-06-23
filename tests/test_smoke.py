"""Integration smoke test: decode + transcribe the VN fixture end-to-end.

Skipped automatically if the model weights are not present, so the pure tests
still run in environments without the ~1.4GB model.
"""
import os

import pytest

from vnstt.engine import create_engine
from vnstt.transcribe import transcribe_file

MODEL = "models/PhoWhisper-medium-ct2-fasterWhisper"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.wav")


GGML = "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin"


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_whisper_cpp_transcribes_vietnamese():
    engine = create_engine("whisper.cpp", model_path=GGML)
    segments = transcribe_file(FIXTURE, engine, language="vi")
    assert segments, "no segments produced"
    text = " ".join(s.text for s in segments).lower()
    assert "việt" in text
    assert all(s.start <= s.end for s in segments)


@pytest.mark.skipif(not os.path.isdir(MODEL), reason="model weights not downloaded")
def test_transcribes_vietnamese():
    engine = create_engine("faster-whisper", model_path=MODEL, device="cpu", compute_type="int8")
    segments = transcribe_file(FIXTURE, engine, language="vi")
    assert segments, "no segments produced"
    text = " ".join(s.text for s in segments).lower()
    # ground-truth sample says "...nhận dạng giọng nói tiếng việt..."
    assert "việt" in text
    # timestamps monotonic within the first segment
    words = segments[0].words
    if words:
        assert all(w.start <= w.end for w in words)
        assert words[0].start >= 0
