# Development Notes

## Scope

This repository started with feasibility analysis. The current product goal is to help Chinese-speaking congregants understand the sermon while they are attending the 11:30 PT service. The design direction is to use the earliest verified pre-11:30 PT Mariners live service as the preparation source, keep 10:00 PT as the conservative production default, publish usable captions before the 11:30 service begins, then use public VOD/live archive sources for offline quality passes.

## Product Priority

1. The 11:30 PT congregation can open and read usable Chinese captions during the sermon.
2. The operator can confirm readiness and publish before 11:30 PT.
3. Scripture, names, and theological terms are accurate enough to help listening comprehension.
4. Offline processing improves quality and follow-up, but does not replace the live congregation experience.

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
  - Persist stable segments.
  - Publish reviewed captions to the 11:30 congregation view and keep rolling VTT/SRT as fallback outputs.

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
  - Escalate if no congregation-ready caption view is published by 11:25 PT.
  - Continue VOD monitoring after the 11:30 service for offline-quality processing.

- `services/offline_job_worker`
  - Import existing captions when available.
  - Extract audio and run ASR when captions are missing.
  - Translate, align, enrich scripture references, generate notes, and export VTT/SRT.

- `scripts/offline_live_sermon_subtitles.py`
  - POC for accepting a YouTube live archive URL.
  - Discover a same-title edited sermon VOD when the live archive has no captions.
  - Infer sermon start from `live_duration - sermon_duration` unless manually overridden.
  - Download available VTT captions and emit sermon-local plus live-aligned VTT/SRT files.

- `scripts/build_playback_simulation.py`
  - Convert the offline-live POC report and live-aligned VTT into browser-loadable playback data.
  - Let the PWA simulate a live archive playback timeline from the real live link output.
  - Preserve English source captions as sidecar text when Chinese captions are not yet generated, so the next model-integration step can be tested without changing the playback contract.

## Design Boundary

The first production milestone is not a general video platform. It is a service-time caption system: an operator-first PWA plus a low-friction congregation caption view that makes Chinese captions usable during the 11:30 sermon.

## Current Operating Assumption

For Mariners Church, the public YouTube VOD source should be treated as post-event input. The earliest verified pre-11:30 PT live service is the preferred source for preparing captions for the 11:30 congregation, with 10:00 PT as the conservative default.

## Current POC Loop

1. Run `scripts/offline_live_sermon_subtitles.py` with a YouTube live archive URL.
2. Confirm the inferred sermon start and generated live-aligned VTT/SRT.
3. Run `scripts/build_playback_simulation.py` to generate `web/playback-simulation.generated.js`.
4. Open the PWA and click `模拟播放` to verify that the congregation caption view can advance through real live-link subtitle timecodes.
5. Replace `AI 中文待生成` placeholders with model-generated Chinese captions in the next integration step.
