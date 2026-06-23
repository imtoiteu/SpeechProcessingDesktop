# 3. Repository & Model Research Plan

What to analyze, and **why it matters** for a decision. Items already researched (2026-06-23) are marked
with current findings; remaining work is flagged.

## Models (ASR)

| Repo / model | Why it matters | Status |
|---|---|---|
| [`vinai/PhoWhisper-{tiny..large}`](https://huggingface.co/vinai/PhoWhisper-large) | Primary candidate; BSD-3 commercial-safe; SOTA VN per paper | Researched. Params 39M/74M/244M/769M/1.55B; paper WER table captured. **To do:** measure on *our* pipeline. |
| [`khanhld/chunkformer-large-vie`](https://huggingface.co/khanhld/chunkformer-large-vie) | **Co-primary candidate** (non-commercial decision lifts the CC-BY-NC blocker): 110M, ≥ PhoWhisper-large accuracy claim at 14× fewer params, native streaming, CTC timestamps | Researched. **To do (now load-bearing):** independent WER under identical eval; **verify cross-platform runtime support (Win/Linux/servers + Apple Silicon)** — less mature than Whisper; check streaming API. |
| [`openai/whisper-large-v3`](https://huggingface.co/openai/whisper-large-v3) | Zero-shot VN baseline; Apache-2.0; reference for "does fine-tuning actually help us" | Researched (FLEURS-vi 8.59% per VietASR). Use as control. |
| [`nguyenvulebinh/wav2vec2-large-vi-vlsp2020`](https://huggingface.co/nguyenvulebinh/wav2vec2-large-vi-vlsp2020) | Strong VLSP numbers w/ LM; different (CTC) architecture | Researched. **CC-BY-NC.** Optional reference only. |
| **Vietnamese ASR: A Revisit** ([arXiv 2603.14779](https://arxiv.org/abs/2603.14779), EACL 2026 Findings) | **High priority** — independent same-test-set comparison of PhoWhisper vs ChunkFormer from the PhoWhisper authors; ships a **500h aggregated VN dataset**. May pre-answer the accuracy ranking + fill the eval-data gap. | Existence + authorship verified; **read full PDF in Phase 0** (abstract didn't expose the WER table; dataset license TBD). |
| **VN Whisper-large-v3-turbo fine-tunes** (e.g. [suzii/vi-whisper-large-v3-turbo](https://huggingface.co/suzii/vi-whisper-large-v3-turbo)) | Whisper-family low-latency candidate (4 decoder layers); promoted to must/nice-benchmark after review | Verified: real, ~240h fine-tune, but **no published WER, no stated license**, low usage → vet a usable checkpoint before relying. |
| VietASR (arXiv 2505.21527), TSPC (2509.05983) | 2024–25 VN ASR research context | Existence verified; headline WERs **unverified** — read before relying (VietASR also has a useful dataset). |

## Runtimes / engines

| Repo | Why it matters | Status / key finding |
|---|---|---|
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) + [CTranslate2](https://opennmt.net/CTranslate2/hardware_support.html) | Easiest PhoWhisper path (pre-converted CT2 exists); word timestamps; portable to NVIDIA | **CPU-only on macOS** — load-bearing limitation. |
| [ggml-org/whisper.cpp](https://github.com/ggml-org/whisper.cpp) | Only runtime with GPU on **both** Apple (Metal/CoreML) and NVIDIA (CUDA) + Win/Linux CPU | Best portability+accel; needs HF→GGML conversion for PhoWhisper. |
| [ml-explore/mlx-examples (whisper)](https://github.com/ml-explore/mlx-examples/tree/main/whisper) / [mlx-whisper](https://pypi.org/project/mlx-whisper/) | Fast Apple-native path; word timestamps; actively maintained | **Apple-only** → lock-in risk; PhoWhisper needs MLX conversion. |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | Word-level alignment + diarization (meetings) + VAD; on faster-whisper | CPU-only on Mac; useful later for meetings. |
| lightning-whisper-mlx | Claimed 10×; **stale (May 2024), no fine-tuned-model path** | Likely unsuitable; do not rely on speed claim. |

## VAD

| Repo | Why it matters | Status |
|---|---|---|
| [snakers4/silero-vad](https://github.com/snakers4/silero-vad) | Default VAD candidate; MIT; tiny; CoreML port | Researched. Verify 512-sample/16 kHz window constraints directly before coding. |
| [TEN-framework/ten-vad](https://github.com/TEN-framework/ten-vad) | Apache-2.0; claims better than Silero + faster transitions | Researched; **claims are vendor self-benchmarks** — must test on VN. |
| [wiseman/py-webrtcvad](https://github.com/wiseman/py-webrtcvad) | Ultralight DSP fallback | Researched; stale (2017) but stable; MIT. |

## Streaming frameworks

| Repo | Why it matters | Status / license flag |
|---|---|---|
| [ufal/whisper_streaming](https://github.com/ufal/whisper_streaming) | LocalAgreement-2 reference; ~3.3s English latency; MLX & faster-whisper backends | Adopt as streaming baseline. MIT. |
| [QuentinFuxa/WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) | Apache-2.0; integrates LocalAgreement **and** AlignAtt; Silero VAD; mlx/faster-whisper backends; active | Strong "buy vs build" candidate for mic mode. |
| [ufal/SimulStreaming](https://github.com/ufal/SimulStreaming) | AlignAtt; ~5× faster | **Contested license** — README says MIT but a "Noncommercial version" release exists; one source reports PolyForm-Noncommercial. WhisperLiveKit's AlignAtt backend *is* SimulStreaming, so its wrapper being Apache-2.0 does **not** clear this. Verify the LICENCE file before any commercial use; default to LocalAgreement-2. |
| [collabora/WhisperLive](https://github.com/collabora/WhisperLive) | MIT; multi-source (file/mic/RTSP) reference design | Reference for Audio Source abstraction. |

## Datasets (see [05](05-benchmark-methodology.md) for full detail)
- License-clean: [FLEURS-vi (CC-BY)](https://huggingface.co/datasets/google/fleurs), [Common Voice-vi (CC0)](https://datacollective.mozillafoundation.org/).
- Reference (license-flagged): [VIVOS (CC-BY-NC-SA)](https://huggingface.co/datasets/AILAB-VNUHCM/vivos), [VLSP (gated)](https://vlsp.org.vn/vlsp2020/eval/asr).
- Dialect / domain: [VietMed (MIT, all accents)](https://huggingface.co/datasets/leduckhai/VietMed), [Bud500 (Apache-2.0, ~500h)](https://github.com/apluka34/Bud500), phonetically-balanced N/C/S (arXiv 1904.05569), Regional Voice (6 regions, paywalled).

## Correction LLM
- [Qwen3 (Apache-2.0)](https://qwenlm.github.io/blog/qwen3/) 1.7B/4B; runs at Q4 on Apple Silicon. **To do only if A6 benchmark justifies it.** GER evidence base captured in [02](02-assumption-audit.md).

## Documentation still to read directly (not just via search)
- Silero VAD wiki/FAQ (confirm exact window/sample-rate constraints).
- CTranslate2 `ct2-transformers-converter` + whisper.cpp `convert-h5-to-ggml.py` + MLX `convert.py` docs (for the conversion-parity tasks).
- WhisperLiveKit README/architecture (buy-vs-build decision for mic mode).
- License texts: ChunkFormer / VIVOS / VLSP participation agreement / Bud500 "research-only" note.
