# Findings Report

Report date: 2026-06-22

Chinese version: [findings-report.zh.md](./findings-report.zh.md)

## Executive Summary

The public YouTube VOD source cannot meet the 11:50 PT subtitle deadline for the Mariners Church Sunday 11:30 PT sermon.

The target video, `V6OKiwbjDZE` (`The Cure for Our Rebellion - Eric Geiger | Mariners Church`), became publicly visible at approximately 2026-06-21 12:28:32 PDT. That is 38 minutes and 32 seconds after the 11:50 PT deadline. Even an instant transcription and translation pipeline would have missed the deadline.

Recent channel history shows the same pattern. In the sampled main Sunday sermon VODs, none were public before 11:50 PT. Public VOD availability is therefore useful for replay/offline captions, but not for a live congregation caption product.

## Questions Answered

1. Was the target video available before the Sunday 11:30 PT service?
2. Does the channel's historical publishing pattern support a reliable 11:50 PT subtitle deadline?

Both questions matter because the first pipeline dependency is source availability. If the source arrives late, model speed cannot recover the missed service-time window.

## Target Video

| Field | Value |
|---|---|
| Video ID | `V6OKiwbjDZE` |
| Title | `The Cure for Our Rebellion - Eric Geiger | Mariners Church` |
| Channel | Mariners Church |
| Duration | 30:58 |
| Public visibility time | 2026-06-21 12:28:32 PDT |

Relative timing:

| Comparison | Result |
|---|---:|
| Compared with 11:30 PT | 58m 32s late |
| Compared with 11:50 PT | 38m 32s late |

## Historical Channel Pattern

The sampled set contains 26 recent Sunday main-sermon videos after excluding podcasts, parenting content, daily devotionals, trailers, stories, shorts, and announcements.

| Metric | Result |
|---|---:|
| Sunday main sermon samples | 26 |
| Public before 11:30 PT | 0 / 26 |
| Public before 11:50 PT | 0 / 26 |
| Public before 12:00 PT | 0 / 26 |
| Earliest public time | 12:24:21 PT |
| Median public time | 12:31:48 PT |
| 90th percentile public time | 12:43:34 PT |
| Latest public time | 17:05:26 PT |

## Implication

A public-VOD-only pipeline becomes an after-service caption system. That can still be valuable for replay, archive, notes, and quotes, but it does not meet the 11:30 congregation use case.

To meet the service-time goal, the system needs an earlier input:

| Source path | Fit for 11:30 goal | Notes |
|---|---|---|
| Public YouTube VOD | No | Usually appears after 12:28 PT |
| Authorized pre-uploaded file | High | Best for stable high-quality captions |
| Authorized unlisted/private access | Possible | Requires church permission and stable access |
| Earlier official live service | High if same sermon | Best practical route for pre-generation |
| Realtime live audio/HLS | Possible | Needs latency and quality testing |
| Sermon notes/manuscript | High if available | Reduces ASR pressure |

## Recommendation

Do not design the first production milestone around public VOD availability. Build source discovery, evidence capture, and fallback handling first:

1. Monitor the target URL and channel list every Sunday.
2. Record first-seen time, title, duration, caption state, and source evidence.
3. Treat 10:00 PT live service as the conservative pre-generation default when it is confirmed as the same sermon.
4. Keep public VOD as the offline-quality source after the service.

Recommended project state:

```text
public-youtube-source-cannot-meet-sla
```
