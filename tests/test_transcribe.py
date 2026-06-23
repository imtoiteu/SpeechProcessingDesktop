"""Pure tests for the hallucination filter — no model required."""
from vnstt.engine import Segment
from vnstt.transcribe import is_likely_hallucination


def test_keeps_real_segment():
    # observed real segment: ~120 chars over 9.54s
    s = Segment(0.0, 9.54, "xin chào hôm nay là một ngày đẹp trời ở hà nội tôi đang "
                           "thử nghiệm hệ thống nhận dạng giọng nói tiếng việt")
    assert not is_likely_hallucination(s)


def test_drops_impossible_density():
    # observed hallucination: 47 chars in 0.08s
    s = Segment(9.72, 9.80, "ngoài tác động tiêu biểu hàn quốc tại thái lan.")
    assert is_likely_hallucination(s)


def test_drops_repetition_blip():
    s = Segment(9.54, 9.72, "còn.....................")
    assert is_likely_hallucination(s)


def test_keeps_short_legit_utterance():
    # a short real reply shouldn't be penalized
    assert not is_likely_hallucination(Segment(2.0, 2.4, "Vâng."))
    assert not is_likely_hallucination(Segment(2.0, 2.3, "Không."))


def test_drops_empty_and_zero_duration():
    assert is_likely_hallucination(Segment(1.0, 1.0, "có chữ nhưng không có thời lượng"))
    assert is_likely_hallucination(Segment(1.0, 2.0, "   "))
