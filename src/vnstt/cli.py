"""CLI: batch (`transcribe file`), simulated stream (`--stream`), live mic (`--mic`)."""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from .engine import create_engine
from .export import write_outputs
from .transcribe import transcribe_file

# Engine-specific default model locations (relative to the repo root).
DEFAULT_MODELS = {
    "whisper.cpp": "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin",
    "faster-whisper": "models/PhoWhisper-medium-ct2-fasterWhisper",
}

# Anchor the relative defaults to the repo root so they resolve no matter what
# directory the CLI/UI is launched from (the cause of the UI's segfault: a
# relative path that only existed when cwd happened to be the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[2]


def resolve_model_arg(engine: str, model: str | None) -> str:
    """Resolve the model arg: explicit override else the per-engine default, tried
    against cwd then the repo root. Returns an absolute path when found; otherwise
    returns the raw value so the engine raises a clear ModelLoadError (never a crash).
    """
    raw = model or DEFAULT_MODELS[engine]
    if Path(raw).exists():  # file (GGML) or directory (CT2)
        return str(Path(raw).resolve())
    anchored = _REPO_ROOT / raw
    if anchored.exists():
        return str(anchored)
    return raw


def _build_engine(args, streaming: bool = False):
    model = resolve_model_arg(args.engine, args.model)
    if args.engine == "whisper.cpp":
        # NOTE: reduced audio_ctx was tried for speed but produces garbage on short
        # buffers; full ctx is fast enough (~0.2s/decode warm). Keep full ctx.
        return create_engine("whisper.cpp", model_path=model)
    return create_engine(
        "faster-whisper", model_path=model, device=args.device, compute_type=args.compute_type
    )


class _StreamRenderer:
    """Committed text solid, live partial dimmed, refreshing in place (TTY)."""

    def __init__(self) -> None:
        self.tty = sys.stdout.isatty()
        self.committed = ""

    def _redraw(self, partial: str) -> None:
        if not self.tty:
            return  # non-TTY: emit one clean line per utterance via on_finalize
        line = self.committed
        if partial:
            line = (line + " " + f"\x1b[2m{partial}\x1b[22m").strip()
        print("\r\x1b[K" + line, end="", flush=True)

    def on_commit(self, text: str) -> None:
        self.committed = (self.committed + " " + text).strip()
        self._redraw("")

    def on_partial(self, text: str) -> None:
        self._redraw(text)

    def on_finalize(self, text: str, _t: float) -> None:
        if self.tty:
            print("\r\x1b[K" + text)
        else:
            print(text)
        self.committed = ""


def _run_streaming(args, engine) -> int:
    from .streaming import StreamingTranscriber, stream_file, stream_microphone

    r = _StreamRenderer()
    st = StreamingTranscriber(
        engine, language=args.language,
        on_commit=r.on_commit, on_partial=r.on_partial, on_finalize=r.on_finalize,
    )
    if args.mic:
        print("Listening… (Ctrl-C to stop)\n", file=sys.stderr)
        final = stream_microphone(st)
    else:
        final = stream_file(args.input, st, realtime=args.realtime)
    if args.output_base:
        path = f"{args.output_base}.txt"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(final + "\n")
        print(f"\nwrote txt: {os.path.abspath(path)}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="transcribe", description="Local-first Vietnamese Speech-to-Text"
    )
    p.add_argument("input", nargs="?", help="audio/video file (wav/mp3/m4a/flac/mp4/mov/mkv)")
    p.add_argument("--mic", action="store_true", help="live microphone streaming")
    p.add_argument("--stream", action="store_true", help="stream the input file (simulated real-time)")
    p.add_argument("--realtime", action="store_true", help="pace --stream to wall-clock")
    p.add_argument(
        "--engine", default="whisper.cpp", choices=["whisper.cpp", "faster-whisper"],
        help="ASR engine (whisper.cpp = Metal fast path on Apple Silicon)",
    )
    p.add_argument("--model", default=None, help="model path (defaults per engine)")
    p.add_argument("--format", default="txt", help="comma list of: txt,srt,vtt (batch only)")
    p.add_argument("--language", default="vi")
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda", "auto"], help="faster-whisper only")
    p.add_argument("--compute-type", default="int8", help="faster-whisper only")
    p.add_argument("--output-base", default=None, help="output path prefix (default: input without ext)")
    args = p.parse_args(argv)

    if not args.mic and not args.input:
        print("error: provide an input file, or use --mic", file=sys.stderr)
        return 2
    if args.input and not os.path.exists(args.input):
        print(f"error: input not found: {args.input}", file=sys.stderr)
        return 2

    engine = _build_engine(args)

    if args.mic or args.stream:
        return _run_streaming(args, engine)

    # batch mode
    formats = [f.strip() for f in args.format.split(",") if f.strip()]
    base = args.output_base or os.path.splitext(args.input)[0]

    def show(seg):
        print(f"[{seg.start:7.2f}s] {seg.text}")

    t0 = time.time()
    segments = transcribe_file(args.input, engine, language=args.language, on_segment=show)
    elapsed = time.time() - t0

    written = write_outputs(segments, base, formats)
    print(f"\n{len(segments)} segments in {elapsed:.1f}s")
    for fmt, path in written.items():
        print(f"wrote {fmt}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
