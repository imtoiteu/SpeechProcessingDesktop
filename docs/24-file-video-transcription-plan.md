# Plan: Audio/Video File Transcription on WhisperLiveKit (extend, don't rebuild)

Status: PLAN ONLY — not implemented. Baseline confirmed working: live mic, turbo · mlx-whisper · SimulStreaming · Apple Silicon.

Principle: reuse the existing WhisperLiveKit (WLK) vanilla-JS frontend + FastAPI/WS backend. No Gradio/React/new frameworks. Minimal divergence from upstream. All findings below verified from source (file:line).

---

## 0. The three facts that determine the whole design

1. **Batch already exists and already handles video.** `POST /v1/audio/transcriptions` (`basic_server.py:249-317`) decodes any container via a one-shot ffmpeg (`_convert_to_pcm`, `basic_server.py:145-161` — no `-f`/codec on input, so mp4/mov/mkv/webm demux transparently) and returns `verbose_json`/`srt`/`vtt` with **real numeric segment timestamps** (`basic_server.py:194-199`). Zero backend change for short/medium files. **But** it reads the whole file + whole decoded PCM into RAM (`:265,271`) and has a hard **120 s** wall-clock timeout (`:304`) → unusable for 1–3 h recordings.

2. **Streaming already exists, is source-agnostic, and scales.** `WS /asr` (`basic_server.py:70-126`) just does `receive_bytes() → process_audio(bytes)`; it doesn't care if bytes are mic or file. ffmpeg decodes them server-side (video included). Memory is bounded (sliding-window, see fact 3). It is **not** realtime-throttled — it processes as fast as bytes arrive / ASR can run, and uses *audio-stream time*, not wall-clock, for segmentation (`tokens_alignment.py:216-227`) — explicitly built for faster-than-realtime feeding. **This is the path for long files**, and it is purely a frontend change to feed it file bytes.

3. **The server forgets everything older than 5 minutes.** `_prune_state_tokens` (`audio_processor.py:219-236`) and `tokens_alignment._prune` (`:57-83`) drop tokens AND finished lines beyond `_retention_seconds = 300.0`. So after a 2 h file the server's `lines` payload only covers the last ~5 min. **"Timestamps remain usable after completion" is therefore false at the server layer** — the **frontend must accumulate all committed lines client-side**. This client-side transcript store is the keystone that also powers copy/export/clear and long-file navigation.

---

## 1. Proposed UI layout & user workflow

Single inlined page (`live_transcription.html` + `live_transcription.js`, inlined by `web_interface.py:16-94` — no build step). Add a left media column and a right transcript column; keep the existing top bar.

```
┌──────────────────────────────────────────────────────────────┐
│ [● Record(mic)]  [Source: Mic | File]  [Mode: Batch | Stream] │  ← reuse .segmented pill pattern (html:45-64)
│ [⚙ settings]                                  [drop / choose file] │
├───────────────────────────────┬──────────────────────────────┤
│  MEDIA (left)                 │  TRANSCRIPT (right)           │
│  <video id=mediaPlayer controls>│  [Copy] [Export .txt] [Clear]│
│   plays uploaded file locally  │  [☑ Show timestamps]          │
│   (object URL) — independent   │                              │
│   of transcription             │  0:00:03 ▸ Xin chào…          │  ← timestamp chip = clickable seek
│                               │  0:00:07 ▸ hôm nay…           │
│                               │  …live buffer (streaming)…    │
└───────────────────────────────┴──────────────────────────────┘
```

Workflows:
- **Mic** (unchanged): existing `recordButton` → `WS /asr`.
- **File · Batch**: choose file → (optional) shows in player → `fetch('/v1/audio/transcriptions', verbose_json)` → render full transcript when done. Best for short/medium clips.
- **File · Streaming**: choose file → player gets object URL (user can play/pause/seek/ignore) → in parallel, file bytes streamed to `WS /asr` → lines appear progressively, accumulated client-side. Best for long files; satisfies the "playback ⟂ transcription" UX requirement natively (player is a local element; transcription is a separate server stream — neither follows the other).
- Clicking any timestamp chip → `mediaPlayer.currentTime = start_s`. Works during and after transcription.

---

## 2. Existing components/APIs reused (the reuse ledger)

| Need | Reused as-is | Source |
|---|---|---|
| Batch audio+video transcription w/ timestamps | `POST /v1/audio/transcriptions` (`verbose_json`) | `basic_server.py:249-317,194-199` |
| Progressive file transcription | `WS /asr` (source-agnostic bytes) | `basic_server.py:70-126` |
| Container→PCM (audio & video) | ffmpeg in both paths (no per-format code) | `ffmpeg_manager.py:60-70`, `basic_server.py:145-161` |
| FrontData stream shape the UI already parses | `lines[], buffer_transcription, status…` | `live_transcription.js:309-328`, `timed_objects.py:196-209` |
| Segment text + (string) timestamps already rendered | `renderLinesWithBuffer` | `live_transcription.js:333-467,383-385` |
| Segmented-pill control pattern + CSS | `.segmented` radiogroup | `live_transcription.html:45-64`, css:322-383 |
| Inlining of new HTML/CSS/JS (no build) | `get_inline_ui_html()` | `web_interface.py:16-94` |

What does **not** exist and must be added (all frontend): file `<input>`, `<video>` player, source/mode toggles, timestamp click-seek, copy/export/clear, and the **client-side transcript store**.

---

## 3. Backend changes required

Goal: keep divergence near-zero. Only two changes, both additive.

- **(Required, tiny) Numeric timestamps on the WS path.** WS `lines` carry only `"H:MM:SS.cc"` strings (`timed_objects.py:159-166` via `format_time`). Numeric seconds already exist on `Segment.start/end`; they're dropped only at `to_dict()`. Add `start_s`/`end_s` floats in `Segment.to_dict()` (`timed_objects.py:159-166`) — additive, non-breaking (frontend ignores unknown keys today). Avoids brittle client-side string parsing. (Batch `verbose_json` already has numeric seconds — no change there.)
- **(Recommended for long batch, optional) Raise/parameterize the 120 s batch timeout** (`basic_server.py:304`) and/or stream-decode instead of whole-file RAM (`:265,271`). *Preferred alternative: don't fix batch for long files — route long files to streaming mode*, which is already memory-safe. Decide per appetite for upstream divergence.

Explicitly **not** required: no new routes for streaming-file (reuse `/asr`), no ffmpeg changes (video already works), no changes to the streaming core, VAD, or model config.

---

## 4. Frontend changes required

All in `live_transcription.html` (DOM) + `live_transcription.js` (behavior); auto-inlined.

1. **Client-side transcript store (keystone).** Maintain an ordered map of committed lines keyed by stable id (e.g. `start_s` rounded, or running index) as FrontData arrives (`onmessage`, `live_transcription.js:307-328`). Never rely on the server payload for history (it prunes to 5 min). This store backs rendering, copy, export, clear, and post-completion navigation.
2. **File input + source/mode toggles.** Add `<input type=file accept="audio/*,video/*">` and two `.segmented` radiogroups (Source: Mic/File, Mode: Batch/Stream). Clone existing pill markup/CSS.
3. **Media player.** `<video id=mediaPlayer controls>` (a `<video>` element also plays audio) sourced via `URL.createObjectURL(file)`. Plays entirely locally → inherently decoupled from transcription.
4. **Batch path.** `FormData` → `fetch('/v1/audio/transcriptions?response_format=verbose_json')` → fill store from `segments[]` (numeric `start/end`) → render.
5. **Streaming path.** Open `WS /asr`; read the File in chunks (`Blob.slice` → `arrayBuffer`) and `websocket.send()` each (with backpressure on `ws.bufferedAmount`); send empty frame for EOF (mirrors mic stop, `live_transcription.js:652-654`). Feed independent of player. Append lines to store as they commit.
6. **Timestamp chips + seek.** Render each line's `start` as a clickable chip carrying `data-seconds=start_s`; on click `mediaPlayer.currentTime = +chip.dataset.seconds`. Add a "Show timestamps" toggle.
7. **Copy / Export .txt / Clear.** Build text from the store (`lines.map(l=>l.text).join('\n')`); Copy=`navigator.clipboard.writeText`, Export=`Blob`+`<a download>`, Clear=reset store + `innerHTML=''` + reset the render-signature cache (`live_transcription.js:25-26,363-371`).
8. **Long-transcript render perf.** Current render rebuilds `innerHTML` wholesale every ~50 ms (`live_transcription.js:462`). For multi-hour transcripts switch to incremental append (only new/changed lines) or windowed rendering.

---

## 5. REST vs WebSocket reuse — verdict

- **Batch → reuse REST `/v1/audio/transcriptions`** as-is for short/medium audio **and video** (verbose_json gives numeric segment timestamps). No backend change.
- **Streaming → reuse WS `/asr`** as-is for audio **and video**; it's source-agnostic and ffmpeg-decoded. No backend change.
- Both endpoints already exist and cover all four feature combinations (audio/video × batch/streaming). The only optional endpoint work is the long-file batch timeout (§3), which streaming sidesteps.

---

## 6. Complexity per feature

| Feature | Backend | Frontend | Overall |
|---|---|---|---|
| Batch audio transcription | none (exists) | S (input + fetch + render) | **S** |
| Batch video transcription | none (ffmpeg demuxes) | S (+ `<video>`) | **S** |
| Video display in UI | none | S (objectURL) | **S** |
| Copy / Export / Clear | none | S (on store) | **S** |
| Timestamp display | tiny (`start_s/end_s`) | S | **S** |
| Click-to-seek (segment-level) | uses `start_s` | S–M | **S–M** |
| Streaming audio file | none | M (stream + accumulate) | **M** |
| Streaming video file | none | M (+ player + mp4 edge case) | **M** |
| Client-side transcript store (keystone) | none | M | **M** |
| Long-file (1–3 h) hardening | maybe (batch timeout) | M (incremental render) | **M** |
| Word-level click-to-seek | real ASR alignment work | — | **L (out of scope)** — word timestamps are interpolated/fake (`basic_server.py:200-209`); only segment-level seek is accurate |

---

## 7. Recommended implementation order

1. **Keystone first:** client-side transcript store + add `start_s/end_s` to `Segment.to_dict()`. Unblocks everything; no UI risk.
2. **Transcript usability:** Copy / Export / Clear on the store (works for the existing mic flow immediately — quick visible win, no media needed).
3. **Timestamp chips + show/hide** for the mic flow (no player yet → chips inert or scroll-only).
4. **Batch file (audio+video):** file input + source/mode toggles + `<video>` player + REST fetch + click-seek via verbose_json. Self-contained, highest reuse, demonstrates end-to-end value.
5. **Streaming file (audio+video):** stream bytes to `/asr` + decoupled player + progressive append. Builds on the store; delivers the long-file path.
6. **Long-file hardening:** incremental rendering, mp4 edge-case handling, backpressure, UX for "still processing".

Rationale: each step ships independently, earliest steps de-risk the keystone and reuse the most, media/player complexity is deferred until the data layer is proven.

---

## 8. Risks, edge cases, performance (1–3 h recordings)

- **[High] 5-minute server pruning** (`audio_processor.py:219-236`, `tokens_alignment.py:57-83`, `_retention_seconds=300`). Mitigation: client-side accumulation (keystone). Without it, long-file navigation and full export are impossible.
- **[High] Batch unsuitable for long files:** whole-file + whole-PCM in RAM (3 h ≈ ~345 MB PCM, `basic_server.py:265,271`) and 120 s timeout truncation (`:304`). Mitigation: route long files to **streaming**; only raise the timeout if batch-for-long is truly wanted.
- **[Med] Non-faststart MP4 over a pipe:** ffmpeg from `pipe:0` can't seek, so an mp4 with `moov` at the end won't decode until fully received → streaming degrades to batch-like latency (still correct). Mitigation: stream anyway (correct, just delayed), document it, or (later) client-side remux to faststart / extract audio.
- **[Med] Large WS transfer of video bytes:** sending GB-scale containers over WS. Mitigation: chunked `send()` gated on `ws.bufferedAmount`; consider client-side audio extraction (WebAudio/`MediaRecorder`) to shrink payload — more complex, defer.
- **[Med] DOM perf for thousands of lines:** wholesale `innerHTML` rebuild every ~50 ms (`live_transcription.js:462`) is O(lines)/tick. Mitigation: incremental append / windowed render (step 6).
- **[Med] Faster-than-realtime burst quality:** streaming policies are tuned for live cadence; bursting a file is supported but commit/stability under burst is unvalidated. We're on **SimulStreaming** now (has repetition guards) — re-validate on a long real file before relying on it.
- **[Low] Word-level seek inaccurate:** word timestamps interpolated, not aligned — keep seek at segment granularity.
- **[Low] Detected-language badge in forced mode** echoes the configured `lan` (e.g. `vi`), not a detection, unless `--language auto`.
- **[Low] Single shared engine (singleton):** mic + file at once contend for one model; fine for single-user local use, but disable mic while a file streams to avoid surprise.

---

### One-line summary
Batch (audio+video) is essentially free via the existing REST endpoint; streaming (audio+video) is free on the backend via the existing `/asr` WS; **the real work is a thin client-side layer** (transcript store + file feeding + player + timestamp chips + copy/export/clear), plus a two-field additive backend tweak for numeric WS timestamps. The single hard constraint shaping all of it is the server's 5-minute memory window, which the client-side store resolves.
