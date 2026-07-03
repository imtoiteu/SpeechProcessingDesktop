"""Batch (file) transcription backends behind a small abstraction layer.

This module powers ONLY the batch ``POST /v1/audio/transcriptions`` endpoint. The
streaming pipeline (``/asr``, ``/asr/file``) is untouched and never routes through here.

Two backends are provided:

- ``WhisperBatchBackend`` — the server's in-process Whisper engine. Behaviorally
  identical to the logic that previously lived inline in ``basic_server.py``.
- ``ChunkFormerBatchBackend`` — runs ``khanhld/chunkformer-large-vie`` **out of
  process** via the isolated ``.venv-chunkformer``. ChunkFormer pulls its own
  torch/torchaudio/transformers which conflict with the STT ``.venv``, so it must
  never be imported into this process. We reuse the already-verified
  ``scripts/chunkformer_transcribe.py --format json`` as a subprocess.

Both backends normalize their output to a common shape::

    [{"start": float_seconds, "end": float_seconds, "text": str}, ...]

and share a single ``render_segments()`` so that response formatting
(json / verbose_json / text / srt / vtt) lives in exactly one place — no
model-specific formatting scattered around.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Union

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Repo root: this file is <root>/WhisperLiveKit/whisperlivekit/batch_backends.py
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Whisper sizes selectable in Batch mode for benchmarking. Deliberately EXCLUDES
# ``large-v3`` (too heavy for testing) — see the project benchmarking policy. Each
# name resolves to an MLX repo via ``MLX_MODEL_MAPPING`` and runs through
# ``MlxWhisperBatchBackend`` (real per-model inference, not the streaming singleton).
WHISPER_BATCH_MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo"]


# ---------------------------------------------------------------------------
# Shared helpers: audio decode, timestamp parsing, response rendering
# ---------------------------------------------------------------------------

async def convert_to_pcm(audio_bytes: bytes) -> bytes:
    """Convert any audio/video format to PCM s16le mono 16kHz using ffmpeg.

    Decodes from a seekable temp file (``-i <path>``) rather than ``-i pipe:0`` so
    container formats whose moov atom is at the end (default for most MP4/MOV
    encoders) decode correctly.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", tmp_path,
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            "-loglevel", "error",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise HTTPException(status_code=400, detail=f"Audio conversion failed: {stderr.decode().strip()}")
        return stdout
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _parse_time_str(time_str: str) -> float:
    """Parse 'H:MM:SS.cc' (Whisper FrontData) to seconds."""
    parts = str(time_str).split(":")
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def _parse_chunkformer_ts(ts: str) -> float:
    """Parse ChunkFormer 'HH:MM:SS:mmm' (colon before ms) to seconds.

    Tolerates the Whisper 'H:MM:SS.cc' shape too, just in case.
    """
    parts = str(ts).split(":")
    if len(parts) == 4:
        h, m, s, ms = parts
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0
    return _parse_time_str(ts)


def _extract_json_payload(raw: str):
    """Parse the first JSON value in *raw*, tolerating leading noise on stdout.

    The ``chunkformer`` package prints a 'torch_npu not found' notice to stdout on
    import, which precedes the JSON. Scan for the first '[' or '{' and decode from there.
    Returns the parsed object, or ``None`` if no JSON value is found.
    """
    raw = raw.strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(raw):
        if ch in "[{":
            try:
                obj, _ = decoder.raw_decode(raw[i:])
                return obj
            except json.JSONDecodeError:
                continue
    return None


def chunkformer_json_to_segments(data) -> List[dict]:
    """Normalize the ChunkFormer script's ``--format json`` output to ``[{start, end, text}]``.

    The script emits a list of ``{decode, start, end}`` with timestamps 'HH:MM:SS:mmm',
    or (rarely) a plain transcript string. Empty segments are dropped.
    """
    segments: List[dict] = []
    if isinstance(data, str):
        if data.strip():
            segments.append({"start": 0.0, "end": 0.0, "text": data.strip()})
        return segments
    for seg in data:
        text = (seg.get("decode") or "").strip()
        if not text:
            continue
        segments.append({
            "start": _parse_chunkformer_ts(seg.get("start", "00:00:00:000")),
            "end": _parse_chunkformer_ts(seg.get("end", "00:00:00:000")),
            "text": text,
        })
    return segments


def _srt_timestamp(seconds: float, fmt: str) -> str:
    """Format seconds as SRT (HH:MM:SS,mmm) or VTT (HH:MM:SS.mmm) timestamp."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    sep = "," if fmt == "srt" else "."
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def render_segments(
    segments: List[dict],
    response_format: str,
    language: Optional[str],
    duration: float,
) -> Union[dict, str]:
    """Render normalized segments ``[{start, end, text}]`` to an OpenAI-compatible response.

    Output is identical to the previous ``_format_openai_response`` (json / verbose_json /
    text / srt / vtt), so existing callers and the UI are unaffected regardless of backend.
    """
    text_parts = [s["text"] for s in segments if s.get("text")]
    full_text = " ".join(p.strip() for p in text_parts).strip()

    if response_format == "text":
        return full_text

    out_segments = []
    words = []
    for seg in segments:
        if not seg.get("text"):
            continue
        start = float(seg["start"])
        end = float(seg["end"])
        out_segments.append({
            "id": len(out_segments),
            "start": round(start, 2),
            "end": round(end, 2),
            "text": seg["text"],
        })
        seg_words = seg["text"].split()
        if seg_words:
            word_duration = (end - start) / max(len(seg_words), 1)
            for j, word in enumerate(seg_words):
                words.append({
                    "word": word,
                    "start": round(start + j * word_duration, 2),
                    "end": round(start + (j + 1) * word_duration, 2),
                })

    if response_format == "verbose_json":
        return {
            "task": "transcribe",
            "language": language or "unknown",
            "duration": round(duration, 2),
            "text": full_text,
            "words": words,
            "segments": out_segments,
        }

    if response_format in ("srt", "vtt"):
        lines_out = []
        if response_format == "vtt":
            lines_out.append("WEBVTT\n")
        for i, seg in enumerate(out_segments):
            start_ts = _srt_timestamp(seg["start"], response_format)
            end_ts = _srt_timestamp(seg["end"], response_format)
            if response_format == "srt":
                lines_out.append(f"{i + 1}")
            lines_out.append(f"{start_ts} --> {end_ts}")
            lines_out.append(seg["text"])
            lines_out.append("")
        return "\n".join(lines_out)

    # Default: json
    return {"text": full_text}


# ---------------------------------------------------------------------------
# Backend abstraction
# ---------------------------------------------------------------------------

class BatchBackend:
    """Abstract batch (file) transcription backend."""

    #: Identifier reported to the UI / /health.
    id: str = "base"

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: Optional[str],
        response_format: str,
    ) -> Union[dict, str]:
        raise NotImplementedError

    @classmethod
    def available(cls) -> bool:
        return True


class WhisperBatchBackend(BatchBackend):
    """In-process Whisper engine (unchanged behavior). Used for streaming too, by nature."""

    id = "large-v3-turbo"

    def __init__(self, transcription_engine):
        self.engine = transcription_engine

    async def transcribe(self, audio_bytes, language, response_format):
        # Imported here (not at module import) to avoid any import-time coupling.
        from whisperlivekit.audio_processor import AudioProcessor

        pcm_data = await convert_to_pcm(audio_bytes)
        duration = len(pcm_data) / (16000 * 2)  # 16kHz, 16-bit mono

        processor = AudioProcessor(
            transcription_engine=self.engine,
            language=language,
        )
        processor.is_pcm_input = True  # we already decoded to PCM above

        results_gen = await processor.create_tasks()
        final_result = None

        async def collect():
            nonlocal final_result
            async for result in results_gen:
                final_result = result

        collect_task = asyncio.create_task(collect())

        chunk_size = 16000 * 2  # 1 second of PCM
        for i in range(0, len(pcm_data), chunk_size):
            await processor.process_audio(pcm_data[i:i + chunk_size])
        await processor.process_audio(b"")  # end-of-audio sentinel

        try:
            await asyncio.wait_for(collect_task, timeout=120.0)
        except asyncio.TimeoutError:
            logger.warning("Whisper batch transcription timed out after 120s")
        finally:
            await processor.cleanup()

        if final_result is None:
            return {"text": ""}

        d = final_result.to_dict()
        segments = []
        for line in d.get("lines", []):
            if line.get("speaker") == -2 or not line.get("text"):
                continue
            segments.append({
                "start": _parse_time_str(line.get("start", "0:00:00")),
                "end": _parse_time_str(line.get("end", "0:00:00")),
                "text": line["text"],
            })
        return render_segments(segments, response_format, language, duration)


class MlxWhisperBatchBackend(BatchBackend):
    """Offline MLX-Whisper batch backend that actually runs the *requested* model.

    Unlike ``WhisperBatchBackend`` (which reuses the startup singleton regardless of
    the requested name), this loads the specific MLX repo for ``model`` and runs
    ``mlx_whisper.transcribe`` — so Batch mode can benchmark tiny/base/small/medium/
    large-v3-turbo on the same file. The streaming pipeline is never touched.

    mlx_whisper's own ``ModelHolder`` keeps the *last* loaded model warm (a 1-slot
    cache), so repeated runs of the same size don't re-load; switching size reloads.
    Models download lazily from the HF hub on first use (nothing at server startup).
    """

    def __init__(self, model: str):
        if model not in WHISPER_BATCH_MODELS:
            raise HTTPException(status_code=400, detail=f"Unknown Whisper model '{model}'")
        self.id = model

    @classmethod
    def available(cls) -> bool:
        # Apple-Silicon + mlx_whisper importable. Individual sizes download on demand,
        # so availability is per-backend, not per-model. Imported lazily so the module
        # loads without pulling the heavy whisperlivekit package (used by unit tests).
        from whisperlivekit.backend_support import mlx_backend_available
        return mlx_backend_available()

    @staticmethod
    def _normalize_language(language: Optional[str]) -> Optional[str]:
        lang = (language or "").strip().lower()
        if lang in ("", "auto", "none"):
            return None  # let MLX-Whisper auto-detect
        return lang

    async def transcribe(self, audio_bytes, language, response_format):
        if not self.available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "MLX-Whisper backend is not available (requires Apple Silicon + "
                    "`mlx_whisper`). Install it into the STT environment or pick another model."
                ),
            )

        import numpy as np  # local: keep module import light / decoupled from numpy
        import mlx_whisper
        from whisperlivekit.model_mapping import MLX_MODEL_MAPPING

        repo = MLX_MODEL_MAPPING[self.id]
        pcm_data = await convert_to_pcm(audio_bytes)
        duration = len(pcm_data) / (16000 * 2)  # 16kHz, 16-bit mono
        # PCM s16le -> float32 in [-1, 1], the shape mlx_whisper expects for a raw array.
        audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0

        lang = self._normalize_language(language)

        def _run():
            return mlx_whisper.transcribe(
                audio,
                path_or_hf_repo=repo,
                language=lang,
                word_timestamps=False,
                verbose=None,
            )

        try:
            result = await asyncio.to_thread(_run)
        except Exception as exc:  # surfacing a clean error beats a 500 stacktrace
            logger.exception("MLX-Whisper batch transcription failed (%s)", repo)
            raise HTTPException(status_code=500, detail=f"MLX-Whisper failed: {exc}") from exc

        segments = []
        for seg in result.get("segments", []):
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            segments.append({
                "start": float(seg.get("start", 0.0)),
                "end": float(seg.get("end", 0.0)),
                "text": text,
            })
        detected = result.get("language") or lang
        return render_segments(segments, response_format, detected, duration)


class ChunkFormerBatchBackend(BatchBackend):
    """ChunkFormer (Vietnamese CTC) via the isolated ``.venv-chunkformer`` subprocess.

    Configurable entirely through environment variables (no code change to switch):

    - ``CHUNKFORMER_PYTHON``  python interpreter   (default ``<root>/.venv-chunkformer/bin/python``)
    - ``CHUNKFORMER_SCRIPT``  transcribe script     (default ``<root>/scripts/chunkformer_transcribe.py``)
    - ``CHUNKFORMER_MODEL``   HF model id           (default ``khanhld/chunkformer-large-vie``)
    - ``CHUNKFORMER_DEVICE``  auto|mps|cpu|cuda      (default ``auto``)
    - ``CHUNKFORMER_TIMEOUT`` subprocess timeout (s) (default ``1800``)
    """

    id = "chunkformer"

    def __init__(self):
        self.python = os.environ.get("CHUNKFORMER_PYTHON", str(_REPO_ROOT / ".venv-chunkformer" / "bin" / "python"))
        self.script = os.environ.get("CHUNKFORMER_SCRIPT", str(_REPO_ROOT / "scripts" / "chunkformer_transcribe.py"))
        self.model = os.environ.get("CHUNKFORMER_MODEL", "khanhld/chunkformer-large-vie")
        self.device = os.environ.get("CHUNKFORMER_DEVICE", "auto")
        try:
            self.timeout = float(os.environ.get("CHUNKFORMER_TIMEOUT", "1800"))
        except ValueError:
            self.timeout = 1800.0

    @classmethod
    def available(cls) -> bool:
        python = os.environ.get("CHUNKFORMER_PYTHON", str(_REPO_ROOT / ".venv-chunkformer" / "bin" / "python"))
        script = os.environ.get("CHUNKFORMER_SCRIPT", str(_REPO_ROOT / "scripts" / "chunkformer_transcribe.py"))
        return Path(python).exists() and Path(script).exists()

    async def transcribe(self, audio_bytes, language, response_format):
        if not self.available():
            raise HTTPException(
                status_code=503,
                detail=(
                    "ChunkFormer backend is not available. Expected interpreter at "
                    f"'{self.python}' and script at '{self.script}'. Set up the .venv-chunkformer "
                    "environment (see docs/CHUNKFORMER_TEST.md)."
                ),
            )

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name

            proc = await asyncio.create_subprocess_exec(
                self.python, self.script, tmp_path,
                "--model", self.model,
                "--device", self.device,
                "--format", "json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(_REPO_ROOT),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                raise HTTPException(status_code=504, detail=f"ChunkFormer timed out after {self.timeout:.0f}s")

            if proc.returncode != 0:
                err = stderr.decode(errors="replace").strip()
                logger.error("ChunkFormer subprocess failed: %s", err)
                raise HTTPException(status_code=500, detail=f"ChunkFormer failed: {err[:500]}")

            raw = stdout.decode(errors="replace")
            data = _extract_json_payload(raw)
            if data is None:
                logger.error("ChunkFormer produced no JSON payload. stdout head: %s", raw[:500])
                raise HTTPException(status_code=500, detail="ChunkFormer produced unreadable output")
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        segments = chunkformer_json_to_segments(data)
        duration = segments[-1]["end"] if segments else 0.0
        # ChunkFormer is Vietnamese-only; report 'vi' rather than the requested language.
        return render_segments(segments, response_format, "vi", duration)


def get_batch_backend(model: str, transcription_engine) -> BatchBackend:
    """Route a batch request to a backend based on the requested ``model``.

    - ``model`` containing 'chunkformer'                 -> ChunkFormerBatchBackend
    - a known Whisper size (tiny/base/small/medium/      -> MlxWhisperBatchBackend
      large-v3-turbo) when MLX-Whisper is available          (runs that exact model)
    - anything else (incl. empty, 'whisper-1', or MLX    -> WhisperBatchBackend
      unavailable)                                           (in-process singleton)

    Keeping the empty default on the singleton Whisper backend preserves
    OpenAI-compatibility for existing callers (e.g. the OpenAI client sends 'whisper-1').
    """
    name = (model or "").strip().lower()
    if "chunkformer" in name:
        logger.info("Batch routing: ChunkFormer selected (requested_model=%r)", model)
        return ChunkFormerBatchBackend()
    if name in WHISPER_BATCH_MODELS:
        if MlxWhisperBatchBackend.available():
            logger.info("Batch routing: mlx-whisper selected (model=%s)", name)
            return MlxWhisperBatchBackend(name)
        logger.info(
            "Batch routing: FALLBACK to in-process Whisper singleton — requested "
            "'%s' but mlx-whisper is unavailable on this host (not Apple Silicon or "
            "mlx_whisper not installed).", name,
        )
        return WhisperBatchBackend(transcription_engine)
    logger.info(
        "Batch routing: in-process Whisper singleton (requested_model=%r -> default)",
        model,
    )
    return WhisperBatchBackend(transcription_engine)


def batch_backends_status() -> List[dict]:
    """List the batch backends offered to the UI, with availability, for ``/health``.

    Whisper sizes share one availability flag (MLX-Whisper present); ChunkFormer has
    its own (the isolated venv + script). The UI disables any entry reported unavailable.
    """
    whisper_ok = MlxWhisperBatchBackend.available()
    status = [{"id": m, "available": whisper_ok} for m in WHISPER_BATCH_MODELS]
    status.append({"id": "chunkformer", "available": ChunkFormerBatchBackend.available()})
    return status
