"""READ-ONLY diagnostic: does the pipeline actually produce multiple segments?

Streams a clip through /asr/file and records, for every WebSocket message, the
raw `lines` the SERVER sent. Then simulates the client store exactly as
live_transcription.js does (upsertLines keyed by start_s) to see how many
segments survive into the store. No app code is modified.
"""
import asyncio
import json
import sys

import websockets

WS = "ws://localhost:8000/asr/file?language=vi"


async def probe(path, label):
    data = open(path, "rb").read()
    messages = []  # each: list of non-silence line dicts (trimmed)
    async with websockets.connect(WS, max_size=None) as ws:
        cfg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        assert cfg.get("type") == "config"

        async def receiver():
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=180)
                except (asyncio.TimeoutError, websockets.ConnectionClosed):
                    break
                msg = json.loads(raw)
                if msg.get("type") in ("ready_to_stop", "error"):
                    break
                lines = msg.get("lines", [])
                trimmed = [
                    {
                        "speaker": ln.get("speaker"),
                        "start": ln.get("start"),
                        "start_s": ln.get("start_s"),
                        "end_s": ln.get("end_s"),
                        "tlen": len((ln.get("text") or "")),
                        "text": (ln.get("text") or ""),
                    }
                    for ln in lines
                ]
                messages.append(trimmed)

        rt = asyncio.create_task(receiver())
        chunk = 256 * 1024
        for i in range(0, len(data), chunk):
            await ws.send(data[i:i + chunk])
        await ws.send(b"")
        await rt

    # ---- analyze ----
    print(f"\n================ {label} ({path}) ================")
    print(f"messages received: {len(messages)}")

    # server segment counts per message (non-silence lines with text)
    seg_counts = []
    speaker_kinds = set()
    for m in messages:
        textsegs = [l for l in m if l["speaker"] != -2 and l["tlen"] > 0]
        seg_counts.append(len(textsegs))
        for l in m:
            speaker_kinds.add(l["speaker"])
    print(f"per-message TEXT-segment count: min={min(seg_counts) if seg_counts else 0} "
          f"max={max(seg_counts) if seg_counts else 0}")
    print(f"distinct speaker values seen across all lines: {sorted(speaker_kinds)}")

    # final message = server's final view
    final = messages[-1] if messages else []
    final_text = [l for l in final if l["speaker"] != -2 and l["tlen"] > 0]
    final_sil = [l for l in final if l["speaker"] == -2]
    print(f"\nFINAL server message: {len(final_text)} text-segment(s), {len(final_sil)} silence-segment(s)")
    for i, l in enumerate(final_text):
        print(f"  text-seg[{i}] start={l['start']} start_s={l['start_s']} end_s={l['end_s']} "
              f"len={l['tlen']} text={l['text'][:60]!r}")
    for i, l in enumerate(final_sil):
        print(f"  silence[{i}] start={l['start']} start_s={l['start_s']} end_s={l['end_s']}")

    # simulate the client store: key by start_s (mirror upsertLines)
    store = {}
    distinct_start_s = set()
    for m in messages:
        for l in m:
            if l["speaker"] == -2:
                continue  # new renderer skips silence; store still keys all, but text filter drops empty
            key = str(l["start_s"]) if l["start_s"] is not None else str(l["start"])
            store[key] = l
            if l["tlen"] > 0:
                distinct_start_s.add(l["start_s"])
    store_text = [v for v in store.values() if v["tlen"] > 0]
    print(f"\nCLIENT STORE simulation (upsertLines keyed by start_s):")
    print(f"  total store keys: {len(store)}")
    print(f"  store entries WITH text (= timestamps the new renderer would show): {len(store_text)}")
    print(f"  distinct start_s among text segments (ever seen): {len(distinct_start_s)}")
    # show the store text entries sorted by start
    for k, v in sorted(((str(x['start_s']), x) for x in store_text), key=lambda kv: float(kv[0]) if kv[0] not in ('None',) else 0):
        print(f"    store[{v['start_s']}] len={v['tlen']} text={v['text'][:55]!r}")

    return {
        "messages": len(messages),
        "final_text_segs": len(final_text),
        "store_text_entries": len(store_text),
        "distinct_start_s": len(distinct_start_s),
    }


async def main():
    r1 = await probe("/tmp/clip_continuous.wav", "CONTINUOUS 49s (no >5s gaps; mimics natural mic recording)")
    r2 = await probe("/tmp/clip_gaps.wav", "GAPPED 41s (two real 6s silences; forces splits)")
    print("\n================ VERDICT ================")
    print(f"Continuous: server final segments={r1['final_text_segs']}, "
          f"client-store timestamps={r1['store_text_entries']}, distinct start_s ever={r1['distinct_start_s']}")
    print(f"Gapped:     server final segments={r2['final_text_segs']}, "
          f"client-store timestamps={r2['store_text_entries']}, distinct start_s ever={r2['distinct_start_s']}")


if __name__ == "__main__":
    asyncio.run(main())
