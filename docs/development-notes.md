# Development Notes

## Scope

This repository starts with feasibility analysis and should evolve into a subtitle pipeline only after the source timing problem is solved.

## Proposed Modules

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
  - Escalate when no source is available by 12:15 PT.

## Design Boundary

Subtitle rendering, website embedding, and viewer UX are intentionally deferred. The first durable question is whether a usable source video, audio file, live stream, or transcript is available before the deadline.

## Current Operating Assumption

For Mariners Church, the public YouTube VOD source should be treated as post-event input, not as a source that can satisfy a Sunday 11:50 PT Chinese subtitle deadline.

