# 5. Benchmark Methodology

> Per the benchmark-first policy: **no model/engine/architecture decision is final before this runs.**
> All numbers we produce must be measured on our pipeline. No invented numbers.

## Evaluation tiers (datasets)

| Tier | Dataset | License | Use | Caveat |
|------|---------|---------|-----|--------|
| Clean read-speech (commercial-safe) | [FLEURS-vi](https://huggingface.co/datasets/google/fleurs) | CC-BY-4.0 | Primary clean WER; cross-lingual comparable | ~12h, formal read speech |
| Clean read-speech (commercial-safe) | [Common Voice-vi](https://datacollective.mozillafoundation.org/) | CC0 | Clean WER; redistributable | ~6–7h validated (confirm on download) |
| Reference (license-flagged) | [VIVOS](https://huggingface.co/datasets/AILAB-VNUHCM/vivos) | CC-BY-NC-SA | Compare vs published numbers | **NC** — eval only, not shipped |
| Reference (gated) | [VLSP 2020/21](https://vlsp.org.vn/vlsp2020/eval/asr) | Gated agreement | Compare vs SOTA | Registration + constrained-use |
| Dialect (N/C/S) | [VietMed](https://huggingface.co/datasets/leduckhai/VietMed) (MIT), phonetically-balanced (arXiv 1904.05569), Regional Voice (paywalled) | mixed | Per-dialect WER | VietMed is medical-domain; Regional Voice license unconfirmed |
| Noisy / spontaneous | [Bud500](https://github.com/apluka34/Bud500) (Apache-2.0, ~500h), GigaSpeech2-vi | check upstream | Noisy/in-the-wild WER | Bud500 "research-only" note |
| Aggregated / general | **Vietnamese ASR: A Revisit** 500h set ([arXiv 2603.14779](https://arxiv.org/abs/2603.14779)) + VietASR set | TBD — check | Larger eval pool; the Revisit paper is an independent PhoWhisper-vs-ChunkFormer comparison | Read full paper first; confirm dataset license |
| Meeting / lecture | **GAP — no open corpus found** | — | — | Record our own small set, or license commercial. Use VLSP-T2 (spontaneous) as the nearest proxy in the meantime. |

**Note:** none of the public WER numbers (PhoWhisper paper, etc.) are on our pipeline; all latency/RTF numbers in
the literature are English/German/Czech on datacenter GPUs. Vietnamese × Apple-Silicon is **[UNKNOWN]** until we measure.

## Metrics

- **WER** (primary) and **CER** — CER matters for Vietnamese (tonal/diacritic, monosyllabic) where one wrong diacritic = wrong word.
- **Normalized WER** under a fixed text-normalization spec (case, diacritics, punctuation, number/unit normalization) — define once, apply uniformly, version it.
- **Per-dialect WER** (Northern / Central / Southern) reported separately.
- **Technical-term accuracy** (entity/keyword error rate on a curated VN technical term list).
- **RTF** (real-time factor = processing time ÷ audio duration) per model×engine×chip.
- **Peak memory** (model + KV/activations) — gate for 16 GB Macs.
- **Streaming metrics:** first-token latency, **commit latency** (audio→confirmed text), and streaming-vs-offline WER delta. ⚠️ The documented LocalAgreement-2 "~3.3 s" figure is **English, large-v2, on an A40 GPU — not transferable** to Vietnamese/PhoWhisper-medium/Apple-Silicon-CPU; LocalAgreement re-decodes the whole buffer each step, so CPU latency scales with utterance length. Measure on the real config.
- **Timestamp-alignment accuracy** (word/segment boundary error vs reference): Whisper word timestamps are fragile and can desync — measure this, do not assume SRT/VTT timing is correct just because WER is low.
- **Hallucination rate** on silence / music / non-speech segments (Whisper is known to fabricate on these).

## Controlled comparisons to run

1. **Model family & size:** PhoWhisper {small, medium, large} **vs ChunkFormer-Large-Vie (co-primary, non-commercial decision)**, + whisper-large-v3 zero-shot control. ChunkFormer eval must use the **same splits/normalization** as PhoWhisper (its published numbers are cross-paper). → settles "is bigger worth it?" *and* "Whisper vs CTC-native-streaming?"
2. **Engine:** faster-whisper (CPU) vs whisper.cpp (Metal/CoreML) vs mlx-whisper — on **identical** PhoWhisper weights. → settles Apple-Silicon engine + portability trade-off.
3. **Quantization:** fp16 vs Q8 vs Q4 (and CoreML ANE encoder) — WER delta vs speed/memory gain, with numeric-parity check vs HF reference.
4. **VAD:** Silero vs TEN vs WebRTC — segmentation accuracy + transition latency on noisy/dialect VN.
5. **Streaming policy:** LocalAgreement-2 vs AlignAtt (via WhisperLiveKit) — latency vs WER vs stability; chunk-size sweep (~1s vs ~2s, per UFAL findings).
6. **Correction A/B:** PhoWhisper alone vs PhoWhisper + Qwen3-{1.7B,4B} Q4 — net WER change (incl. hallucination/over-correction count) and added latency. → decides whether the correction layer exists at all.

## Procedure & reproducibility
- One harness, one config per run; pin model revisions, engine versions, decode params (beam size, temperature, VAD thresholds).
- Same normalized reference transcripts across all runs; store raw + normalized hypotheses.
- Report mean **and** spread; flag any catastrophic per-clip failures, not just averages.
- Record hardware (chip, RAM), OS, and thermal state caveats.
- Keep a results table that explicitly marks each cell as measured (with date) vs not-yet-run.

## Exit criterion for "benchmark phase done"
A populated comparison table (model × engine × quantization × dialect) with WER/CER/RTF/memory, plus
streaming latency and a correction A/B verdict — sufficient to choose a default model+engine **on evidence**.
