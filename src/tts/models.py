"""Pydantic request/response schemas for the TTS HTTP API.

These are *our* clean contract for the UI; they are intentionally decoupled from
the engine internals so :mod:`tts.vieneu_engine` is the only place that knows
about the VieNeu-TTS SDK. The surface mirrors VieNeu-TTS's own streaming app
(models / voices / synthesize / stream / extract_url).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SynthesizeRequest(BaseModel):
    """One-shot text-to-speech with a built-in preset voice."""

    text: str = Field(..., min_length=1, description="Text to synthesize.")
    voice: Optional[str] = Field(None, description="Preset voice id. Omit for the model default.")
    format: str = Field("wav", description="Output format: wav, flac, mp3, ogg, opus.")
    temperature: Optional[float] = Field(None, ge=0.1, le=1.0)
    chunk_length: Optional[int] = Field(None, ge=100, le=1000, description="-> max_chars per chunk.")
    normalize: Optional[bool] = Field(None, description="Normalize numbers/text before synthesis.")


class StreamRequest(BaseModel):
    """Low-latency streaming synthesis (used for long text via POST)."""

    text: str = Field(..., min_length=1)
    voice: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0.1, le=1.0)
    normalize: Optional[bool] = None


class SetModelRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_key: str = Field(..., description="Model key (q4/q8/ngochuyen) or a custom GGUF repo id.")


class ExtractUrlRequest(BaseModel):
    url: str
    max_chars: int = Field(5000, ge=100, le=20000)


class VoiceInfo(BaseModel):
    id: str
    name: str


class VoicesResponse(BaseModel):
    voices: list[VoiceInfo]


class ModelInfo(BaseModel):
    key: str
    name: str
    desc: str = ""
    active: bool = False


class ModelsResponse(BaseModel):
    models: list[ModelInfo]


class HealthResponse(BaseModel):
    # `model_loaded` collides with pydantic's protected `model_` namespace; opt out.
    model_config = ConfigDict(protected_namespaces=())

    status: str
    model_loaded: bool
    checkpoints_present: bool
    device: Optional[str] = None
    precision: Optional[str] = None
    sample_rate: Optional[int] = None
    detail: Optional[str] = None
    engine: Optional[str] = None
    model_key: Optional[str] = None
    backbone: Optional[str] = None
    n_voices: Optional[int] = None
    default_voice: Optional[str] = None
