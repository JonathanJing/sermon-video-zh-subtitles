# Cloud Run Deployment Prep

Last updated: 2026-06-22

Chinese version: [cloud-run-deployment-prep.zh.md](./cloud-run-deployment-prep.zh.md)

This checklist prepares the POC for Cloud Run while keeping the repository safe to open source. Runtime secrets go to Google Secret Manager. Public browser files, generated artifacts, Git history, logs, and GCS outputs must not contain secret values.

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
- Production public playback JS should not include Secret Manager resource names.
- Server-side manifests may reference Secret Manager resource names, but should not be exposed directly to the congregation page.
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
