"""End-to-end generation test (VieNeu-TTS).

Skips unless the VieNeu runtime is importable (run in VieNeu-TTS/.venv). This
actually runs synthesis with a built-in preset voice, so it is marked slow.
"""

import importlib.util

import pytest

requires_vieneu = pytest.mark.skipif(
    importlib.util.find_spec("vieneu") is None,
    reason="vieneu runtime not importable (run in VieNeu-TTS/.venv)",
)


@requires_vieneu
@pytest.mark.slow
def test_synthesize_wav_default_voice(tmp_config):
    from tts.service import TtsService

    svc = TtsService(tmp_config)
    data, mime, sample_rate = svc.synthesize(
        text="Xin chào, đây là bài kiểm tra giọng nói.",
        fmt="wav",
    )
    assert mime == "audio/wav"
    assert data[:4] == b"RIFF"
    assert len(data) > 2000
    assert sample_rate > 0


@requires_vieneu
@pytest.mark.slow
def test_stream_yields_wav(tmp_config):
    """Streaming yields a WAV header followed by PCM chunks."""
    from tts.service import TtsService

    svc = TtsService(tmp_config)
    chunks = list(svc.stream(text="Xin chào.", voice=None))
    assert chunks and chunks[0][:4] == b"RIFF"
    total = sum(len(c) for c in chunks)
    assert total > 44 + 1000  # header + real audio


def test_synthesize_empty_text_rejected(tmp_config):
    """Empty-text validation happens before any model work, so this runs anywhere."""
    from tts.service import TtsService

    svc = TtsService(tmp_config)
    with pytest.raises(ValueError):
        svc.synthesize(text="   ", fmt="wav")
