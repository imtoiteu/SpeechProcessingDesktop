"""UI glue tests — no server launch, no real mic. gradio-gated."""
import os

import numpy as np
import pytest

pytest.importorskip("gradio", reason="UI extra not installed ([ui])")

from vnstt import ui  # noqa: E402
from vnstt.audio import SAMPLE_RATE  # noqa: E402

GGML = "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin"
FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def test_resampler_to_16k_mono_from_48k_int16():
    # 1s 440Hz tone at 48k stereo int16 -> 16k mono float32 in [-1, 1].
    t = np.linspace(0, 1, 48000, endpoint=False)
    tone = (np.sin(2 * np.pi * 440 * t) * 30000).astype(np.int16)
    stereo = np.stack([tone, tone], axis=1)
    out = ui._to_mono16k(stereo, 48000)
    assert out.dtype == np.float32
    assert out.ndim == 1
    assert abs(out.size - SAMPLE_RATE) <= 2          # ~16000 samples
    assert 0.5 < np.abs(out).max() <= 1.0            # amplitude preserved, normalized


def test_build_ui_constructs():
    # Exercises every event binding (click/stream/start_recording/stop_recording).
    demo = ui.build_ui()
    assert demo is not None


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_empty_chunk_is_safe():
    sid, final, partial = ui.mic_stream(None, None, "whisper.cpp", "vi")
    assert (final, partial) == ("", "")
    ui.mic_clear(sid)  # stop the worker thread


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_transcribe_upload_audio_returns_text_and_three_downloads():
    text, ftxt, fsrt, fvtt = ui.transcribe_upload(
        os.path.join(FIX, "sample.wav"), "whisper.cpp", "vi"
    )
    assert "việt" in text.lower()
    for p in (ftxt, fsrt, fvtt):
        assert p and os.path.isfile(p)
    assert ftxt.endswith(".txt") and fsrt.endswith(".srt") and fvtt.endswith(".vtt")


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_transcribe_upload_video_uses_same_pipeline():
    text, *_ = ui.transcribe_upload(os.path.join(FIX, "sample.mp4"), "whisper.cpp", "vi")
    assert text.strip() and text != "(no speech detected)"


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_mic_session_background_worker_flow(tmp_path):
    # Full mic session through the background-worker path: stop drains the queue and
    # flushes a COMPLETE final, saves the processed WAV, and a post-stop chunk neither
    # blanks nor mutates the final (RC-2/RC-3/symptom-6).
    from vnstt.audio import decode_audio

    y = decode_audio(os.path.join(FIX, "multi.wav"))
    step = int(0.5 * SAMPLE_RATE)
    sid, _, _ = ui.mic_start(None, "whisper.cpp", "vi")
    for i in range(0, y.size, step):
        sid, _final, _partial = ui.mic_stream((SAMPLE_RATE, y[i : i + step]), sid, "whisper.cpp", "vi")
    # stop() joins the worker after draining, so the final must be complete here.
    sid, final_stop, partial_stop, wav = ui.mic_stop(sid, "whisper.cpp", "vi")
    assert "xin" in final_stop.lower().split()      # onset preserved end-to-end
    assert "nghe." in final_stop.lower() or "nghe" in final_stop.lower()  # last word survived
    assert partial_stop == ""
    assert wav and os.path.isfile(wav)              # processed audio captured (symptom 6)

    sid, final_stray, _ = ui.mic_stream((SAMPLE_RATE, y[:step]), sid, "whisper.cpp", "vi")
    assert final_stray == final_stop                # trailing chunk must not change the final


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_mic_start_reuses_racing_session_no_onset_loss():
    # RC-3: a stream chunk that arrives before start_recording opens session A; the
    # subsequent mic_start must REUSE A (not orphan it), so the first chunk survives.
    sidA, _, _ = ui.mic_stream(None, None, "whisper.cpp", "vi")   # stream raced ahead
    sidB, _, _ = ui.mic_start(sidA, "whisper.cpp", "vi")          # Record pressed after
    assert sidB == sidA                                          # same session reused
    ui.mic_clear(sidB)
