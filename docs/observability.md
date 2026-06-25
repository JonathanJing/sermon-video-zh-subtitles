# Observability And Logs

Chinese version: [observability.zh.md](./observability.zh.md)

The Sunday operation needs enough telemetry to answer three practical questions before and during the 11:30 PT service:

1. When did Cloud Scheduler, Cloud Tasks, or an operator trigger live capture?
2. When did captions become usable for the congregation page?
3. How many distinct devices opened the congregation caption page?

All backend, worker, and promotion logs are written as structured JSON to stdout. Cloud Run and Cloud Run Jobs ingest those records into Cloud Logging.

## Structured Events

| Event | Source | Purpose |
|---|---|---|
| `live_source_monitor_completed` | `POST /api/admin/sundays/YYYY-MM-DD/discover-source` or `scripts/live_source_monitor.py` | Records source discovery status, selected service/source kind, fallback/operator-alert state, and candidate count. |
| `live_capture_triggered` | `POST /api/admin/sundays/YYYY-MM-DD/generate` | Records that live capture was requested, including `triggerSource`, `sunday`, `sessionId`, `runPrefix`, and a safe live-source summary. |
| `live_capture_planned` | API when inline worker is disabled | Records the generated worker plan when the API is only planning or queueing work. |
| `live_capture_worker_started` | `python -m backend.worker` | Records that a Cloud Run Job or manual worker run actually started. |
| `worker_stage_started` / `worker_stage_completed` | API inline worker or Cloud Run Job | Records prepare, translate, upload, and promote stage timing. |
| `captions_ready` | Worker completion or `promote_sunday_manifest.py` | Records that a stable Sunday manifest is available for the congregation page. |
| `congregation_page_view` | Browser page load | Records anonymous page-view telemetry, including `anonymousDeviceId`, `visitId`, viewport, timezone, language, and `viewMode`. |

## Trigger Source Detection

`triggerSource` is read first from the request payload field `triggerSource` or `trigger_source`. If it is missing, the backend infers a source from headers:

- `cloud-scheduler`
- `cloud-tasks`
- `internal-task`
- `operator`

Cloud Scheduler should send an explicit payload:

```json
{
  "triggerSource": "cloud-scheduler",
  "service": "auto",
  "operatorAlertTime": "09:58",
  "autoGenerate": true
}
```

## Cloud Logging Queries

Live capture trigger:

```text
resource.type="cloud_run_revision"
jsonPayload.event="live_capture_triggered"
jsonPayload.sunday="2026-06-28"
```

Live-source discovery:

```text
resource.type="cloud_run_revision"
jsonPayload.event="live_source_monitor_completed"
jsonPayload.sunday="2026-06-28"
```

Captions ready:

```text
resource.type=("cloud_run_revision" OR "cloud_run_job")
jsonPayload.event="captions_ready"
jsonPayload.sunday="2026-06-28"
```

Congregation page views:

```text
resource.type="cloud_run_revision"
jsonPayload.event="congregation_page_view"
jsonPayload.viewMode="congregation"
jsonPayload.sunday="2026-06-28"
```

## Device Counts

The public page creates a random anonymous `anonymousDeviceId` in browser `localStorage`. It is not a login identity. It is only used to estimate distinct browser/device usage.

If Cloud Logging Log Analytics or a BigQuery sink is enabled, count distinct devices by `anonymousDeviceId`:

```sql
SELECT
  COUNT(DISTINCT jsonPayload.anonymousDeviceId) AS unique_devices,
  COUNT(*) AS page_views
FROM `PROJECT.DATASET._AllLogs`
WHERE jsonPayload.event = "congregation_page_view"
  AND jsonPayload.viewMode = "congregation"
  AND jsonPayload.sunday = "2026-06-28";
```

## Privacy And Security

- Do not log raw API keys, Secret Manager resource names, cookies, or `Authorization` headers.
- Live URLs are reduced to host/path plus a stable hash; full query strings are not logged.
- IP address and user agent are logged only as hashes.
- The browser device ID is random and anonymous; clearing browser storage creates a new ID.
