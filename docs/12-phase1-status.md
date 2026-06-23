# 12. Phase 1 (Audio MVP) — Build Status

> Outcome of executing [doc 11](11-implementation-plan.md). Functionally complete; one material performance
> finding to decide on before Phase 2/3.

## What was built (all tasks done)

| Task | Result |
|---|---|
| T1 env + weights | Python **3.12** venv (`.venv`), `faster-whisper 1.2.1` / `ctranslate2 4.8.0` installed cleanly; PhoWhisper-medium CT2 weights (1.4 GB fp16) in `models/`. Loads + transcribes ✅ |
| T2 audio decode | `src/vnstt/audio.py` — ffmpeg → 16 kHz mono float32; errors on no-audio/corrupt ✅ |
| T3 engine | `src/vnstt/engine/` — `ASREngine` protocol + `Segment`/`Word`; `FasterWhisperEngine` (int8, Silero VAD, word timestamps, anti-hallucination flags) ✅ |
| T4 orchestrator | `src/vnstt/transcribe.py` — incremental segment stream + **chars/sec hallucination filter** ✅ |
| T5 exporters | `src/vnstt/export.py` — TXT / SRT / VTT (well-formed, validated) ✅ |
| T6 CLI | `transcribe <file> --format txt,srt,vtt` ✅ |
| T7 smoke + perf | `tests/` 10 passed; RTF/memory measured ✅ (see finding) |

Correct output on the VN sample: `xin chào hôm nay là một ngày đẹp trời ở hà nội tôi đang thử nghiệm hệ
thống nhận dạng giọng nói tiếng việt trên máy tính apple silicon.` — `máy tính apple silicon` rendered correctly.

## Quality finding — hallucination on trailing silence (fixed)
Whisper fabricated confident garbage on the ~0.3 s tail (e.g. 47 chars in 0.08 s ≈ 590 chars/s). `no_speech_prob`
was 0.000 (useless), so we added an **engine-agnostic chars-per-second plausibility filter** (`>30 chars/s` on
text longer than 15 chars → drop) plus `condition_on_previous_text=False` and `hallucination_silence_threshold`.
Output is now clean; covered by pure unit tests.

## Performance finding — **CPU on Apple Silicon misses RTF<1** (decision needed)
- PhoWhisper-medium `int8`, CPU, on the dev **M3 / 16 GB**: same 9.85 s clip measured **RTF ≈ 2.3 in one run and ≈ 6.9 in the next**, peak RSS **3.3 GB**.
- Same code back-to-back → the variance is **thermal throttling** (base M3 is fanless-class); even the best case is **>2× slower than real-time**.
- **Implication:** batch file transcription is usable but slow (a 1 h file ≈ 2–7 h); this is the Stage-0-flagged "CPU-only faster-whisper on Mac" risk, now confirmed. It does **not** block the MVP's correctness, but it blocks the RTF<1 target and would hurt real-time mic (Phase 3).

### Options to address (for your call — this is the Phase-4 perf lever brought forward)
1. **whisper.cpp (Metal/CoreML)** — the documented fallback; offloads to the M3 GPU/ANE, sidesteps CPU thermal throttling. Same model, swapped behind the engine abstraction. *Most promising.*
2. **Smaller/faster model** — PhoWhisper-small, or the VN large-v3-**turbo** (4 decoder layers) — trade some accuracy for speed.
3. **CPU thread tuning** (`cpu_threads`, performance cores) — minor, won't overcome thermal limits.
4. **Accept for batch** — fine if the product targets background/offline file transcription, not interactive.

## Repo state
```
pyproject.toml · README.md · src/vnstt/{audio,transcribe,export,cli}.py · src/vnstt/engine/{__init__,faster_whisper}.py
tests/{test_export,test_transcribe,test_smoke}.py + fixtures/sample.wav · models/PhoWhisper-medium-ct2-fasterWhisper/
```
`stage0/` (throwaway probe + 3.14 venv) and `.venv-stage0/` can be deleted; not part of the product.

## Recommended next step
Given the RTF finding, **bring Phase 4 forward**: validate the **whisper.cpp-Metal** engine behind the existing
abstraction and re-measure RTF before building Phase 2 (video) or Phase 3 (mic). If Metal hits RTF<1, proceed to
video/mic on solid footing; if not, reconsider model size. This keeps us evidence-led rather than building more
surface area on a CPU path we already know is too slow.
