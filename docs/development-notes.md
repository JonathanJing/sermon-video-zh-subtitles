# Development Notes

## Scope

This repository started with feasibility analysis. The current design direction is to use the earliest verified pre-11:30 PT Mariners live service as the primary realtime source, keep 10:00 PT as the conservative production default, then use public VOD/live archive sources for offline quality passes.

## Proposed Modules

- `scripts/live_source_monitor.py`
  - Start every Sunday at 08:20 PT for the 8:30 service.
  - Check Mariners Online, YouTube streams, and manually configured fallback URLs.
  - Fall forward to the 10:00 service if the 8:30 source is missing or not confirmed as the same sermon.
  - Emit structured evidence for live source availability and trigger operator fallback if no 10:00 source is found by 09:58 PT.

- `services/realtime_session_api`
  - Create realtime caption sessions.
  - Issue short-lived provider credentials.
  - Expose status, events, reconnect, and freeze endpoints.

- `services/realtime_caption_worker`
  - Ingest live audio.
  - Produce draft and stable Chinese captions.
  - Persist stable segments and rolling VTT/SRT outputs.

- `scripts/detect_video_availability.py`
  - Poll a target YouTube video URL and channel videos feed.
  - Record first public availability time.
  - Store structured JSON evidence.

- `scripts/analyze_channel_publish_history.py`
  - Fetch recent channel videos.
  - Filter main sermon candidates.
  - Compute SLA metrics.
  - Emit CSV and Markdown summary.

- `scripts/run_sunday_sla_watch.py`
  - Scheduled runner for Sunday monitoring.
  - Escalate when no live source is available by 09:58 PT.
  - Continue VOD monitoring after the realtime service for offline-quality processing.

- `services/offline_job_worker`
  - Import existing captions when available.
  - Extract audio and run ASR when captions are missing.
  - Translate, align, enrich scripture references, generate notes, and export VTT/SRT.

- `scripts/offline_live_sermon_subtitles.py`
  - POC for accepting a YouTube live archive URL.
  - Discover a same-title edited sermon VOD when the live archive has no captions.
  - Infer sermon start from `live_duration - sermon_duration` unless manually overridden.
  - Download available VTT captions and emit sermon-local plus live-aligned VTT/SRT files.

## Design Boundary

The first production milestone is not a general video platform. It is an operator-first PWA that can monitor a live source, show realtime Chinese captions, preserve stable segments, and export usable subtitles before the Sunday deadline.

## Current Operating Assumption

For Mariners Church, the public YouTube VOD source should be treated as post-event input. The earliest verified pre-11:30 PT live service is the preferred source for meeting the Sunday 11:30-11:50 PT Chinese subtitle SLA, with 10:00 PT as the conservative default.
