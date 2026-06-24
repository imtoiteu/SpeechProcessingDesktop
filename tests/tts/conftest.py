"""Test fixtures for the TTS subsystem (VieNeu-TTS backend).

These tests are self-contained and SKIP (never fail) when the VieNeu runtime is
unavailable, so they are safe to collect from any environment — including the STT
`.venv` running the full STT suite. The model-loading / synthesis tests only run
where `vieneu` is importable (i.e. VieNeu-TTS/.venv).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# Make `import tts...` work without installing the package (PYTHONPATH=src style).
SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: loads the VieNeu-TTS model (heavy)")


def vieneu_available() -> bool:
    return importlib.util.find_spec("vieneu") is not None


requires_vieneu = pytest.mark.skipif(
    not vieneu_available(), reason="vieneu runtime not importable (run in VieNeu-TTS/.venv)"
)


@pytest.fixture
def tmp_config(tmp_path):
    """A TtsConfig pointing at a temp data dir (no model needed)."""
    from tts.config import TtsConfig

    cfg = TtsConfig.from_env()
    cfg.data_dir = tmp_path / "tts-data"
    return cfg
