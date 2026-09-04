# Sermon Video Chinese Subtitles

<p>
  <a href="./README.zh.md">
    <img src="https://img.shields.io/badge/Language-中文说明-blue" alt="中文说明" />
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </a>
</p>

This repository has one product goal: help Chinese-speaking attendees follow an English sermon. It now has two concrete operator workflows—a Saturday post-live PDF workflow and a Sunday local live-caption POC. Everything else is research, evaluation, or infrastructure supporting those two paths.

The complete diagrams, artifact contracts, local latency budget, and test gates are in the [two-workflow README](docs/workflows/README.zh.md).

> **State calibrated on 2026-09-04.** Current claims below are backed by code, tests, or versioned reports on `main`; they are not a live health check of local services or venue readiness. Per-run recordings, transcripts, and PDFs are intentionally kept out of Git; reviewed benchmark derivatives may be versioned with provenance. Output filenames describe the artifact contract rather than bundled deliverables.

> This is an independent personal open-source project. It is not affiliated with, endorsed by, sponsored by, approved by, or operated by Mariners Church. Use only public or otherwise authorized media, and do not bypass access controls, DRM, or platform restrictions.

![Project workflow map](docs/diagrams/project-map.svg)

## 1. Working workflows

### A. Saturday: livestream/archive to two reviewed PDFs

The Saturday workflow discovers or receives the public livestream URL, preserves the complete post-live media, asks an operator to confirm the sermon window, transcribes the English sermon, prepares the Chinese reading text, and renders two canonical outputs for Sunday use:

1. `sermon_zh_en_reading.pdf` — the bilingual translation/reading edition.
2. `sermon_interpretation_zh.pdf` — the Chinese sermon companion/outline, limited to sermon-related supporting information.

![Saturday post-live dual-PDF workflow](docs/diagrams/saturday-post-live-workflow.svg)

This is the repository's mature post-live path. A run is not complete until the source, approved window, reading-text QA, both PDFs, and both PDF QA reports are present and passing.

Key references:

- [Stable post-live reading-PDF workflow](docs/stable-post-live-reading-pdf-workflow.md)
- [Codex local weekend production runbook](docs/codex-local-production-runbook.zh.md)
- [Sermon Production Supervisor Agent](docs/sermon-production-supervisor-agent.md)

### B. Sunday: local microphone to live Chinese captions

The Sunday workflow runs locally on a MacBook: browser microphone capture, durable audio/event logging, local English ASR, MiLMMT English-to-Chinese translation, and a one-page large-type caption display.

![Sunday local live-caption workflow](docs/diagrams/sunday-live-workflow.svg)

The current POC implements microphone selection, durable recording, Qwen3-ASR 0.6B through MLX, MiLMMT 4B Q8 token streaming, large captions, a tokenized read-only phone viewer, frozen-English replay/A-B, and per-session performance evidence. A repaired 60-minute real browser/speaker/microphone soak completed with 99.92% ASR final availability and 100% translation final availability. It remains a POC until the explicitly excluded church-site rehearsal is completed.

Key references:

- [Complete Saturday/Sunday workflow and latency budget](docs/workflows/README.zh.md)
- [Local live-caption POC](experiments/local-live-poc/README.md)
- [Local live-caption design](experiments/local-live-poc/DESIGN.zh.md)

## 2. Discovery, gaps, and next work

### What has been demonstrated

| Area | Current evidence |
|---|---|
| Saturday PDF production | Workflow code, tests, dated QA evidence, human sermon-window gate, resumable state; generated PDFs remain local/ignored |
| Sunday live POC | Real microphone, Qwen3-ASR, MiLMMT token stream, 60-minute soak, large UI, read-only phone viewer |
| Saturday-to-Sunday context | Ordered weekly-pack builder, guarded runtime policy, provenance-safe automatic activation |
| Replay and A/B | Frozen ASR finals, deterministic context-policy replay, blind review CSV, source/model hashes |
| Operations | One-click start/stop, supervisor/recovery, session retention preview/apply, fail-closed ASR Gold gate |

### Active discovery and missing gates

- **Formal ASR accuracy:** five speakers and edge cases have provisional machine-reference evidence; the six-case human word-level Gold queue still requires an actual reviewer before its WER can be used for model promotion.
- **Verified live latency:** in the repaired 60-minute Qwen + MiLMMT run, audio-end-to-browser-first-Chinese was p50 1.419s / p95 1.486s; complete Chinese was p50 1.530s / p95 1.720s. Venue acoustics can differ.
- **Content-pack quality decision:** tooling is complete, but a real Saturday pack and human review of blind A/B output are still needed each week; machine Chinese is not silently injected.
- **Local runtime options:** Ollama is the current A0 path; direct MLX serving remains a Discovery alternative and must use the same frozen inputs and latency/quality gate before replacement.
- **Operational boundary:** one-hour local soak and controlled MLX recovery passed. The remaining production gate is the formal church-site rehearsal; LAN viewer access also depends on the venue Wi-Fi allowing client-to-client traffic.
- **Resource ceiling:** Ollama memory grew during the one-hour soak without latency collapse, and post-run swap was 0 MB. The main sampler's point-in-time swap field was invalid, so it is not evidence of zero swap throughout; clean startup before each service remains the rule until multi-service testing establishes a higher bound.

### Post-training track

Post-training remains a separate project and must not complicate the live POC contract:

1. Build a provenance-preserving parallel corpus from existing subtitle sources, reviewed Saturday/Sunday translations, terminology corrections, and selected audio evidence.
2. Freeze train/dev/test splits by sermon to prevent segment leakage; only human-approved `Gold` material is eligible for promotion.
3. Use a strong teacher translation plus independent bilingual review; send only risky segments and a stable sample to audio review.
4. Train a smaller student translation model with SFT/LoRA, then compare it against MiLMMT A0 on terminology, Scripture names, adequacy, hallucination rate, and latency.
5. Promote a model only when the frozen evaluation gate passes. The browser should remain unchanged; replacing `LOCAL_LIVE_OLLAMA_MODEL` swaps the backend model.

All other architecture, provider comparisons, cloud experiments, historical realtime prototypes, and deployment notes belong in the [documentation index](docs/README.md), not in the primary product narrative.
