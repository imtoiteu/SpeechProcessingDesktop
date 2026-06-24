# first run
cd /Users/imtoiteu/Desktop/Speech2Text/VieNeu-TTS
uv sync

# stop the current server

lsof -ti :8000 | xargs kill

pkill -f whisperlivekit-server

# relaunch with auto-detect (badge will reflect the REAL spoken language; handles English)

whisperlivekit-server \
 --model large-v3-turbo \
 --backend mlx-whisper \
 --backend-policy simulstreaming \
 --language auto \
 --host localhost --port 8000




TTS — VieNeu-TTS (reuses the VieNeu-TTS venv; torch-free, model already cached)

cd VieNeu-TTS && uv sync          # one-time: torch-free core ('vieneu' SDK + deps)
# `uv sync` does NOT install these two (they live only in the heavy gpu group):
uv pip install --python .venv "llama-cpp-python==0.3.16" \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/metal/ \
    --index-strategy unsafe-best-match     # GGUF backbone (required)
uv pip install --python .venv "trafilatura>=2.0.0"   # URL extraction (optional)
cd ..
./scripts/download_tts_model.sh   # OPTIONAL: warm the HF cache (q4/q8/ngochuyen + ONNX codec)
./scripts/run_tts_server.sh       # sidecar on :8011 (preflights deps) → STT UI → "Text → Speech" tab
The model loads lazily on first request (or TTS_EAGER_LOAD=1). The tab offers
model selection (q4/q8/ngochuyen), all built-in Vietnamese voices, Text/URL input,
and streaming playback. NOTE: a later bare `uv sync` re-prunes llama-cpp-python —
re-run the two `uv pip install` lines if so.


kill 
pkill -f vieneu-stream    # or: lsof -nP -iTCP:8001 -sTCP:LISTEN
