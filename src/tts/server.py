"""FastAPI sidecar exposing the TTS service over HTTP.

Runs as its own process in the VieNeu-TTS venv and is called cross-origin by the
STTLive web UI's "Text to Speech" tab. It shares nothing with the STT
(WhisperLiveKit) server.

Run it with::

    ./scripts/run_tts_server.sh
    # or: PYTHONPATH=src VieNeu-TTS/.venv/bin/python -m tts.server

Endpoints (JSON / audio):

    GET    /                    -> minimal info page
    GET    /tts/health          -> readiness + model/device/voices info
    GET    /tts/models          -> selectable models (q4/q8/ngochuyen) + active
    POST   /tts/model           -> switch the active model (reloads backbone)
    GET    /tts/voices          -> built-in preset voices for the active model
    POST   /tts/synthesize      -> one-shot text -> audio (wav/flac/mp3/...)
    GET    /tts/stream          -> low-latency streaming WAV (?text=&voice=&temperature=)
    POST   /tts/stream          -> streaming WAV for long text (JSON body)
    POST   /tts/extract_url     -> extract article text from a URL
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

from tts.config import TtsConfig
from tts.models import (
    ExtractUrlRequest,
    HealthResponse,
    ModelsResponse,
    SetModelRequest,
    StreamRequest,
    SynthesizeRequest,
    VoicesResponse,
)
from tts.service import TtsService
from tts.vieneu_engine import TtsModelNotLoaded

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("tts.server")

config = TtsConfig.from_env()
service = TtsService(config)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if config.eager_load:
        try:
            logger.info("Eager-loading VieNeu-TTS model...")
            service.ensure_loaded()
            logger.info("VieNeu-TTS model loaded.")
        except Exception as exc:  # don't crash the server; surface via /health
            logger.error("Eager load failed: %s", exc)
    yield


app = FastAPI(title="STTLive TTS (VieNeu-TTS)", version="0.3.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origin_list(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _audio_response(data: bytes, mime: str, *, filename: str) -> Response:
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@app.get("/", response_class=HTMLResponse)
async def index():
    h = service.health()
    state = "loaded" if h["model_loaded"] else (
        "model cached (lazy load on first request)"
        if h["checkpoints_present"]
        else "model NOT cached (downloads on first request)"
    )
    return (
        "<html><body style='font-family:sans-serif;max-width:640px;margin:40px auto'>"
        "<h2>STTLive TTS sidecar (VieNeu-TTS)</h2>"
        f"<p>Status: <b>{state}</b></p>"
        f"<p>Model: {h.get('model_key')} ({h.get('backbone')}) &middot; Device: "
        f"{h.get('device') or config.backbone_device} &middot; {h.get('precision')}</p>"
        f"<p>Voices: {h.get('n_voices')} &middot; default: {h.get('default_voice')}</p>"
        "<p>Use the <b>Text to Speech</b> tab in the STTLive UI.</p>"
        "</body></html>"
    )


@app.get("/tts/health", response_model=HealthResponse)
async def health():
    return JSONResponse(service.health())


@app.get("/tts/models", response_model=ModelsResponse)
async def list_models():
    return ModelsResponse(models=service.list_models())


@app.post("/tts/model")
async def set_model(req: SetModelRequest):
    try:
        return JSONResponse(service.switch_model(req.model_key))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TtsModelNotLoaded as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("Model switch failed")
        raise HTTPException(status_code=500, detail=f"Model switch failed: {exc}")


@app.get("/tts/voices", response_model=VoicesResponse)
async def list_voices():
    # Built-in voices come from the model; load it (best-effort) so the UI's
    # dropdown is populated. Degrades to an empty list if the model can't load.
    try:
        service.ensure_loaded()
    except Exception as exc:  # noqa: BLE001 - surfaced via /tts/health instead
        logger.warning("Voice listing could not load the model: %s", exc)
    return VoicesResponse(voices=service.list_voices())


@app.post("/tts/synthesize")
async def synthesize(req: SynthesizeRequest):
    try:
        data, mime, _sr = service.synthesize(
            text=req.text,
            voice=req.voice,
            fmt=req.format,
            temperature=req.temperature,
            chunk_length=req.chunk_length,
            normalize=req.normalize,
        )
    except TtsModelNotLoaded as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("Synthesis failed")
        raise HTTPException(status_code=500, detail=f"Synthesis failed: {exc}")
    return _audio_response(data, mime, filename=f"speech.{req.format}")


def _stream_response(text, voice, temperature, normalize):
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty.")
    try:
        service.ensure_loaded()
    except TtsModelNotLoaded as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    gen = service.stream(text=text, voice=voice, temperature=temperature, normalize=normalize)
    return StreamingResponse(gen, media_type="audio/wav")


@app.get("/tts/stream")
async def stream_get(text: str, voice: str = None, temperature: float = None):
    return _stream_response(text, voice, temperature, None)


@app.post("/tts/stream")
async def stream_post(req: StreamRequest):
    return _stream_response(req.text, req.voice, req.temperature, req.normalize)


@app.post("/tts/extract_url")
async def extract_url(req: ExtractUrlRequest):
    return JSONResponse(service.extract_url(req.url, max_chars=req.max_chars))


def main():
    import uvicorn

    logger.info(
        "Starting TTS sidecar on %s:%s (engine=vieneu, model=%s, device=%s)",
        config.host, config.port, config.backbone_repo, config.backbone_device,
    )
    if not config.model_cached():
        logger.warning(
            "VieNeu backbone %s not found in the HF cache. The server will start "
            "but the model will be downloaded on first request (needs network).",
            config.backbone_repo,
        )
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
