"""Unit tests for the batch-backend abstraction (no model load, no subprocess).

Covers the pure logic: ChunkFormer timestamp parsing, JSON->segments normalization,
response rendering for every format, and backend routing. The module is loaded directly
from its file so these tests don't pull in torch / the whole whisperlivekit package.
"""

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("fastapi")  # batch_backends imports fastapi.HTTPException at module load

_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "WhisperLiveKit" / "whisperlivekit" / "batch_backends.py"
)
_spec = importlib.util.spec_from_file_location("batch_backends_under_test", _MODULE_PATH)
bb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bb)


# --- ChunkFormer timestamp parsing -----------------------------------------

def test_parse_chunkformer_ts_basic():
    assert bb._parse_chunkformer_ts("00:00:04:080") == pytest.approx(4.08)
    assert bb._parse_chunkformer_ts("01:02:03:500") == pytest.approx(3723.5)
    assert bb._parse_chunkformer_ts("00:00:00:000") == pytest.approx(0.0)


def test_parse_chunkformer_ts_tolerates_whisper_shape():
    # 'H:MM:SS.cc' (colon-free ms) should still parse via the fallback.
    assert bb._parse_chunkformer_ts("0:00:05.50") == pytest.approx(5.5)


# --- JSON -> normalized segments -------------------------------------------

def test_json_to_segments_filters_empty_and_parses():
    data = [
        {"decode": "xin chào", "start": "00:00:00:000", "end": "00:00:00:880"},
        {"decode": "  ", "start": "00:00:00:880", "end": "00:00:01:000"},  # dropped (empty)
        {"decode": "hà nội", "start": "00:00:01:000", "end": "00:00:04:000"},
    ]
    segs = bb.chunkformer_json_to_segments(data)
    assert len(segs) == 2
    assert segs[0] == {"start": pytest.approx(0.0), "end": pytest.approx(0.88), "text": "xin chào"}
    assert segs[1]["text"] == "hà nội"
    assert segs[1]["end"] == pytest.approx(4.0)


def test_json_to_segments_plain_string():
    assert bb.chunkformer_json_to_segments("hello") == [
        {"start": 0.0, "end": 0.0, "text": "hello"}
    ]
    assert bb.chunkformer_json_to_segments("   ") == []


# --- render_segments: every response_format --------------------------------

SEGMENTS = [
    {"start": 0.0, "end": 0.88, "text": "xin chào"},
    {"start": 1.0, "end": 4.0, "text": "hà nội"},
]


def test_render_text():
    out = bb.render_segments(SEGMENTS, "text", "vi", 4.0)
    assert out == "xin chào hà nội"


def test_render_json_default():
    out = bb.render_segments(SEGMENTS, "json", "vi", 4.0)
    assert out == {"text": "xin chào hà nội"}


def test_render_verbose_json():
    out = bb.render_segments(SEGMENTS, "verbose_json", "vi", 4.0)
    assert out["task"] == "transcribe"
    assert out["language"] == "vi"
    assert out["duration"] == pytest.approx(4.0)
    assert out["text"] == "xin chào hà nội"
    assert [s["text"] for s in out["segments"]] == ["xin chào", "hà nội"]
    assert out["segments"][0]["id"] == 0 and out["segments"][1]["id"] == 1
    assert out["segments"][0]["start"] == pytest.approx(0.0)
    assert out["segments"][1]["end"] == pytest.approx(4.0)
    # words are estimated by splitting text
    assert any(w["word"] == "chào" for w in out["words"])


def test_render_srt():
    out = bb.render_segments(SEGMENTS, "srt", "vi", 4.0)
    assert "1\n" in out  # SRT index
    assert "-->" in out
    assert "00:00:00,000 --> 00:00:00,880" in out  # comma ms for SRT
    assert "xin chào" in out


def test_render_vtt():
    out = bb.render_segments(SEGMENTS, "vtt", "vi", 4.0)
    assert out.startswith("WEBVTT")
    assert "00:00:01.000 --> 00:00:04.000" in out  # dot ms for VTT


# --- model registry --------------------------------------------------------

def test_whisper_batch_models_registry():
    # Benchmarking set: tiny..large-v3-turbo, with large-v3 deliberately EXCLUDED.
    assert bb.WHISPER_BATCH_MODELS == ["tiny", "base", "small", "medium", "large-v3-turbo"]
    assert "large-v3" not in bb.WHISPER_BATCH_MODELS


# --- backend routing -------------------------------------------------------

def test_get_batch_backend_routes_chunkformer():
    be = bb.get_batch_backend("chunkformer", transcription_engine=None)
    assert isinstance(be, bb.ChunkFormerBatchBackend)
    assert be.id == "chunkformer"


@pytest.mark.parametrize("model", bb.WHISPER_BATCH_MODELS)
def test_get_batch_backend_routes_mlx_when_available(monkeypatch, model):
    # When MLX-Whisper is available, a known size runs that exact model (not the singleton).
    monkeypatch.setattr(bb.MlxWhisperBatchBackend, "available", classmethod(lambda cls: True))
    be = bb.get_batch_backend(model, transcription_engine=object())
    assert isinstance(be, bb.MlxWhisperBatchBackend)
    assert be.id == model


@pytest.mark.parametrize("model", bb.WHISPER_BATCH_MODELS)
def test_get_batch_backend_falls_back_when_mlx_unavailable(monkeypatch, model):
    # No MLX (e.g. non-Apple-Silicon) -> the in-process singleton handles it.
    monkeypatch.setattr(bb.MlxWhisperBatchBackend, "available", classmethod(lambda cls: False))
    sentinel = object()
    be = bb.get_batch_backend(model, transcription_engine=sentinel)
    assert isinstance(be, bb.WhisperBatchBackend)
    assert be.engine is sentinel


@pytest.mark.parametrize("model", ["", "whisper-1", "whisper-large", "large-v3"])
def test_get_batch_backend_unknown_defaults_to_whisper(monkeypatch, model):
    # Empty (OpenAI default), unknown names, and the excluded large-v3 -> singleton Whisper.
    monkeypatch.setattr(bb.MlxWhisperBatchBackend, "available", classmethod(lambda cls: True))
    sentinel = object()
    be = bb.get_batch_backend(model, transcription_engine=sentinel)
    assert isinstance(be, bb.WhisperBatchBackend)
    assert be.engine is sentinel


def test_mlx_backend_rejects_unknown_model():
    with pytest.raises(bb.HTTPException):
        bb.MlxWhisperBatchBackend("bogus-model")


@pytest.mark.parametrize("raw,expected", [
    ("auto", None), ("", None), (None, None), ("none", None), ("vi", "vi"), ("EN", "en"),
])
def test_mlx_normalize_language(raw, expected):
    assert bb.MlxWhisperBatchBackend._normalize_language(raw) == expected


def test_batch_backends_status_shape(monkeypatch):
    monkeypatch.setattr(bb.MlxWhisperBatchBackend, "available", classmethod(lambda cls: True))
    monkeypatch.setattr(bb.ChunkFormerBatchBackend, "available", classmethod(lambda cls: False))
    status = bb.batch_backends_status()
    ids = [s["id"] for s in status]
    assert ids == bb.WHISPER_BATCH_MODELS + ["chunkformer"]
    avail = {s["id"]: s["available"] for s in status}
    assert all(avail[m] is True for m in bb.WHISPER_BATCH_MODELS)
    assert avail["chunkformer"] is False


def test_chunkformer_available_returns_bool():
    assert isinstance(bb.ChunkFormerBatchBackend.available(), bool)


def test_full_chunkformer_normalization_to_verbose_json():
    data = [
        {"decode": "xin chào", "start": "00:00:00:000", "end": "00:00:00:880"},
        {"decode": "hà nội", "start": "00:00:01:000", "end": "00:00:04:000"},
    ]
    segs = bb.chunkformer_json_to_segments(data)
    out = bb.render_segments(segs, "verbose_json", "vi", segs[-1]["end"])
    assert out["text"] == "xin chào hà nội"
    assert len(out["segments"]) == 2
    assert out["duration"] == pytest.approx(4.0)
