# 17. Quality pass — onset word loss fixed + engine accuracy A/B

> Two pre-implementation-blocking quality tasks before any new capability:
> **(1)** fix onset word loss in mic streaming, **(2)** lightweight whisper.cpp-vs-
> faster-whisper accuracy comparison to decide whether whisper.cpp stays the default.
> Measured on the dev **M3 / 16 GB (fanless)**. 24 tests pass.

## 1. Onset word loss — root cause found and fixed

Previously documented (doc 16) as *"inherent to chunked-Whisper streaming + per-utterance
buffer reset."* **That was wrong.** Instrumenting every decode + emit on `multi.wav` showed the
onset word is decoded correctly **every time** and then lost in the streaming logic:

```
[PARTIAL] decode buf=1.0s raw=['.']          # whisper.cpp hallucinates a bare "." on silence
[PARTIAL] decode buf=2.0s raw=['.']          # LocalAgreement sees "." twice -> commits it
--- FINALIZE ---
[FINALIZE] decode raw=['.xin','chào','tôi','tên','là','lan.']
[FINALIZE] emit  in=['chào',...]   <-- ".xin" SKIPPED  → output "chào tôi tên là lan"  (xin lost)
```

**Mechanism:** whisper.cpp emits a bare `.` while only the onset silence is buffered. LocalAgreement-2
commits it into `committed[0]`. The real first word then arrives fused as `.xin`, but `insert()` /
`finalize()` slice from `len(committed)` (=1), so **index 0 is skipped and the first word is dropped.**
The phantom `.` only causes loss when it gets the 2-way agreement to commit — which is why utt1/utt3
lost their onset and utt2/utt4 (where `.` appeared only once) did not. A timing-dependent,
intermittent loss — exactly the symptom seen.

**Fix** (`_clean_tokens`, applied to every decode before it enters the buffer): drop punct-only
tokens (kills the phantom `.`) and strip a leading `.`/`…` off a word (`.xin` → `xin`). Committed
indices then always track real words.

| | before | after |
|---|---|---|
| `multi.wav` stream (4 utterances) | `chào …` / `đang thử …` (xin, tôi lost) | **`xin chào … tôi tên là lan. … tôi đang thử …`** (complete) |
| onset words preserved | 2 / 4 | **4 / 4**, stable across runs |

Regression guards added: `test_phantom_punctuation_does_not_eat_onset_word` (exact pattern, fast,
no model) and `test_stream_preserves_onset_words` (end-to-end on `multi.wav`, GGML-gated).

### Doubt-review correction (adversarial pass)
The first version of the fix stripped a broad punctuation set (`-`, `–`, `(`, `"`, …). A fresh-context
adversarial review (Critical finding **C1**) showed `lstrip` then corrupts content: `"-5"`→`"5"`,
`"3–5"`→`"35"`, `'"Nam"'`→`'Nam"'`. **Fixed:** only `.`/`…` are stripped now; dashes, signs, ranges
and quotes adjacent to content are preserved (`test_clean_tokens_preserves_signed_numbers_and_quotes`).
*Cross-model second opinion available on request — single-model review used here (as in the prior cycle).*

## 2. Engine accuracy A/B — whisper.cpp (default) vs faster-whisper (reference)

Batch decode (no streaming, so this isolates **engine fidelity**) of both fixtures with both engines.
Reproduce: `scripts/ab_engines.py`. **Precision note:** the GGML weights are **f16** (verified from the
file header — no quantization loss); faster-whisper loads CT2 weights and quantizes to **int8** at
runtime. So whisper.cpp is the *higher-precision* path; faster-whisper is a cross-implementation control.

| clip | whisper.cpp (f16, ~1.9 s) | faster-whisper (int8, 28–63 s) |
|---|---|---|
| `multi.wav` | `my` xin chào … cảm ơn bạn đã lắng nghe. | xin chào … lắng nghe. **+ fabricated:** *"đó là sự kế thừa cho cuộc sống bản thân mình vì sự trang trí của mình."* |
| `sample.wav` | `my` xin chào … trên **máy tiếng** apple silicon. | xin chào … trên **máy tính** apple silicon. **+ fabricated:** *"còn…… ngoài tác động tiêu biểu hàn quốc tại thái lan."* |

`whisper.cpp vs reference WER = 3.7%` (just the spurious `my`); `faster-whisper vs reference = 63%`
(inflated by its trailing fabrication).

**Findings (deterministic — whisper.cpp greedy decode is stable across runs):**
1. **On actual spoken content the two engines agree almost word-for-word.** The large engine-vs-engine
   WER (33–41%) is driven almost entirely by faster-whisper's hallucinations, not real disagreement.
2. **faster-whisper fabricates whole sentences on trailing silence — on both clips — even with its own
   anti-hallucination settings on** (`condition_on_previous_text=False`, `hallucination_silence_threshold`).
   whisper.cpp stays clean. The product's chars/sec filter (`transcribe_file`) would catch the dense
   `……` case but **not** the natural-text fabrication, so this is a real in-product risk for faster-whisper.
3. whisper.cpp's only genuine content slip: **`máy tiếng`** vs correct **`máy tính`** (faster-whisper
   right). One word; a decoding/implementation difference, not a precision one.
4. whisper.cpp inserts a spurious leading **`my`** at session start on both clips (deterministic onset
   artifact; in streaming it does not reach the committed output).
5. Speed: whisper.cpp **~15–30× faster** (~1.9 s vs 28–63 s on M3).

**Verdict: whisper.cpp is accurate enough to remain the default.** On clean speech it matches the
int8 reference on real content, is markedly cleaner on trailing silence, and is far faster. Its
weaknesses (leading `my`, occasional lexical slip like `máy tiếng`) are minor and bounded; faster-
whisper's whole-sentence fabrication is a worse failure mode for a product.

**Honest caveats (this is a sanity check, not a benchmark):** 2 clips, clean/likely-TTS, **no
dialectal, noisy, lecture, or meeting audio**. The `máy tiếng` slip hints whisper.cpp *may* trail the
reference on harder lexical/acoustic cases — unquantified. A definitive accuracy verdict needs real
dialectal recordings (deferred; needs user-provided audio).

## 3. Final assessment

### Production readiness
**Usable for conversational Vietnamese on Apple Silicon; not yet validated for adverse conditions.**
- ✅ Audio + video files (batch), real-time mic streaming, three export formats, engine abstraction,
  24 passing tests, clean per-utterance streaming UX, onset loss fixed.
- ⚠️ Gating factors: thermal throttling on fanless hardware (RTF→~1 under sustained load); accuracy
  proven only on clean/scripted speech; live-mic content unverifiable in this environment.

### Recommended default engine
**whisper.cpp / Metal (PhoWhisper-medium GGML, f16).** Co-primary fidelity with the int8 reference on
clean speech, cleaner trailing-silence behavior, ~15–30× faster. **faster-whisper stays available**
(`--engine faster-whisper`) as a cross-check / portability path (CPU, non-Metal hosts).

### Remaining known limitations
1. **Thermal throttling (fanless M3)** — decode slows 3–5× under sustained streaming; biggest limiter.
2. **whisper.cpp `máy tiếng`-class lexical slips** and a **leading `my`** session-start artifact — minor.
3. **LocalAgreement-2 cannot repair a committed word** the model later corrects (review finding M1) —
   inherent stability/accuracy trade-off of the streaming policy; low frequency.
4. **Standalone punctuation and syllable-vs-word granularity** — punct-only tokens are dropped; VN
   multi-syllable words commit per syllable (review M3/m2). Acceptable for transcription.
5. **Accuracy unproven on dialectal/noisy/long-form audio.** **Streaming emits TXT only.**

### Deferred roadmap (in priority order)
1. **Real-world accuracy validation** — dialectal (Northern/Central/Southern), noisy, lecture, meeting
   recordings; user-provided. Would also settle the `máy tiếng`-class question and whether a correction
   layer (Qwen) earns its cost.
2. **Streaming SRT/VTT** — needs streaming word timestamps.
3. **Onset `my` / lexical-slip cleanup** — small post-filter or beam-search trial.
4. **ChunkFormer-Large-Vie** evaluation (native streaming, CTC timestamps) as an alternative engine.
5. **SmartDocs-Agent integration.**
