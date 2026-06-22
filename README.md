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

This is an independent open-source project and is not affiliated with, endorsed by, or operated by Mariners Church.

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
- Keep API/model keys in Google Secret Manager; generated files may reference secret resource names but must never include key material.
- Keep offline processing, notes, and quote extraction as support features for quality, review, and follow-up.

## Key Finding

Based on the current public YouTube metadata analysis for Mariners Church, waiting for the public VOD to appear cannot meet a Sunday 11:50 PT completion deadline. Recent Sunday sermon videos typically become public around 12:28-12:43 PT, with a median around 12:31 PT.

The more promising input is the official live service. Mariners Online lists Sunday live services at 7:00, 8:30, 10:00, and 11:30 AM PT. The system design therefore prepares captions from the earliest verified same-sermon service, treats 10:00 PT as the conservative production default, and uses public VOD as a later offline-quality source.

## Documentation

| Area | English | Chinese |
|---|---|---|
| Documentation index | [docs/README.md](docs/README.md) | [docs/README.zh.md](docs/README.zh.md) |
| System design | [docs/system-design.md](docs/system-design.md) | [docs/system-design.zh.md](docs/system-design.zh.md) |
| Findings report | [docs/findings-report.md](docs/findings-report.md) | [docs/findings-report.zh.md](docs/findings-report.zh.md) |
| Model/provider comparison | [docs/model-provider-comparison.md](docs/model-provider-comparison.md) | [docs/model-provider-comparison.zh.md](docs/model-provider-comparison.zh.md) |
| Cloud Run deployment prep | [docs/cloud-run-deployment-prep.md](docs/cloud-run-deployment-prep.md) | [docs/cloud-run-deployment-prep.zh.md](docs/cloud-run-deployment-prep.zh.md) |
| YouTube source analysis | [bilingual report](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md) | [same bilingual report](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md) |
| Backlog and review | [docs/backlog.md](docs/backlog.md), [docs/review-testing.md](docs/review-testing.md) | [docs/backlog.zh.md](docs/backlog.zh.md) |

Other project files:

- [Historical publish timing dataset](data/mariners_church_sunday_sermon_publish_times.csv)
- [Live source findings dataset](data/mariners_church_live_source_findings.csv)
- [Frontend operator prototype](web/)
- [Development notes](docs/development-notes.md)

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

The script uploads generated reports, VTT/SRT files, playback data, and `cloud-manifest.json` to GCS. It records only the Secret Manager resource name; API key material is never written into generated files.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [CONTRIBUTING.zh.md](CONTRIBUTING.zh.md), [SECURITY.md](SECURITY.md), and [SECURITY.zh.md](SECURITY.zh.md).

## License

MIT. See [LICENSE](LICENSE).

## Source Video

- Target video: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=V6OKiwbjDZE)
- Live archive candidate: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=FsUijL9uB1I)
- Channel: [Mariners Church](https://www.youtube.com/@marinerschurch)
