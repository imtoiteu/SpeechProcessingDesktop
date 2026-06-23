"""Transcript exporters: TXT, SRT, VTT."""
from __future__ import annotations

import os
from typing import Iterable

from .engine import Segment

_FORMATS = ("txt", "srt", "vtt")


def _stamp(seconds: float, sep: str) -> str:
    """Format seconds as HH:MM:SS<sep>mmm (sep is ',' for SRT, '.' for VTT)."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h, total_ms = divmod(total_ms, 3_600_000)
    m, total_ms = divmod(total_ms, 60_000)
    s, ms = divmod(total_ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_txt(segments: Iterable[Segment]) -> str:
    return "\n".join(s.text.strip() for s in segments if s.text.strip()) + "\n"


def to_srt(segments: Iterable[Segment]) -> str:
    lines: list[str] = []
    for i, s in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_stamp(s.start, ',')} --> {_stamp(s.end, ',')}")
        lines.append(s.text.strip())
        lines.append("")
    return "\n".join(lines)


def to_vtt(segments: Iterable[Segment]) -> str:
    lines: list[str] = ["WEBVTT", ""]
    for s in segments:
        lines.append(f"{_stamp(s.start, '.')} --> {_stamp(s.end, '.')}")
        lines.append(s.text.strip())
        lines.append("")
    return "\n".join(lines)


_RENDERERS = {"txt": to_txt, "srt": to_srt, "vtt": to_vtt}


def write_outputs(
    segments: list[Segment], base_path: str, formats: Iterable[str]
) -> dict[str, str]:
    """Write requested formats next to `base_path`. Returns {format: path}."""
    written: dict[str, str] = {}
    for fmt in formats:
        fmt = fmt.lower().strip()
        if fmt not in _RENDERERS:
            raise ValueError(f"unknown format {fmt!r}; choose from {_FORMATS}")
        out_path = f"{base_path}.{fmt}"
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(_RENDERERS[fmt](segments))
        written[fmt] = os.path.abspath(out_path)
    return written
