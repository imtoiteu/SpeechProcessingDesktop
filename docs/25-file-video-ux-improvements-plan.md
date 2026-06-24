# Plan: Language selector, explicit Start, video fix, model selector (extend WLK)

Status: ✅ IMPLEMENTED + verified end-to-end (2026-06-23). All four backend changes (A–D) plus the
frontend changes are in. Headless verification (`scripts/verify_ux_improvements.py`) passes: batch
video (moov@end MP4 → clean Vietnamese transcript), `/asr/file` streaming video (same clean
transcript, progressive), and per-session language (`en→en`, `vi→vi`, `auto→vi`-detected; the old
"everything→vi" bug is gone). `/health` now exposes `model`. `node --check` + `py_compile` pass;
29/29 runnable WLK tests pass (3 async tests skip only because pytest-asyncio isn't installed).
Original plan + verified analysis below.
Constraint: extend the existing WhisperLiveKit vanilla HTML/CSS/JS + FastAPI/WS. No React/Gradio. Minimal divergence.
Current running server: `whisperlivekit-server --model large-v3-turbo --backend mlx-whisper --backend-policy simulstreaming --language vi` (port 8000). Edits to `web/*.{html,css,js}` are picked up on page reload (inliner reads disk per request); `timed_objects.py` / `basic_server.py` / `simul_whisper/backend.py` changes need a server restart.

## Verified facts (empirical, this session)
1. **Video root cause (NOT frontend):** server decodes via non-seekable pipe `ffmpeg -i pipe:0` in BOTH paths — `_convert_to_pcm` (basic_server.py:148, batch) and `FFmpegManager` (ffmpeg_manager.py:60-70, streaming). MP4/MOV with `moov` atom at END (default for most encoders/phones) → pipe decode yields **0 bytes, "partial file"**. Faststart MP4 (moov@front) via pipe → OK. Default MP4 via FILE input (`-i tempfile`, seekable) → OK. Audio (wav/mp3) needs no seek → always worked. FIX = seekable temp file.
2. **Per-session language ignored by SimulStreaming:** `SessionASRProxy` only overrides `original_language` during `transcribe()` (session_asr_proxy.py:33-41); SimulStreaming's `transcribe()` is a no-op (backend.py:562-566) and it builds tokenizer/detection from `cfg.language` set at engine init (align_att_base.py:66-68). Tested: `?language=en|vi|auto` on a Vi clip ALL returned Vi with badge `vi`. Works for LocalAgreement only.
3. **Model = restart:** `TranscriptionEngine` singleton built once at lifespan (basic_server.py:24); `reset()` is test-only. No dynamic switch.
4. UI badge already reads `detected_language` per line (live_transcription.js ~398); forced→`cfg.language`, auto→detected. So badge auto-reflects mode once language plumbing works.

## Backend changes (contained)
A. **Batch video fix** — `_convert_to_pcm` (basic_server.py:145-161): write `audio_bytes` to a `tempfile.NamedTemporaryFile`, run `ffmpeg -i <path> -f s16le -acodec pcm_s16le -ar 16000 -ac 1 -loglevel error pipe:1` (seekable), unlink in finally. Fixes ALL batch video.

B. **New WS `/asr/file`** (basic_server.py, after `/asr`) — robust streaming for audio+video+long files:
   - accept; read query `language`; build `AudioProcessor(transcription_engine, language=…)`, set `is_pcm_input=True`.
   - send `{"type":"config","useAudioWorklet":false,"mode":"full"}`; `results_gen = await ap.create_tasks()`; spawn `handle_websocket_results(ws, results_gen)`.
   - receive_bytes loop → write to a temp file until empty-frame EOF.
   - then `ffmpeg -i <tempfile> -f s16le … pipe:1` (seekable → handles moov@end); read stdout in ~32000-byte (~1 s) chunks → `await ap.process_audio(chunk)`; then `process_audio(b"")`; await results task.
   - finally: unlink temp, `ap.cleanup()`. Reuses AudioProcessor + handle_websocket_results fully. Streams PCM in chunks (no whole-file RAM; no 120 s cap) → safe for 1–3 h.

C. **SimulStreaming per-session language** — `SimulStreamingOnlineProcessor.__init__` (simul_whisper/backend.py:48-71): before `_create_alignatt()`, compute a per-session cfg:
   ```py
   import dataclasses
   sess = getattr(self.asr, "_session_language", "__unset__")  # only SessionASRProxy has it; None==auto
   cfg = self.asr.cfg
   if sess != "__unset__":
       lang = sess if sess is not None else "auto"
       if lang != cfg.language: cfg = dataclasses.replace(cfg, language=lang)
   self._session_cfg = cfg
   ```
   `_create_alignatt` uses `self._session_cfg` instead of `self.asr.cfg`. `process_iter` already reads `self.model.cfg.language` (the AlignAtt's cfg) — consistent. Shared torch model untouched; only tokenizer/SOT/detection differ. ~12 lines.

D. **Expose model in /health** (basic_server.py:46-50): add `"model": getattr(transcription_engine.config,"model_size",None)` for UI preselect.

## Frontend changes (live_transcription.{html,css,js})
- **Language selector**: `<select id="languageSelect">` from a JS list `LANGUAGES=[{code:'auto',label:'Auto Detect'},{code:'vi',label:'Vietnamese'},{code:'en',label:'English'}]` (extensible). Default `auto`. Pass `?language=<code>` on every WS connect (mic via setupWebSocket URL; file via /asr/file) and as `language` form field on batch REST. Persist in localStorage.
- **Model selector**: `<select id="modelSelect">` from `MODELS=['large-v3-turbo']` (extensible; PhoWhisper later = add string). Preselect from `/health`.model. On change to a non-running model → status note: "Restart server with --model <x> (model can't hot-swap)". No hot-swap.
- **Explicit Start (req 2)**: file `change` → set player src + preview ONLY (do not transcribe). Enable a `#startBtn` "Start Transcription". Start reads mode/language/model, then: streaming → open `/asr/file?language=…` and stream file bytes; batch → POST REST (+language). Keep `resetTranscriptStore()` at Start, not at file-select.
- **Routing**: file streaming → new `/asr/file` (NOT `/asr`, which can't decode moov@end progressively); file batch → `/v1/audio/transcriptions` (now temp-file fixed). Mic still uses `/asr`.

## UX tweaks (small, high-value)
- Group language/model/mode + Start into one controls row near the file button.
- Disable Start until a file is loaded; show "Transcribing… (lag)" status; keep Copy/Export/Clear + Timestamps toggle.
- For long files prefer Streaming (/asr/file) — note in UI tooltip.

## Verify (after implementing)
- ffmpeg: temp-file decode of /tmp/test_vid.mp4 (moov@end) → PCM > 0.
- node --check JS; py_compile; inliner produces new elements.
- restart server; batch curl mp4 (moov@end) → text; /asr/file headless WS with mp4 → progressive lines; language switch en/vi/auto changes badge+output; mic still works.

See memory [[wlk-extension-verified-facts]], [[model-decision-turbo]], [[repo-eval-streaming-stack]]. Prior file/video work: docs/24.
