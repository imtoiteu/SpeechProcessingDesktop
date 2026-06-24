#!/usr/bin/env python3
"""PoC: validate WhisperLiveKit's embeddable core for Vietnamese, on Apple Silicon.

Compares two ASR models through the SAME WhisperLiveKit streaming pipeline:
    1. whisper-large-v3-turbo   (mlx-community, auto-downloaded)
    2. PhoWhisper-medium        (you supply a converted MLX dir via --phowhisper-dir)

Fixed config (the validated path from the source review):
    backend_policy = "localagreement"   # re-transcribe + LocalAgreement-2 commit
    backend        = "mlx-whisper"       # Apple GPU (Metal) via MLX
    language (lan) = "vi"

Nothing in WhisperLiveKit is modified. We reuse, unchanged:
    TranscriptionEngine  -> loads the model once from config kwargs
    AudioProcessor       -> VAD -> buffer -> ASR -> transcript pipeline
    TestHarness          -> a thin, exported wrapper over those two (file feed + flush)

REUSE FOR GRADIO (later): the mic path uses the EXACT same two classes —
build ONE TranscriptionEngine at app start, create an AudioProcessor per
connection, push mic bytes with `await ap.process_audio(pcm_bytes)`, and
consume `await ap.create_tasks()` (an async generator of FrontData).
TestHarness.__aenter__/feed_pcm (test_harness.py:473-599) is the reference wiring.

------------------------------------------------------------------------------
RUN (inside the project's .venv, python 3.12):

    # installs WhisperLiveKit + its deps (torch, librosa, soundfile, tiktoken, ...)
    # plus the MLX backend. WLK requires-python >=3.11,<3.14, so 3.12 is fine.
    pip install -e ./WhisperLiveKit mlx-whisper
    # (if you skip the editable install, this script still imports whisperlivekit
    #  from the ./WhisperLiveKit clone via the sys.path bootstrap below, but you
    #  must install its deps yourself: torch torchaudio librosa soundfile tiktoken)

    # turbo only (smoke test the pipeline end-to-end):
    python scripts/poc_wlk_mlx_compare.py tests/fixtures/sample.wav

    # full comparison once PhoWhisper is converted to MLX:
    python scripts/poc_wlk_mlx_compare.py my_vietnamese.wav \
        --phowhisper-dir ./models/phowhisper-medium-mlx \
        --reference "đây là câu thoại đúng để tính WER"     # optional -> enables WER

CONVERSION REQUIREMENT (no pre-built MLX PhoWhisper exists):
    python -m mlx_whisper.convert \
        --torch-name-or-path vinai/PhoWhisper-medium \
        --mlx-path ./models/phowhisper-medium-mlx --dtype float16
    # verify flag names with: python -m mlx_whisper.convert --help

    Zero-conversion fallback (CPU, not Apple GPU): a pre-built CTranslate2 build
    exists (quocphu/PhoWhisper-ct2-FasterWhisper). Run this script with
    --backend faster-whisper --phowhisper-dir <ct2_dir> to use it through the
    identical harness.
------------------------------------------------------------------------------
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- bootstrap: import `whisperlivekit` from the sibling clone if not pip-installed ---
_CLONE = Path(__file__).resolve().parent.parent / "WhisperLiveKit"
if _CLONE.is_dir() and str(_CLONE) not in sys.path:
    sys.path.insert(0, str(_CLONE))

# Defaults requested for this validation. Overridable via CLI for fallback testing.
DEFAULT_BACKEND = "mlx-whisper"
DEFAULT_POLICY = "localagreement"
DEFAULT_LANG = "vi"
DEFAULT_TURBO = "large-v3-turbo"  # -> mlx-community/whisper-large-v3-turbo


@dataclass
class RunResult:
    label: str
    model_ref: str
    backend: str = ""
    ok: bool = False
    transcript: str = ""
    audio_s: float = 0.0
    asr_compute_s: float = 0.0   # sum of per-iter ASR time (pure compute)
    wall_s: float = 0.0          # wall-clock feed+flush (includes pipeline overhead)
    rtf: float = 0.0             # asr_compute_s / audio_s  (built-in metrics.rtf is unpopulated)
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    n_calls: int = 0
    wer: Optional[float] = None
    error: str = ""
    hint: str = ""


def _diagnose(exc: Exception) -> str:
    """Turn the common failure modes into one actionable line."""
    msg = str(exc)
    low = msg.lower()
    if "mlx-whisper" in low and "not installed" in low:
        return "Install MLX backend:  pip install mlx-whisper   (requires Apple Silicon)."
    if "no mlx weights" in low or ("mlx" in low and "weights" in low and "found" in low):
        return ("CONVERSION REQUIRED. The dir has no MLX weights. Convert PhoWhisper:\n"
                "      python -m mlx_whisper.convert --torch-name-or-path vinai/PhoWhisper-medium "
                "--mlx-path ./models/phowhisper-medium-mlx --dtype float16")
    if "ctranslate2 weights" in low or "faster-whisper weights" in low:
        return ("Dir is not a CTranslate2 build. Convert (or use quocphu/PhoWhisper-ct2-FasterWhisper):\n"
                "      ct2-transformers-converter --model vinai/PhoWhisper-medium "
                "--output_dir ./models/phowhisper-medium-ct2 --quantization int8")
    if isinstance(exc, ModuleNotFoundError):
        return f"Missing dependency: pip install {exc.name.replace('_', '-')}"
    if "darwin" in low or "arm64" in low or "metal" in low:
        return "mlx-whisper only runs on Apple Silicon (macOS arm64)."
    if "repository not found" in low or "snapshot_download" in low or "404" in low:
        return "Model id/path not found locally or on HuggingFace. Check --phowhisper-dir / model name."
    return ""


def detect_backend(model_dir: str, fallback: str = "mlx-whisper") -> str:
    """Pick the WLK backend that matches a model dir's on-disk format.

    Uses WhisperLiveKit's own detector so the harness 'just works' whether you
    point --phowhisper-dir at MLX weights, a CTranslate2 build, or HF/PyTorch.
    """
    try:
        from whisperlivekit.model_paths import detect_model_format, resolve_model_path
        info = detect_model_format(resolve_model_path(model_dir))
        if info.compatible_whisper_mlx:
            return "mlx-whisper"
        if info.compatible_faster_whisper:
            return "faster-whisper"
        if info.has_pytorch:
            return "whisper"
    except Exception:
        pass
    return fallback


async def transcribe_file(
    label: str,
    audio_path: Path,
    *,
    backend: str,
    policy: str,
    lan: str,
    model_size: Optional[str] = None,
    model_dir: Optional[str] = None,
    speed: float = 1.0,
    drain_s: float = 2.0,
    reference: Optional[str] = None,
    warmup: bool = True,
) -> RunResult:
    """Run one model through the WhisperLiveKit pipeline on a local file.

    speed=1.0  -> feed in real time. This is the REPRESENTATIVE mode: the pipeline
                  is built for incremental feeding and this is how Gradio mic drives it.
    speed=0.0  -> flood all audio at once. NON-REPRESENTATIVE: LocalAgreement then
                  re-transcribes one huge buffer, which both inflates RTF and triggers
                  Whisper repetition-hallucination. Don't trust speed=0 output/timing.
    drain_s    -> after feeding, wait this long so in-flight ASR commits the tail
                  before finish() (the WLK feed->drain->finish pattern).
    warmup=True -> do one untimed pass first so MLX Metal-kernel compilation and
                   model load are EXCLUDED from the timed RTF. The engine is cached
                   by config (TestHarness._engine_cache), so the timed pass reuses
                   the already-warm model. Essential on short clips, where cold-start
                   otherwise dominates (observed: first call ~18s of kernel compile).
    """
    model_ref = model_dir or model_size or "?"
    res = RunResult(label=label, model_ref=model_ref, backend=backend)
    try:
        from whisperlivekit.test_harness import TestHarness  # imports the whole core
    except Exception as exc:  # noqa: BLE001
        res.error = f"{type(exc).__name__}: {exc}"
        res.hint = _diagnose(exc) or "Install the core + deps:  pip install -e ./WhisperLiveKit mlx-whisper"
        return res

    kwargs = dict(
        backend=backend,
        backend_policy=policy,
        lan=lan,
        diarization=False,   # single speaker
        vac=True,            # Silero VAD on (bundled)
        pcm_input=True,      # TestHarness feeds decoded s16le PCM
    )
    if model_dir:
        kwargs["model_dir"] = model_dir
    if model_size:
        kwargs["model_size"] = model_size

    try:
        # Warm pass (untimed): loads + JIT-compiles MLX kernels so they don't
        # pollute the measured RTF. Reuses the cached engine on the timed pass.
        if warmup:
            async with TestHarness(**kwargs) as hw:
                await hw.feed(str(audio_path), speed=0.0)
                await hw.finish()

        t0 = time.perf_counter()
        async with TestHarness(**kwargs) as h:
            await h.feed(str(audio_path), speed=speed)
            if drain_s > 0:
                await h.drain(drain_s)   # let in-flight ASR commit the tail
            state = await h.finish()
            wall = time.perf_counter() - t0

            m = h.metrics
            audio_s = h.audio_position or 0.0   # seconds fed; total_audio_duration_s is set only in cleanup()
            asr_s = float(sum(m.transcription_durations)) if m else 0.0

            res.ok = True
            # committed_text = finalized lines only. state.text appends the
            # still-unconfirmed buffer, which duplicates the tail at end-of-stream.
            res.transcript = (state.committed_text or state.text or "").strip()
            res.audio_s = audio_s
            res.asr_compute_s = asr_s
            res.wall_s = wall
            res.rtf = (asr_s / audio_s) if audio_s > 0 else 0.0
            res.avg_latency_ms = m.avg_latency_ms if m else 0.0
            res.p95_latency_ms = m.p95_latency_ms if m else 0.0
            res.n_calls = m.n_transcription_calls if m else 0

            if reference:
                try:
                    res.wer = state.wer(reference)
                except Exception as werr:  # noqa: BLE001
                    res.hint = f"WER unavailable: {werr} (try: pip install jiwer)"
    except Exception as exc:  # noqa: BLE001  -- model load / runtime failures land here
        res.ok = False
        res.error = f"{type(exc).__name__}: {exc}"
        res.hint = _diagnose(exc)
    return res


def _print_report(audio_path: Path, results: list[RunResult], speed: float) -> None:
    print()
    print("=" * 78)
    print("Vietnamese STT PoC — WhisperLiveKit core (localagreement + mlx-whisper)")
    print(f"audio : {audio_path}")
    if results and results[0].audio_s:
        print(f"length: {results[0].audio_s:.1f}s    feed speed: "
              f"{'max (speed=0)' if speed == 0 else f'{speed}x'}")
    print("RTF = ASR-compute / audio (lower = faster). NOTE: speed is only comparable")
    print("within the SAME backend (mlx-whisper=Apple GPU, faster-whisper=CPU here).")
    print("=" * 78)

    hdr = (f"{'model':<20}{'backend':<16}{'status':<7}{'rtf':>6}{'asr_s':>8}"
           f"{'avg_ms':>8}{'p95_ms':>8}{'calls':>6}{'wer':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        if r.ok:
            wer = f"{r.wer*100:.1f}%" if r.wer is not None else "—"
            print(f"{r.label:<20}{r.backend:<16}{'ok':<7}{r.rtf:>6.2f}{r.asr_compute_s:>8.1f}"
                  f"{r.avg_latency_ms:>8.0f}{r.p95_latency_ms:>8.0f}{r.n_calls:>6}{wer:>8}")
        else:
            print(f"{r.label:<20}{r.backend:<16}{'FAIL':<7}{'—':>6}{'—':>8}{'—':>8}{'—':>8}{'—':>6}{'—':>8}")
    print()

    for r in results:
        print(f"--- {r.label}  [{r.backend}]  ({r.model_ref}) ---")
        if r.ok:
            print(r.transcript or "(empty transcript)")
        else:
            print(f"ERROR: {r.error}")
        if r.hint:
            print(f"HINT : {r.hint}")
        print()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path, help="path to a local audio file (any format ffmpeg reads)")
    ap.add_argument("--phowhisper-dir", default=None,
                    help="path (or HF id) of a CONVERTED PhoWhisper model dir. "
                         "Omit to run turbo only.")
    ap.add_argument("--turbo-name", default=DEFAULT_TURBO,
                    help=f"turbo model size key (default: {DEFAULT_TURBO})")
    ap.add_argument("--reference", default=None, help="ground-truth text to compute WER")
    ap.add_argument("--backend", default=DEFAULT_BACKEND,
                    help=f"backend for the TURBO model (default: {DEFAULT_BACKEND})")
    ap.add_argument("--phowhisper-backend", default=None,
                    help="backend for PhoWhisper (default: auto-detect from the dir's format: "
                         "MLX weights->mlx-whisper, CTranslate2->faster-whisper, PyTorch->whisper)")
    ap.add_argument("--policy", default=DEFAULT_POLICY, help=f"backend_policy (default: {DEFAULT_POLICY})")
    ap.add_argument("--lang", default=DEFAULT_LANG, help=f"language code (default: {DEFAULT_LANG})")
    ap.add_argument("--speed", type=float, default=1.0,
                    help="feed speed: 1.0=real-time (representative; default). 0=flood "
                         "(non-representative: inflates RTF, causes hallucination)")
    ap.add_argument("--drain", type=float, default=2.0,
                    help="seconds to wait after feeding so the ASR commits the tail (default 2.0)")
    ap.add_argument("--no-warmup", action="store_true",
                    help="skip the untimed warm pass (RTF will include MLX cold-start)")
    ap.add_argument("--only", choices=["turbo", "phowhisper"], default=None,
                    help="run just one model")
    ap.add_argument("--verbose", action="store_true", help="show WhisperLiveKit DEBUG logs")
    args = ap.parse_args()

    if not args.verbose:
        logging.disable(logging.INFO)  # WLK logs DEBUG/INFO heavily; keep output readable

    if not args.audio.exists():
        print(f"audio file not found: {args.audio}", file=sys.stderr)
        return 2

    async def runner() -> list[RunResult]:
        out: list[RunResult] = []
        # Run sequentially: each model is fully processed before the next so the
        # MLX ModelHolder (one global model) swaps cleanly between runs.
        if args.only != "phowhisper":
            out.append(await transcribe_file(
                "large-v3-turbo", args.audio,
                backend=args.backend, policy=args.policy, lan=args.lang,
                model_size=args.turbo_name, speed=args.speed, drain_s=args.drain, reference=args.reference,
                warmup=not args.no_warmup,
            ))
        if args.only != "turbo":
            if args.phowhisper_dir:
                pw_backend = args.phowhisper_backend or detect_backend(args.phowhisper_dir)
                out.append(await transcribe_file(
                    "phowhisper-medium", args.audio,
                    backend=pw_backend, policy=args.policy, lan=args.lang,
                    model_dir=args.phowhisper_dir, speed=args.speed, drain_s=args.drain, reference=args.reference,
                    warmup=not args.no_warmup,
                ))
            elif args.only == "phowhisper":
                r = RunResult("phowhisper-medium", "(not provided)")
                r.error = "no --phowhisper-dir given"
                r.hint = _diagnose(RuntimeError("no mlx weights found"))
                out.append(r)
            else:
                print("[note] --phowhisper-dir not given; skipping PhoWhisper. "
                      "Convert it first (see --help) to compare.\n")
        return out

    results = asyncio.run(runner())
    _print_report(args.audio, results, args.speed)
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
