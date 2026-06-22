# Sermon Video Chinese Subtitles

证道视频中文字幕项目，用于研究并建设从英文证道视频自动生成中文字幕的 pipeline。

The project explores and builds a pipeline for generating Chinese subtitles from English sermon videos.

## Current Focus

- Detect when a target YouTube sermon video becomes publicly available.
- Analyze historical publish timing for the same channel.
- Decide whether a Sunday 11:30-11:50 PT subtitle generation SLA is feasible.
- Keep subtitle rendering/display design out of scope until source timing is proven viable.

## Key Finding

Based on the current public YouTube metadata analysis for Mariners Church, waiting for the public VOD to appear cannot meet a Sunday 11:50 PT completion deadline. Recent Sunday sermon videos typically become public around 12:28-12:43 PT, with a median around 12:31 PT.

## Repository Contents

- [Bilingual analysis report](docs/youtube-sermon-subtitle-pipeline-analysis.zh-en.md)
- [Historical publish timing dataset](data/mariners_church_sunday_sermon_publish_times.csv)
- [Project notes](docs/development-notes.md)

## Source Video

- Target video: [The Cure for Our Rebellion - Eric Geiger | Mariners Church](https://www.youtube.com/watch?v=V6OKiwbjDZE)
- Channel: [Mariners Church](https://www.youtube.com/@marinerschurch)

