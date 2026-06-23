"""Near-real-time streaming transcription.

Whisper is a 30s batch model, so "streaming" = re-decode a growing buffer and
stabilize with **LocalAgreement-2**: a word is committed (final) only once two
consecutive hypotheses agree on it. Silero VAD (reused from faster-whisper)
segments at natural pauses so the buffer stays small — which is what keeps both
latency and RTF low. Use the whisper.cpp/Metal engine here.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

import numpy as np

from .audio import SAMPLE_RATE, decode_audio
from .engine import ASREngine

_PUNCT_ONLY = re.compile(r"^\W+$", re.UNICODE)
# The ONLY leading marks whisper.cpp fuses onto an onset word are sentence dots.
# Deliberately excludes -, –, (, ", etc. so "-5", "3–5", '"Nam"' survive intact.
_ONSET_PUNCT = ".…"


def _clean_tokens(tokens: list[str]) -> list[str]:
    """Remove two whisper.cpp onset artifacts before tokens enter LocalAgreement.

    On a near-silent onset buffer whisper.cpp emits a bare ``.``; once real speech
    arrives it fuses a sentence period onto the first word (``.xin``). If the bare
    ``.`` is committed it takes index 0, and the real onset word is then skipped by
    the ``insert()``/``finalize()`` slicing (which counts from ``len(committed)``) —
    so the utterance loses its first word.

    This drops punct-only tokens (the bare ``.``) and strips a leading ``.``/``…``
    off a word (``.xin`` → ``xin``). It does NOT claim to repair arbitrary index
    drift — only these two onset patterns. Only ``.``/``…`` are stripped, so signed
    numbers, ranges, and quoted/parenthesised text are preserved; trailing
    punctuation (``lan.``) is kept for display.
    """
    out: list[str] = []
    for tok in tokens:
        if _PUNCT_ONLY.match(tok):  # bare "." / "…" / "(" → drop (also kills the phantom)
            continue
        tok = tok.lstrip(_ONSET_PUNCT)  # ".xin" → "xin"; leaves "-5", '"Nam"' intact
        if tok:
            out.append(tok)
    return out


class HypothesisBuffer:
    """LocalAgreement-2 over word tokens."""

    def __init__(self) -> None:
        self.committed: list[str] = []
        self._prev: list[str] = []

    def insert(self, words: list[str]) -> list[str]:
        c = len(self.committed)
        prev_tail, new_tail = self._prev[c:], words[c:]
        n = 0
        for a, b in zip(prev_tail, new_tail):
            if a == b:
                n += 1
            else:
                break
        newly = new_tail[:n]
        self.committed += newly
        self._prev = words
        return newly

    def pending(self) -> list[str]:
        return self._prev[len(self.committed):]

    def finalize(self) -> list[str]:
        rest = self._prev[len(self.committed):]
        self.committed += rest
        return rest


class StreamingTranscriber:
    """Feed audio chunks; emit stabilized partial + committed-final text.

    Defaults are tuned for conversational Vietnamese on whisper.cpp/Metal (M3).
    """

    def __init__(
        self,
        engine: ASREngine,
        *,
        language: str = "vi",
        decode_interval_s: float = 1.0,  # partials ~1/s; keeps RTF in budget on M3
        min_finalize_silence_s: float = 0.4,
        vad_threshold: float = 0.5,
        min_speech_s: float = 0.25,
        max_utterance_s: float = 15.0,
        normalize_gain: bool = True,  # peak-normalize each decode buffer (doc 19 RC-1)
        on_partial: Optional[Callable[[str], None]] = None,
        on_commit: Optional[Callable[[str], None]] = None,
        on_finalize: Optional[Callable[[str, float], None]] = None,
    ) -> None:
        self.engine = engine
        self.language = language
        self._interval = int(decode_interval_s * SAMPLE_RATE)
        self._min_finalize_silence_s = min_finalize_silence_s
        self._vad_threshold = vad_threshold
        self._min_speech_s = min_speech_s
        self._max_buffer = int(max_utterance_s * SAMPLE_RATE)
        self._normalize_gain = normalize_gain
        self.on_partial = on_partial
        self.on_commit = on_commit
        self.on_finalize = on_finalize

        self.buffer = np.zeros(0, dtype=np.float32)
        self.hyp = HypothesisBuffer()
        self._since_decode = 0
        self._offset_s = 0.0  # audio time of buffer[0]
        self._utt_words: list[str] = []  # committed words of the in-progress utterance
        self.final_words: list[str] = []  # all committed words (whole stream)
        self.total_decode_s = 0.0  # for streaming RTF
        self._last_decode_s = 0.0

    # ---- public ----
    def feed(self, chunk: np.ndarray) -> None:
        chunk = np.asarray(chunk, dtype=np.float32).reshape(-1)
        self.buffer = np.concatenate([self.buffer, chunk])
        self._since_decode += len(chunk)

        ts = self._vad(self.buffer)
        if not ts:  # no speech in buffer — keep a 1s tail (preserve speech onset), never decode silence
            keep = int(1.0 * SAMPLE_RATE)
            if self.buffer.size > keep:
                self._offset_s += (self.buffer.size - keep) / SAMPLE_RATE
                self.buffer = self.buffer[-keep:]
            return

        trailing_s = (self.buffer.size - ts[-1]["end"]) / SAMPLE_RATE
        speech_s = sum(t["end"] - t["start"] for t in ts) / SAMPLE_RATE
        if trailing_s >= self._min_finalize_silence_s and speech_s >= self._min_speech_s:
            self._finalize(speech_end_s=self._offset_s + ts[-1]["end"] / SAMPLE_RATE)
        elif self.buffer.size >= self._max_buffer:
            self._finalize(speech_end_s=self._offset_s + self.buffer.size / SAMPLE_RATE)
        elif self._since_decode >= self._interval:
            self._decode_partial()

    def close(self) -> str:
        ts = self._vad(self.buffer)
        if ts and sum(t["end"] - t["start"] for t in ts) / SAMPLE_RATE >= self._min_speech_s:
            self._finalize(speech_end_s=self._offset_s + ts[-1]["end"] / SAMPLE_RATE)
        return " ".join(self.final_words)

    # ---- internals ----
    def _vad(self, audio: np.ndarray):
        if audio.size < int(0.2 * SAMPLE_RATE):
            return []
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        opts = VadOptions(
            threshold=self._vad_threshold,
            min_silence_duration_ms=int(self._min_finalize_silence_s * 1000),
        )
        try:
            return get_speech_timestamps(audio, vad_options=opts)
        except TypeError:
            return get_speech_timestamps(audio)

    def _hypothesis(self) -> list[str]:
        audio = self._gain_normalized(self.buffer)
        t = time.perf_counter()
        segs = list(self.engine.transcribe(audio, language=self.language))
        self._last_decode_s = time.perf_counter() - t
        self.total_decode_s += self._last_decode_s
        # Canonicalize BEFORE the buffer sees them so committed indices track real
        # words (prevents phantom-punctuation onset loss — see _clean_tokens).
        return _clean_tokens(" ".join(s.text.strip() for s in segs).split())

    def _gain_normalized(self, buf: np.ndarray) -> np.ndarray:
        """Peak-normalize a COPY of the decode buffer to ~0.95 (doc 19 RC-1).

        Whisper hallucinates badly on quiet/low-level short streaming segments
        (measured: low-gain mic WER 81% → 0% with this). Returns a new array;
        self.buffer is never mutated. Gain is capped so near-silence/noise isn't
        amplified to speech levels (the VAD `not ts` branch already skips silence).
        """
        if not self._normalize_gain or buf.size == 0:
            return buf
        peak = float(np.abs(buf).max())
        if peak <= 1e-3:  # essentially silence — don't amplify noise
            return buf
        gain = min(0.95 / peak, 12.0)
        return (buf * gain).astype(np.float32)

    def _emit(self, words: list[str]) -> list[str]:
        # words are already cleaned in _hypothesis(); just record + announce them.
        if words:
            self._utt_words += words
            self.final_words += words
            if self.on_commit:
                self.on_commit(" ".join(words))
        return words

    def _decode_partial(self) -> None:
        self._since_decode = 0
        self._emit(self.hyp.insert(self._hypothesis()))
        if self.on_partial:
            self.on_partial(" ".join(self.hyp.pending()))

    def _finalize(self, *, speech_end_s: float) -> None:
        newly = self.hyp.insert(self._hypothesis())
        newly = newly + self.hyp.finalize()
        self._emit(newly)
        if self._utt_words and self.on_finalize:
            self.on_finalize(" ".join(self._utt_words), speech_end_s)
        # reset for the next utterance
        self._offset_s += self.buffer.size / SAMPLE_RATE
        self.buffer = np.zeros(0, dtype=np.float32)
        self.hyp = HypothesisBuffer()
        self._since_decode = 0
        self._utt_words = []


def stream_file(
    path: str,
    transcriber: StreamingTranscriber,
    *,
    chunk_s: float = 0.5,
    realtime: bool = False,
    sleep=time.sleep,
) -> str:
    """Feed a decoded file through the transcriber in chunks.

    realtime=True paces chunks to wall-clock (to measure perceived latency).
    """
    audio = decode_audio(path)
    step = int(chunk_s * SAMPLE_RATE)
    for i in range(0, len(audio), step):
        if realtime:
            sleep(chunk_s)
        transcriber.feed(audio[i : i + step])
    return transcriber.close()


def stream_microphone(transcriber: StreamingTranscriber, *, chunk_s: float = 0.5) -> str:
    """Live mic capture → transcriber until KeyboardInterrupt. Returns full transcript."""
    import sounddevice as sd

    step = int(chunk_s * SAMPLE_RATE)
    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=step) as stream:
            while True:
                block, _ = stream.read(step)
                transcriber.feed(block.reshape(-1))
    except KeyboardInterrupt:
        pass
    return transcriber.close()
