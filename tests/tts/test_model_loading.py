"""Model-loading test for the VieNeu-TTS engine.

Skips unless the VieNeu runtime is importable (run in VieNeu-TTS/.venv). Loads
the configured backbone + codec and checks the engine reports a sane state.
"""

import importlib.util

import pytest

requires_vieneu = pytest.mark.skipif(
    importlib.util.find_spec("vieneu") is None,
    reason="vieneu runtime not importable (run in VieNeu-TTS/.venv)",
)


@requires_vieneu
@pytest.mark.slow
def test_vieneu_loads_and_reports_health(tmp_config):
    from tts.service import TtsService

    svc = TtsService(tmp_config)
    svc.ensure_loaded()
    h = svc.health()

    assert h["model_loaded"] is True
    assert h["status"] in ("ok", "ready")
    assert h["sample_rate"] in (24_000, 48_000)
    assert h["n_voices"] >= 1
    assert h["model_key"] in ("q4", "q8", "ngochuyen", "custom")
    # The built-in voices must be listable for the UI dropdown.
    voices = svc.list_voices()
    assert len(voices) >= 1
    assert all("id" in v and "name" in v for v in voices)
    # Models are listable with exactly one active.
    assert sum(1 for m in svc.list_models() if m["active"]) == 1


def test_engine_load_without_runtime_raises(monkeypatch, tmp_config):
    """If `import vieneu` fails, ensure_loaded() must raise a clear
    TtsModelNotLoaded (never a bare ImportError), in any environment."""
    import builtins

    from tts.vieneu_engine import TtsModelNotLoaded, VieNeuEngine

    real_import = builtins.__import__

    def _block(name, *a, **k):
        if name == "vieneu" or name.startswith("vieneu."):
            raise ImportError("blocked for test")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _block)
    engine = VieNeuEngine(tmp_config)
    with pytest.raises(TtsModelNotLoaded):
        engine.ensure_loaded()
