"""Smoke tests: import the TTS package and exercise the pure-Python pieces.

No VieNeu runtime or model weights required (the heavy `import vieneu` is
deferred to engine load).
"""

import importlib

import pytest


def test_package_imports():
    import tts

    assert tts.__version__


def test_config_defaults_and_env(monkeypatch):
    from tts.config import DEFAULT_BACKBONE, TtsConfig

    cfg = TtsConfig()
    assert cfg.port == 8011
    assert cfg.mode == "standard"
    assert cfg.backbone_repo == DEFAULT_BACKBONE
    assert "gguf" in cfg.backbone_repo.lower()
    assert cfg.codec_repo.startswith("neuphonic/")
    assert cfg.voices_dir == cfg.data_dir / "voices"

    monkeypatch.setenv("TTS_PORT", "9099")
    monkeypatch.setenv("TTS_DEVICE", "cpu")
    monkeypatch.setenv("TTS_BACKBONE", "pnnbao-ump/VieNeu-TTS-0.3B-q4-gguf")
    monkeypatch.setenv("TTS_TEMPERATURE", "0.5")
    cfg2 = TtsConfig.from_env()
    assert cfg2.port == 9099
    assert cfg2.backbone_device == "cpu"
    assert cfg2.backbone_repo.endswith("q4-gguf")
    assert cfg2.default_temperature == 0.5


def test_cors_origin_parsing():
    from tts.config import TtsConfig

    assert TtsConfig(cors_origins="*").cors_origin_list() == ["*"]
    assert TtsConfig(cors_origins="http://a, http://b").cors_origin_list() == [
        "http://a",
        "http://b",
    ]


def test_encode_audio_wav_flac():
    np = pytest.importorskip("numpy")
    pytest.importorskip("soundfile")
    from tts.service import TtsService

    samples = (0.1 * np.sin(np.linspace(0, 6.28 * 220, 4800))).astype("float32")
    wav, mime = TtsService._encode_audio(samples, 24000, "wav")
    assert wav[:4] == b"RIFF" and mime == "audio/wav" and len(wav) > 1000
    flac, mime = TtsService._encode_audio(samples, 24000, "flac")
    assert flac[:4] == b"fLaC" and mime == "audio/flac"
    with pytest.raises(ValueError):
        TtsService._encode_audio(samples, 24000, "aiff")


def test_models_validation():
    pytest.importorskip("pydantic")
    from tts.models import SynthesizeRequest

    req = SynthesizeRequest(text="hello", temperature=0.7)
    assert req.format == "wav"
    with pytest.raises(Exception):
        SynthesizeRequest(text="x", temperature=5.0)  # out of range


def test_model_registry_and_resolve():
    from tts.config import AVAILABLE_MODELS, resolve_model

    assert set(AVAILABLE_MODELS) == {"q4", "q8", "ngochuyen"}
    assert resolve_model("q4")[1].endswith("q4-gguf")
    assert resolve_model("org/custom-gguf") == ("org/custom-gguf", "org/custom-gguf")
    with pytest.raises(ValueError):
        resolve_model("not-a-model")  # no 'gguf' -> rejected


def test_service_constructs_without_runtime(tmp_config):
    """The service must be constructible without the VieNeu runtime loaded;
    health() reports not-loaded rather than raising, and the model list shows the
    selectable models with q8 active by default."""
    from tts.service import TtsService

    svc = TtsService(tmp_config)
    h = svc.health()
    assert h["engine"] == "vieneu"
    assert h["model_loaded"] is False
    assert h["model_key"] == "q8"
    assert isinstance(h["checkpoints_present"], bool)
    assert svc.list_voices() == []  # no built-in voices until the model loads
    active = [m for m in svc.list_models() if m["active"]]
    assert len(active) == 1 and active[0]["key"] == "q8"


def test_server_module_imports():
    pytest.importorskip("fastapi")
    server = importlib.import_module("tts.server")
    paths = {r.path for r in server.app.routes}
    assert {"/tts/synthesize", "/tts/health", "/tts/voices",
            "/tts/models", "/tts/model", "/tts/stream", "/tts/extract_url"} <= paths
    # Cloning endpoints must be gone.
    assert "/tts/clone" not in paths
