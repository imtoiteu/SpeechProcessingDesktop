"""Stage 0 runnability probe (throwaway, NOT the benchmark harness).
Answers only: does this Whisper-family model load, run on a small VN sample,
produce text, and roughly how much memory / how fast? One model+device per run.
"""
import sys, json, time, resource, argparse, wave
import numpy as np
import torch


def read_wav(path):
    w = wave.open(path, "rb")
    sr = w.getframerate()
    raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return a, sr


def peak_rss_gb():
    # macOS reports ru_maxrss in BYTES
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 3)


def make_pipe(model, dtype, device):
    from transformers import pipeline
    try:
        return pipeline("automatic-speech-recognition", model=model, dtype=dtype, device=device)
    except TypeError:
        return pipeline("automatic-speech-recognition", model=model, torch_dtype=dtype, device=device)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--device", default="cpu")  # cpu | mps
    ap.add_argument("--audio", default="sample.wav")
    args = ap.parse_args()

    res = {"model": args.model, "device": args.device}
    try:
        dtype = torch.float16 if args.device == "mps" else torch.float32
        arr, sr = read_wav(args.audio)
        res["audio_sec"] = round(len(arr) / sr, 3)

        t0 = time.time()
        asr = make_pipe(args.model, dtype, args.device)
        res["load_sec"] = round(time.time() - t0, 2)

        gen = {"language": "vietnamese", "task": "transcribe"}
        t1 = time.time()
        out = asr({"array": arr, "sampling_rate": sr}, generate_kwargs=gen)
        infer = time.time() - t1
        res["infer_sec"] = round(infer, 2)
        res["rtf"] = round(infer / res["audio_sec"], 3)
        res["text"] = out["text"].strip()
        res["peak_rss_gb"] = round(peak_rss_gb(), 2)
        res["status"] = "OK"
    except Exception as e:
        import traceback
        res["status"] = "ERROR"
        res["error"] = f"{type(e).__name__}: {e}"
        res["trace"] = traceback.format_exc()[-1200:]
        res["peak_rss_gb"] = round(peak_rss_gb(), 2)

    print("RESULT_JSON:" + json.dumps(res, ensure_ascii=False))


main()
