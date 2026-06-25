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

- `POST /api/admin/sundays/YYYY-MM-DD/discover-source`
- `POST /api/admin/sundays/YYYY-MM-DD/generate`

Both endpoints also accept `current` in place of `YYYY-MM-DD`; the backend
resolves it to the active Sunday before writing logs, run prefixes, or
manifests. This keeps scheduled jobs stable without producing
`sundays/current/...` artifact paths.

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

Before triggering generation automatically, run the live-source monitor. It
checks 8:30 first, falls forward to 10:00 when the earlier source is missing or
not confirmed as the same sermon, and emits an operator-audio fallback alert
after the configured deadline:

```bash
python3 scripts/live_source_monitor.py \
  --sunday 2026-06-28 \
  --expected-title 'The Cure for Our Rebellion - Eric Geiger | Mariners Church' \
  --out artifacts/live-source-monitor/2026-06-28.json
```

The report includes sanitized candidate evidence, the selected source, and a
`generationRequest` payload that can be sent to
`POST /api/admin/sundays/YYYY-MM-DD/generate`. Fixture-based tests cover the
8:30 -> 10:00 -> operator audio fallback decision tree without relying on live
network behavior.

The same discovery flow is available inside the backend:

```bash
curl -sS -X POST "$SERVICE_URL/api/admin/sundays/2026-06-28/discover-source" \
  -H "X-Internal-Task-Token: $INTERNAL_TASK_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"autoGenerate":true,"service":"auto"}'
```

When `autoGenerate` is true and a usable source is selected, the endpoint returns
a generation plan summary with session id, GCS prefix, and command count. It
does not return worker commands, so the discovery response does not expose
Secret Manager resource names.

Cloud Scheduler can be configured with a redacted dry run first:

```bash
python3 scripts/configure_live_source_scheduler.py \
  --project ai-for-god \
  --location us-west1 \
  --service-url "$SERVICE_URL"
```

The generated job calls
`/api/admin/sundays/current/discover-source` with `autoGenerate:true`, so the
backend discovers the best 8:30/10:00/manual source and plans the offline
generation handoff for the resolved Sunday. To create or update the job, set
`INTERNAL_TASK_TOKEN` in the shell and pass `--apply`; dry-run output redacts
the token and does not expose Secret Manager resource names.

To let a scheduled job hand off directly to the backend generation endpoint,
add `--post-generate` and pass either the operator token or the internal task
token through the runtime environment:

```bash
python3 scripts/live_source_monitor.py \
  --sunday 2026-06-28 \
  --backend-url https://SERVICE_URL \
  --post-generate \
  --internal-task-token "$INTERNAL_TASK_TOKEN"
```

The worker command writes generated content under:

```text
gs://$SERMON_ARTIFACT_BUCKET/$SERMON_ARTIFACT_PREFIX/YYYY-MM-DD/runs/<session_id>/
```

The planned worker chain first preflights OpenAI Responses access for
`gpt-5.5-mini`, prepares playback data, translates captions with
`gpt-5.5-mini`, exports translated Chinese VTT/SRT files, validates the offline
chain contract, uploads the translated playback JS plus run manifest, and then
promotes the Sunday manifest. This keeps the caption publish path independent
from optional notes/quote generation.

To generate traceable notes/quote candidates after the caption manifest is
published, pass `includeInsights: true` in the generation request or
`--include-insights` on the worker CLI. That optional step uses `gpt-5.5-mini`
with reasoning effort `medium` and updates `insights/openai-notes.json`.

If a `gpt-5.5-mini` translation JSONL already exists and only the export or
publish steps need to be resumed, pass `translationsJsonl` in the generation
request or `--translations-jsonl` on the worker CLI. In that recovery mode the
worker replays the saved translations instead of making a fresh translation API
call. Treat that as artifact recovery evidence, not proof that new
`gpt-5.5-mini` access succeeded.

For YouTube live archives, the planned offline route is explicit:
`gpt-4o-transcribe` is used only when captions/VTT are unavailable, and
`gpt-5.5-mini` translates the aligned text. The translated playback JS is then
exported to `artifacts/sermon.zh.live-aligned.vtt` and
`artifacts/sermon.zh.live-aligned.srt`, and the archive path does not use
`gpt-realtime-translate`.

The worker runs the offline verifier before publishing:

```bash
python3 scripts/validate_offline_chain.py \
  --report /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/report.json \
  --playback-js /tmp/sermon-worker/YYYY-MM-DD/<session_id>/web/playback-simulation.generated.js \
  --zh-vtt /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/sermon.zh.live-aligned.vtt \
  --zh-srt /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/sermon.zh.live-aligned.srt \
  --manifest /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/cloud-manifest.json
```

This gate fails if the offline archive path uses `gpt-realtime-translate`, if
the ASR fallback uses anything other than `gpt-4o-transcribe`, if the report
does not include `offline_route.strategy=captions_first_then_asr`, if a caption
route claims audio extraction, if an ASR route is missing the
`no_requested_caption_track` fallback reason, if Chinese segments are still
placeholders, or if translated Chinese VTT/SRT outputs are missing.

The next deployment step is to promote the selected run manifest to the stable
Sunday pointer:

```text
gs://$SERMON_ARTIFACT_BUCKET/$SERMON_ARTIFACT_PREFIX/YYYY-MM-DD/cloud-manifest.json
```

The promoted manifest includes a `readiness` contract with the published state,
public artifact checks, source mode, published timestamp, fallback reason when
applicable, and model routing. `/api/sundays/current` and `/api/admin/status`
expose that safe summary without raw keys, event tokens, or Secret Manager
resource names.

Validate a promoted Sunday manifest before treating it as production-ready:

```bash
python3 scripts/validate_sunday_manifest.py \
  --manifest "gs://$SERMON_ARTIFACT_BUCKET/$SERMON_ARTIFACT_PREFIX/2026-06-28/cloud-manifest.json" \
  --sunday 2026-06-28 \
  --require-readable-artifacts
```

This gate requires translated Chinese VTT/SRT, a ready translated playback JS,
the expected model routing (`gpt-4o-transcribe`, `gpt-5.5-mini`, and
`gpt-realtime-translate`), readiness state, and clean secret flags.

When offline artifacts, the promoted Sunday manifest, and realtime JSONL are all
available, run the combined production gate:

```bash
python3 scripts/run_sunday_evidence_bundle.py \
  --sunday 2026-06-28 \
  --session-id <worker_session_id> \
  --artifact-location gcs \
  --artifact-bucket "$SERMON_ARTIFACT_BUCKET" \
  --artifact-prefix "$SERMON_ARTIFACT_PREFIX" \
  --realtime-location gcs \
  --realtime-event-gcs-prefix "$REALTIME_EVENT_GCS_PREFIX" \
  --require-readable-sunday-artifacts \
  --realtime-smoke-report artifacts/realtime-live-session/report.json \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --web-realtime-contract-report artifacts/evidence/web-realtime-contract.json \
  --realtime-public-sse-smoke-report artifacts/evidence/realtime-public-sse-smoke.json \
  --realtime-session-validation-report artifacts/evidence/realtime-openai-smoke/realtime-session-validation.json \
  --offline-chain-validation-report artifacts/evidence/offline-chain-validation.json \
  --offline-asr-smoke-report artifacts/evidence/offline-asr-fallback-smoke/report.json \
  --sunday-manifest-validation-report artifacts/evidence/sunday-manifest-validation.json \
  --openai-model-access-preflight-report artifacts/evidence/openai-model-access-preflight.json \
  --openai-alternative-model-access-preflight-report artifacts/evidence/openai-model-access-preflight-gpt-5.5.json \
  --out artifacts/evidence/caption-route-readiness.json \
  --evidence-matrix-out artifacts/evidence/production-evidence-matrix.json \
  --goal-audit-out artifacts/evidence/production-goal-readiness-audit.json \
  --bundle-report-out artifacts/evidence/sunday-evidence-bundle.json
```

The runner expands the standard GCS/local paths and calls
`validate_production_readiness.py`, then optionally generates the production
evidence matrix and goal audit in the same run. The resulting reports fail unless
the offline archive path is clean, the promoted Sunday manifest is readable, and
realtime English/Chinese deltas plus stable corrections are present. You can
still pass `--realtime-session-id` directly; when both are provided, the explicit
session id wins. If the smoke report includes `realtimeEventsJsonl`, that exact
JSONL URI is used before deriving one from the realtime session id.

## Realtime Events

Realtime sessions use short-lived OpenAI client secrets for browser WebRTC and
store sanitized English/Chinese delta events in backend memory plus JSONL files
under `REALTIME_EVENT_LOG_DIR` (default `/tmp/sermon-realtime-events`). The JSONL
archive intentionally omits API keys, client secrets, event tokens, and request
authorization headers. Set `REALTIME_EVENT_GCS_PREFIX=gs://BUCKET/PREFIX` to
mirror each session JSONL to GCS after every append, for example:

```text
REALTIME_EVENT_GCS_PREFIX=gs://sermon-zh-artifacts-ai-for-god/realtime-events
```

The mirror object path is `<prefix>/<sunday>/<session_id>.jsonl`. This keeps the
fast local archive for SSE/stabilizer reads while giving Cloud Run a durable
copy outside the container filesystem. Firestore can still replace this archive
later when exact segment state and richer query patterns are needed.

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

For a venue-provided authorized HTTP(S) audio stream, the worker can skip the
download step and let `ffmpeg` read the live stream directly. Reports redact URL
query strings so short-lived stream tokens do not end up in artifacts:

```bash
python3 scripts/realtime_media_worker.py \
  --sunday 2026-06-28 \
  --audio-url 'https://audio.example.test/live/sermon.m3u8?token=...' \
  --backend-url http://127.0.0.1:8080 \
  --create-backend-session \
  --connect-openai \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest
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

Use the end-to-end smoke wrapper for a short authorized audio clip when
validating `iPad/iPhone mic or captured audio -> gpt-realtime-translate ->
backend event stream -> public SSE`:

```bash
python3 scripts/realtime_openai_smoke_test.py \
  --sunday 2026-06-28 \
  --audio-file /path/to/authorized-short-sermon-audio.wav \
  --backend-url http://127.0.0.1:8080 \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest
```

Success requires both OpenAI realtime Chinese caption events and English input
transcript events to appear in the backend SSE stream. The report is written to
`artifacts/realtime-openai-smoke/report.json`; it records counts and paths but
does not include API key material or Secret Manager resource names.

For the 11:30 live run, prefer the live-session wrapper. It creates the backend
session once, keeps the event token in memory, starts the server media worker,
and runs `gpt-5.5-mini` stable corrections every few seconds against the saved
realtime JSONL. Use `--audio-url` for a venue-authorized stream, `--youtube-url`
for an authorized YouTube live source, or `--audio-file` for rehearsal:

```bash
python3 scripts/run_realtime_live_session.py \
  --sunday 2026-06-28 \
  --audio-url 'https://audio.example.test/live/sermon.m3u8?token=...' \
  --backend-url http://127.0.0.1:8080 \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --read-events-from-gcs \
  --require-stable-correction
```

The live-session report includes the session id, source kind, realtime/stable
models, worker counts, stable-correction counts, and the realtime JSONL URI; it
does not include the event token, API key material, or Secret Manager resource
names.

After a live/smoke session, validate the saved JSONL evidence before treating the
realtime path as production-ready:

```bash
python3 scripts/validate_realtime_session.py \
  --events-jsonl /tmp/sermon-realtime-events/<session_id>.jsonl
```

The verifier requires a realtime model event for `gpt-realtime-translate`,
English input transcript events, Chinese caption events, approved realtime event
sources, and a clean archive with no API keys, client secrets, event tokens, or
Secret Manager resource names.

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

To publish those stable corrections back into the live caption stream, include
the realtime session id and one posting credential. Browser WebRTC sessions do
not expose the event token to backend jobs, so use the operator admin token or
internal task token; the backend accepts those tokens only for
`gpt-5.5-mini-stable-correction` `caption_final` events:

```bash
python3 scripts/stabilize_realtime_deltas_with_openai.py \
  --input-jsonl /tmp/sermon-realtime-events/<session_id>.jsonl \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --post-backend-url http://127.0.0.1:8080 \
  --post-session-id <session_id> \
  --post-internal-task-token "$INTERNAL_TASK_TOKEN"
```

The script posts each stable correction as a `caption_final` event with source
`gpt-5.5-mini-stable-correction`, so the public SSE caption view can replace the
low-latency draft with the more stable Chinese line.

After stable corrections have posted, rerun the realtime session verifier with
the correction gate enabled:

```bash
python3 scripts/validate_realtime_session.py \
  --events-jsonl /tmp/sermon-realtime-events/<session_id>.jsonl \
  --require-stable-correction
```

For an already-running browser WebRTC session, the lower-level loop wrapper can
repeat the correction pass using admin/internal auth and skip segments it has
already posted. `--input-jsonl` may be a local event log or the GCS mirror URI:

```bash
python3 scripts/run_realtime_stabilizer_loop.py \
  --input-jsonl gs://sermon-zh-artifacts-ai-for-god/realtime-events/2026-06-28/<session_id>.jsonl \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url http://127.0.0.1:8080 \
  --session-id <session_id> \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --interval-seconds 6 \
  --min-age-seconds 4
```

The output is `artifacts/realtime-stable-corrections/stable-corrections.json`
plus a report and raw model-output JSONL. This is the bridge from low-latency
draft captions to higher-quality stable captions.

The loop writes `<session_id>.model-access-preflight.json` before the first
iteration. If `gpt-5.5-mini` is unavailable through OpenAI Responses, it exits
before reading event JSONL or posting any correction, which keeps the realtime
draft stream independent from delayed stable-correction failures.

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
