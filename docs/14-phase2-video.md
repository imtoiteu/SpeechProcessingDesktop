# 14. Phase 2 — Video support

> Exit criterion (doc 10): *video → subtitles through the identical path; no pipeline duplication.* **Met.**

## Outcome
Video (`mp4`, `mov`, `mkv`) transcribes through the **exact same pipeline** as audio — **zero new pipeline
code**. This validates the shared-pipeline architecture: `decode_audio()` already shells out to ffmpeg, which
extracts a video's audio stream identically to decoding an audio file.

- `transcribe tests/fixtures/sample.mp4 --format srt` → correct VN transcript + subtitles in ~2 s (whisper.cpp/Metal).
- mov and mkv decode identically (verified).

## Small fixes made during Phase 2
1. **Timestamp clamp** (`transcribe._clamp_to_duration`) — whisper.cpp inflated a short segment's end to its
   30 s decode window, producing a `00:00:30,000` SRT cue for a 10 s clip. The orchestrator knows the true audio
   duration, so segment/word times are now clamped to it. SRT end is now `00:00:09,856`. (Engine-agnostic; also
   tightens the hallucination filter.)
2. **No-audio-track handling** — a video with no audio stream raises a clear `AudioDecodeError` (tested).
3. CLI input help + README updated to list video formats.

## Tests
**16 pass** (5 new): decode mp4/mov/mkv, no-audio-track error, end-to-end video transcription with clamped timestamps.

## Notes / still deferred
- A short single-utterance clip yields one long cue; real multi-segment content gets proper per-segment boundaries.
- whisper.cpp word-level timestamps remain segment-level (per [doc 13](13-whisper-cpp-metal.md)); fine for SRT/VTT now.
- Large-video memory: `decode_audio` reads full PCM into memory (~1.2 MB/min @16 kHz mono) — fine for typical files; streaming decode is a future item for multi-hour inputs.
- Still ahead: Phase 3 (real-time mic), whisper.cpp-vs-faster-whisper **accuracy A/B**, optional correction LLM.
