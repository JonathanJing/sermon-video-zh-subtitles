# Backend API / Worker Scaffold

This is the smallest backend path for the Sunday caption product. It keeps the
current static PWA untouched while adding a Cloud Run-compatible API surface.

## Public Read Path

- `GET /api/health`
- `GET /api/sundays/current`
- `GET /api/sundays/YYYY-MM-DD`
- `GET /api/sundays/YYYY-MM-DD/artifacts/<artifact-key>`
- `POST /api/telemetry/page-view`

The public Sunday response is intentionally filtered. It exposes only playback
JS and caption files from the server-side manifest. It strips Secret Manager
resource names, admin controls, raw model output, and generated report JSON.

The page-view telemetry endpoint accepts anonymous browser/device metadata and
writes a `congregation_page_view` JSON log event. It does not create a login
identity and should not receive cookies, API keys, or raw user identifiers.

Required config:

```text
SERMON_ARTIFACT_BUCKET=sermon-zh-artifacts-ai-for-god
SERMON_ARTIFACT_PREFIX=sundays
APP_TIMEZONE=America/Los_Angeles
```

For the already-generated POC run, the service can be pointed at an explicit
manifest while the formal Sunday pointer is promoted:

```text
SERMON_CURRENT_MANIFEST_URI=gs://sermon-zh-artifacts-ai-for-god/runs/2026-06-23/e2e-FsUijL9uB1I/artifacts/cloud-manifest.json
```

## Admin / Worker Path

- `POST /api/admin/sundays/YYYY-MM-DD/generate`

Auth accepts either:

```text
Authorization: Bearer $OPERATOR_ADMIN_TOKEN
X-Internal-Task-Token: $INTERNAL_TASK_TOKEN
```

By default the endpoint returns a generation command with HTTP 202. Set
`ENABLE_INLINE_WORKER=1` only for a controlled Cloud Run Job-style environment
where running the worker inside the request is acceptable.

Worker CLI:

```bash
python3 -m backend.worker \
  --sunday 2026-06-28 \
  --live-url 'https://www.youtube.com/watch?v=...' \
  --plan-only
```

The worker command writes generated content under:

```text
gs://$SERMON_ARTIFACT_BUCKET/$SERMON_ARTIFACT_PREFIX/YYYY-MM-DD/runs/<session_id>/
```

The next deployment step is to promote the selected run manifest to the stable
Sunday pointer:

```text
gs://$SERMON_ARTIFACT_BUCKET/$SERMON_ARTIFACT_PREFIX/YYYY-MM-DD/cloud-manifest.json
```

## Observability

Backend and worker logs are structured JSON records written to stdout for Cloud
Logging. Key events are:

- `live_capture_triggered`
- `live_capture_planned`
- `live_capture_worker_started`
- `worker_stage_started`
- `worker_stage_completed`
- `captions_ready`
- `congregation_page_view`

See [docs/observability.md](../docs/observability.md) for Cloud Logging queries
and the privacy boundary for device counts.
