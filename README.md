# Sermon Video Chinese Subtitles

证道视频中文字幕项目，用于研究并建设从英文证道视频自动生成中文字幕的 pipeline。

The project explores and builds a pipeline for generating Chinese subtitles from English sermon videos.

## Current Focus

- Detect when a target YouTube sermon video becomes publicly available.
- Analyze historical publish timing for the same channel.
- Use the earliest verified pre-11:30 PT Mariners live service as the realtime source for the Sunday 11:30-11:50 PT subtitle SLA, with 10:00 PT as the conservative default.
- Design realtime and offline subtitle pipelines for Chinese captions, scripture sidebars, notes, and quote extraction.

## Key Finding

Based on the current public YouTube metadata analysis for Mariners Church, waiting for the public VOD to appear cannot meet a Sunday 11:50 PT completion deadline. Recent Sunday sermon videos typically become public around 12:28-12:43 PT, with a median around 12:31 PT.

The more promising input is the official live service. Mariners Online lists Sunday live services at 7:00, 8:30, 10:00, and 11:30 AM PT. The system design therefore tries the earliest verified same-sermon service first, treats 10:00 PT as the conservative production default, and uses public VOD as a later offline-quality source.

## Repository Contents

- [System design in Chinese](docs/system-design.zh.md)
- [Findings report in Chinese](docs/findings-report.zh.md)
- [Bilingual analysis report](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md)
- [Historical publish timing dataset](data/mariners_church_sunday_sermon_publish_times.csv)
- [Live source findings dataset](data/mariners_church_live_source_findings.csv)
- [Project notes](docs/development-notes.md)

## Source Video

- Target video: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=V6OKiwbjDZE)
- Live archive candidate: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=FsUijL9uB1I)
- Channel: [Mariners Church](https://www.youtube.com/@marinerschurch)
