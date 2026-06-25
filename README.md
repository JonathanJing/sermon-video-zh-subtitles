# Sermon Video Chinese Subtitles

<p>
  <a href="./README.zh.md">
    <img src="https://img.shields.io/badge/Language-中文说明-blue" alt="中文说明" />
  </a>
  <a href="./LICENSE">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License" />
  </a>
</p>

This project builds a pipeline for usable Chinese captions during the Mariners Church Sunday 11:30 PT sermon, so Chinese-speaking congregants can follow the message while it is being preached.

## Disclaimer

This is an independent personal open-source project. It is not affiliated with, endorsed by, sponsored by, approved by, or operated by Mariners Church.

The project uses publicly accessible Mariners Church live streams, live archives, and public video metadata as source material for transcription, translation, subtitle timing, and technical feasibility research. It does not use private Mariners Church systems, private media, YouTube Studio access, internal files, or any non-public channel permissions.

The project does not bypass paywalls, access controls, DRM, platform restrictions, or copyright protections. Operators are responsible for using the tools only with public or otherwise authorized audio/video sources and for respecting Mariners Church, YouTube, and other applicable terms and rights.

This repository is currently being prepared for broader open-source collaboration. Contributions are welcome when they improve the 11:30 congregation caption experience, especially around translation quality, latency, scripture terminology, mobile/tablet UX, deployment reliability, testing, and documentation.

## Product North Star

The core product goal is not only to archive or translate sermons after the fact. The core goal is:

```text
By the time the 11:30 PT service begins, Chinese-speaking congregants should have a usable caption experience that helps them listen to the sermon in real time.
```

All realtime, offline, UI, storage, and export work should be evaluated by whether it improves that 11:30 listener experience.

## Current Focus

- Prepare usable Chinese captions before the 11:30 PT service audience needs them.
- Use the earliest verified pre-11:30 PT Mariners live service as the preparation source, with 10:00 PT as the conservative default.
- Let an operator monitor readiness, review key terms/scripture, and publish captions for the 11:30 service.
- Store generated content in GCS for durable Cloud Run workflows.
- Keep API/model keys in Google Secret Manager; public browser files and generated artifacts must never include key material or Secret Manager resource names.
- Keep offline processing, notes, and quote extraction as support features for quality, review, and follow-up.

## Key Finding

Based on the current public YouTube metadata analysis for Mariners Church, waiting for the public VOD to appear cannot meet a Sunday 11:50 PT completion deadline. Recent Sunday sermon videos typically become public around 12:28-12:43 PT, with a median around 12:31 PT.

The more promising input is the official live service. Mariners Online lists Sunday live services at 7:00, 8:30, 10:00, and 11:30 AM PT. The system design therefore prepares captions from the earliest verified same-sermon service, treats 10:00 PT as the conservative production default, and uses public VOD as a later offline-quality source.

Current YouTube Streams metadata also supports the offline live-link route: among current visible Sunday live records, standard live links almost always start around 08:21 PT, leaving roughly three hours before the 11:30 PT congregation service for live/archive capture, English transcription, Chinese translation, and operator review. See [offline live-archive timing feasibility](docs/offline-live-archive-timing-feasibility.zh.md).

## Documentation

| Area | English | Chinese |
|---|---|---|
| Documentation index | [docs/README.md](docs/README.md) | [docs/README.zh.md](docs/README.zh.md) |
| System design | [docs/system-design.md](docs/system-design.md) | [docs/system-design.zh.md](docs/system-design.zh.md) |
| System design gap analysis | [docs/system-design-gap-analysis.md](docs/system-design-gap-analysis.md) | [docs/system-design-gap-analysis.zh.md](docs/system-design-gap-analysis.zh.md) |
| Findings report | [docs/findings-report.md](docs/findings-report.md) | [docs/findings-report.zh.md](docs/findings-report.zh.md) |
| Model/provider comparison | [docs/model-provider-comparison.md](docs/model-provider-comparison.md) | [docs/model-provider-comparison.zh.md](docs/model-provider-comparison.zh.md) |
| Cloud Run deployment prep | [docs/cloud-run-deployment-prep.md](docs/cloud-run-deployment-prep.md) | [docs/cloud-run-deployment-prep.zh.md](docs/cloud-run-deployment-prep.zh.md) |
| Admin workflow | [docs/admin-workflow.md](docs/admin-workflow.md) | [docs/admin-workflow.zh.md](docs/admin-workflow.zh.md) |
| Scripture source | [docs/scripture-source.md](docs/scripture-source.md) | [docs/scripture-source.zh.md](docs/scripture-source.zh.md) |
| Observability and logs | [docs/observability.md](docs/observability.md) | [docs/observability.zh.md](docs/observability.zh.md) |
| Open-source readiness | [docs/open-source-readiness.md](docs/open-source-readiness.md) | [docs/open-source-readiness.zh.md](docs/open-source-readiness.zh.md) |
| Sunday live test runbook | [docs/sunday-live-test-runbook.md](docs/sunday-live-test-runbook.md) | [docs/sunday-live-test-runbook.zh.md](docs/sunday-live-test-runbook.zh.md) |
| YouTube source analysis | [bilingual report](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md) | [same bilingual report](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md) |
| Offline live-archive timing feasibility | [Chinese report](docs/offline-live-archive-timing-feasibility.zh.md) | [same Chinese report](docs/offline-live-archive-timing-feasibility.zh.md) |
| Backlog and review | [docs/backlog.md](docs/backlog.md), [docs/review-testing.md](docs/review-testing.md) | [docs/backlog.zh.md](docs/backlog.zh.md) |

Other project files:

- [Historical publish timing dataset](data/mariners_church_sunday_sermon_publish_times.csv)
- [Live source findings dataset](data/mariners_church_live_source_findings.csv)
- [Frontend operator prototype](web/)
- [Development notes](docs/development-notes.md)

## Prerequisites

For local POC runs:

- Python 3.10 or newer.
- `yt-dlp` available on `PATH` for public YouTube metadata and subtitle extraction.
- Network access to the public source URLs used in the POC.

For GCS / Cloud Run-style artifact publishing:

- Google Cloud SDK `gcloud` installed and authenticated.
- Access to the target GCS bucket.
- Secret Manager resource names for model/API keys; do not pass raw key material.

## Operations And Logs

The Cloud Run API and worker write structured JSON logs to stdout for Cloud Logging. The current operational events cover live-capture triggers, worker stage timing, caption readiness, and anonymous congregation page views. See [Observability and logs](docs/observability.md) for event names, Cloud Logging queries, and the privacy boundary for device counts.

## Live-Link POC

Prepare the web playback simulation from a live archive link:

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

Then open `web/index.html` and click `模拟播放`. The page shows the sermon title, live-link status, and the caption line currently being generated for the 11:30 congregation view.

When generated content should be persisted for Cloud Run or production-style testing, publish it to GCS and reference the model API key through Secret Manager:

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I' \
  --gcs-bucket sermon-zh-artifacts \
  --gcs-prefix runs/2026-06-22/FsUijL9uB1I \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest
```

The script uploads generated reports, VTT/SRT files, playback data, and `cloud-manifest.json` to GCS. The Secret Manager resource name is validated at runtime but is not written into public generated artifacts; they only record `apiKeyMaterialIncluded=false` and `secretResourceNamesIncluded=false`.

For lower-level debugging, extract sermon subtitles from a live archive link:

```bash
python3 scripts/offline_live_sermon_subtitles.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

Build browser playback simulation data from the POC output:

```bash
python3 scripts/build_playback_simulation.py \
  --report artifacts/offline-live-sermon-poc/report.json \
  --out web/playback-simulation.generated.js
```

If the available source captions are English, the UI keeps the English sidecar and marks the Chinese line as `AI 中文待生成` until the translation model is connected.

## Open-Source Hygiene

- Do not commit API keys, cookies, generated transcripts, generated captions, model output JSONL, private media, or service account JSON files.
- Runtime secrets belong in Google Secret Manager. See [Cloud Run deployment prep](docs/cloud-run-deployment-prep.md).
- Generated artifacts belong in GCS or ignored local `artifacts/`.
- Respect platform permissions, copyright, and terms of service. This project does not bypass access controls or DRM.
- Before making the repository public, run the [open-source readiness checklist](docs/open-source-readiness.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [CONTRIBUTING.zh.md](CONTRIBUTING.zh.md), [SECURITY.md](SECURITY.md), and [SECURITY.zh.md](SECURITY.zh.md). Good first areas include caption quality, provider benchmarking, mobile/tablet ergonomics, scripture matching, deployment automation, and observability.

## License

MIT. See [LICENSE](LICENSE).

## Source Video

- Target video: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=V6OKiwbjDZE)
- Live archive candidate: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=FsUijL9uB1I)
- Channel: [Mariners Church](https://www.youtube.com/@marinerschurch)
