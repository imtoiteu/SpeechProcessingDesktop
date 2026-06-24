"""VieNeu-TTS Text-to-Speech subsystem for STTLive.

This package is fully independent of the Speech-to-Text stack. It runs in its
own process (a FastAPI sidecar, see :mod:`tts.server`) and its own virtual
environment — by default the VieNeu-TTS venv (``VieNeu-TTS/.venv``), whose
``vieneu`` SDK, llama.cpp and ONNX codec never touch the STT environment.

Layers:

    tts.server         -- FastAPI sidecar (HTTP surface for the UI: /tts/*)
    tts.service        -- service layer (lifecycle, serialization, voice presets,
                          audio encoding)
    tts.vieneu_engine  -- thin adapter around the VieNeu-TTS SDK (vieneu.Vieneu)
    vieneu.*           -- the VieNeu-TTS runtime (installed in the TTS venv)

Only :mod:`tts.config`, :mod:`tts.models` and :mod:`tts.utils` are safe to import
without the VieNeu runtime installed; the heavy ``import vieneu`` is deferred to
:meth:`tts.vieneu_engine.VieNeuEngine.ensure_loaded`.
"""

__all__ = ["__version__"]

__version__ = "0.2.0"
