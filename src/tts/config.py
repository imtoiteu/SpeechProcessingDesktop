"""Configuration for the TTS subsystem (VieNeu-TTS backend).

Deliberately separate from the STT (`WhisperLiveKitConfig`) configuration so the
two systems share nothing. Everything is overridable via ``TTS_*`` environment
variables, which keeps the sidecar 12-factor friendly and lets us switch models
or devices without code changes.

Engine
------
The TTS engine is **VieNeu-TTS** (https://github.com/pnnbao97/VieNeu-TTS),
integrated directly via its Python SDK (``from vieneu import Vieneu``). The
default runtime is the proven, torch-free Apple-Silicon config:

    mode      = standard
    backbone  = pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf   (GGUF, llama.cpp + Metal)
    codec     = neuphonic/neucodec-onnx-decoder-int8 (ONNX, CPU, decode-only)

This runs entirely on CPU/Metal without PyTorch and ships 6 built-in Vietnamese
voices (Northern/Southern, male/female). Switch model with a single env var::

    TTS_BACKBONE=pnnbao-ump/VieNeu-TTS-0.3B-q4-gguf ./scripts/run_tts_server.sh

Note on voice cloning: the ONNX decoder cannot *encode* new reference audio, so
one-shot cloning and saving new voice presets require the full PyTorch codec
(``pip install vieneu[gpu]`` + a torch-capable codec). With the default codec the
sidecar serves preset voices only and reports ``clone_supported: false`` via
``/tts/health``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Repo root = .../Speech2Text  (this file is .../Speech2Text/src/tts/config.py)
REPO_ROOT = Path(__file__).resolve().parents[2]

# Selectable models — mirrors VieNeu-TTS's own apps/web_stream.py AVAILABLE_MODELS
# so the STTLive model picker offers the same choices as the upstream app. Any of
# these GGUF repos loads in `standard` mode with the ONNX decoder (torch-free).
AVAILABLE_MODELS = {
    "q4": {
        "id": "pnnbao-ump/VieNeu-TTS-0.3B-q4-gguf",
        "name": "VieNeu 0.3B (Q4_0) — Fast/Light",
        "desc": "Recommended for most CPUs (Speed > Quality)",
    },
    "q8": {
        "id": "pnnbao-ump/VieNeu-TTS-0.3B-q8-gguf",
        "name": "VieNeu 0.3B (Q8_0) — High Quality",
        "desc": "Higher quality but slower (Requires strong CPU)",
    },
    "ngochuyen": {
        "id": "pnnbao-ump/VieNeu-TTS-0.3B-ngoc-huyen-gguf-Q4_0",
        "name": "VieNeu 0.3B (Q4_0) — Ngoc Huyen",
        "desc": "Ngoc Huyen Voice (LoRA)",
    },
}
DEFAULT_MODEL_KEY = "q8"

# Proven, cached, torch-free defaults for Apple Silicon (see module docstring).
DEFAULT_BACKBONE = AVAILABLE_MODELS[DEFAULT_MODEL_KEY]["id"]
DEFAULT_GGUF_FILENAME = "*.gguf"
DEFAULT_CODEC = "neuphonic/neucodec-onnx-decoder-int8"


def resolve_model(model_key_or_repo: str) -> tuple[str, str]:
    """Map a model key (q4/q8/ngochuyen) or a custom GGUF repo id to ``(key, repo)``.

    Mirrors VieNeu-TTS web_stream.load_model_instance: a known key resolves to its
    repo; otherwise the value is treated as a custom HF repo id and must contain
    'gguf' (the standard backend runs GGUF models).
    """
    key = (model_key_or_repo or "").strip()
    if key in AVAILABLE_MODELS:
        return key, AVAILABLE_MODELS[key]["id"]
    if "gguf" not in key.lower():
        raise ValueError(
            f"Unknown model {key!r}. Use one of {list(AVAILABLE_MODELS)} or a custom "
            "Hugging Face GGUF repo id (must contain 'gguf')."
        )
    return key, key  # custom repo: key == repo id


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_opt(name: str) -> Optional[str]:
    v = os.environ.get(name)
    return v if v else None


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def hf_cache_dir() -> Path:
    """Resolve the Hugging Face hub cache directory (respects env overrides)."""
    hub = os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hub:
        return Path(hub)
    home = os.environ.get("HF_HOME")
    if home:
        return Path(home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


@dataclass
class TtsConfig:
    """Single source of truth for TTS runtime configuration."""

    # --- VieNeu engine selection ---
    mode: str = "standard"
    backbone_repo: str = DEFAULT_BACKBONE
    gguf_filename: str = DEFAULT_GGUF_FILENAME
    codec_repo: str = DEFAULT_CODEC
    # Devices: "cpu" is the reliable, torch-free path. GGUF backbone uses
    # llama.cpp (Metal-accelerated automatically); the ONNX codec is CPU-only.
    backbone_device: str = "cpu"
    codec_device: str = "cpu"
    emotion: str = "natural"
    hf_token: Optional[str] = None

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8011
    # Browsers load the STT UI from the WhisperLiveKit server (default :8000) and
    # call this sidecar cross-origin, so CORS must allow that origin.
    cors_origins: str = "*"
    # Eager-load the model at startup instead of lazily on first request.
    eager_load: bool = False

    # --- Data (user-saved voice presets) ---
    data_dir: Path = REPO_ROOT / "tts-data"

    # --- Generation defaults (VieNeu standard infer: temperature + top_k) ---
    default_temperature: float = 0.7
    default_top_k: int = 50
    default_max_chars: int = 256
    normalize: bool = True

    # Maximum reference-audio upload size for voice cloning (bytes).
    max_reference_bytes: int = 25 * 1024 * 1024

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)

    @classmethod
    def from_env(cls) -> "TtsConfig":
        """Build a config from ``TTS_*`` environment variables, falling back to
        the dataclass defaults."""
        d = cls()
        return cls(
            mode=_env("TTS_MODE", d.mode),
            backbone_repo=_env("TTS_BACKBONE", d.backbone_repo),
            gguf_filename=_env("TTS_GGUF_FILENAME", d.gguf_filename),
            codec_repo=_env("TTS_CODEC", d.codec_repo),
            backbone_device=_env("TTS_DEVICE", d.backbone_device),
            codec_device=_env("TTS_CODEC_DEVICE", d.codec_device),
            emotion=_env("TTS_EMOTION", d.emotion),
            hf_token=_env_opt("TTS_HF_TOKEN") or _env_opt("HF_TOKEN"),
            host=_env("TTS_HOST", d.host),
            port=int(_env("TTS_PORT", str(d.port))),
            cors_origins=_env("TTS_CORS_ORIGINS", d.cors_origins),
            eager_load=_env_bool("TTS_EAGER_LOAD", d.eager_load),
            data_dir=Path(_env("TTS_DATA_DIR", str(d.data_dir))),
            default_temperature=float(_env("TTS_TEMPERATURE", str(d.default_temperature))),
            default_top_k=int(_env("TTS_TOP_K", str(d.default_top_k))),
            normalize=_env_bool("TTS_NORMALIZE", d.normalize),
        )

    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*" or raw == "":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    def model_cached(self) -> bool:
        """True if the backbone repo appears present in the HF hub cache.

        Used only for the UI readiness hint (``checkpoints_present``); it never
        gates loading — the engine attempts the load regardless and downloads on
        demand when online.
        """
        repo = self.backbone_repo.strip("/")
        if Path(repo).exists():  # local path
            return True
        cache_name = "models--" + repo.replace("/", "--")
        snap = hf_cache_dir() / cache_name / "snapshots"
        if not snap.is_dir():
            return False
        return any(snap.iterdir())

    @property
    def voices_dir(self) -> Path:
        return self.data_dir / "voices"
