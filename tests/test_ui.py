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


@pytest.fixture(autouse=True)
def _reset_mic_state():
    # Finish any worker a test left open so threads don't leak between tests.
    yield
    for s in list(ui._MIC_SESSIONS.values()):
        if not s.stopped:
            try:
                s.finish()
            except Exception:
                pass
    ui._MIC_SESSIONS.clear()


def test_empty_chunk_is_safe():
    # No session id + no chunk -> no capture, no crash, no model load.
    sid, final, partial = ui.mic_stream(None, None, "whisper.cpp", "vi")
    assert (final, partial) == ("", "")


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
def test_mic_start_reuses_racing_session_no_onset_loss(tmp_path):
    # doc-20 RC-3 baseline: a stream chunk that arrives BEFORE start_recording lazily
    # opens a session; mic_start must then REUSE that same session (same id), so the
    # onset chunk is not orphaned by a second, replacement session.
    from vnstt.audio import decode_audio

    y = decode_audio(os.path.join(FIX, "multi.wav"))
    chunk = (SAMPLE_RATE, y[: int(0.5 * SAMPLE_RATE)])
    sid_race, _, _ = ui.mic_stream(chunk, None, "whisper.cpp", "vi")   # stream first (race)
    assert sid_race is not None
    sid_start, _, _ = ui.mic_start(sid_race, "whisper.cpp", "vi")      # Record after
    assert sid_start == sid_race                                       # reused, not replaced
    ui._MIC_SESSIONS[sid_race]._q.join()
    assert sum(a.size for a in ui._MIC_SESSIONS[sid_race]._audio) > 0  # onset chunk kept


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_consecutive_sessions_normal_order_capture_full_audio(tmp_path):
    # Baseline sanity (doc 21 finding #2): in strict start->stream->stop order, two
    # back-to-back sessions each capture the full audio. (The reported real-world
    # failure occurs only under the event RACE that this serial harness cannot create —
    # which is exactly why we now instrument for live browser logs, see doc 23.)
    from vnstt.audio import decode_audio

    y = decode_audio(os.path.join(FIX, "multi.wav"))
    step = int(0.5 * SAMPLE_RATE)
    chunks = [(SAMPLE_RATE, y[i : i + step]) for i in range(0, y.size, step)]
    full_s = y.size / SAMPLE_RATE

    def run_session(prev_sid):
        sid, _, _ = ui.mic_start(prev_sid, "whisper.cpp", "vi")
        for c in chunks:
            sid, _, _ = ui.mic_stream(c, sid, "whisper.cpp", "vi")
        sid, final, _, _ = ui.mic_stop(sid, "whisper.cpp", "vi")
        ui._MIC_SESSIONS[sid]._q.join()
        captured = sum(a.size for a in ui._MIC_SESSIONS[sid]._audio) / SAMPLE_RATE
        return sid, final, captured

    sid1, final1, cap1 = run_session(None)
    sid2, final2, cap2 = run_session(sid1)
    assert sid2 != sid1
    assert "xin" in final1.lower().split() and "xin" in final2.lower().split()
    assert cap1 > 0.8 * full_s and cap2 > 0.8 * full_s
