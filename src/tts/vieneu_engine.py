"""VieNeu-TTS engine adapter.

Thin wrapper around the **VieNeu-TTS SDK** (``from vieneu import Vieneu``). It is
the *only* place that knows about VieNeu internals; everything above it (service,
HTTP server) talks to this small, stable interface. We integrate the SDK
directly rather than reimplementing inference or wrapping a compatibility layer.

Model selection + switching mirrors VieNeu-TTS's own ``apps/web_stream.py``
(``AVAILABLE_MODELS`` + ``load_model_instance`` + ``/set_model``) so the STTLive
model picker behaves like the upstream streaming app. Synthesis exposes both a
one-shot (:meth:`synthesize`) and a streaming (:meth:`infer_stream`) path, the
latter reusing the SDK's ``infer_stream`` generator.

The ``import vieneu`` is deferred to :meth:`ensure_loaded` so this module (and the
service/server above it) import cleanly even without the VieNeu runtime (e.g. the
STT venv, for smoke tests). Loading the model requires ``VieNeu-TTS/.venv``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Generator, List, Optional, Tuple

import numpy as np

from tts.config import AVAILABLE_MODELS, TtsConfig, resolve_model

logger = logging.getLogger("tts.vieneu")


class TtsModelNotLoaded(RuntimeError):
    """Raised when synthesis is attempted but the model failed to load."""


class VieNeuEngine:
    """Loads a VieNeu-TTS model (switchable) and exposes synthesis + voices."""

    def __init__(self, config: TtsConfig):
        self.config = config
        self.model: Any = None
        self.sample_rate: int = 24_000
        self._load_error: Optional[str] = None
        # Resolve the initial model key from the configured backbone repo.
        self.current_key, self.current_repo = self._initial_model()

    def _initial_model(self) -> Tuple[str, str]:
        repo = self.config.backbone_repo
        for key, meta in AVAILABLE_MODELS.items():
            if meta["id"] == repo:
                return key, repo
        return "custom", repo

    # ------------------------------------------------------------------ load
    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def ensure_loaded(self) -> None:
        """Instantiate the VieNeu model once. Idempotent."""
        if self.model is not None:
            return
        self._load(self.current_repo)

    def _load(self, backbone_repo: str) -> None:
        try:
            from vieneu import Vieneu  # deferred: needs VieNeu-TTS/.venv
        except Exception as exc:  # pragma: no cover - depends on runtime venv
            self._load_error = (
                f"VieNeu runtime not importable ({exc}). Run the sidecar in "
                "VieNeu-TTS/.venv (see scripts/run_tts_server.sh)."
            )
            raise TtsModelNotLoaded(self._load_error) from exc

        c = self.config
        logger.info("Loading VieNeu-TTS: backbone=%s codec=%s", backbone_repo, c.codec_repo)
        try:
            model = Vieneu(
                mode=c.mode,
                backbone_repo=backbone_repo,
                backbone_device=c.backbone_device,
                codec_repo=c.codec_repo,
                codec_device=c.codec_device,
                gguf_filename=c.gguf_filename,
                emotion=c.emotion,
                hf_token=c.hf_token,
            )
        except Exception as exc:
            self._load_error = f"VieNeu model load failed ({backbone_repo}): {exc}"
            raise TtsModelNotLoaded(self._load_error) from exc

        # Replace only after a successful load so a failed switch keeps the old model.
        old = self.model
        self.model = model
        self.current_repo = backbone_repo
        self.sample_rate = int(getattr(model, "sample_rate", 24_000))
        self._load_error = None
        if old is not None:
            try:
                old.close()
            except Exception:  # pragma: no cover
                pass
        logger.info(
            "VieNeu-TTS ready: backbone=%s sample_rate=%d voices=%d",
            backbone_repo, self.sample_rate, len(self.list_preset_voices()),
        )

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    # ----------------------------------------------------------------- models
    def list_models(self) -> List[Dict[str, Any]]:
        """Selectable models (mirrors web_stream /models), with the active flag."""
        out = [
            {"key": k, "name": m["name"], "desc": m["desc"], "active": k == self.current_key}
            for k, m in AVAILABLE_MODELS.items()
        ]
        if self.current_key == "custom":
            out.append({"key": "custom", "name": self.current_repo, "desc": "Custom GGUF repo",
                        "active": True})
        return out

    def switch_model(self, model_key_or_repo: str) -> str:
        """Reload the backbone for ``model_key_or_repo``. Returns the active key."""
        key, repo = resolve_model(model_key_or_repo)
        if self.model is not None and key == self.current_key and repo == self.current_repo:
            return key
        self._load(repo)
        self.current_key = key
        return key

    # ----------------------------------------------------------------- voices
    def list_preset_voices(self) -> List[Tuple[str, str]]:
        """Built-in VieNeu preset voices as ``(description, id)`` for the model."""
        if self.model is None:
            return []
        try:
            return list(self.model.list_preset_voices())
        except Exception as exc:  # pragma: no cover
            logger.warning("list_preset_voices failed: %s", exc)
            return []

    def default_voice_id(self) -> Optional[str]:
        if self.model is None:
            return None
        return getattr(self.model, "_default_voice", None)

    def _voice(self, voice_id: Optional[str]) -> Dict[str, Any]:
        try:
            return self.model.get_preset_voice(voice_id or None)
        except Exception as exc:
            raise KeyError(f"Unknown voice: {voice_id!r} ({exc})") from exc

    # -------------------------------------------------------------- inference
    def _temp(self, temperature: Optional[float]) -> float:
        return self.config.default_temperature if temperature is None else float(temperature)

    def synthesize(
        self,
        text: str,
        *,
        voice_id: Optional[str] = None,
        temperature: Optional[float] = None,
        max_chars: Optional[int] = None,
        normalize: Optional[bool] = None,
    ) -> Tuple[np.ndarray, int]:
        """One-shot synthesis with a preset voice. Returns ``(float32_wave, sr)``."""
        self.ensure_loaded()
        if not text or not text.strip():
            raise ValueError("Text must not be empty.")
        do_norm = self.config.normalize if normalize is None else bool(normalize)
        wav = self.model.infer(
            text,
            voice=self._voice(voice_id),
            temperature=self._temp(temperature),
            top_k=self.config.default_top_k,
            max_chars=self.config.default_max_chars if max_chars is None else int(max_chars),
            skip_normalize=not do_norm,
        )
        return np.asarray(wav, dtype=np.float32), self.sample_rate

    def infer_stream(
        self,
        text: str,
        *,
        voice_id: Optional[str] = None,
        temperature: Optional[float] = None,
        normalize: Optional[bool] = None,
    ) -> Generator[np.ndarray, None, None]:
        """Stream float32 audio chunks (reuses the SDK's ``infer_stream``)."""
        self.ensure_loaded()
        if not text or not text.strip():
            raise ValueError("Text must not be empty.")
        do_norm = self.config.normalize if normalize is None else bool(normalize)
        for chunk in self.model.infer_stream(
            text,
            voice=self._voice(voice_id),
            temperature=self._temp(temperature),
            top_k=self.config.default_top_k,
            skip_normalize=not do_norm,
        ):
            yield np.asarray(chunk, dtype=np.float32)

    # ------------------------------------------------------------------ health
    def health(self) -> Dict[str, Any]:
        return {
            "engine": "vieneu",
            "mode": self.config.mode,
            "model_key": self.current_key,
            "backbone": self.current_repo,
            "model_loaded": self.is_loaded,
            "device": self.config.backbone_device,
            "sample_rate": self.sample_rate if self.is_loaded else None,
            "n_voices": len(self.list_preset_voices()),
            "default_voice": self.default_voice_id(),
            "load_error": self._load_error,
        }
