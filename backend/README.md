# Backend API / Worker Scaffold

This is the smallest backend path for the Sunday caption product. It keeps the
current static PWA untouched while adding a Cloud Run-compatible API surface.

## Public Read Path

- `GET /api/health`
- `GET /api/sundays/current`
- `GET /api/sundays/YYYY-MM-DD`
- `GET /api/sundays/YYYY-MM-DD/artifacts/<artifact-key>`
- `POST /api/telemetry/page-view`
- `GET /api/admin/status`

The public Sunday response is intentionally filtered. It exposes only playback
JS and caption files from the server-side manifest. It strips Secret Manager
resource names, admin controls, raw model output, and generated report JSON.

The page-view telemetry endpoint accepts anonymous browser/device metadata and
writes a `congregation_page_view` JSON log event. It does not create a login
identity and should not receive cookies, API keys, or raw user identifiers.

`GET /api/admin/status` returns a safe Admin summary for the operator page. It
may show bucket/prefix, manifest status, timezone, and secret configured/missing
state, but must never return raw key material, tokens, cookies, or Secret
Manager resource names.

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

The planned worker chain prepares playback data, translates captions, generates
traceable notes/quote candidates with `gpt-5.5-mini` using reasoning effort
`medium`, updates `insights/openai-notes.json`, and then promotes the Sunday
manifest.

The next deployment step is to promote the selected run manifest to the stable
Sunday pointer:

```text
gs://$SERMON_ARTIFACT_BUCKET/$SERMON_ARTIFACT_PREFIX/YYYY-MM-DD/cloud-manifest.json
```

## Realtime Events

Realtime sessions use short-lived OpenAI client secrets for browser WebRTC and
store sanitized English/Chinese delta events in backend memory plus JSONL files
under `REALTIME_EVENT_LOG_DIR` (default `/tmp/sermon-realtime-events`). The JSONL
archive intentionally omits API keys, client secrets, event tokens, and request
authorization headers. Firestore/GCS can replace this first local archive once
the production state store is wired.

Server-side media workers can create a backend-only realtime session and publish
events into the same SSE/public-caption contract:

```bash
python3 scripts/realtime_media_worker.py \
  --sunday 2026-06-28 \
  --backend-url http://127.0.0.1:8080 \
  --create-backend-session \
  --replay-jsonl /tmp/sermon-realtime-events/<session_id>.jsonl
```

For an authorized local audio source, the worker plans an `ffmpeg` normalization
step:

```bash
python3 scripts/realtime_media_worker.py \
  --sunday 2026-06-28 \
  --audio-file /path/to/authorized-sermon-audio.m4a \
  --dry-run
```

To stream a server-side media source into `gpt-realtime-translate`, enable the
OpenAI WebSocket relay. The worker sends base64 24 kHz PCM16 chunks to
`/v1/realtime/translations`, maps `session.output_transcript.delta` to Chinese
caption deltas, maps `session.input_transcript.delta` to English sidecar deltas,
and posts both to the backend event stream:

```bash
python3 scripts/realtime_media_worker.py \
  --sunday 2026-06-28 \
  --audio-file /path/to/authorized-sermon-audio.m4a \
  --backend-url http://127.0.0.1:8080 \
  --create-backend-session \
  --connect-openai \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest
```

For an authorized YouTube live/archive source, the worker can use `yt-dlp` to
resolve the best audio stream before piping it through `ffmpeg` into the same
WebSocket relay. This path must still be live-validated with the actual
authorized source and platform rules before Sunday production.

Saved realtime JSONL can be stabilized with `gpt-5.5-mini` after a short delay:

```bash
python3 scripts/stabilize_realtime_deltas_with_openai.py \
  --input-jsonl /tmp/sermon-realtime-events/<session_id>.jsonl \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest
```

The output is `artifacts/realtime-stable-corrections/stable-corrections.json`
plus a report and raw model-output JSONL. This is the bridge from low-latency
draft captions to higher-quality stable captions.

## Observability

Backend and worker logs are structured JSON records written to stdout for Cloud
Logging. Key events are:

- `live_capture_triggered`
- `live_capture_planned`
- `live_capture_worker_started`
- `worker_stage_started`
- `worker_stage_completed`
- `realtime_session_created`
- `realtime_media_worker_event`
- `realtime_caption_event`
- `captions_ready`
- `congregation_page_view`

See [docs/observability.md](../docs/observability.md) for Cloud Logging queries
and the privacy boundary for device counts.
