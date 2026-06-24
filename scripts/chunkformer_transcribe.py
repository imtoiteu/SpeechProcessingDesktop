#!/usr/bin/env python3
"""Standalone Vietnamese transcription with ChunkFormer — for testing only.

Temporarily lets you transcribe audio/video files with
`khanhld/chunkformer-large-vie` (ChunkFormer CTC, ~110M) instead of the project's
Whisper-based STT. It is fully isolated: runs in `.venv-chunkformer`, imports only
`chunkformer`, and touches nothing in the WhisperLiveKit STT stack.

Usage:
    .venv-chunkformer/bin/python scripts/chunkformer_transcribe.py AUDIO_OR_VIDEO [options]

    # plain text
    .venv-chunkformer/bin/python scripts/chunkformer_transcribe.py meeting.mp4 --format text
    # SRT subtitles to a file
    .venv-chunkformer/bin/python scripts/chunkformer_transcribe.py talk.wav --format srt -o talk.srt

Options:
    --model ID        HF model id (default: khanhld/chunkformer-large-vie)
    --device DEV      auto | mps | cpu | cuda   (default: auto → MPS, fall back to CPU)
    --format FMT      segments | text | srt | vtt | json   (default: segments)
    -o, --output F    write result to file instead of stdout
    --chunk-size / --left / --right / --batch-duration / --max-silence
                      ChunkFormer decode params (defaults match the library)

Input may be any ffmpeg-decodable audio or video; it is transcoded to 16 kHz mono
WAV before decoding. ChunkFormer outputs lowercase Vietnamese without punctuation.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import tempfile

# Let unsupported MPS ops fall back to CPU instead of hard-failing.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

DEFAULT_MODEL = "khanhld/chunkformer-large-vie"


def ffmpeg_to_wav16k(src: str, dst: str) -> None:
    """Transcode any audio/video to 16 kHz mono PCM WAV."""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", "-f", "wav",
         dst, "-loglevel", "error"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to decode {src!r}:\n{proc.stderr.strip()}")


def resolve_devices(pref: str) -> list[str]:
    import torch

    if pref and pref != "auto":
        return [pref]
    order = []
    if torch.backends.mps.is_available():
        order.append("mps")
    if torch.cuda.is_available():
        order.append("cuda")
    order.append("cpu")
    return order


def _ts_parts(ts: str):
    """Parse ChunkFormer 'HH:MM:SS:mmm' into (h, m, s, ms)."""
    h, m, s, ms = (ts.split(":") + ["0", "0", "0", "0"])[:4]
    return int(h), int(m), int(s), int(ms)


def _fmt_ts(ts: str, sep: str) -> str:
    h, m, s, ms = _ts_parts(ts)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def render(segments: list[dict], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(segments, ensure_ascii=False, indent=2)
    if fmt == "text":
        return " ".join(seg.get("decode", "").strip() for seg in segments).strip()
    if fmt in ("srt", "vtt"):
        sep = "," if fmt == "srt" else "."
        lines = ["WEBVTT", ""] if fmt == "vtt" else []
        for i, seg in enumerate(segments, 1):
            if fmt == "srt":
                lines.append(str(i))
            lines.append(f"{_fmt_ts(seg['start'], sep)} --> {_fmt_ts(seg['end'], sep)}")
            lines.append(seg.get("decode", "").strip())
            lines.append("")
        return "\n".join(lines).strip() + "\n"
    # default: human-readable segments
    out = []
    for seg in segments:
        start = _fmt_ts(seg["start"], ".")
        end = _fmt_ts(seg["end"], ".")
        out.append(f"[{start} -> {end}]  {seg.get('decode', '').strip()}")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Transcribe with ChunkFormer (Vietnamese).")
    ap.add_argument("audio", help="audio or video file (any ffmpeg-decodable format)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="auto", help="auto|mps|cpu|cuda")
    ap.add_argument("--format", default="segments",
                    choices=["segments", "text", "srt", "vtt", "json"])
    ap.add_argument("-o", "--output", default=None)
    ap.add_argument("--chunk-size", type=int, default=64)
    ap.add_argument("--left", type=int, default=128)
    ap.add_argument("--right", type=int, default=128)
    ap.add_argument("--batch-duration", type=int, default=1800,
                    help="total batched audio seconds per pass (raise for very long files)")
    ap.add_argument("--max-silence", type=float, default=0.5)
    ap.add_argument("--cache-dir", default=None, help="HF download cache dir")
    args = ap.parse_args()

    if not os.path.exists(args.audio):
        print(f"error: file not found: {args.audio}", file=sys.stderr)
        return 2

    # Importing chunkformer prints a 'torch_npu not found' notice to stdout, which would
    # corrupt --format json (and any machine consumer). Redirect stdout to stderr during
    # the import so only the final result is written to stdout.
    with contextlib.redirect_stdout(sys.stderr):
        from chunkformer import ChunkFormerModel

    print(f"Loading {args.model} ...", file=sys.stderr)
    model = ChunkFormerModel.from_pretrained(args.model, cache_dir=args.cache_dir)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav = tmp.name
    try:
        ffmpeg_to_wav16k(args.audio, wav)

        segments = None
        last_err = None
        for dev in resolve_devices(args.device):
            try:
                model.to(dev)
                print(f"Decoding on {dev} ...", file=sys.stderr)
                segments = model.endless_decode(
                    audio_path=wav,
                    chunk_size=args.chunk_size,
                    left_context_size=args.left,
                    right_context_size=args.right,
                    total_batch_duration=args.batch_duration,
                    return_timestamps=True,
                    max_silence_duration=args.max_silence,
                )
                break
            except Exception as e:  # noqa: BLE001 — fall back to next device
                last_err = e
                print(f"  {dev} failed ({type(e).__name__}: {str(e)[:120]}); "
                      f"trying next device", file=sys.stderr)
        if segments is None:
            raise RuntimeError(f"All devices failed. Last error: {last_err}")
    finally:
        try:
            os.unlink(wav)
        except OSError:
            pass

    # ChunkFormer returns a list of {decode, start, end}; tolerate a plain string.
    if isinstance(segments, str):
        text = segments
        result = text if args.format in ("text", "json") else f"[full]  {text}"
    else:
        result = render(segments, args.format)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result + ("\n" if not result.endswith("\n") else ""))
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
