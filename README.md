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

> **State calibrated on 2026-09-04, code baseline main `beeda82`.** Current claims below are backed by code, tests, or versioned reports on `main`; they are not a live health check of local services or venue readiness. Per-run recordings, transcripts, and PDFs are intentionally kept out of Git; reviewed benchmark derivatives may be versioned with provenance. Output filenames describe the artifact contract rather than bundled deliverables.

> This is an independent personal open-source project. It is not affiliated with, endorsed by, sponsored by, approved by, or operated by Mariners Church. Use only public or otherwise authorized media, and do not bypass access controls, DRM, or platform restrictions.

![Project workflow map](docs/diagrams/project-map.svg)

## Why this architecture exists

Sunday services currently do not have dependable Chinese captions. Generic live speech translation can produce a useful draft, but it does not reliably preserve Scripture references, biblical names, quoted verses, or church-specific terminology. Unstable segmentation and end-to-end delay can also make otherwise correct text difficult to follow in the room.

The first hypothesis was to extract and translate the Saturday public livestream, then reuse that content on Sunday. Testing exposed an important boundary: the Saturday and Sunday sermons may follow the same message framework, but they cannot be assumed to be the same delivery word for word. Wording, order, examples, and live additions may differ. A Saturday transcript is therefore useful preparation, but it cannot be the source of truth for Sunday captions.

The current architecture supports an optional guarded hybrid; the tested Sunday default remains `contextPolicy=none`: Sunday live audio and the English recognized from it remain authoritative, while authorized Saturday material supplies guarded structure, terminology, Scripture references, and reviewed examples. Domain post-training is a separate future enhancement. Its first goal is better terminology and translation quality; any latency improvement must be demonstrated on frozen inputs and the same hardware rather than assumed.

![Solution journey from the Sunday caption gap to a guarded hybrid workflow](docs/diagrams/solution-journey.svg)

## 1. Working workflows

### A. Saturday: livestream/archive to two reviewed PDFs

The Saturday workflow discovers or receives the public livestream URL, preserves the complete post-live media, asks an operator to confirm the sermon window, transcribes the English sermon, prepares the Chinese reading text, and renders two canonical outputs for Sunday use:

1. `sermon_zh_en_reading.pdf` — the bilingual translation/reading edition.
2. `sermon_interpretation_zh.pdf` — the Chinese sermon companion/outline, limited to sermon-related supporting information.

<table>
  <tr>
    <th>Bilingual reading edition</th>
    <th>Chinese sermon companion</th>
  </tr>
  <tr>
    <td><img src="docs/assets/pdf-examples/sermon-zh-en-reading-real-page-1.png" alt="Real page 1 from the bilingual sermon reading PDF" /></td>
    <td><img src="docs/assets/pdf-examples/sermon-interpretation-zh-real-page-1.png" alt="Real page 1 from the Chinese sermon companion PDF" /></td>
  </tr>
</table>

_Real page-1 renders from the 2026-08-30 run. Both individual PDF QA reports pass; complete per-run PDFs remain outside Git. See the [example provenance](docs/assets/pdf-examples/README.md)._

![Saturday post-live dual-PDF workflow](docs/diagrams/saturday-post-live-workflow.svg)

The weekly Supervisor uses Astra Medium for translation, two reading reviews and the companion text, and enables Context Pack export after PDF QA. Exported message identity starts as `unknown`; automatic export is not human approval.

This is the repository's mature post-live path. A run is not complete until the source, approved window, reading-text QA, both PDFs, and both PDF QA reports are present and passing.

Key references:

- [Stable post-live reading-PDF workflow](docs/stable-post-live-reading-pdf-workflow.md)
- [Codex local weekend production runbook](docs/codex-local-production-runbook.zh.md)
- [Sermon Production Supervisor Agent](docs/sermon-production-supervisor-agent.md)

### B. Sunday: local microphone to live Chinese captions

The Sunday workflow runs locally on a MacBook: browser microphone capture, durable audio/event logging, local English ASR, MiLMMT English-to-Chinese translation, and a one-page large-type caption display.

![Sunday local live-caption workflow](docs/diagrams/sunday-live-workflow.svg)

The current implementation uses independent MediaRecorder recovery audio, 16 kHz PCM over WebSocket, Qwen3-ASR/MLX, and MiLMMT Q8 through Ollama. Immutable English finals pass a lexical fragment guard before immediate translation. The `readable_chunks` display retains the previous complete bilingual pair; Firebase Hosting/Realtime Database provides public read-only viewing, with a separate LAN/SSE fallback. Gateway recovery resumes the same session, preserves recording and viewer identity, and records caption gaps explicitly.

The merged runtime completed a **60-minute browser WAV replay** (20 minutes of unique audio repeated three times): **1,287 ASR finals → 1,287 translations → 1,287 readable operator-page displays**. P95 was **1.776 seconds from audio-segment end**, or **4.763 seconds from segment start**, to the first readable caption. This is delivery evidence, not translation accuracy, physical microphone/phone proof, or venue acceptance. See the [current readiness report](experiments/local-live-poc/benchmarks/SUNDAY_READINESS_20260904.zh.md).

![Local runtime, recovery storage and public/LAN viewing](docs/diagrams/local-live-architecture.svg)

Key references:

- [Complete Saturday/Sunday workflow and latency budget](docs/workflows/README.zh.md)
- [Local live-caption POC](experiments/local-live-poc/README.md)
- [Local live-caption design](experiments/local-live-poc/DESIGN.zh.md)

## 2. Discovery, gaps, and next work

### What has been demonstrated

| Area | Current evidence |
|---|---|
| Saturday PDF production | Workflow code, tests, dated QA evidence, human sermon-window gate, resumable state; generated PDFs remain local/ignored |
| Sunday live POC | Real-model browser WAV replay, readable display acknowledgements, verified recovery recording, phone viewport and reconnect checks; field gates remain |
| Saturday-to-Sunday context | Exporter, builder/retriever, readiness and Gateway capability ceiling implemented; Supervisor exports after PDF QA with message identity initially `unknown` |
| Replay and A/B | Frozen inputs and hashes; actual 3s/6s ASR and bounded translation-unit comparisons; neither candidate promoted |
| Operations | One-click start/stop, runtime identity, current-connection drain, same-session recovery, bounded public publisher and LAN fallback |

### Active discovery and missing gates

- **Saturday production bridge:** the Supervisor enables `--export-sunday-context` after dual-PDF QA. Export does not grant live usage: same-message approval, hashes, expiry and review status determine readiness. English-only alignment does not change the frozen A0 prompt. See the [Context Pack contract](docs/saturday-to-sunday-context-pack-plan.zh.md).
- **Semantic fidelity:** proper names, incomplete sentences, negation, causality and Scripture relations still need listening and bilingual human review. ASR Gold remains fail-closed; eight diagnostic listening groups are prepared locally. Machine-reviewed references are not human Gold.
- **Segmentation:** keep the 3-second window, `translationUnitPolicy=legacy`, `content_words` fragment guard and `contextPolicy=none` defaults. Longer windows and bounded semantic assembly produced both improvements and regressions; the latter remains opt-in evaluation code.
- **Recovery:** the actual Gateway restart replay preserved the independent recording, but had a 1.6-second PCM gap, one unresolved in-flight ASR task and a 7.234-second interval between new captions. Recovery is not lossless captioning.
- **Field acceptance:** venue microphone/mixer input, non-speech, physical phones on Wi-Fi/cellular and actual phone render latency still require validation. Public-viewer tab reconnect and portrait/landscape browser tests do not close these gates.
- **Resource ceiling:** 357 in-recording samples in the latest replay had zero swap, with initial/tail sampling gaps explicitly reported. Translation-process RSS rose from 5,863.719 to 9,664.609 MiB and still grew in the last ten minutes; no plateau or consecutive-service bound has been demonstrated.
- **Optional enhancements:** real weekly Pack benefit, alternate local serving and domain post-training remain separate evaluations. The no-Pack A0 path must continue working.

### Post-training track

Post-training remains a separate project and must not complicate the live POC contract:

1. Build a provenance-preserving parallel corpus from existing subtitle sources, reviewed Saturday/Sunday translations, terminology corrections, and selected audio evidence.
2. Freeze train/dev/test splits by sermon to prevent segment leakage; only human-approved `Gold` material is eligible for promotion.
3. Use a strong teacher translation plus independent bilingual review; send only risky segments and a stable sample to audio review.
4. Train a smaller student translation model with SFT/LoRA, then compare it against MiLMMT A0 on terminology, Scripture names, adequacy, hallucination rate, and latency.
5. Promote a model only when the frozen evaluation gate passes. The browser should remain unchanged; replacing `LOCAL_LIVE_OLLAMA_MODEL` swaps the backend model.

All other architecture, provider comparisons, cloud experiments, historical realtime prototypes, and deployment notes belong in the [documentation index](docs/README.md), not in the primary product narrative.
