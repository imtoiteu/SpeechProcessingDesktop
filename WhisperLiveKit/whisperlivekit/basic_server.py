import asyncio
import logging
import os
import tempfile
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse

from whisperlivekit import AudioProcessor, TranscriptionEngine, get_inline_ui_html, parse_args
from whisperlivekit.batch_backends import batch_backends_status, get_batch_backend
from whisperlivekit.config import parse_cors_origins

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logging.getLogger().setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

config = parse_args()
transcription_engine = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global transcription_engine
    transcription_engine = TranscriptionEngine(config=config)
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_cors_origins(config.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def get():
    return HTMLResponse(get_inline_ui_html())


@app.get("/health")
async def health():
    """Health check endpoint."""
    global transcription_engine
    backend = getattr(transcription_engine.config, "backend", "whisper") if transcription_engine else None
    model = getattr(transcription_engine.config, "model_size", None) if transcription_engine else None
    return JSONResponse({
        "status": "ok",
        "backend": backend,
        "model": model,
        "ready": transcription_engine is not None,
        # Batch (file) backends selectable from the UI (Whisper sizes + ChunkFormer).
        # Streaming always uses the in-process Whisper singleton chosen at startup.
        "batch_backends": batch_backends_status(),
    })


async def handle_websocket_results(websocket, results_generator, diff_tracker=None):
    """Consumes results from the audio processor and sends them via WebSocket."""
    try:
        async for response in results_generator:
            if diff_tracker is not None:
                await websocket.send_json(diff_tracker.to_message(response))
            else:
                await websocket.send_json(response.to_dict())
        # when the results_generator finishes it means all audio has been processed
        logger.info("Results generator finished. Sending 'ready_to_stop' to client.")
        await websocket.send_json({"type": "ready_to_stop"})
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected while handling results (client likely closed connection).")
    except Exception as e:
        logger.exception(f"Error in WebSocket results handler: {e}")


@app.websocket("/asr")
async def websocket_endpoint(websocket: WebSocket):
    global transcription_engine

    # Read per-session options from query parameters
    session_language = websocket.query_params.get("language", None)
    mode = websocket.query_params.get("mode", "full")

    audio_processor = AudioProcessor(
        transcription_engine=transcription_engine,
        language=session_language,
    )
    await websocket.accept()
    # Log which streaming backend/model serves this session (once, on open) so the
    # operator can confirm the live pipeline without enabling per-frame logging.
    _eng_cfg = getattr(transcription_engine, "config", None)
    logger.info(
        "Streaming /asr session opened — backend=%s model=%s language=%s mode=%s",
        getattr(_eng_cfg, "backend", None),
        getattr(_eng_cfg, "model_size", None),
        session_language or "auto",
        mode,
    )
    diff_tracker = None
    if mode == "diff":
        from whisperlivekit.diff_protocol import DiffTracker
        diff_tracker = DiffTracker()
        logger.info("Client requested diff mode")

    try:
        await websocket.send_json({"type": "config", "useAudioWorklet": bool(config.pcm_input), "mode": mode})
    except Exception as e:
        logger.warning(f"Failed to send config to client: {e}")

    results_generator = await audio_processor.create_tasks()
    websocket_task = asyncio.create_task(handle_websocket_results(websocket, results_generator, diff_tracker))

    try:
        while True:
            message = await websocket.receive_bytes()
            await audio_processor.process_audio(message)
    except KeyError as e:
        if 'bytes' in str(e):
            logger.warning("Client has closed the connection.")
        else:
            logger.error(f"Unexpected KeyError in websocket_endpoint: {e}", exc_info=True)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected by client during message receiving loop.")
    except Exception as e:
        logger.error(f"Unexpected error in websocket_endpoint main loop: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up WebSocket endpoint...")
        if not websocket_task.done():
            websocket_task.cancel()
        try:
            await websocket_task
        except asyncio.CancelledError:
            logger.info("WebSocket results handler task was cancelled.")
        except Exception as e:
            logger.warning(f"Exception while awaiting websocket_task completion: {e}")

        await audio_processor.cleanup()
        logger.info("WebSocket endpoint cleaned up successfully.")


@app.websocket("/asr/file")
async def websocket_file_endpoint(websocket: WebSocket):
    """Streaming transcription for uploaded audio/video files.

    The browser streams the raw container bytes (any ffmpeg-decodable format)
    followed by a single empty frame as the end-of-upload sentinel. We buffer the
    upload to a *seekable* temp file, then decode it with ffmpeg (``-i <file>``)
    and feed the resulting PCM into the standard AudioProcessor pipeline in ~1s
    chunks, streaming results back exactly like the live ``/asr`` endpoint.

    Why a temp file and not the live ``/asr`` pipe: decoding from a real file (not
    ``pipe:0``) lets ffmpeg seek to a moov atom at the end of the container, which
    is the default for most MP4/MOV encoders — the root cause of broken video.
    Streaming the PCM in chunks (rather than holding it all) plus qsize-based
    backpressure keeps memory bounded for multi-hour files.
    """
    global transcription_engine

    session_language = websocket.query_params.get("language", None)

    audio_processor = AudioProcessor(
        transcription_engine=transcription_engine,
        language=session_language,
    )
    # Bytes arriving here are an encoded container; we decode to PCM ourselves
    # below, so tell the processor its input is already PCM (skips ffmpeg_manager).
    audio_processor.is_pcm_input = True

    await websocket.accept()
    logger.info(
        "File WebSocket connection opened.%s",
        f" language={session_language}" if session_language else "",
    )

    try:
        await websocket.send_json({"type": "config", "useAudioWorklet": False, "mode": "full"})
    except Exception as e:
        logger.warning(f"Failed to send config to client: {e}")

    results_generator = await audio_processor.create_tasks()
    websocket_task = asyncio.create_task(handle_websocket_results(websocket, results_generator))

    tmp_path = None
    ffmpeg_proc = None
    try:
        # 1) Buffer the uploaded container to a seekable temp file (no whole-file RAM).
        with tempfile.NamedTemporaryFile(delete=False, suffix=".upload") as tmp:
            tmp_path = tmp.name
            while True:
                try:
                    message = await websocket.receive_bytes()
                except KeyError as e:
                    if "bytes" in str(e):
                        logger.warning("File client closed the connection before EOF sentinel.")
                        break
                    raise
                if message == b"":
                    break  # end-of-upload sentinel
                tmp.write(message)

        # 2) Decode the complete file (seekable -> handles moov@end) and stream PCM.
        ffmpeg_proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", tmp_path,
            "-f", "s16le", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            "-loglevel", "error",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stderr_chunks: List[bytes] = []

        async def _drain_stderr():
            try:
                while True:
                    buf = await ffmpeg_proc.stderr.read(4096)
                    if not buf:
                        break
                    stderr_chunks.append(buf)
            except Exception:
                pass

        stderr_task = asyncio.create_task(_drain_stderr())

        chunk_size = 16000 * 2  # ~1 second of 16kHz s16le mono
        while True:
            pcm_chunk = await ffmpeg_proc.stdout.read(chunk_size)
            if not pcm_chunk:
                break
            await audio_processor.process_audio(pcm_chunk)
            # Backpressure: keep the ASR queue bounded so multi-hour files don't
            # accumulate decoded PCM faster than the model can consume it.
            q = audio_processor.transcription_queue
            while q is not None and q.qsize() > 32:
                await asyncio.sleep(0.1)

        await ffmpeg_proc.wait()
        await stderr_task

        if ffmpeg_proc.returncode != 0:
            err = b"".join(stderr_chunks).decode(errors="replace").strip()
            logger.error(f"ffmpeg decode failed for uploaded file: {err}")
            try:
                await websocket.send_json({"type": "error", "message": f"Decode failed: {err[:200]}"})
            except Exception:
                pass

        # 3) Signal end-of-audio so the pipeline flushes and the results generator finishes.
        await audio_processor.process_audio(b"")

        # 4) Wait for the results handler to drain (it sends 'ready_to_stop').
        await websocket_task

    except WebSocketDisconnect:
        logger.info("File WebSocket disconnected by client.")
    except Exception as e:
        logger.error(f"Unexpected error in /asr/file endpoint: {e}", exc_info=True)
    finally:
        logger.info("Cleaning up /asr/file endpoint...")
        if ffmpeg_proc is not None and ffmpeg_proc.returncode is None:
            try:
                ffmpeg_proc.kill()
            except ProcessLookupError:
                pass
        if not websocket_task.done():
            websocket_task.cancel()
            try:
                await websocket_task
            except asyncio.CancelledError:
                logger.info("File WebSocket results handler task was cancelled.")
            except Exception as e:
                logger.warning(f"Exception while awaiting websocket_task completion: {e}")
        await audio_processor.cleanup()
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        logger.info("/asr/file endpoint cleaned up successfully.")


# ---------------------------------------------------------------------------
# Deepgram-compatible WebSocket API  (/v1/listen)
# ---------------------------------------------------------------------------

@app.websocket("/v1/listen")
async def deepgram_websocket_endpoint(websocket: WebSocket):
    """Deepgram-compatible live transcription WebSocket."""
    global transcription_engine
    from whisperlivekit.deepgram_compat import handle_deepgram_websocket
    await handle_deepgram_websocket(websocket, transcription_engine, config)


# ---------------------------------------------------------------------------
# OpenAI-compatible REST API  (/v1/audio/transcriptions)
# ---------------------------------------------------------------------------

@app.post("/v1/audio/transcriptions")
async def create_transcription(
    file: UploadFile = File(...),
    model: str = Form(default=""),
    language: Optional[str] = Form(default=None),
    prompt: str = Form(default=""),
    response_format: str = Form(default="json"),
    timestamp_granularities: Optional[List[str]] = Form(default=None),
):
    """OpenAI-compatible audio transcription endpoint (batch / file).

    Accepts the same parameters as OpenAI's /v1/audio/transcriptions API. The
    ``model`` field selects the batch backend (see ``batch_backends.get_batch_backend``):
    a value containing 'chunkformer' routes to the isolated ChunkFormer subprocess;
    anything else (incl. empty, for OpenAI-compatibility) uses the in-process Whisper engine.
    Streaming endpoints are unaffected.
    """
    global transcription_engine

    audio_bytes = await file.read()
    if not audio_bytes:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Empty audio file")

    requested_model = (model or "").strip() or "(default)"
    logger.info(
        "Batch transcription request received — requested_model=%r language=%s "
        "response_format=%s size=%d bytes",
        requested_model, language or "auto", response_format, len(audio_bytes),
    )

    # get_batch_backend() logs the routing decision (chunkformer / mlx-whisper /
    # fallback). We log the resolved backend id here and time the run.
    backend = get_batch_backend(model, transcription_engine)
    logger.info(
        "Batch backend selected — id=%s%s",
        backend.id,
        " [ChunkFormer Vietnamese]" if backend.id == "chunkformer" else "",
    )

    started = time.monotonic()
    try:
        result = await backend.transcribe(audio_bytes, language, response_format)
    except Exception:
        logger.exception(
            "Batch transcription FAILED after %.2fs (requested_model=%r backend=%s)",
            time.monotonic() - started, requested_model, backend.id,
        )
        raise
    logger.info(
        "Batch transcription finished — backend=%s elapsed=%.2fs",
        backend.id, time.monotonic() - started,
    )

    if isinstance(result, str):
        return PlainTextResponse(result)
    return JSONResponse(result)


@app.get("/v1/models")
async def list_models():
    """OpenAI-compatible model listing endpoint."""
    global transcription_engine
    backend = getattr(transcription_engine.config, "backend", "whisper") if transcription_engine else "whisper"
    model_size = getattr(transcription_engine.config, "model_size", "base") if transcription_engine else "base"
    return JSONResponse({
        "object": "list",
        "data": [{
            "id": f"{backend}/{model_size}" if backend != "whisper" else f"whisper-{model_size}",
            "object": "model",
            "owned_by": "whisperlivekit",
        }],
    })


def main():
    """Entry point for the CLI command."""
    import uvicorn

    from whisperlivekit.cli import print_banner

    ssl = bool(config.ssl_certfile and config.ssl_keyfile)
    print_banner(config, config.host, config.port, ssl=ssl)

    # The desktop status bar polls GET /health every few seconds, which otherwise
    # floods the uvicorn access log with `GET /health 200 OK`. Drop just those
    # access-log lines — real requests and errors are still logged normally.
    class _HealthAccessFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return "/health" not in record.getMessage()

    logging.getLogger("uvicorn.access").addFilter(_HealthAccessFilter())

    uvicorn_kwargs = {
        "app": "whisperlivekit.basic_server:app",
        "host": config.host,
        "port": config.port,
        "reload": False,
        "log_level": "info",
        "lifespan": "on",
    }

    ssl_kwargs = {}
    if config.ssl_certfile or config.ssl_keyfile:
        if not (config.ssl_certfile and config.ssl_keyfile):
            raise ValueError("Both --ssl-certfile and --ssl-keyfile must be specified together.")
        ssl_kwargs = {
            "ssl_certfile": config.ssl_certfile,
            "ssl_keyfile": config.ssl_keyfile,
        }

    if ssl_kwargs:
        uvicorn_kwargs = {**uvicorn_kwargs, **ssl_kwargs}
    if config.forwarded_allow_ips:
        uvicorn_kwargs = {**uvicorn_kwargs, "forwarded_allow_ips": config.forwarded_allow_ips}

    uvicorn.run(**uvicorn_kwargs)

if __name__ == "__main__":
    main()
