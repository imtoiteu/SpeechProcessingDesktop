"""Lightweight LOCAL Gradio testing UI for the vnstt pipeline.

Purpose: rapid real-world testing and Vietnamese sample collection — NOT a
production app. No accounts, no database, no cloud. It only wires the browser to
the EXISTING pipeline, unchanged:

    upload/mic ─► decode_audio / resample ─► engine.transcribe
              ─► transcribe_file (hallucination filter + clamp)
              ─► to_txt / to_srt / to_vtt   (StreamingTranscriber for live mic)

Run:  python -m vnstt.ui      (after: uv pip install -e '.[ui]'  — installs gradio)
"""
from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import uuid
import wave

import gradio as gr
import numpy as np

from .audio import SAMPLE_RATE, AudioDecodeError
from .cli import resolve_model_arg
from .engine import ModelLoadError, create_engine, validate_whispercpp_model_path
from .export import write_outputs
from .streaming import StreamingTranscriber
from .transcribe import transcribe_file

ENGINES = ["whisper.cpp", "faster-whisper"]

# Heavy ASR models are not safe to call concurrently; this is a single-user
# testing tool, so we load each engine once and serialize all inference.
_ENGINE_CACHE: dict[tuple[str, str], object] = {}
_MODEL_LOCK = threading.Lock()
_OUT_DIR = tempfile.mkdtemp(prefix="vnstt_ui_")  # one dir for downloadable exports


def _get_engine(name: str, model: str | None = None):
    # Resolve against cwd + repo root so launching the UI from any directory works;
    # the engine constructors validate and raise ModelLoadError (no native segfault).
    path = resolve_model_arg(name, model)
    key = (name, path)
    if key not in _ENGINE_CACHE:
        if name == "whisper.cpp":
            _ENGINE_CACHE[key] = create_engine("whisper.cpp", model_path=path)
        else:
            _ENGINE_CACHE[key] = create_engine(
                "faster-whisper", model_path=path, device="cpu", compute_type="int8"
            )
    return _ENGINE_CACHE[key]


# ---- audio conversion glue (browser mic is rarely 16 kHz mono float) ----
def _to_mono16k(y: np.ndarray, sr: int) -> np.ndarray:
    """Gradio mic chunk -> 16 kHz mono float32, matching decode_audio's output.

    A lightweight linear resampler (no scipy/soxr dependency). Quality is fine for
    live testing; archival-grade decoding still goes through ffmpeg via file upload.
    """
    y = np.asarray(y)
    if y.ndim == 0 or y.size == 0:
        return np.zeros(0, dtype=np.float32)
    # Normalize dtype BEFORE mixing to mono: averaging int channels promotes to
    # float and would otherwise skip the integer scaling, leaving a raw-scale signal.
    # Scale by the dtype's range (not a hardcoded 32768) so int16/int32/int8 all map
    # to [-1, 1]; Gradio's mic delivers int16 in practice.
    if np.issubdtype(y.dtype, np.integer):
        y = y.astype(np.float32) / float(np.iinfo(y.dtype).max + 1)
    else:
        y = y.astype(np.float32)
    if y.ndim > 1:  # (samples, channels) -> mono
        y = y.mean(axis=1)
    if sr != SAMPLE_RATE and y.size > 1:
        n_dst = int(round(y.size * SAMPLE_RATE / sr))
        if n_dst > 0:
            y = np.interp(
                np.linspace(0, y.size - 1, num=n_dst), np.arange(y.size), y
            ).astype(np.float32)
    return np.clip(y, -1.0, 1.0)


# ---- file tab (shared by Audio + Video; decode_audio handles both) ----
def transcribe_upload(path: str | None, engine_name: str, language: str):
    """Returns (transcript_text, txt_path, srt_path, vtt_path) for download."""
    if not path:
        return "Upload a file, then click Transcribe.", None, None, None
    try:
        engine = _get_engine(engine_name)
    except ModelLoadError as e:
        return f"⚠️ Model could not be loaded.\n\n{e}", None, None, None
    try:
        with _MODEL_LOCK:
            segments = transcribe_file(path, engine, language=(language or "vi"))
    except AudioDecodeError as e:
        return f"⚠️ Could not decode this file.\n\n{e}", None, None, None
    text = "\n".join(s.text.strip() for s in segments if s.text.strip())
    base = os.path.join(_OUT_DIR, os.path.splitext(os.path.basename(path))[0] or "transcript")
    written = write_outputs(segments, base, ["txt", "srt", "vtt"])
    if not text:
        text = "(no speech detected)"
    return text, written["txt"], written["srt"], written["vtt"]


# ---- microphone tab: live partial + final via a background ASR worker ----
#
# Why a worker (doc 19 RC-2): the ASR decode is ~0.8-1.1s (3-5x under thermal load)
# but Gradio delivers a mic chunk every 0.5s. If the stream handler ran the decode
# inline it would overrun the cadence and Gradio would DROP/coalesce audio (the
# measured cause of missing words / garbled onsets). So the handler only ENQUEUES
# audio and returns in ms; one worker thread per session drains the queue, runs the
# (globally serialized) ASR, and publishes snapshots the handler reads instantly.
#
# Sessions live in this module registry keyed by a string id; gr.State holds only the
# id, so Gradio never has to copy the Thread/Queue (which it can't).
_MIC_SESSIONS: dict[str, "MicSession"] = {}


class MicSession:
    def __init__(self, engine_name: str, language: str) -> None:
        self.committed: list[str] = []          # touched only by the worker thread
        self._audio: list[np.ndarray] = []       # exact 16kHz samples processed (for WAV)
        self._snap = ("", "")                     # (committed, partial) published to the UI
        self._lock = threading.Lock()            # guards _snap and _audio (cross-thread)
        self._q: "queue.Queue" = queue.Queue()
        self.stopped = False
        self._wav_name = f"mic_{uuid.uuid4().hex[:8]}.wav"  # unique → no stale browser cache
        engine = _get_engine(engine_name)         # may raise ModelLoadError (before thread)
        self.st = StreamingTranscriber(
            engine, language=(language or "vi"), on_commit=self.committed.append
        )
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def _run(self) -> None:
        while True:
            chunk = self._q.get()
            try:
                if chunk is None:                 # sentinel: queue drained, exit
                    break
                with _MODEL_LOCK:                 # engine is shared / not thread-safe
                    self.st.feed(chunk)
                with self._lock:
                    self._audio.append(chunk)
                    self._snap = (" ".join(self.committed).strip(),
                                  " ".join(self.st.hyp.pending()).strip())
            finally:
                self._q.task_done()

    def enqueue(self, audio: np.ndarray) -> None:
        self._q.put(audio)

    def snapshot(self) -> tuple[str, str]:
        with self._lock:
            return self._snap

    def finish(self) -> tuple[str, str | None]:
        """Drain the queue, flush the last utterance, stop the worker. -> (final, wav)."""
        if not self.stopped:
            self._q.put(None)                     # process everything queued, then stop
            self._worker.join(timeout=60)
            with _MODEL_LOCK:
                self.st.close()
            with self._lock:
                self.stopped = True
                self._snap = (" ".join(self.committed).strip(), "")
        return self.snapshot()[0], self._save_wav()

    def _save_wav(self) -> str | None:
        with self._lock:
            audio = np.concatenate(self._audio) if self._audio else np.zeros(0, np.float32)
        if audio.size == 0:
            return None
        path = os.path.join(_OUT_DIR, self._wav_name)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        return path


def _mic_new(engine_name: str, language: str) -> str:
    # Prune old finished sessions so the registry can't grow without bound.
    for old in [k for k, s in list(_MIC_SESSIONS.items()) if s.stopped][:-4]:
        _MIC_SESSIONS.pop(old, None)
    sid = uuid.uuid4().hex[:12]
    _MIC_SESSIONS[sid] = MicSession(engine_name, language)
    return sid


def mic_start(sid, engine_name, language):
    # Record pressed. If a racing stream chunk already opened a session for this take,
    # KEEP it (RC-3: never orphan the onset); otherwise open a fresh one.
    sess = _MIC_SESSIONS.get(sid) if sid else None
    if sess is not None and not sess.stopped:
        c, p = sess.snapshot()
        return sid, c, p
    try:
        sid = _mic_new(engine_name, language)
    except ModelLoadError as e:
        return None, f"⚠️ {e}", ""
    return sid, "", ""


def mic_stream(new_chunk, sid, engine_name, language):
    sess = _MIC_SESSIONS.get(sid) if sid else None
    if sess is None:                              # stream raced ahead of start on a new take
        try:
            sid = _mic_new(engine_name, language)
        except ModelLoadError as e:
            return None, f"⚠️ {e}", ""
        sess = _MIC_SESSIONS[sid]
    if sess.stopped:                              # trailing chunk after Stop — keep the final
        c, p = sess.snapshot()
        return sid, c, p
    if new_chunk is not None:
        sr, y = new_chunk
        audio = _to_mono16k(y, sr)
        if audio.size:
            sess.enqueue(audio)                   # returns immediately; worker does the ASR
    c, p = sess.snapshot()
    return sid, c, p


def mic_stop(sid, engine_name, language):
    sess = _MIC_SESSIONS.get(sid) if sid else None
    if sess is None:
        return sid, "", "", None
    final, wav = sess.finish()
    return sid, final, "", wav


def mic_clear(sid):
    sess = _MIC_SESSIONS.pop(sid, None) if sid else None
    if sess is not None and not sess.stopped:
        try:
            sess.finish()                         # stop the worker thread (avoid a leak)
        except Exception:
            pass
    return None, "", "", None


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="vnstt — Vietnamese STT testing UI") as demo:
        gr.Markdown(
            "# 🎙️ vnstt — Vietnamese Speech-to-Text (local testing UI)\n"
            "Local testing only — no accounts, no database, no cloud. "
            "Reuses the existing pipeline; default engine **whisper.cpp / Metal**."
        )
        with gr.Row():
            engine_dd = gr.Dropdown(ENGINES, value="whisper.cpp", label="Engine")
            lang_tb = gr.Textbox(value="vi", label="Language", scale=1)

        with gr.Tabs():
            # ---------------- Audio ----------------
            with gr.Tab("Audio"):
                a_in = gr.Audio(sources=["upload"], type="filepath", label="Upload audio")
                a_btn = gr.Button("Transcribe", variant="primary")
                a_txt = gr.Textbox(label="Transcript", lines=10, show_copy_button=True)
                with gr.Row():
                    a_f_txt = gr.File(label="TXT")
                    a_f_srt = gr.File(label="SRT")
                    a_f_vtt = gr.File(label="VTT")
                a_btn.click(
                    transcribe_upload,
                    inputs=[a_in, engine_dd, lang_tb],
                    outputs=[a_txt, a_f_txt, a_f_srt, a_f_vtt],
                    concurrency_limit=1,
                )

            # ---------------- Video ----------------
            with gr.Tab("Video"):
                v_in = gr.Video(sources=["upload"], label="Upload video")
                v_btn = gr.Button("Transcribe", variant="primary")
                v_txt = gr.Textbox(label="Transcript", lines=10, show_copy_button=True)
                with gr.Row():
                    v_f_txt = gr.File(label="TXT")
                    v_f_srt = gr.File(label="SRT")
                    v_f_vtt = gr.File(label="VTT")
                v_btn.click(
                    transcribe_upload,
                    inputs=[v_in, engine_dd, lang_tb],
                    outputs=[v_txt, v_f_txt, v_f_srt, v_f_vtt],
                    concurrency_limit=1,
                )

            # ---------------- Microphone ----------------
            with gr.Tab("Microphone"):
                gr.Markdown(
                    "Click **Record**, speak Vietnamese, then **Stop** to flush the "
                    "last sentence. Final text is committed (stable); partial is the "
                    "live, still-changing estimate. After **Stop**, the exact audio the "
                    "system processed appears below for playback."
                )
                m_state = gr.State(None)
                m_in = gr.Audio(sources=["microphone"], streaming=True, label="Microphone")
                m_final = gr.Textbox(label="Final transcript (committed)", lines=6, show_copy_button=True)
                m_partial = gr.Textbox(label="Partial (live)", lines=2)
                m_wav = gr.Audio(
                    label="Processed audio (exactly what ASR received — 16 kHz mono)",
                    type="filepath", interactive=False, show_download_button=True,
                )
                m_clear = gr.Button("Clear")

                m_in.start_recording(
                    mic_start, inputs=[m_state, engine_dd, lang_tb],
                    outputs=[m_state, m_final, m_partial],
                )
                m_in.stream(
                    mic_stream,
                    inputs=[m_in, m_state, engine_dd, lang_tb],
                    outputs=[m_state, m_final, m_partial],
                    stream_every=0.5,
                    time_limit=None,
                    show_progress="hidden",
                    concurrency_limit=1,
                )
                m_in.stop_recording(
                    mic_stop, inputs=[m_state, engine_dd, lang_tb],
                    outputs=[m_state, m_final, m_partial, m_wav],
                )
                m_clear.click(mic_clear, inputs=[m_state], outputs=[m_state, m_final, m_partial, m_wav])

        gr.Markdown(
            "_Tip: keep one tab active at a time (inference is serialized). "
            "Exports for the last file are in the TXT/SRT/VTT boxes above._"
        )
    return demo


def main() -> None:
    # Pre-flight: warn (do NOT crash) if the default whisper.cpp model can't be
    # found. Path validation here is cheap and avoids the old failure mode where a
    # missing model only surfaced as a native segfault on the first transcription.
    try:
        validate_whispercpp_model_path(resolve_model_arg("whisper.cpp", None))
    except ModelLoadError as e:
        print(
            f"⚠️  Default whisper.cpp model not found — the UI will start, but "
            f"transcription will report an error until this is fixed:\n{e}\n",
            file=sys.stderr,
        )
    build_ui().queue().launch(server_name="127.0.0.1", inbrowser=False)


if __name__ == "__main__":
    main()
