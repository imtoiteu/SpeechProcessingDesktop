"""Lightweight LOCAL Gradio testing UI for the vnstt pipeline.

Purpose: rapid real-world testing and Vietnamese sample collection — NOT a
production app. No accounts, no database, no cloud. It only wires the browser to
the EXISTING pipeline, unchanged:

    upload/mic ─► decode_audio / resample ─► engine.transcribe
              ─► transcribe_file (hallucination filter + clamp)
              ─► to_txt / to_srt / to_vtt   (StreamingTranscriber for live mic)

Run:  python -m vnstt.ui      (after: uv pip install -e '.[ui]'  — installs gradio)

Live mic diagnostics (temporary, opt-in): set VNSTT_MIC_DEBUG=1 to log every mic
lifecycle event (start/stream/stop/clear, session + worker create/destroy, queue
size, audio seconds received vs exported, finish() join time / timeout) to stderr
with a timestamp + thread name, so a REAL browser session can be inspected. Set
VNSTT_MIC_LOG=/path/to/file to also append the same lines to a file. See doc 23.
"""
from __future__ import annotations

import os
import queue
import sys
import tempfile
import threading
import time
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


# ---- temporary live diagnostics (opt-in via VNSTT_MIC_DEBUG) ----
# This is investigation scaffolding (doc 23), NOT a feature. It exists so we can
# read what actually happens in a real browser session — when synthetic harnesses
# (which serialize start→stream→stop) can't reproduce the real event interleave.
def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() not in ("", "0", "false", "no", "off")


_MIC_DEBUG = _truthy(os.environ.get("VNSTT_MIC_DEBUG"))
_MIC_LOG_PATH = os.environ.get("VNSTT_MIC_LOG") or None
_T0 = time.monotonic()
_DBG_LOCK = threading.Lock()


def _dbg(event: str, **fields) -> None:
    """Emit one timestamped, thread-tagged diagnostic line (no-op unless enabled)."""
    if not _MIC_DEBUG:
        return
    t = time.monotonic() - _T0
    tid = threading.current_thread().name
    parts = " ".join(f"{k}={v}" for k, v in fields.items())
    line = f"[mic {t:9.3f}s {tid:>16}] {event:<22} {parts}".rstrip()
    with _DBG_LOCK:
        print(line, file=sys.stderr, flush=True)
        if _MIC_LOG_PATH:
            try:
                with open(_MIC_LOG_PATH, "a") as f:
                    f.write(line + "\n")
            except OSError:
                pass


def _wav_seconds(path: str | None) -> float | None:
    if not path or not os.path.isfile(path):
        return None
    try:
        with wave.open(path, "rb") as w:
            return round(w.getnframes() / float(w.getframerate()), 2)
    except Exception:
        return None


# ---- CLIENT-side (browser) diagnostics, injected into <head> only when debugging ----
# Investigation only — no fixes. Read-only wrappers around the browser audio-capture
# APIs the streaming mic uses, to answer ONE question: on recording #2, is the browser
# still capturing and emitting audio, or did capture stop before the server received it?
# Capture: open DevTools Console, reproduce, then run __micDump() to copy every line.
_MIC_CLIENT_JS = r"""
<script>
(function () {
  try {
    var t0 = performance.now();
    var buf = (window.__micClientLog = window.__micClientLog || []);
    function log(ev, info) {
      var ts = ((performance.now() - t0) / 1000).toFixed(3);
      var line = "[mic-client " + ts + "s] " + ev +
                 (info !== undefined ? " " + JSON.stringify(info) : "");
      buf.push(line);
      try { console.log(line); } catch (e) {}
    }
    window.__micDump = function () {
      var s = buf.join("\n");
      try { copy(s); console.log("(copied " + buf.length + " mic-client lines)"); } catch (e) {}
      return s;
    };
    log("loaded", { ua: navigator.userAgent });

    // getUserMedia + per-track lifecycle — the decisive "is it capturing?" signal.
    var md = navigator.mediaDevices;
    if (md && md.getUserMedia) {
      var gum = md.getUserMedia.bind(md);
      md.getUserMedia = function (c) {
        log("getUserMedia.request");
        return gum(c).then(function (s) {
          var tr = s.getAudioTracks();
          log("getUserMedia.granted", { audioTracks: tr.length });
          tr.forEach(function (t, i) {
            log("track.acquired", { i: i, readyState: t.readyState, enabled: t.enabled, muted: t.muted });
            t.addEventListener("ended",  function () { log("track.ENDED", { i: i }); });
            t.addEventListener("mute",   function () { log("track.MUTE", { i: i }); });
            t.addEventListener("unmute", function () { log("track.unmute", { i: i }); });
          });
          return s;
        }, function (e) { log("getUserMedia.ERROR", { e: String(e) }); throw e; });
      };
    } else { log("getUserMedia.MISSING"); }

    // track.stop(): did the app tear the mic down on Stop and never re-acquire it?
    if (window.MediaStreamTrack && MediaStreamTrack.prototype.stop) {
      var ostop = MediaStreamTrack.prototype.stop;
      MediaStreamTrack.prototype.stop = function () {
        log("track.stop()", { kind: this.kind, readyState: this.readyState });
        return ostop.apply(this, arguments);
      };
    }

    // AudioContext graph — streaming mic pushes raw PCM through a worklet.
    var AC = window.AudioContext || window.webkitAudioContext;
    if (AC && AC.prototype) {
      var cms = AC.prototype.createMediaStreamSource;
      if (cms) AC.prototype.createMediaStreamSource = function (s) {
        log("createMediaStreamSource", { ctxState: this.state,
            audioTracks: s.getAudioTracks ? s.getAudioTracks().length : "?" });
        try { var self = this; this.addEventListener("statechange",
              function () { log("AudioContext.state", { state: self.state }); }); } catch (e) {}
        return cms.apply(this, arguments);
      };
      ["resume", "suspend", "close"].forEach(function (m) {
        if (AC.prototype[m]) {
          var o = AC.prototype[m];
          AC.prototype[m] = function () { log("AudioContext." + m + "()", { state: this.state }); return o.apply(this, arguments); };
        }
      });
      var csp = AC.prototype.createScriptProcessor;
      if (csp) AC.prototype.createScriptProcessor = function () {
        var node = csp.apply(this, arguments), n = 0;
        try { node.addEventListener("audioprocess", function () { n++; if (n <= 2 || n % 40 === 0) log("scriptProcessor.audioprocess", { n: n }); }); } catch (e) {}
        log("createScriptProcessor", { ctxState: this.state });
        return node;
      };
    }

    // AudioWorkletNode: count PCM frames the mic actually produces on the main thread.
    if (window.AudioWorkletNode) {
      var OWN = window.AudioWorkletNode;
      function WAWN(ctx, name, opts) {
        log("AudioWorkletNode.new", { name: name, ctxState: ctx && ctx.state });
        var node = new OWN(ctx, name, opts);
        try {
          if (node.port && node.port.addEventListener) {
            var n = 0;
            node.port.addEventListener("message", function () { n++; if (n <= 3 || n % 40 === 0) log("worklet.msg", { n: n }); });
          }
        } catch (e) {}
        return node;
      }
      WAWN.prototype = OWN.prototype;
      try { window.AudioWorkletNode = WAWN; } catch (e) {}
    }

    // MediaRecorder — in case this build records-then-uploads instead of streaming PCM.
    if (window.MediaRecorder) {
      var OMR = window.MediaRecorder;
      function WMR(stream, opts) {
        log("MediaRecorder.new", opts || {});
        var mr = new OMR(stream, opts), n = 0, bytes = 0;
        mr.addEventListener("start", function () { log("MediaRecorder.start"); });
        mr.addEventListener("dataavailable", function (e) { n++; bytes += (e.data && e.data.size) || 0; if (n <= 3 || n % 5 === 0) log("MediaRecorder.data", { n: n, size: (e.data && e.data.size) || 0 }); });
        mr.addEventListener("stop", function () { log("MediaRecorder.stop", { chunks: n, bytes: bytes }); });
        mr.addEventListener("error", function (e) { log("MediaRecorder.ERROR", { e: String((e && e.error) || e) }); });
        return mr;
      }
      WMR.prototype = OMR.prototype;
      if (OMR.isTypeSupported) WMR.isTypeSupported = OMR.isTypeSupported.bind(OMR);
      try { window.MediaRecorder = WMR; } catch (e) {}
    }
  } catch (e) { try { console.log("[mic-client] instrumentation error", e); } catch (_) {} }
})();
</script>
"""


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
#
# ROUTING (reverted to the doc-20 baseline, doc 23): audio is routed by the per-event
# `m_state` session id, NOT by a module-global "armed session" pointer. The doc-22
# `_ACTIVE_SID` abstraction was reverted — it regressed first-recording quality and did
# not fix the real-world consecutive-session failure. We are re-baselining and
# instrumenting to capture REAL browser logs before changing routing again.
_MIC_SESSIONS: dict[str, "MicSession"] = {}


class MicSession:
    def __init__(self, engine_name: str, language: str, sid: str = "") -> None:
        self.sid = sid
        self.committed: list[str] = []          # touched only by the worker thread
        self._audio: list[np.ndarray] = []       # exact 16kHz samples processed (for WAV)
        self._recv_samples = 0                    # 16kHz samples ENQUEUED (received)
        self._snap = ("", "")                     # (committed, partial) published to the UI
        self._lock = threading.Lock()            # guards _snap and _audio (cross-thread)
        self._q: "queue.Queue" = queue.Queue()
        self.stopped = False
        self._wav_name = f"mic_{uuid.uuid4().hex[:8]}.wav"  # unique → no stale browser cache
        engine = _get_engine(engine_name)         # may raise ModelLoadError (before thread)
        self.st = StreamingTranscriber(
            engine, language=(language or "vi"), on_commit=self.committed.append
        )
        self._worker = threading.Thread(target=self._run, daemon=True, name=f"mic-{sid or '?'}")
        self._worker.start()

    def _run(self) -> None:
        _dbg("worker.start", sid=self.sid)
        n = 0
        while True:
            chunk = self._q.get()
            try:
                if chunk is None:                 # sentinel: queue drained, exit
                    _dbg("worker.sentinel", sid=self.sid, processed=n)
                    break
                with _MODEL_LOCK:                 # engine is shared / not thread-safe
                    self.st.feed(chunk)
                with self._lock:
                    self._audio.append(chunk)
                    self._snap = (" ".join(self.committed).strip(),
                                  " ".join(self.st.hyp.pending()).strip())
                n += 1
            finally:
                self._q.task_done()
        with self._lock:
            exported = sum(a.size for a in self._audio) / SAMPLE_RATE
        _dbg("worker.exit", sid=self.sid, processed=n, exported_s=round(exported, 2))

    def enqueue(self, audio: np.ndarray) -> None:
        self._recv_samples += int(audio.size)
        self._q.put(audio)
        if _MIC_DEBUG:
            _dbg("worker.enqueue", sid=self.sid, qsize=self._q.qsize(),
                 recv_s=round(self._recv_samples / SAMPLE_RATE, 2))

    def snapshot(self) -> tuple[str, str]:
        with self._lock:
            return self._snap

    def finish(self) -> tuple[str, str | None]:
        """Drain the queue, flush the last utterance, stop the worker. -> (final, wav)."""
        if not self.stopped:
            with self._lock:
                backlog_s = sum(a.size for a in self._audio) / SAMPLE_RATE
            _dbg("finish.enter", sid=self.sid, qsize=self._q.qsize(),
                 recv_s=round(self._recv_samples / SAMPLE_RATE, 2),
                 processed_s=round(backlog_s, 2))
            t = time.monotonic()
            self._q.put(None)                     # process everything queued, then stop
            self._worker.join(timeout=60)
            timed_out = self._worker.is_alive()   # backlog too big to drain in 60s → leak/short WAV
            with _MODEL_LOCK:
                self.st.close()
            with self._lock:
                self.stopped = True
                self._snap = (" ".join(self.committed).strip(), "")
                exported = sum(a.size for a in self._audio) / SAMPLE_RATE
            _dbg("finish.done", sid=self.sid, join_s=round(time.monotonic() - t, 2),
                 timed_out=timed_out, recv_s=round(self._recv_samples / SAMPLE_RATE, 2),
                 exported_s=round(exported, 2))
        return self.snapshot()[0], self._save_wav()

    def _save_wav(self) -> str | None:
        with self._lock:
            audio = np.concatenate(self._audio) if self._audio else np.zeros(0, np.float32)
        if audio.size == 0:
            _dbg("wav.empty", sid=self.sid)
            return None
        path = os.path.join(_OUT_DIR, self._wav_name)
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
            w.writeframes(pcm.tobytes())
        _dbg("wav.save", sid=self.sid, wav=self._wav_name, wav_s=round(audio.size / SAMPLE_RATE, 2))
        return path


def _new_session(engine_name: str, language: str) -> str:
    # Prune old finished sessions so the registry can't grow without bound.
    for old in [k for k, s in list(_MIC_SESSIONS.items()) if s.stopped][:-4]:
        _MIC_SESSIONS.pop(old, None)
        _dbg("session.prune", sid=old)
    sid = uuid.uuid4().hex[:12]
    _MIC_SESSIONS[sid] = MicSession(engine_name, language, sid=sid)
    _dbg("session.create", sid=sid, n_sessions=len(_MIC_SESSIONS))
    return sid


def mic_start(sid, engine_name, language):
    # doc-20 baseline (reverted from doc-22): Record pressed. If a racing stream chunk
    # already opened a (non-stopped) session for this m_state id, REUSE it so the onset
    # isn't orphaned (RC-3); otherwise open a fresh session.
    _dbg("mic_start.enter", sid_in=sid)
    sess = _MIC_SESSIONS.get(sid) if sid else None
    if sess is not None and not sess.stopped:
        _dbg("mic_start.reuse", sid=sid)
        return sid, "", ""
    try:
        new = _new_session(engine_name, language)
    except ModelLoadError as e:
        _dbg("mic_start.model_error", err=str(e))
        return None, f"⚠️ {e}", ""
    _dbg("mic_start.new", sid_out=new)
    return new, "", ""


def mic_stream(new_chunk, sid, engine_name, language):
    # doc-20 baseline routing: route by the per-event m_state `sid`.
    have = new_chunk is not None
    sess = _MIC_SESSIONS.get(sid) if sid else None
    if sess is None:
        # No session yet for this id. Lazily open one only if there is audio (this is the
        # session-1 m_state=None path, and the pre-start_recording onset race).
        if not have:
            _dbg("mic_stream.noop", sid_in=sid)
            return sid, "", ""
        try:
            sid = _new_session(engine_name, language)
        except ModelLoadError as e:
            _dbg("mic_stream.model_error", err=str(e))
            return None, f"⚠️ {e}", ""
        sess = _MIC_SESSIONS[sid]
        _dbg("mic_stream.lazy_create", sid=sid)
    if sess.stopped:
        # doc-20 behaviour (the suspected bug): a stopped session drops the chunk and
        # echoes its own id back into m_state. Instrumented so real logs reveal whether
        # this branch is actually being hit on session 2 in a live browser.
        c, p = sess.snapshot()
        _dbg("mic_stream.drop_stopped", sid=sid, have=have)
        return sid, c, p
    if have:
        sr, y = new_chunk
        in_samples = int(np.asarray(y).size)
        audio = _to_mono16k(y, sr)
        if audio.size:
            sess.enqueue(audio)                   # returns immediately; worker does the ASR
        if _MIC_DEBUG:
            _dbg("mic_stream.feed", sid=sid, sr=sr, in_samples=in_samples,
                 samples16k=int(audio.size), qsize=sess._q.qsize())
    c, p = sess.snapshot()
    return sid, c, p


def mic_stop(sid, engine_name, language):
    # Finalize the session named by m_state (doc-20 baseline).
    _dbg("mic_stop.enter", sid_in=sid)
    sess = _MIC_SESSIONS.get(sid) if sid else None
    if sess is None:
        _dbg("mic_stop.no_session", sid_in=sid)
        return sid, "", "", None
    t = time.monotonic()
    final, wav = sess.finish()
    _dbg("mic_stop.done", sid=sid, dur_s=round(time.monotonic() - t, 2),
         final_chars=len(final), wav=os.path.basename(wav) if wav else None,
         wav_s=_wav_seconds(wav))
    return sid, final, "", wav


def mic_stop_and_remount(sid, take_n, engine_name, language):
    # Generator (doc 23 §12): closes the remount-latency race. The mic is DISABLED on the
    # first yield — emitted BEFORE the possibly-multi-second mic_stop->finish() drain — so the
    # user can't start the next take on the stale streaming component while it finalizes. Only
    # the FINAL yield bumps m_take, which re-renders the mic tab and destroys+recreates the
    # gr.Audio (a fresh MediaRecorder/stream pipeline) — the workaround for Gradio #10486
    # (streaming mic stops sending after the first Stop without a page reload). Routing/worker
    # are unchanged. gr.skip() leaves an output untouched.
    #       m_state     m_final     m_partial                        m_wav       m_take      m_in
    yield (gr.skip(), gr.skip(),
           "⏳ Finalizing previous recording — the mic resets in a moment…",
           gr.skip(), gr.skip(), gr.update(interactive=False))
    sid, final, partial, wav = mic_stop(sid, engine_name, language)
    # Deliver results AND bump m_take together; m_take's change then remounts a fresh, enabled
    # mic. This is the final yield, so destroying the (old) trigger component here is safe.
    yield (sid, final, partial, wav, int(take_n) + 1, gr.skip())


def mic_clear(sid):
    _dbg("mic_clear.enter", sid_in=sid)
    sess = _MIC_SESSIONS.get(sid) if sid else None
    if sess is not None and not sess.stopped:
        try:
            sess.finish()                         # stop the worker thread (avoid a leak)
        except Exception:
            pass
    return None, "", "", None


def build_ui() -> gr.Blocks:
    # Inject the read-only client diagnostics into <head> only while debugging; default
    # (VNSTT_MIC_DEBUG unset) ships no extra script and the UI is byte-for-byte unchanged.
    head = _MIC_CLIENT_JS if _MIC_DEBUG else None
    with gr.Blocks(title="vnstt — Vietnamese STT testing UI", head=head) as demo:
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
                # Bumped on every Stop; the streaming mic below re-renders on this, which
                # remounts a FRESH gr.Audio so the browser rebuilds its capture/stream
                # pipeline for the next take (workaround for Gradio #10486 — the streaming
                # mic stops sending after the first Stop without a page reload).
                m_take = gr.State(0)
                # Outputs live OUTSIDE the render so they persist across mic remounts.
                m_final = gr.Textbox(label="Final transcript (committed)", lines=6, show_copy_button=True)
                m_partial = gr.Textbox(label="Partial (live)", lines=2)
                m_wav = gr.Audio(
                    label="Processed audio (exactly what ASR received — 16 kHz mono)",
                    type="filepath", interactive=False, show_download_button=True,
                )
                m_clear = gr.Button("Clear")

                # @gr.render re-runs on load and whenever m_take changes; with no `key=`,
                # Gradio destroys+recreates the component each render (a fresh front-end
                # MediaRecorder), instead of reusing the stale one that stops dispatching.
                # All listeners that use the in-render component must be defined in here.
                @gr.render(inputs=[m_take])
                def _mic_input(_take_n):
                    m_in = gr.Audio(sources=["microphone"], streaming=True, label="Microphone")
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
                        mic_stop_and_remount, inputs=[m_state, m_take, engine_dd, lang_tb],
                        outputs=[m_state, m_final, m_partial, m_wav, m_take, m_in],
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
    if _MIC_DEBUG:
        print(
            "🔎 VNSTT_MIC_DEBUG on (doc 23):\n"
            "   • SERVER mic lifecycle → stderr"
            + (f" + {_MIC_LOG_PATH}" if _MIC_LOG_PATH else "")
            + "\n   • CLIENT capture diagnostics → browser DevTools Console "
            "([mic-client …]); run __micDump() there to copy all lines.",
            file=sys.stderr,
        )
    build_ui().queue().launch(server_name="127.0.0.1", inbrowser=False)


if __name__ == "__main__":
    main()
