# Sermon Video Chinese Subtitles

证道视频中文字幕项目，用于在 Mariners Church 周日 11:30 场证道中，为正在听道的中文会众提供可使用的中文字幕。

The project builds a pipeline for usable Chinese captions during the Sunday 11:30 sermon, so Chinese-speaking congregants can follow the message while it is being preached.

## Product North Star

The core product goal is not only to archive or translate sermons after the fact. The core goal is:

```text
By the time the 11:30 PT service begins, Chinese-speaking congregants should have a usable caption experience that helps them listen to the sermon in real time.
```

All realtime, offline, UI, and export work should be evaluated by whether it improves that 11:30 listener experience.

## Current Focus

- Prepare usable Chinese captions before the 11:30 PT service audience needs them.
- Use the earliest verified pre-11:30 PT Mariners live service as the preparation source, with 10:00 PT as the conservative default.
- Let an operator monitor readiness, review key terms/scripture, and publish captions for the 11:30 service.
- Keep offline processing, notes, and quote extraction as support features for quality, review, and follow-up.

## Key Finding

Based on the current public YouTube metadata analysis for Mariners Church, waiting for the public VOD to appear cannot meet a Sunday 11:50 PT completion deadline. Recent Sunday sermon videos typically become public around 12:28-12:43 PT, with a median around 12:31 PT.

The more promising input is the official live service. Mariners Online lists Sunday live services at 7:00, 8:30, 10:00, and 11:30 AM PT. The system design therefore prepares captions from the earliest verified same-sermon service, treats 10:00 PT as the conservative production default, and uses public VOD as a later offline-quality source.

## Repository Contents

- [System design in Chinese](docs/system-design.zh.md)
- [Findings report in Chinese](docs/findings-report.zh.md)
- [Bilingual analysis report](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md)
- [Historical publish timing dataset](data/mariners_church_sunday_sermon_publish_times.csv)
- [Live source findings dataset](data/mariners_church_live_source_findings.csv)
- [Frontend operator prototype](web/)
- [Project notes](docs/development-notes.md)

## Offline POC

Prepare the web playback simulation from a live archive link:

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

Then open `web/index.html` and click `模拟播放`. The page shows the sermon title, live-link status, and the caption line currently being generated for the 11:30 congregation view.

When generated content should be persisted for Cloud Run / production-style testing, publish it to GCS and reference the model API key through Secret Manager:

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

The POC first checks the live archive for captions. If none are available, it tries to find a same-title edited sermon VOD from the channel, infers where the sermon starts inside the live archive, and writes both sermon-local and live-aligned VTT/SRT files under `artifacts/offline-live-sermon-poc/`.

Build browser playback simulation data from the POC output:

```bash
python3 scripts/build_playback_simulation.py \
  --report artifacts/offline-live-sermon-poc/report.json \
  --out web/playback-simulation.generated.js
```

Then open `web/index.html` and click `模拟播放`. The browser uses the live-aligned subtitle timecodes to simulate how the 11:30 congregation caption view behaves during playback. If the available source captions are English, the UI keeps the English sidecar and marks the Chinese line as `AI 中文待生成` until the translation model is connected.

## Source Video

- Target video: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=V6OKiwbjDZE)
- Live archive candidate: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=FsUijL9uB1I)
- Channel: [Mariners Church](https://www.youtube.com/@marinerschurch)
