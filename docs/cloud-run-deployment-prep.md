# Cloud Run Deployment Prep

Last updated: 2026-06-23

Chinese version: [cloud-run-deployment-prep.zh.md](./cloud-run-deployment-prep.zh.md)

This checklist prepares the POC for Cloud Run while keeping the repository safe to open source. Runtime secrets go to Google Secret Manager. Public browser files, generated artifacts, Git history, logs, and GCS outputs must not contain secret values.

Sunday validation runbook: [sunday-live-test-runbook.md](./sunday-live-test-runbook.md)

## V1 Deployment Shape

| Module | V1 shape | Notes |
|---|---|---|
| `web` | Cloud Run static assets + API | PWA for congregation and operator |
| `api` | Same Cloud Run service | Sessions, segments, manifests, publish state |
| `worker` | Cloud Run job or background task | Offline ASR, translation, notes, quotes |
| `live-source-monitor` | Scheduler/Tasks invoking Cloud Run | Sunday source discovery and fallback alerts |
| `realtime-relay` | Optional separate service | Only needed for non-browser audio sources |

## Secrets To Store In Secret Manager

| Secret ID | Cloud Run env var | Required | Purpose |
|---|---|---:|---|
| `openai-api-key` | `OPENAI_API_KEY` | P0 if OpenAI is primary | Realtime translate, realtime whisper, corrections |
| `gemini-api-key` | `GEMINI_API_KEY` | P0/P1 recommended | Gemini Live Translate and Flash-Lite fallback |
| `openrouter-api-key` | `OPENROUTER_API_KEY` | P1 optional | Text-translation fallback and benchmark |
| `operator-session-secret` | `OPERATOR_SESSION_SECRET` | P0 | Operator session/cookie/JWT signing |
| `operator-admin-token` | `OPERATOR_ADMIN_TOKEN` | P0 temporary | Early private operator auth |
| `internal-task-token` | `INTERNAL_TASK_TOKEN` | P0/P1 if bearer auth is used | Internal Scheduler/Tasks calls |
| `youtube-data-api-key` | `YOUTUBE_DATA_API_KEY` | P1 optional | YouTube metadata API quota |
| `youtube-oauth-client-secret` | `YOUTUBE_OAUTH_CLIENT_SECRET` | Only if authorized OAuth is used | OAuth client secret |
| `youtube-cookies-txt` | secret volume file | Only with explicit authorization | Authorized metadata/caption access |
| `authorized-live-source-token` | `AUTHORIZED_LIVE_SOURCE_TOKEN` | Only for authorized source | Private relay or church-provided stream |
| `bible-api-key` | `BIBLE_API_KEY` | Optional | External/licensed Bible API |
| `alert-webhook-url` | `ALERT_WEBHOOK_URL` | Optional | Operator alerts |
| `sentry-dsn` | `SENTRY_DSN` | Optional | Error monitoring |

Do not use cookies, OAuth secrets, or source tokens to bypass access controls, DRM, or platform rules.

## Non-Secret Runtime Config

| Config | Suggested env var |
|---|---|
| GCS bucket | `SERMON_ARTIFACT_BUCKET` |
| GCS prefix | `SERMON_ARTIFACT_PREFIX` |
| Realtime event GCS mirror prefix | `REALTIME_EVENT_GCS_PREFIX=gs://<bucket>/realtime-events` for the background best-effort JSONL mirror; upload failures do not block live SSE |
| Firestore database / collection prefix | `FIRESTORE_DATABASE`, `FIRESTORE_COLLECTION_PREFIX` |
| Time zone | `APP_TIMEZONE=America/Los_Angeles` |
| Public base URL | `PUBLIC_BASE_URL` |
| Default live/channel URLs | `MARINERS_LIVE_URL`, `MARINERS_CHANNEL_URL` |
| Realtime provider | `REALTIME_TRANSLATE_PROVIDER=openai` |
| Model timeout and reconnect settings | `MODEL_TIMEOUT_MS`, `MODEL_RECONNECT_MS` |
| Feature flags | `ENABLE_OFFLINE_NOTES`, `ENABLE_OPENROUTER_BENCHMARK` |

## IAM

Use a Cloud Run service account instead of service account JSON keys:

```text
sermon-caption-runner@<project-id>.iam.gserviceaccount.com
```

Minimum practical permissions:

| Permission | Use |
|---|---|
| `roles/secretmanager.secretAccessor` | Read only required secrets |
| GCS object read/write role | Read/write generated artifacts bucket |
| `roles/datastore.user` | Firestore session and caption state |
| `roles/cloudtasks.enqueuer` | Enqueue offline jobs if used |
| `roles/run.invoker` | Scheduler/Tasks invocation |

Prefer per-secret IAM bindings instead of granting access to every project secret.

## Public Artifact Rules

- Public playback JS must not include raw secret values.
- Production public playback JS and generated GCS artifacts should not include Secret Manager resource names.
- Secret Manager resource names belong in runtime configuration, command invocations, or restricted deployment metadata, not in public or generated content artifacts.
- Logs must not print provider request headers, cookies, tokens, or model API keys.
- Generated transcripts, captions, model JSONL, and media stay out of Git.

## Readiness Checklist

- Required Secret Manager secrets exist.
- Cloud Run service account can read only the needed secrets.
- GCS bucket exists and the service account can read/write generated artifacts.
- Firestore is enabled and scoped for session/caption state.
- Public browser files have been checked for secret values and secret resource names.
- 11:30 SLA env vars are configured.
- Operator auth is enabled before any publish endpoint is exposed.

## Live Deployment Snapshot

Verified on 2026-06-23 around 13:29 PT:

| Field | Value |
|---|---|
| Project | `ai-for-god` |
| Region | `us-west1` |
| Service | `sermon-zh-caption-web` |
| URL | `https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/` |
| Status | `Ready` |
| Verified revision at snapshot time | `sermon-zh-caption-web-00012-bqj` |
| Recent ready rollback candidates at snapshot time | `sermon-zh-caption-web-00011-2nz`, `sermon-zh-caption-web-00010-54f`, `sermon-zh-caption-web-00009-bqz`, `sermon-zh-caption-web-00008-frx` |
| Traffic | `100%` to latest ready revision |
| Public invoker | `allUsers` has `roles/run.invoker` |
| Service account | Default Compute Engine service account, redacted in public docs |
| Artifact bucket | `sermon-zh-artifacts-ai-for-god` |
| Max scale | `20` |
| Container concurrency | `80` |

The service account is currently the default Compute Engine service account. Before a real production Sunday, prefer moving to a dedicated Cloud Run service account such as `sermon-caption-runner@PROJECT_ID.iam.gserviceaccount.com` with only the required Secret Manager and GCS permissions.

## Current Service Env Vars

Verified config on the current revision:

| Env var | Value | Secret? | Notes |
|---|---|---:|---|
| `APP_TIMEZONE` | `America/Los_Angeles` | No | Required for 11:30 PT workflow decisions. |
| `SERMON_ARTIFACT_BUCKET` | `sermon-zh-artifacts-ai-for-god` | No | Matches the verified bucket. |
| `SERMON_ARTIFACT_PREFIX` | `sundays` | No | Stable Sunday manifest prefix for congregation reads. |
| `OPENAI_API_KEY_SECRET` | `projects/PROJECT_NUMBER/secrets/openai-api-key/versions/latest` | Resource reference only | Server-side pointer used by the backend to resolve the OpenAI key. Do not expose this in public artifacts or browser JS. |

No raw provider API keys or operator tokens were visible in the Cloud Run service env var list returned by `gcloud run services describe`. The Secret Manager resource reference is deployment metadata and must stay server-side.

## Post-Deploy Validation Commands

```bash
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/app.js
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/playback-simulation.generated.js
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/health
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/sundays/current
```

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

```bash
gcloud run revisions list \
  --service=sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1
```

Pass criteria:

- Root URL returns `HTTP 200` and `content-type: text/html`.
- Required static JS assets return `HTTP 200`.
- `/api/health` returns `status=ok`.
- `/api/sundays/current` returns a filtered public Sunday payload and does not expose Secret Manager resource names.
- Service condition `Ready=True`.
- Traffic points to the intended revision.
- Public browser artifacts do not expose raw API keys, operator tokens, webhook URLs, or Secret Manager resource names.

## Cloud Scheduler Live-Source Job

Configure the weekly live-source discovery job with a redacted dry run first:

```bash
python3 scripts/configure_live_source_scheduler.py \
  --project ai-for-god \
  --location us-west1 \
  --service-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app
```

The job targets:

```text
/api/admin/sundays/current/discover-source
```

Payload shape:

```json
{
  "triggerSource": "cloud-scheduler",
  "service": "auto",
  "operatorAlertTime": "09:58",
  "autoGenerate": true
}
```

The backend resolves `current` to the active Sunday before planning artifact
paths, so generated runs still publish under
`sundays/YYYY-MM-DD/runs/<session_id>/`. When the dry-run output looks correct,
set `INTERNAL_TASK_TOKEN` in the shell and add `--apply` to create or update the
Cloud Scheduler job. The script redacts the token in its report; do not paste
the raw token into docs, shell transcripts, tickets, or logs.

## Observability Smoke

See [observability.md](./observability.md) for the event schema and standard queries.

After deployment, send one test page-view telemetry event and verify that Cloud Logging receives `congregation_page_view`:

```bash
curl -sS -X POST \
  -H 'content-type: application/json' \
  -d '{"anonymousDeviceId":"dev-deploy-smoke","visitId":"deploy-smoke","sunday":"2026-06-28","viewMode":"congregation","path":"/","timezone":"America/Los_Angeles","language":"en-US","viewport":{"width":390,"height":844},"screen":{"width":390,"height":844}}' \
  https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/telemetry/page-view
```

Cloud Logging query:

```text
resource.type="cloud_run_revision"
jsonPayload.event="congregation_page_view"
jsonPayload.anonymousDeviceId="dev-deploy-smoke"
```

For a Sunday workflow, also verify `live_capture_triggered`, `worker_stage_completed`, and `captions_ready` for the target `sunday`.

## GCS Artifact Verification

Bucket verification:

```bash
gcloud storage buckets describe gs://sermon-zh-artifacts-ai-for-god --format=json
gcloud storage ls gs://sermon-zh-artifacts-ai-for-god
```

Current bucket checks passed on 2026-06-23:

- Bucket exists in `US-WEST1`.
- Uniform bucket-level access is enabled.
- Public access prevention is enforced.
- Top-level `runs/` prefix exists.

After the worker exports translated captions and before treating the run as
publishable, validate the local/offline chain:

```bash
python3 scripts/validate_offline_chain.py \
  --report /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/report.json \
  --playback-js /tmp/sermon-worker/YYYY-MM-DD/<session_id>/web/playback-simulation.generated.js \
  --zh-vtt /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/sermon.zh.live-aligned.vtt \
  --zh-srt /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/sermon.zh.live-aligned.srt \
  --manifest /tmp/sermon-worker/YYYY-MM-DD/<session_id>/artifacts/cloud-manifest.json
```

Pass criteria: the verifier reports `status=ok`, uses a caption source or
`gpt-4o-transcribe` ASR fallback, confirms `gpt-5.5-mini` translation, rejects
any `gpt-realtime-translate` use in the offline path, confirms
`offline_route.strategy=captions_first_then_asr`, confirms caption routes did
not extract audio and ASR routes are marked as `no_requested_caption_track`
fallbacks, and finds readable Chinese VTT/SRT plus translated playback JS.

If the `gpt-5.5-mini` call has already produced a saved model-output JSONL but
the caption/export step must be resumed, replay the saved translations without
calling OpenAI again:

```bash
python3 scripts/translate_playback_with_openai.py \
  --input /tmp/sermon-worker/YYYY-MM-DD/<session_id>/web/playback-simulation.generated.js \
  --out /tmp/sermon-worker/YYYY-MM-DD/<session_id>/web/playback-simulation.generated.js \
  --out-dir /tmp/sermon-worker/YYYY-MM-DD/<session_id>/model-output \
  --translations-jsonl /tmp/sermon-worker/YYYY-MM-DD/<session_id>/model-output/openai-translation-output.jsonl \
  --model gpt-5.5-mini
```

This replay mode is only artifact recovery. It proves the saved translations can
be turned into playback/VTT/SRT/manifest outputs, but it is not evidence that a
fresh `gpt-5.5-mini` API call succeeded.

After a Sunday worker run and promotion, validate the stable Sunday manifest and
its public artifacts:

```bash
python3 scripts/validate_sunday_manifest.py \
  --manifest gs://sermon-zh-artifacts-ai-for-god/sundays/YYYY-MM-DD/cloud-manifest.json \
  --sunday YYYY-MM-DD \
  --require-readable-artifacts \
  --out artifacts/evidence/sunday-manifest-validation.json
```

Pass criteria: the verifier reports `status=ok`, includes translated Chinese
VTT/SRT outputs, confirms the playback JS has `translationStatus=ready`, records
`gpt-4o-transcribe` for offline ASR, `gpt-5.5-mini` for offline translation and
stable correction, `gpt-realtime-translate` for realtime draft, and finds no raw
key material or Secret Manager resource names.

For a live realtime session, validate the durable JSONL mirror as a separate
gate:

```bash
python3 scripts/validate_realtime_session.py \
  --events-jsonl gs://sermon-zh-artifacts-ai-for-god/realtime-events/YYYY-MM-DD/<session_id>.jsonl \
  --require-stable-correction
```

Pass criteria: the verifier reports `status=ok`, sees a
`gpt-realtime-translate` model event, English input transcript events, Chinese
caption events, approved realtime sources, at least one
`gpt-5.5-mini-stable-correction` caption final when the correction gate is
enabled, and no raw key material, client secrets, event tokens, or Secret
Manager resource names.

Because the current realtime public SSE stream keeps the active session in the
Cloud Run process while mirroring sanitized deltas to JSONL/GCS, the first
production realtime deployment must run as a single-instance service unless a
shared realtime fanout store is deployed. Validate the deployed service config:

For a quick read-only refresh before the 11:30 live run, use the consolidated
preflight wrapper. It does not run `gcloud run services update` and continues
through matrix/audit generation even when `gpt-5.5-mini` access or Cloud Run
realtime config fails. It also refreshes the non-mutating Cloud Run update plan
and apply dry-run evidence, but never passes `--approve`:

```bash
python3 scripts/refresh_production_preflight_evidence.py \
  --out artifacts/evidence/production-preflight-refresh.json
```

Pass criteria for production readiness is still the matrix/audit result, not the
wrapper finishing all steps. If the wrapper returns `status=incomplete`, inspect
`failedSteps` and the refreshed reports it wrote under `artifacts/evidence/`,
including the update plan and dry-run execution report.

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json > artifacts/evidence/cloud-run-service.json

python3 scripts/validate_cloud_run_realtime_config.py \
  --service-json artifacts/evidence/cloud-run-service.json \
  --out artifacts/evidence/cloud-run-realtime-config.json
```

Pass criteria: `status=ok`, `maxInstances=1`, `REALTIME_EVENT_GCS_PREFIX` is
configured, Sunday artifact env vars are configured, OpenAI key material remains
server-side, operator/internal task tokens are present, and no sensitive env var
is set as a direct plaintext value.

If the config verifier fails, generate the approval bundle before changing the
service:

```bash
python3 scripts/prepare_cloud_run_realtime_update_plan.py \
  --config-report artifacts/evidence/cloud-run-realtime-config.json \
  --service sermon-zh-caption-web \
  --project ai-for-god \
  --region us-west1 \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --out artifacts/evidence/cloud-run-realtime-update-plan.json
```

The plan is non-mutating. It records the failed checks, the exact apply command,
the rollback command, and the post-apply validation commands. Execute the apply
command only after an operator explicitly approves the Cloud Run runtime/secret
wiring change.

The update plan may include short Secret Manager references in `--update-secrets`
and therefore sets `secretReferencesIncluded=true`. It must still keep
`apiKeyMaterialIncluded=false` and `secretResourceNamesIncluded=false`; the
redacted execution report removes those short secret references as well.

After approval, use the plan runner so the apply, validation, and optional
rollback are recorded in one redacted execution report:

```bash
python3 scripts/apply_cloud_run_realtime_update_plan.py \
  --plan artifacts/evidence/cloud-run-realtime-update-plan.json \
  --approve \
  --rollback-on-failure \
  --out artifacts/evidence/cloud-run-realtime-update-execution.json
```

For validation tokens, the runner uses the shell environment first; if the token
is not present, it reads the Secret Manager mapping from the approved
`--update-secrets` plan before applying the Cloud Run change. If token access
fails, the runner stops before `gcloud run services update`.

Without `--approve`, the runner is a dry-run and does not mutate Cloud Run.

Then run the deployed API preflight. The first command is read-only and leaves
realtime session creation as a warning:

```bash
python3 scripts/run_cloud_run_realtime_preflight.py \
  --base-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --out artifacts/evidence/cloud-run-api-preflight-readonly.json
```

After the operator/internal token deployment is approved, run the mutation-aware
session check and use this report for the final audit:

```bash
python3 scripts/run_cloud_run_realtime_preflight.py \
  --base-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --create-realtime-session \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --out artifacts/evidence/cloud-run-api-preflight.json
```

Pass criteria: root HTML, `/api/health`, `/api/sundays/current`, and
`/api/admin/status` are readable and sanitized. The final audit report must also
show realtime local session creation with `gpt-realtime-translate`; it records
whether an event token was returned but never writes the token value.

Also verify the public SSE contract without calling OpenAI:

```bash
python3 scripts/run_realtime_public_sse_smoke.py \
  --base-url https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app \
  --sunday YYYY-MM-DD \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --session-validation-out artifacts/evidence/realtime-public-sse-session-validation.json \
  --out artifacts/evidence/realtime-public-sse-smoke.json
```

For local backend runs before Cloud Run, replace the GCS prefix with the local
event log directory:

```bash
python3 scripts/run_realtime_public_sse_smoke.py \
  --base-url http://127.0.0.1:8080 \
  --sunday YYYY-MM-DD \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --event-log-dir /tmp/sermon-realtime-events \
  --session-validation-out artifacts/evidence/realtime-public-sse-session-validation-local.json \
  --out artifacts/evidence/realtime-public-sse-smoke-local.json
```

This synthetic smoke creates a realtime session, posts one English transcript
delta, one Chinese caption delta, and one `gpt-5.5-mini` stable correction, then
reads them back from `/api/realtime/sessions/current/events`. It proves the
backend/public stream contract and, when the GCS prefix is supplied, validates
that the same events were saved to the durable session JSONL. With
`--event-log-dir`, it performs the same archive validation against the local
JSONL file. It still does not replace the real OpenAI realtime smoke.

Before the OpenAI realtime smoke, validate the authorized audio source without
calling OpenAI:

```bash
python3 scripts/run_realtime_audio_source_preflight.py \
  --sunday YYYY-MM-DD \
  --audio-file /path/to/authorized-rehearsal-audio.wav \
  --prepare-audio \
  --out artifacts/evidence/realtime-audio-source-preflight.json
```

Use exactly one of `--audio-file`, `--audio-url`, or `--youtube-url`. Reports
redact URL query strings and record only the source kind/display path, readiness
checks, and sanitized command results.

Validate the browser-side iPad/iPhone mic contract as its own local evidence:

```bash
python3 scripts/validate_web_realtime_contract.py \
  --out artifacts/evidence/web-realtime-contract.json
```

Pass criteria: `status=ok`, the report confirms browser `getUserMedia`, WebRTC
session creation for `gpt-realtime-translate`, OpenAI transcript event
normalization, backend event posting, public SSE subscription, and stable
correction display. The report must not include client secrets, event tokens,
API keys, or Secret Manager resource names.

Before the offline OpenAI/translation chain, validate the YouTube archive route
without downloading captions or calling OpenAI:

```bash
python3 scripts/run_offline_archive_preflight.py \
  --live-url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --sunday YYYY-MM-DD \
  --out artifacts/evidence/offline-archive-preflight.json
```

Pass criteria: `status=ok` and `offlineRoute.strategy=captions_first_then_asr`.
If `offlineRoute.decision=use_caption_track`, proceed with the caption route. If
`decision=use_asr_fallback`, confirm the ASR fallback run uses
`gpt-4o-transcribe` and does not touch realtime.

Before any offline translation or stable-correction run, preflight the text
model through the same OpenAI Responses route used by production:

```bash
python3 scripts/run_openai_model_access_preflight.py \
  --cloud-run-service sermon-zh-caption-web \
  --project ai-for-god \
  --region us-west1 \
  --model gpt-5.5-mini \
  --out artifacts/evidence/openai-model-access-preflight.json
```

Pass criteria: the report has `status=ok` and the
`responses_model:gpt-5.5-mini` check passes. If this fails with a model
404 or access error, do not treat offline Chinese VTT/SRT or stable correction
as production-ready; fix the model name/access first, then rerun translation and
stable-correction validation.

When all three evidence sets are available, run the combined readiness gate:

```bash
python3 scripts/run_sunday_evidence_bundle.py \
  --sunday YYYY-MM-DD \
  --session-id <worker_session_id> \
  --artifact-location gcs \
  --artifact-bucket sermon-zh-artifacts-ai-for-god \
  --artifact-prefix sundays \
  --realtime-location gcs \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --require-readable-sunday-artifacts \
  --realtime-smoke-report artifacts/realtime-openai-smoke/report.json \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --realtime-audio-source-preflight-report artifacts/evidence/realtime-audio-source-preflight.json \
  --web-realtime-contract-report artifacts/evidence/web-realtime-contract.json \
  --realtime-public-sse-smoke-report artifacts/evidence/realtime-public-sse-smoke.json \
  --realtime-openai-smoke-report artifacts/evidence/realtime-openai-smoke/report.json \
  --realtime-session-validation-report artifacts/evidence/realtime-openai-smoke/realtime-session-validation.json \
  --offline-archive-preflight-report artifacts/evidence/offline-archive-preflight.json \
  --offline-chain-validation-report artifacts/evidence/offline-chain-validation.json \
  --offline-asr-smoke-report artifacts/evidence/offline-asr-fallback-smoke/report.json \
  --offline-translation-report artifacts/evidence/offline-caption-route/model-output/openai-translation-report.json \
  --sunday-manifest-validation-report artifacts/evidence/sunday-manifest-validation.json \
  --openai-model-access-preflight-report artifacts/evidence/openai-model-access-preflight.json \
  --openai-alternative-model-access-preflight-report artifacts/evidence/openai-model-access-preflight-gpt-5.5.json \
  --cloud-run-update-plan artifacts/evidence/cloud-run-realtime-update-plan.json \
  --cloud-run-update-execution artifacts/evidence/cloud-run-realtime-update-execution.json \
  --out artifacts/evidence/caption-route-readiness.json \
  --evidence-matrix-out artifacts/evidence/production-evidence-matrix.json \
  --goal-audit-out artifacts/evidence/production-goal-readiness-audit.json \
  --bundle-report-out artifacts/evidence/sunday-evidence-bundle.json
```

Treat `run_sunday_evidence_bundle.py` as the Sunday evidence entrypoint. It
expands the standard local/GCS paths, calls `validate_production_readiness.py`,
can then call `collect_production_evidence_matrix.py` and
`audit_production_goal_readiness.py`, and returns non-zero if any required
evidence is missing or failed. Pass `--realtime-session-id` directly when you
already know the session id; otherwise the runner can read it from the realtime
smoke report. If the smoke report contains `realtimeEventsJsonl`, the runner uses
that exact JSONL URI. If `--evidence-matrix-out` or `--goal-audit-out` is passed
without `--out`, the runner writes a dated production-readiness report under
`artifacts/evidence/`.
Use `--bundle-report-out` to persist the top-level runner summary, including all
expanded commands and step return codes.
Alternative model access reports are only side evidence; a green `gpt-5.5`
preflight does not satisfy the required `gpt-5.5-mini` stable/offline route.
If the production-readiness validator exits before it can write `--out`, the
bundle writes a minimal failed readiness report and still runs the matrix/audit
steps. That keeps the Sunday handoff focused on the final status board instead
of dropping downstream evidence when an early artifact is missing.
Likewise, if matrix generation exits before writing `--evidence-matrix-out`, the
bundle writes a minimal incomplete matrix so the goal audit can still run and
record the handoff failure.

After collecting provider, offline, Cloud Run, and Sunday-manifest evidence,
generate the readable evidence matrix:

```bash
python3 scripts/collect_production_evidence_matrix.py \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --realtime-audio-source-preflight-report artifacts/evidence/realtime-audio-source-preflight.json \
  --web-realtime-contract-report artifacts/evidence/web-realtime-contract.json \
  --realtime-public-sse-smoke-report artifacts/evidence/realtime-public-sse-smoke.json \
  --realtime-openai-smoke-report artifacts/evidence/realtime-openai-smoke/report.json \
  --realtime-session-validation-report artifacts/evidence/realtime-openai-smoke/realtime-session-validation.json \
  --offline-archive-preflight-report artifacts/evidence/offline-archive-preflight.json \
  --offline-chain-validation-report artifacts/evidence/offline-chain-validation.json \
  --offline-asr-smoke-report artifacts/evidence/offline-asr-fallback-smoke/report.json \
  --offline-translation-report artifacts/evidence/offline-caption-route/model-output/openai-translation-report.json \
  --sunday-manifest-validation-report artifacts/evidence/sunday-manifest-validation.json \
  --openai-model-access-preflight-report artifacts/evidence/openai-model-access-preflight.json \
  --openai-alternative-model-access-preflight-report artifacts/evidence/openai-model-access-preflight-gpt-5.5.json \
  --update-plan artifacts/evidence/cloud-run-realtime-update-plan.json \
  --update-execution artifacts/evidence/cloud-run-realtime-update-execution.json \
  --production-readiness-report artifacts/evidence/caption-route-readiness.json \
  --production-readiness-report artifacts/evidence/asr-route-readiness.json \
  --out artifacts/evidence/production-evidence-matrix.json
```

Use the matrix as the Sunday status board: it lists each requirement, the exact
evidence file that proves it, and the next action for every failed or missing
row. A realtime OpenAI smoke report only proves provider behavior; pair it with
`realtime-session-validation.json` so the saved JSONL is checked for session id
continuity, strictly increasing event ids, English input transcript events, and
Chinese caption events. Pair the offline translation report with
`offline-chain-validation.json` so missing Chinese VTT/SRT/playback/manifest
outputs remain visible when model access fails before export.

For the current handoff flow, prefer the refresh wrapper before reading the
matrix. It regenerates the local Sunday manifest evidence under
`artifacts/evidence/manifest-promotion-guard`, writes
`artifacts/evidence/offline-chain-validation.json`, prepares
`artifacts/evidence/gcs-sunday-manifest-publish-plan.json`, and then refreshes
the matrix/unblock/audit artifacts without applying Cloud Run changes or
uploading GCS artifacts:

```bash
python3 scripts/refresh_production_preflight_evidence.py \
  --sunday YYYY-MM-DD \
  --out artifacts/evidence/production-preflight-refresh.json
```

After generating the matrix, run the goal-level audit:

```bash
python3 scripts/audit_production_goal_readiness.py \
  --production-readiness-report artifacts/evidence/caption-route-readiness.json \
  --production-readiness-report artifacts/evidence/asr-route-readiness.json \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --evidence-matrix-report artifacts/evidence/production-evidence-matrix.json
```

The audit is intentionally stricter than a single Sunday bundle: it remains
`incomplete` until realtime live evidence, stable-correction evidence, a
caption-route archive run, a no-caption ASR fallback archive run, and Cloud
Run/GCS manifest plus realtime-safe Cloud Run config/API evidence are all
present. The matrix is the human-readable handoff view and the audit input that
prevents proven row-level evidence, such as the realtime session JSONL
validation, from being dropped during goal-level verification.

Current E2E run prefix:

```text
gs://sermon-zh-artifacts-ai-for-god/runs/2026-06-23/openai-translation-e2e-FsUijL9uB1I
```

Verified objects:

| Object | Content type | Size | Generation |
|---|---:|---:|---:|
| `artifacts/openai-translation-e2e/FsUijL9uB1I/openai-translation-report.json` | `application/json` | `1005` | `1782239054691283` |
| `web/playback-simulation.generated.js` | `text/javascript` | `42750` | `1782239345874920` |

The report had `status=ok`, `translationStatus=ready`, `totalSegments=80`, `translatedSegments=80`, `apiKeyMaterialIncluded=false`, and `secretResourceNamesIncluded=false`. Public browser JS and generated reports must continue to strip Secret Manager resource names.

During verification, `cloud-manifest.json` was not present at this OpenAI translation E2E prefix. Treat that as a follow-up gap for the E2E publishing path; do not assume a manifest exists unless the Sunday run explicitly verifies it.

## Rollback Notes

Revision rollback for the current service:

```bash
gcloud run services update-traffic sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --to-revisions=REVISION_NAME=100
```

Choose `REVISION_NAME` from the current `gcloud run revisions list` output. At the 2026-06-23 13:29 PT snapshot, recent ready candidates included `sermon-zh-caption-web-00011-2nz`, `sermon-zh-caption-web-00010-54f`, `sermon-zh-caption-web-00009-bqz`, and `sermon-zh-caption-web-00008-frx`. After rollback, rerun the post-deploy validation commands and confirm traffic points to the intended revision.

If only the artifact prefix is wrong, prefer updating `SERMON_ARTIFACT_PREFIX` to a last known-good prefix instead of rolling back static assets:

```bash
gcloud run services update sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --update-env-vars=SERMON_ARTIFACT_PREFIX=runs/YYYY-MM-DD/last-known-good
```

This creates a new revision. Record both the old revision and the new revision in the Sunday evidence log.
