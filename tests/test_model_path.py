"""Model-path validation: a bad path must raise a clear ModelLoadError BEFORE it
reaches pywhispercpp (which would otherwise load a NULL model and SIGSEGV on first
use). These tests must never construct an engine with an invalid native path.
"""
import os

import pytest

from vnstt.cli import resolve_model_arg
from vnstt.engine import (
    ModelLoadError,
    create_engine,
    validate_faster_whisper_model,
    validate_whispercpp_model_path,
)

GGML = "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin"


# ---- whisper.cpp validation ----
def test_whispercpp_missing_path_raises_clear_error_not_segfault():
    with pytest.raises(ModelLoadError) as ei:
        validate_whispercpp_model_path("models/does/not/exist.bin")
    msg = str(ei.value)
    assert "not found" in msg and "exist.bin" in msg  # names the offending path
    assert "segfault" in msg.lower()                   # explains why we stop early


def test_whispercpp_empty_or_none_raises():
    for bad in ("", None):
        with pytest.raises(ModelLoadError):
            validate_whispercpp_model_path(bad)  # type: ignore[arg-type]


def test_whispercpp_known_model_name_is_accepted_without_file():
    # A bare known name is fine (pywhispercpp can download it); must not raise.
    assert validate_whispercpp_model_path("tiny") == "tiny"


def test_create_engine_whispercpp_bad_path_raises_before_native_call():
    # The critical regression: this must RAISE, not crash the interpreter.
    with pytest.raises(ModelLoadError):
        create_engine("whisper.cpp", model_path="/nonexistent/ggml-model.bin")


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_whispercpp_existing_path_returns_absolute():
    out = validate_whispercpp_model_path(GGML)
    assert os.path.isabs(out) and os.path.isfile(out)


# ---- faster-whisper validation ----
def test_faster_whisper_missing_local_path_raises():
    with pytest.raises(ModelLoadError):
        validate_faster_whisper_model("./models/not-a-real-ct2-dir")


def test_faster_whisper_bare_hf_id_passes_through():
    assert validate_faster_whisper_model("large-v3") == "large-v3"


# ---- cwd-robust default resolution (the actual UI bug: relative path + launch dir) ----
def test_resolve_model_arg_unknown_path_returned_raw_for_engine_to_reject():
    # When nothing is found, return the raw value so the engine raises a clear error.
    assert resolve_model_arg("whisper.cpp", "/totally/bogus.bin") == "/totally/bogus.bin"


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_resolve_model_arg_finds_default_from_any_cwd(monkeypatch, tmp_path):
    # Reproduces the fix: launched from an unrelated directory, the relative default
    # still resolves (anchored to the repo root) to an absolute existing file.
    monkeypatch.chdir(tmp_path)
    out = resolve_model_arg("whisper.cpp", None)
    assert os.path.isabs(out) and os.path.isfile(out)
