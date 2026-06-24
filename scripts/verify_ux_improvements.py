"""Headless verification for the WLK UX improvements (docs/25).

Tests against a running server on :8000 (SimulStreaming / large-v3-turbo):
  1. /asr/file streaming of a moov@end MP4  -> progressive lines (video fix, Backend B+A)
  2. /asr per-session language en|vi|auto    -> badge reflects mode (Backend C)
  3. /v1/audio/transcriptions batch of MP4    -> text (Backend A)
"""
import asyncio
import json
import sys

import websockets

BASE_WS = "ws://localhost:8000"
BASE_HTTP = "http://localhost:8000"
MP4 = "/tmp/test_vid.mp4"            # moov@end (the bug trigger)
WAV = "tests/fixtures/sample.wav"    # any speech clip


async def _drive_ws(url, payload_bytes, chunk=256 * 1024, settle_timeout=120):
    """Connect, stream bytes + EOF sentinel, collect lines until ready_to_stop.

    Mirrors the real frontend: the server sends cumulative full-state each
    message, so we de-duplicate committed lines by their start key (exactly
    what live_transcription.js's upsertLines/transcriptStore does) instead of
    naively appending every message's text.
    """
    store, langs, n_msgs, err = {}, set(), 0, None
    async with websockets.connect(url, max_size=None) as ws:
        # config first
        cfg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        assert cfg.get("type") == "config", f"expected config, got {cfg}"

        async def receiver():
            nonlocal n_msgs, err
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=settle_timeout)
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    break
                msg = json.loads(raw)
                n_msgs += 1
                if msg.get("type") == "ready_to_stop":
                    break
                if msg.get("type") == "error":
                    err = msg.get("message")
                    break
                for ln in msg.get("lines", []):
                    if ln.get("speaker") == -2:
                        continue
                    key = ln.get("start_s")
                    if key is None:
                        key = ln.get("start", f"idx-{len(store)}")
                    store[key] = ln  # last write wins, same as the frontend
                    if ln.get("detected_language"):
                        langs.add(ln["detected_language"])

        recv_task = asyncio.create_task(receiver())
        for i in range(0, len(payload_bytes), chunk):
            await ws.send(payload_bytes[i:i + chunk])
        await ws.send(b"")  # EOF sentinel
        await recv_task
    # ordered by start key, like getStoreLines() rendered in arrival order
    ordered = [store[k] for k in store]
    lines = [ln["text"] for ln in ordered if ln.get("text")]
    return {"lines": lines, "langs": langs, "n_msgs": n_msgs, "err": err}


async def test_file_streaming_video():
    print("\n[1] /asr/file streaming of moov@end MP4 ...")
    data = open(MP4, "rb").read()
    r = await _drive_ws(f"{BASE_WS}/asr/file?language=auto", data)
    text = " ".join(r["lines"]).strip()
    print(f"    msgs={r['n_msgs']} langs={r['langs']} err={r['err']}")
    print(f"    text[:160]={text[:160]!r}")
    ok = r["err"] is None and len(text) > 0
    print(f"    -> {'PASS' if ok else 'FAIL'} (video streams + decodes via temp file)")
    return ok


async def test_language_modes():
    print("\n[2] /asr per-session language (en|vi|auto) ...")
    data = open(WAV, "rb").read()
    results = {}
    for lang in ("en", "vi", "auto"):
        r = await _drive_ws(f"{BASE_WS}/asr?language={lang}", data)
        results[lang] = r["langs"]
        print(f"    language={lang:4s} -> badge={r['langs'] or '{}'}  (lines={len(r['lines'])})")
    # Forced modes must report their forced language; previously ALL were 'vi'.
    en_ok = ("en" in results["en"]) and ("vi" not in results["en"])
    vi_ok = ("vi" in results["vi"])
    differ = results["en"] != results["vi"]
    ok = en_ok and vi_ok and differ
    print(f"    en_forces_en={en_ok} vi_forces_vi={vi_ok} en!=vi={differ}")
    print(f"    -> {'PASS' if ok else 'FAIL'} (SimulStreaming honors per-session language)")
    return ok


def test_batch_video():
    print("\n[3] /v1/audio/transcriptions batch of moov@end MP4 ...")
    import urllib.request
    import uuid
    boundary = uuid.uuid4().hex
    data = open(MP4, "rb").read()
    parts = []
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test_vid.mp4\"\r\nContent-Type: video/mp4\r\n\r\n".encode())
    parts.append(data)
    parts.append(f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"response_format\"\r\n\r\nverbose_json\r\n".encode())
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"language\"\r\n\r\nauto\r\n".encode())
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(
        f"{BASE_HTTP}/v1/audio/transcriptions", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.loads(resp.read())
    text = (out.get("text") or "").strip()
    print(f"    duration={out.get('duration')} segments={len(out.get('segments', []))}")
    print(f"    text[:160]={text[:160]!r}")
    ok = len(text) > 0
    print(f"    -> {'PASS' if ok else 'FAIL'} (batch video decodes from seekable temp file)")
    return ok


async def main():
    results = []
    results.append(("file-streaming-video", await test_file_streaming_video()))
    results.append(("language-modes", await test_language_modes()))
    results.append(("batch-video", test_batch_video()))
    print("\n==== SUMMARY ====")
    for name, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
