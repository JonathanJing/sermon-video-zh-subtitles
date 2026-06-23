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

Verified on 2026-06-23 around 11:34 PT:

| Field | Value |
|---|---|
| Project | `ai-for-god` |
| Region | `us-west1` |
| Service | `sermon-zh-caption-web` |
| URL | `https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/` |
| Status | `Ready` |
| Verified revision at snapshot time | `sermon-zh-caption-web-00002-58c` |
| Known rollback revision at snapshot time | `sermon-zh-caption-web-00001-mqg` |
| Traffic | `100%` to latest ready revision |
| Public invoker | `allUsers` has `roles/run.invoker` |
| Service account | `760303847302-compute@developer.gserviceaccount.com` |
| Artifact bucket | `sermon-zh-artifacts-ai-for-god` |

The service account is currently the default Compute Engine service account. Before a real production Sunday, prefer moving to a dedicated Cloud Run service account such as `sermon-caption-runner@ai-for-god.iam.gserviceaccount.com` with only the required Secret Manager and GCS permissions.

## Current Service Env Vars

Verified public config on the current revision:

| Env var | Value | Secret? | Notes |
|---|---|---:|---|
| `APP_TIMEZONE` | `America/Los_Angeles` | No | Required for 11:30 PT workflow decisions. |
| `SERMON_ARTIFACT_BUCKET` | `sermon-zh-artifacts-ai-for-god` | No | Matches the verified bucket. |
| `SERMON_ARTIFACT_PREFIX` | `runs/2026-06-23/openai-translation-e2e-FsUijL9uB1I` | No | Current E2E test run prefix. Use a dated Sunday prefix for live tests. |

No provider API keys or operator tokens were visible in the Cloud Run service env var list returned by `gcloud run services describe`.

## Post-Deploy Validation Commands

```bash
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/app.js
curl -I -L --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/playback-simulation.generated.js
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
- Service condition `Ready=True`.
- Traffic points to the intended revision.
- Public browser artifacts do not expose raw API keys, operator tokens, webhook URLs, or Secret Manager resource names.

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
  --to-revisions=sermon-zh-caption-web-00001-mqg=100
```

After rollback, rerun the post-deploy validation commands and confirm traffic points to the intended revision.

If only the artifact prefix is wrong, prefer updating `SERMON_ARTIFACT_PREFIX` to a last known-good prefix instead of rolling back static assets:

```bash
gcloud run services update sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --update-env-vars=SERMON_ARTIFACT_PREFIX=runs/YYYY-MM-DD/last-known-good
```

This creates a new revision. Record both the old revision and the new revision in the Sunday evidence log.
