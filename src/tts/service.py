"""TTS service layer (VieNeu-TTS backend).

Owns the engine lifecycle, serializes inference (the GGUF/llama.cpp worker is
single-threaded), and encodes output audio. The FastAPI sidecar in
:mod:`tts.server` is a thin HTTP shell over this class.

It exposes the same workflow as VieNeu-TTS's own streaming app: model listing +
switching, preset-voice listing, one-shot synthesis, low-latency streaming, and
URL article extraction. All VieNeu-specific logic lives in
:mod:`tts.vieneu_engine`.
"""

from __future__ import annotations

import io
import logging
import threading
import wave
from typing import Any, Dict, Generator, List, Optional, Tuple

import numpy as np

from tts.config import TtsConfig
from tts.vieneu_engine import VieNeuEngine

logger = logging.getLogger("tts.service")

# Output formats for one-shot synthesis. wav/flac/ogg via libsndfile (soundfile);
# compressed formats via pydub+ffmpeg. Streaming always uses WAV/PCM16.
_MIME = {
    "wav": "audio/wav", "flac": "audio/flac", "ogg": "audio/ogg",
    "opus": "audio/opus", "mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac",
}
_SOUNDFILE_FORMATS = {"wav": "WAV", "flac": "FLAC", "ogg": "OGG"}


def _float_to_pcm16_bytes(wav: np.ndarray) -> bytes:
    pcm = (np.clip(wav, -1.0, 1.0) * 32767.0).astype("<i2")
    return pcm.tobytes()


def _streaming_wav_header(sample_rate: int) -> bytes:
    """A WAV header with an oversized data length so browsers play progressively
    (mirrors VieNeu-TTS web_stream's streaming header)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.setnframes(100_000_000)
    return buf.getvalue()


class TtsService:
    """High-level TTS service used by the HTTP sidecar."""

    def __init__(self, config: Optional[TtsConfig] = None):
        self.config = config or TtsConfig.from_env()
        self.engine = VieNeuEngine(self.config)
        # llama.cpp / ONNX inference is not re-entrant; serialize all model use.
        self._infer_lock = threading.Lock()

    # ------------------------------------------------------------------ load
    def ensure_loaded(self) -> None:
        self.engine.ensure_loaded()

    # ---------------------------------------------------------------- models
    def list_models(self) -> List[Dict[str, Any]]:
        return self.engine.list_models()

    def switch_model(self, model_key: str) -> Dict[str, Any]:
        """Switch the active model (reloads the backbone). Returns the new state."""
        with self._infer_lock:
            key = self.engine.switch_model(model_key)
        return {
            "status": "ok",
            "model_key": key,
            "backbone": self.engine.current_repo,
            "sample_rate": self.engine.sample_rate,
            "voices": self.list_voices(),
        }

    # ---------------------------------------------------------------- voices
    def list_voices(self) -> List[Dict[str, Any]]:
        return [{"id": vid, "name": desc} for desc, vid in self.engine.list_preset_voices()]

    # ---------------------------------------------------------------- health
    def health(self) -> Dict[str, Any]:
        h = self.engine.health()
        cached = self.config.model_cached()
        loaded = h["model_loaded"]
        if loaded:
            status, detail = "ok", None
        elif cached:
            status, detail = "ready", "Model loads on first request."
        else:
            status = "degraded"
            detail = (
                f"Model {h['backbone']} not found in the HF cache; it will be "
                "downloaded on first request (needs network)."
            )
        if h.get("load_error"):
            status, detail = "error", h["load_error"]
        return {
            "status": status,
            "engine": "vieneu",
            "model_loaded": loaded,
            "model_key": h.get("model_key"),
            "backbone": h.get("backbone"),
            # Kept for UI back-compat: "checkpoints present" == model available.
            "checkpoints_present": cached or loaded,
            "device": h.get("device"),
            "precision": self._precision_label(),
            "sample_rate": h.get("sample_rate"),
            "n_voices": h.get("n_voices", 0),
            "default_voice": h.get("default_voice"),
            "detail": detail,
        }

    def _precision_label(self) -> str:
        repo = self.engine.current_repo.lower()
        if "q8" in repo:
            return "gguf-q8"
        if "q4" in repo:
            return "gguf-q4"
        return "gguf" if "gguf" in repo else "fp32"

    # ------------------------------------------------------------- synthesize
    def synthesize(
        self,
        *,
        text: str,
        voice: Optional[str] = None,
        fmt: str = "wav",
        temperature: Optional[float] = None,
        chunk_length: Optional[int] = None,
        normalize: Optional[bool] = None,
    ) -> Tuple[bytes, str, int]:
        """One-shot synthesis → ``(audio_bytes, mime, sample_rate)``."""
        if not text or not text.strip():
            raise ValueError("Text must not be empty.")
        self.ensure_loaded()
        with self._infer_lock:
            wav, sr = self.engine.synthesize(
                text, voice_id=voice, temperature=temperature,
                max_chars=chunk_length, normalize=normalize,
            )
        if wav.size == 0:
            raise ValueError("Synthesis produced empty audio.")
        data, mime = self._encode_audio(wav, sr, fmt)
        return data, mime, sr

    def stream(
        self,
        *,
        text: str,
        voice: Optional[str] = None,
        temperature: Optional[float] = None,
        normalize: Optional[bool] = None,
    ) -> Generator[bytes, None, None]:
        """Yield a streaming WAV (header + PCM16 chunks) for StreamingResponse.

        Holds the inference lock for the whole stream so model switches and other
        requests can't interleave with llama.cpp generation.
        """
        if not text or not text.strip():
            raise ValueError("Text must not be empty.")
        self.ensure_loaded()
        with self._infer_lock:
            yield _streaming_wav_header(self.engine.sample_rate)
            for chunk in self.engine.infer_stream(
                text, voice_id=voice, temperature=temperature, normalize=normalize,
            ):
                if chunk.size:
                    yield _float_to_pcm16_bytes(chunk)

    # ------------------------------------------------------------- url extract
    def extract_url(self, url: str, max_chars: int = 5000) -> Dict[str, Any]:
        """Extract article text from a URL (reuses vieneu_utils.url_extract)."""
        try:
            from vieneu_utils.url_extract import extract_text_from_url
        except Exception as exc:  # pragma: no cover - optional dep
            return {"status": "error",
                    "message": f"URL extraction unavailable (trafilatura not installed): {exc}"}
        result = extract_text_from_url(url, max_chars=max_chars)
        if result.get("error"):
            return {"status": "error", "message": result["error"]}
        return {
            "status": "ok",
            "title": result.get("title"),
            "text": result.get("text", ""),
            "char_count": result.get("char_count", 0),
            "truncated": result.get("truncated", False),
        }

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _encode_audio(wav: np.ndarray, sr: int, fmt: str) -> Tuple[bytes, str]:
        fmt = (fmt or "wav").lower().lstrip(".")
        if fmt not in _MIME:
            raise ValueError(f"Unsupported format: {fmt!r}. Use one of {sorted(_MIME)}.")
        wav = np.ascontiguousarray(np.clip(wav, -1.0, 1.0), dtype=np.float32)
        if fmt in _SOUNDFILE_FORMATS:
            import soundfile as sf
            buf = io.BytesIO()
            sf.write(buf, wav, sr, format=_SOUNDFILE_FORMATS[fmt])
            return buf.getvalue(), _MIME[fmt]
        from pydub import AudioSegment
        pcm16 = (wav * 32767.0).astype(np.int16)
        seg = AudioSegment(data=pcm16.tobytes(), sample_width=2, frame_rate=sr, channels=1)
        buf = io.BytesIO()
        seg.export(buf, format="ipod" if fmt in ("m4a", "aac") else fmt)
        return buf.getvalue(), _MIME[fmt]
