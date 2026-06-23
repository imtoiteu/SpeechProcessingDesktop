# 11. Implementation Plan — Phase 1 (Audio MVP)

> Spec-driven PLAN/TASKS for the path chosen in [doc 10](10-implementation-decision.md). This is planning, not
> code. Coding starts on your go-ahead. Scope here is the **MVP only**: local audio files → VN transcript →
> TXT/SRT/VTT, incremental output, CLI.

## Objective & success criteria

Transcribe a local Vietnamese audio file (`wav/mp3/m4a/flac`) to text with timestamps and export TXT/SRT/VTT,
emitting segments incrementally, from a CLI. **Done when:**

1. `transcribe sample.mp3 --format srt,vtt,txt` produces all three files with correct Vietnamese text.
2. SRT/VTT pass a format validator (monotonic, well-formed cues).
3. Word/segment timestamps are present and monotonic.
4. Runs on the dev M3 at **RTF < 1.0** with PhoWhisper-medium `int8` (target, to confirm in T7).
5. Engine is accessed only through the abstraction (no faster-whisper symbols outside `engine/`).

## Tech stack (locked for Phase 1)

- **Python 3.12** (pinned; `uv` for env/deps) — *not* 3.14.
- **faster-whisper** (CTranslate2), `compute_type="int8"`, `device="cpu"` on Mac.
- **PhoWhisper-medium** CT2 weights — `quocphu/PhoWhisper-ct2-FasterWhisper` (or convert `vinai/PhoWhisper-medium` via `ct2-transformers-converter`).
- **ffmpeg** (installed) for decode.
- **Silero VAD** via faster-whisper `vad_filter=True`.
- Stdlib + small deps only for exports.

## Proposed project structure

```
Speech2Text/
├── pyproject.toml            # uv project, pin python 3.12, deps, CLI entry point
├── src/vnstt/
│   ├── __init__.py
│   ├── audio.py              # ffmpeg decode → 16kHz mono float32 (and format sniffing)
│   ├── engine/
│   │   ├── __init__.py       # ASREngine protocol + Segment/Word dataclasses + factory
│   │   └── faster_whisper.py # FasterWhisperEngine (the one Phase-1 impl)
│   ├── transcribe.py         # orchestrates decode → engine → Iterator[Segment] (incremental)
│   ├── export.py             # TXT / SRT / VTT formatters
│   └── cli.py                # `transcribe` command
├── tests/
│   ├── fixtures/sample.wav   # the 9.85s VN clip already generated in stage0/
│   ├── test_export.py        # SRT/VTT/TXT formatting (pure, no model)
│   └── test_smoke.py         # integration: transcribe sample → non-empty VN text
└── docs/                     # existing planning docs
```
*(The `stage0/` throwaway probe + venv stay separate and can be deleted; they are not part of the product.)*

## Engine abstraction (the one interface that must be right)

```python
# engine/__init__.py  — sketch, not final code
from dataclasses import dataclass
from typing import Protocol, Iterator, Union
import numpy as np

@dataclass
class Word:    start: float; end: float; text: str
@dataclass
class Segment: start: float; end: float; text: str; words: list[Word]

class ASREngine(Protocol):
    def transcribe(self, audio: Union[str, np.ndarray], *,
                   language: str = "vi") -> Iterator[Segment]: ...
```
`FasterWhisperEngine` wraps `WhisperModel(path, device="cpu", compute_type="int8")` and adapts its
`transcribe(..., vad_filter=True, word_timestamps=True, language="vi")` output into our `Segment` stream.
Everything downstream (transcribe orchestrator, exporters, CLI) depends only on `ASREngine`/`Segment` — so the
whisper.cpp fallback later is a new class, not a rewrite.

## Task breakdown (ordered by dependency)

- [ ] **T1 — Bootstrap env + weights**
  - Acceptance: `uv`-managed **Python 3.12** venv; `import faster_whisper` works; PhoWhisper-medium CT2 weights present locally.
  - Verify: load the model and transcribe `tests/fixtures/sample.wav` → Vietnamese text printed.
  - Files: `pyproject.toml`, `README` setup section.
- [ ] **T2 — Audio decode**
  - Acceptance: decode `wav/mp3/m4a/flac` → 16 kHz mono float32 via ffmpeg; clear error on no-audio/corrupt input.
  - Verify: `test` decoding the sample + a generated mp3/m4a/flac; assert shape/rate.
  - Files: `src/vnstt/audio.py`.
- [ ] **T3 — Engine abstraction + FasterWhisperEngine**
  - Acceptance: `transcribe()` yields `Segment`s with `words` and monotonic timestamps for the sample.
  - Verify: run on sample; assert non-empty VN text and `0 <= w.start <= w.end`.
  - Files: `src/vnstt/engine/__init__.py`, `src/vnstt/engine/faster_whisper.py`.
- [ ] **T4 — Incremental transcribe orchestrator**
  - Acceptance: streams segments as decoded (generator), prints each on arrival.
  - Verify: observe incremental console output on the sample.
  - Files: `src/vnstt/transcribe.py`.
- [ ] **T5 — Exporters TXT / SRT / VTT**
  - Acceptance: well-formed SRT (`HH:MM:SS,mmm`) and VTT (`WEBVTT` + `HH:MM:SS.mmm`); TXT plain/with-timestamps.
  - Verify: `test_export.py` parses output (regex/subtitle lib) on synthetic segments — pure, no model needed.
  - Files: `src/vnstt/export.py`.
- [ ] **T6 — CLI**
  - Acceptance: `transcribe <file> --format srt,vtt,txt --model <path>` writes the requested files.
  - Verify: run end-to-end on the sample; files exist and validate.
  - Files: `src/vnstt/cli.py`, `pyproject.toml` entry point.
- [ ] **T7 — Smoke + RTF check on dev Mac**
  - Acceptance: integration smoke test green; record RTF + peak memory at PhoWhisper-medium int8.
  - Verify: `test_smoke.py`; note whether RTF < 1.0 (informs Phase-3 latency planning).
  - Files: `tests/test_smoke.py`.

## Testing strategy (lightweight, not the benchmark harness)

- `pytest`. Pure unit tests for `export` (no model) and `audio` (decode). One integration smoke test
  (transcribe the 9.85 s sample → non-empty Vietnamese). No accuracy/WER measurement here — that's Stage 1.

## Boundaries

- **Always:** keep the engine behind `ASREngine`; pin Python 3.12; keep `int8` CPU default on Mac; cite model license in README.
- **Ask first:** adding a heavy dependency; changing the default model; wiring real-time mic or video early.
- **Never:** import faster-whisper outside `engine/`; commit model weights; hardcode a single engine in CLI/business logic.

## Risks carried into Phase 1 (and first-task mitigations)

1. **faster-whisper/CT2 install** — T1 validates it on Python 3.12 immediately; if it fails, fall back to the proven transformers+MPS engine behind the same abstraction (the interface is identical).
2. **CT2 PhoWhisper weights** — pre-converted repo exists; if unusable, convert from `vinai/PhoWhisper-medium` with `ct2-transformers-converter` (one command).
3. **Timestamp sync** — record timing sanity in T7; full timing-accuracy benchmark deferred to Stage 1.

## To start coding I need from you

1. **Go-ahead** to write code (you've gated each step so far).
2. **Names** — OK to use package `vnstt` + CLI command `transcribe`? (easy to change.)
3. **Weights** — should I download the CT2 PhoWhisper-medium weights (~1–1.5 GB int8/fp16) during T1, or will you place them? (You control downloads per the last instruction.)
