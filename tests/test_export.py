"""Pure formatting tests for exporters — no model required."""
import re

from vnstt.engine import Segment, Word
from vnstt.export import _stamp, to_srt, to_txt, to_vtt


def _segs():
    return [
        Segment(0.0, 2.2, "xin chào", [Word(0.0, 0.42, "xin"), Word(0.42, 2.2, " chào")]),
        Segment(2.5, 3725.061, "một hai ba"),  # > 1h to exercise HH
    ]


def test_stamp_srt_and_vtt():
    assert _stamp(0, ",") == "00:00:00,000"
    assert _stamp(3725.061, ",") == "01:02:05,061"
    assert _stamp(3725.061, ".") == "01:02:05.061"
    assert _stamp(-1, ",") == "00:00:00,000"  # clamp negatives


def test_txt():
    out = to_txt(_segs())
    assert "xin chào" in out and "một hai ba" in out
    assert out.endswith("\n")


def test_srt_well_formed():
    out = to_srt(_segs())
    # index 1, arrow timestamps, blank-line separated cues
    assert out.startswith("1\n")
    assert "00:00:00,000 --> 00:00:02,200" in out
    assert "01:02:05,061" in out
    # every cue has "N\nHH:MM:SS,mmm --> HH:MM:SS,mmm\ntext"
    assert re.search(r"^\d+\n\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}\n", out, re.M)


def test_vtt_well_formed():
    out = to_vtt(_segs())
    assert out.startswith("WEBVTT\n")
    assert "00:00:00.000 --> 00:00:02.200" in out
    assert "," not in out.split("\n", 1)[0]  # VTT uses '.' not ','
