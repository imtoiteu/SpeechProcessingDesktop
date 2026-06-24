"""
Phonemization module for VieNeu-TTS.
Delegates all normalization and G2P logic to the sea-g2p library,
which provides a unified, tested, and maintained Vietnamese G2P pipeline.
"""

import functools
import logging
import re
from typing import Optional
from sea_g2p import SEAPipeline, G2P, Normalizer

logger = logging.getLogger("Vieneu.Phonemizer")

# ---------------------------------------------------------------------------
# Inline non-verbal cues (emotion tokens) — v3 Turbo emotion checkpoint
# ---------------------------------------------------------------------------
# The emotion checkpoint was trained with three non-verbal cues embedded directly
# in the PHONEME stream as special tokens. In the *text* they appear as bracketed
# tags; phonemization must leave them as the matching <|emotion_k|> token instead
# of spelling the bracketed words out. The mapping + spacing reproduce the
# training data (cột `phones` của VieNeu-TTS-1000h-in-the-wild-coded) EXACTLY.
#
#   [chuckle]      / [cười]       -> <|emotion_1|>  (cười)
#   [sigh]         / [thở dài]    -> <|emotion_2|>  (thở dài)
#   [clear throat] / [hắng giọng] -> <|emotion_3|>  (hắng giọng)
_EMOTION_TAG_TO_K = {
    "chuckle": 1, "cười": 1, "cuoi": 1,
    "sigh": 2, "thở dài": 2, "tho dai": 2,
    "clear throat": 3, "hắng giọng": 3, "hang giong": 3,
}
# Split on a [bracketed tag] or an already-resolved <|emotion_k|> token.
_EMOTION_SPLIT_RE = re.compile(r"(\[[^\]]+\]|<\|emotion_\d+\|>)")
# Punctuation that stays attached to the preceding emotion token (no space),
# mirroring the training phones, e.g. "... <|emotion_2|>. ...".
_ATTACHING_PUNCT = set(".,!?;:…)]}\"'’”")


def _emotion_tag_token(tag: str) -> Optional[str]:
    """Map a raw ``[tag]`` / ``<|emotion_k|>`` string to its ``<|emotion_k|>`` form.

    Returns ``None`` for an unrecognized bracketed span (caller phonemizes it as
    ordinary text).
    """
    t = tag.strip()
    if t.startswith("<|"):
        return t  # already an explicit emotion token — pass through unchanged
    inner = t[1:-1].strip().lower()  # drop the surrounding [ ]
    k = _EMOTION_TAG_TO_K.get(inner)
    return f"<|emotion_{k}|>" if k is not None else None

# ---------------------------------------------------------------------------
# Always-punc_norm normalizer wrapper
# ---------------------------------------------------------------------------
# VieNeu-TTS LUÔN bật punc_norm (sea-g2p >= 0.7.6): câu ngắn (<5 từ) ép dấu cuối
# về ".", câu dài thiếu dấu kết thúc thì thêm ".". Dùng wrapper này thay cho
# sea_g2p.Normalizer ở mọi nơi để không phải truyền punc_norm=True rải rác và để
# bảo đảm hành vi "luôn luôn" kể cả ở các call-site tương lai.
class PuncNormalizer:
    """``sea_g2p.Normalizer`` với punc_norm mặc định True."""

    def __init__(self, lang: str = "vi") -> None:
        self._n = Normalizer(lang=lang)

    def normalize(self, text, punc_norm: bool = True):
        return self._n.normalize(text, punc_norm=punc_norm)

    def normalize_batch(self, texts, punc_norm: bool = True):
        return self._n.normalize_batch(texts, punc_norm=punc_norm)


# ---------------------------------------------------------------------------
# Shared singletons (instantiation is lazy-safe and thread-safe via GIL)
# ---------------------------------------------------------------------------
_pipeline: SEAPipeline = None
_g2p: G2P = None
_normalizer: PuncNormalizer = None

def _get_pipeline() -> SEAPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = SEAPipeline(lang="vi")
    return _pipeline

def _get_g2p() -> G2P:
    global _g2p
    if _g2p is None:
        _g2p = G2P(lang="vi")
    return _g2p

def _get_normalizer() -> PuncNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = PuncNormalizer()
    return _normalizer

# ---------------------------------------------------------------------------
# Public API  (same signatures as before — callers don't need to change)
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1024)
def _phonemize_cached(text: str, punc_norm: bool = True) -> str:
    """Cached single-text phonemization (normalize + G2P), punc_norm bật mặc định."""
    return _get_pipeline().run(text, punc_norm=punc_norm)


def phonemize_text(text: str) -> str:
    """Normalize and phonemize a single Vietnamese/bilingual text string."""
    return _phonemize_cached(text)


# Dấu kết thúc câu hợp lệ ở tầng phoneme.
_TERMINAL_PUNCT = ".!?"
# Dấu ngắt yếu ở cuối cần thay bằng "." (mirror punc_norm cho câu).
_WEAK_TRAILING = ",;:… \t"


def _ensure_terminal_punct(phones: str) -> str:
    """Đảm bảo chuỗi phoneme của MỘT chunk kết thúc bằng một dấu câu hợp lệ.

    Dùng cho đường emotion: các fragment được phonemize với punc_norm=False để
    không chèn "." vào giữa câu, nên cần chốt dấu cuối ở mức cả chunk. Nếu chunk
    kết thúc bằng emotion token (``...|>``) thì thành ``...|>.`` — khớp format
    training ("<|emotion_k|>."). Dấu ngắt yếu cuối (",;:…") được thay bằng ".".
    """
    s = phones.rstrip()
    if not s:
        return s
    if s[-1] in _TERMINAL_PUNCT:
        return s
    s = s.rstrip(_WEAK_TRAILING)
    return (s + ".") if s else phones


def phonemize_text_with_emotions(text: str) -> str:
    """Phonemize ``text`` while preserving inline non-verbal cues as emotion tokens.

    Same as :func:`phonemize_text`, but inline cues ``[cười]``/``[thở dài]``/
    ``[hắng giọng]`` (or the English ``[chuckle]``/``[sigh]``/``[clear throat]``,
    or an explicit ``<|emotion_k|>``) are kept as ``<|emotion_1|>``/``<|emotion_2|>``/
    ``<|emotion_3|>`` in the phoneme stream instead of being spelled out. Used by the
    v3 Turbo emotion checkpoint. Spacing matches the training data exactly: one
    space before the token, with following punctuation attached.
    """
    if "[" not in text and "<|emotion_" not in text:
        return _phonemize_cached(text)  # fast path: no cues → plain cached phonemize
    out = ""
    for i, part in enumerate(_EMOTION_SPLIT_RE.split(text)):
        token = _emotion_tag_token(part) if i % 2 == 1 else None
        if token is not None:
            out = (out + " " + token) if out else token
            continue
        # Fragment giữa các emotion token: KHÔNG ép punc_norm để tránh chèn "."
        # vào giữa câu — giữ đúng spacing/format khớp dữ liệu train của checkpoint
        # emotion. (Toàn chunk đã được split sentence-aware trước đó.)
        ph = _phonemize_cached(part, punc_norm=False) if part and part.strip() else ""
        if not ph:
            continue
        if not out:
            out = ph
        elif ph[0] in _ATTACHING_PUNCT:
            out += ph          # punctuation attaches to the previous token/phones
        else:
            out += " " + ph
    # Chốt dấu cuối ở mức cả chunk (fragment bên trong đã punc_norm=False).
    return _ensure_terminal_punct(out)


def phonemize_batch(
    texts: list[str],
    skip_normalize: bool = False,
    phoneme_dict: dict = None,
    **kwargs,
) -> list[str]:
    """
    Phonemize multiple texts with bilingual support.

    Args:
        texts:          List of input strings.
        skip_normalize: If True, assume the texts are already normalized
                        (i.e. only run G2P, not the normalizer).
        phoneme_dict:   Optional custom {word: phoneme} dict that overrides
                        the built-in dictionary for specific words.
    """
    if not texts:
        return []

    g2p = _get_g2p()

    # punc_norm LUÔN bật ở tầng G2P: kể cả text đã normalize sẵn (skip_normalize)
    # hay thiếu dấu câu, chuỗi phones vẫn kết thúc bằng "." hợp lệ.
    if skip_normalize:
        # Texts are pre-normalized — only run the G2P layer
        return g2p.phonemize_batch(texts, punc_norm=True, phoneme_dict=phoneme_dict)
    else:
        # Full pipeline: normalize (punc_norm) then G2P (punc_norm)
        normalizer = _get_normalizer()
        normalized = [normalizer.normalize(t) for t in texts]
        return g2p.phonemize_batch(normalized, punc_norm=True, phoneme_dict=phoneme_dict)


def phonemize_with_dict(
    text: str,
    phoneme_dict: dict = None,
    skip_normalize: bool = False,
) -> str:
    """
    Phonemize a single text, optionally with a custom word→phoneme mapping.

    When phoneme_dict is None and skip_normalize is False, the result is
    cached via lru_cache for performance.
    """
    if phoneme_dict is not None:
        # Custom dict supplied — skip cache to avoid cross-contamination
        return phonemize_batch(
            [text], skip_normalize=skip_normalize, phoneme_dict=phoneme_dict
        )[0]
    if skip_normalize:
        # punc_norm vẫn bật ở tầng G2P dù text đã normalize sẵn.
        return _get_g2p().phonemize_batch([text], punc_norm=True)[0]
    return _phonemize_cached(text)


def normalize_to_chunks(
    text: str,
    max_chars: int = 256,
    skip_normalize: bool = False,
) -> list[str]:
    """Split raw text into chunks FIRST, then normalize each chunk (punc_norm=True).

    Tách chunk TRƯỚC khi normalize để mỗi chunk là một đơn vị độc lập và — nhờ
    punc_norm — luôn kết thúc bằng dấu câu hợp lệ (câu ngắn ép ".", câu dài thiếu
    dấu thì thêm "."). Nếu normalize cả câu rồi mới cắt thì một chunk có thể kết
    thúc lửng hoặc bằng dấu ",". Trả về list text đã chuẩn hóa.
    """
    from vieneu_utils.core_utils import split_text_into_chunks

    if not text:
        return []

    raw_chunks = split_text_into_chunks(text, max_chars=max_chars)
    if skip_normalize:
        return raw_chunks

    normalizer = _get_normalizer()
    return [normalizer.normalize(chunk, punc_norm=True) for chunk in raw_chunks]


def phonemize_to_chunks(
    text: str,
    max_chars: int = 256,
    min_chunk_size: int = 10,
    source_max_chars: Optional[int] = None,
    skip_normalize: bool = False,
    phoneme_dict: dict = None,
):
    """
    Convert long raw text into bounded phoneme chunks.

    Some dependencies in the normalization/tokenization stack use Rust regex
    engines with backtracking limits. Split before those stages so DOCX-sized
    inputs are never passed to a single regex operation.

    Thứ tự: split raw -> normalize từng chunk (punc_norm=True) -> phonemize
    (punc_norm=True) -> split lại ở tầng phoneme. Mỗi chunk vì thế luôn có dấu
    câu kết thúc hợp lệ.
    """
    from vieneu_utils.core_utils import split_text_into_chunks, split_into_chunks_v2

    if not text:
        return []

    source_limit = source_max_chars or max_chars
    raw_chunks = split_text_into_chunks(text, max_chars=source_limit)
    if not raw_chunks:
        return []

    if skip_normalize:
        normalized_chunks = raw_chunks
    else:
        normalizer = _get_normalizer()
        normalized_chunks = [normalizer.normalize(chunk, punc_norm=True) for chunk in raw_chunks]

    phonemes = phonemize_batch(
        normalized_chunks,
        skip_normalize=True,
        phoneme_dict=phoneme_dict,
    )

    phone_chunks = []
    for chunk_phonemes in phonemes:
        phone_chunks.extend(
            split_into_chunks_v2(
                chunk_phonemes,
                max_chunk_size=max_chars,
                min_chunk_size=min_chunk_size,
            )
        )
    return phone_chunks


# ---------------------------------------------------------------------------
# CLI helper (python -m vieneu_utils.phonemize_text "some text")
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    test_text = (
        " ".join(sys.argv[1:])
        if len(sys.argv) > 1
        else "Giá SP500 hôm nay là 4.200,5 điểm."
    )
    print(f"Output: {phonemize_text(test_text)}")