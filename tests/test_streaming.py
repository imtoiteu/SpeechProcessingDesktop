"""Streaming: LocalAgreement-2 logic (pure) + an end-to-end convergence test."""
import os

import pytest

from vnstt.engine import create_engine
from vnstt.streaming import (
    HypothesisBuffer,
    StreamingTranscriber,
    _clean_tokens,
    stream_file,
)

GGML = "models/ggml-phowhisper-medium/ggml-PhoWhisper-medium.bin"
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.wav")
MULTI = os.path.join(os.path.dirname(__file__), "fixtures", "multi.wav")


def test_commits_only_on_two_way_agreement():
    h = HypothesisBuffer()
    assert h.insert(["xin", "chào", "các"]) == []          # first hypothesis: commit nothing
    assert h.insert(["xin", "chào", "bạn"]) == ["xin", "chào"]  # agreed prefix commits
    assert h.committed == ["xin", "chào"]
    assert h.pending() == ["bạn"]
    assert h.finalize() == ["bạn"]
    assert h.committed == ["xin", "chào", "bạn"]


def test_no_commit_when_hypotheses_disagree():
    h = HypothesisBuffer()
    h.insert(["một", "hai"])
    assert h.insert(["ba", "bốn"]) == []                   # disagreement → nothing committed


def test_committed_words_are_stable_once_emitted():
    h = HypothesisBuffer()
    h.insert(["a", "b", "c"])
    h.insert(["a", "b", "z"])            # commits a, b
    before = list(h.committed)
    h.insert(["a", "b", "z", "q"])       # must never revoke a, b
    assert h.committed[: len(before)] == before


def test_clean_tokens_strips_leading_punct_and_drops_bare_punct():
    # whisper.cpp onset hallucinations: bare "." and ".xin" fused onto a word.
    assert _clean_tokens(["."]) == []
    assert _clean_tokens(["…", "—", "ok"]) == ["ok"]
    assert _clean_tokens([".xin", "chào", "lan."]) == ["xin", "chào", "lan."]  # trailing "." kept


def test_clean_tokens_preserves_signed_numbers_and_quotes():
    # Regression for the adversarial-review C1 finding: only "." / "…" are stripped,
    # so dashes, signs, ranges and quotes adjacent to content must survive intact.
    assert _clean_tokens(["-5", "°C"]) == ["-5", "°C"]
    assert _clean_tokens(["3–5", "ngày"]) == ["3–5", "ngày"]
    assert _clean_tokens(['"Nam"']) == ['"Nam"']


def test_phantom_punctuation_does_not_eat_onset_word():
    # Regression: whisper.cpp decodes a bare "." on the near-silent onset buffer,
    # then the real first word arrives fused as ".xin". Pre-fix, LocalAgreement
    # committed the "." at index 0 and the finalize index math skipped "xin".
    # Cleaning tokens before the buffer keeps committed indices on real words.
    h = HypothesisBuffer()
    h.insert(_clean_tokens(["."]))                        # partial 1 (near-silence)
    h.insert(_clean_tokens(["."]))                        # partial 2 — would commit "." pre-fix
    h.insert(_clean_tokens([".xin", "chào", "tôi"]))      # real onset arrives
    final = h.committed + h.finalize()
    assert final[0] == "xin"


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_stream_preserves_onset_words():
    # End-to-end guard on the real model: every utterance's first word must survive.
    engine = create_engine("whisper.cpp", model_path=GGML)
    st = StreamingTranscriber(engine)
    final = stream_file(MULTI, st, chunk_s=0.5).lower()
    for onset in ("xin", "hôm", "tôi", "cảm"):
        assert onset in final.split(), f"onset word {onset!r} lost: {final!r}"


@pytest.mark.skipif(not os.path.isfile(GGML), reason="GGML weights not downloaded")
def test_stream_file_converges_to_vietnamese():
    engine = create_engine("whisper.cpp", model_path=GGML)
    commits = []
    st = StreamingTranscriber(engine, on_commit=lambda t: commits.append(t))
    final = stream_file(FIXTURE, st, chunk_s=0.5)
    assert "việt" in final.lower()
    # commits are monotonic: their concatenation equals the accumulated transcript
    assert " ".join(commits).split() == st.final_words
