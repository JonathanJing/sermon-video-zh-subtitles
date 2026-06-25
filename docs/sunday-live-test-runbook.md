# Sunday Live Test Runbook

Chinese version: [sunday-live-test-runbook.zh.md](./sunday-live-test-runbook.zh.md)

Last updated: 2026-06-23

This runbook is for deployment validation and Sunday live testing of the Cloud Run PWA and GCS artifact path. It intentionally does not change UI styling or translation worker behavior.

## Production Handles

| Item | Value |
|---|---|
| Cloud Run project | `ai-for-god` |
| Cloud Run region | `us-west1` |
| Cloud Run service | `sermon-zh-caption-web` |
| Public URL | `https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/` |
| Artifact bucket | `gs://sermon-zh-artifacts-ai-for-god` |
| Time zone | `America/Los_Angeles` |

## Current Verified State

Verified on 2026-06-23 around 13:29 PT:

- The public Cloud Run URL returns `HTTP 200` with `content-type: text/html`.
- Static assets `/app.js` and `/playback-simulation.generated.js` return `HTTP 200`.
- Cloud Run service status is `Ready`.
- Traffic was `100%` to revision `sermon-zh-caption-web-00012-bqj` at snapshot time. Re-check the live revision before each deploy or Sunday test.
- Current env vars are `APP_TIMEZONE=America/Los_Angeles`, `SERMON_ARTIFACT_BUCKET=sermon-zh-artifacts-ai-for-god`, `SERMON_ARTIFACT_PREFIX=sundays`, and server-side `OPENAI_API_KEY_SECRET=projects/PROJECT_NUMBER/secrets/openai-api-key/versions/latest`.
- The service is publicly invokable with `roles/run.invoker` granted to `allUsers`.
- The GCS bucket exists in `US-WEST1`, has uniform bucket-level access, and has public access prevention enforced.
- The configured GCS prefix contains translated report, model JSONL, and playback JS outputs.
- No `cloud-manifest.json` was present at the configured OpenAI translation E2E prefix during verification. Treat the report and playback JS as the confirmed artifacts for this run until manifest publication is added for this path.
- The deployed public HTML and playback JS did not match the checked secret patterns.

## Pre-Sunday Setup

Complete these before Sunday morning:

- Confirm the intended live source. The conservative production default is the earliest verified same-sermon service that gives enough review time before 11:30 PT, with 10:00 PT as the safer baseline.
- Pick the Sunday artifact prefix, for example `runs/2026-06-28/live-test-1000-service`.
- Confirm the current rollback revision before any deploy or env update:

```bash
gcloud run revisions list \
  --service=sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1
```

- Confirm the service env vars point to the Sunday prefix:

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

- If `SERMON_ARTIFACT_PREFIX` must change, update it before the live window and record the new revision:

```bash
gcloud run services update sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --update-env-vars=SERMON_ARTIFACT_PREFIX=runs/YYYY-MM-DD/live-test-1000-service
```

## Sunday Live Test Timeline

All times are Pacific Time.

| Time | Action | Pass condition |
|---|---|---|
| T-60 min | Open the Cloud Run URL from a normal browser session. | Page loads without auth or browser console blockers. |
| T-45 min | Verify Cloud Run readiness and static assets. | Root, `/app.js`, and `/playback-simulation.generated.js` return `HTTP 200`. |
| T-40 min | Verify bucket and target prefix. | Bucket is reachable; target prefix exists or is intentionally empty before generation. |
| T-30 min | Confirm rollback revision and log URL. | Previous known-good revision is recorded. |
| 9:55 or 10:00 | Start the live-source or E2E generation workflow for the chosen source. | Artifacts start writing to the planned GCS prefix. |
| 10:01 | Check Cloud Logging for `live_capture_triggered`. | The event has the right `sunday`, `triggerSource`, and live-source hash. |
| 10:10 | Check first usable caption segments. | Report/playback data has nonzero segments and no secret material flag. |
| 10:45 | Check translation completeness. | `translationStatus=ready` or an explicit fallback decision is recorded. |
| 10:50 | Check Cloud Logging for `captions_ready`. | The event exists for the target `sunday` and points to the stable Sunday manifest. |
| 11:10 | Operator review pass. | Sermon title, source, and first screen captions look correct. |
| 11:20 | Publish/freeze the 11:30 audience artifact set. | The artifact prefix is stable and matches the Cloud Run env or selected manifest. |
| 11:30 | Audience smoke test. | A clean browser session can load captions for the published Sunday set and emits `congregation_page_view`. |
| 11:50 | Post-SLA check. | Caption experience is still usable; failures and fallback timing are logged. |
| After service | Capture evidence. | Record revision, prefix, object generations, trigger/ready log timestamps, unique-device estimate, and any rollback or fallback action. |

## Cloud Run Smoke Commands

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
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/health
curl -sS --max-time 20 https://sermon-zh-caption-web-wu7uk5rgdq-uw.a.run.app/api/sundays/current
```

## Logging Verification

Use [observability.md](./observability.md) for the full event schema.

Required Sunday log evidence:

- `live_capture_triggered` for the target `sunday`.
- `worker_stage_completed` for prepare, translate, upload, and promote stages.
- `captions_ready` before the 11:30 audience window.
- `congregation_page_view` after the public page is opened from a clean browser session.

Cloud Logging examples:

```text
resource.type="cloud_run_revision"
jsonPayload.event="live_capture_triggered"
jsonPayload.sunday="YYYY-MM-DD"
```

```text
resource.type=("cloud_run_revision" OR "cloud_run_job")
jsonPayload.event="captions_ready"
jsonPayload.sunday="YYYY-MM-DD"
```

```text
resource.type="cloud_run_revision"
jsonPayload.event="congregation_page_view"
jsonPayload.viewMode="congregation"
jsonPayload.sunday="YYYY-MM-DD"
```

## GCS Artifact Verification

List the Sunday prefix:

```bash
gcloud storage ls --recursive gs://sermon-zh-artifacts-ai-for-god/runs/YYYY-MM-DD/live-test-1000-service
```

Inspect the key objects:

```bash
gcloud storage objects describe \
  gs://sermon-zh-artifacts-ai-for-god/runs/YYYY-MM-DD/live-test-1000-service/web/playback-simulation.generated.js \
  --format=json
```

```bash
gcloud storage cat \
  gs://sermon-zh-artifacts-ai-for-god/runs/YYYY-MM-DD/live-test-1000-service/artifacts/openai-translation-e2e/LIVE_ID/openai-translation-report.json
```

Required checks:

- `apiKeyMaterialIncluded` is `false`.
- Public playback JS does not contain raw API keys, operator tokens, webhook URLs, or Secret Manager resource names.
- `translationStatus` is `ready` for a green test, or the fallback state is explicitly recorded.
- `translatedSegments` equals `totalSegments` for a complete OpenAI translation E2E run.
- Object generation numbers are recorded for the final playback JS and report.

Run the realtime draft smoke first for the live path:

```bash
python3 scripts/realtime_openai_smoke_test.py \
  --audio-file authorized-smoke.wav \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --sunday YYYY-MM-DD \
  --admin-token "$ADMIN_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --out artifacts/realtime-openai-smoke/report.json
```

Then run the stabilized realtime smoke. This creates the backend session itself,
keeps the event token in memory only, posts one `gpt-5.5-mini` stable correction,
and validates the saved realtime JSONL with `--require-stable-correction`:

```bash
python3 scripts/realtime_stabilized_smoke_test.py \
  --audio-file authorized-smoke.wav \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --sunday YYYY-MM-DD \
  --admin-token "$ADMIN_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --read-events-from-gcs \
  --out artifacts/realtime-stabilized-smoke/report.json
```

Required checks for the stabilized report:

- `status` is `ok`.
- `models.realtimeDraft` is `gpt-realtime-translate`.
- `models.stableCorrection` is `gpt-5.5-mini`.
- `stableCorrection.postedStableCorrections` is greater than `0`.
- `validation.status` is `ok`.
- `eventTokenIncluded`, `apiKeyMaterialIncluded`, and `secretResourceNamesIncluded` are all `false`.

For the 11:30 live run, use the live-session wrapper instead of separate worker
and stabilizer commands. It creates the backend session, keeps the event token in
memory, streams the authorized source through `gpt-realtime-translate`, and runs
`gpt-5.5-mini` stable corrections against the saved realtime JSONL:

```bash
python3 scripts/run_realtime_live_session.py \
  --audio-url 'https://AUTHORIZED_AUDIO_SOURCE/live.m3u8?token=...' \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --sunday YYYY-MM-DD \
  --admin-token "$ADMIN_TOKEN" \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --read-events-from-gcs \
  --require-stable-correction \
  --out artifacts/realtime-live-session/report.json
```

If the authorized source is YouTube live, replace `--audio-url ...` with
`--youtube-url 'https://www.youtube.com/watch?v=...'` after confirming access
and platform rules. For iPad/iPhone mic, use the admin browser WebRTC path; the
backend event contract and stabilizer output are the same. After the browser
creates a realtime session, run the stabilizer loop with admin/internal auth so
the event token stays inside the browser session:

```bash
python3 scripts/run_realtime_stabilizer_loop.py \
  --input-jsonl gs://sermon-zh-artifacts-ai-for-god/realtime-events/YYYY-MM-DD/<browser_session_id>.jsonl \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest \
  --backend-url https://CLOUD_RUN_URL \
  --session-id <browser_session_id> \
  --internal-task-token "$INTERNAL_TASK_TOKEN" \
  --interval-seconds 6 \
  --min-age-seconds 4
```

The loop writes `<browser_session_id>.model-access-preflight.json` first. If
`gpt-5.5-mini` is unavailable through OpenAI Responses, it exits before reading
the event log or posting corrections; the low-latency `gpt-realtime-translate`
draft session should keep running.

Build the combined evidence command first:

```bash
python3 scripts/run_sunday_evidence_bundle.py \
  --sunday YYYY-MM-DD \
  --session-id <worker_session_id> \
  --artifact-location gcs \
  --artifact-bucket sermon-zh-artifacts-ai-for-god \
  --artifact-prefix sundays \
  --realtime-location gcs \
  --realtime-event-gcs-prefix gs://sermon-zh-artifacts-ai-for-god/realtime-events \
  --realtime-smoke-report artifacts/realtime-live-session/report.json \
  --require-readable-sunday-artifacts \
  --cloud-run-config-report artifacts/evidence/cloud-run-realtime-config.json \
  --cloud-run-api-preflight-report artifacts/evidence/cloud-run-api-preflight.json \
  --web-realtime-contract-report artifacts/evidence/web-realtime-contract.json \
  --realtime-public-sse-smoke-report artifacts/evidence/realtime-public-sse-smoke.json \
  --realtime-session-validation-report artifacts/evidence/realtime-live-session/realtime-session-validation.json \
  --offline-chain-validation-report artifacts/evidence/offline-chain-validation.json \
  --offline-asr-smoke-report artifacts/evidence/offline-asr-fallback-smoke/report.json \
  --sunday-manifest-validation-report artifacts/evidence/sunday-manifest-validation.json \
  --openai-model-access-preflight-report artifacts/evidence/openai-model-access-preflight.json \
  --openai-alternative-model-access-preflight-report artifacts/evidence/openai-model-access-preflight-gpt-5.5.json \
  --out artifacts/evidence/caption-route-readiness.json \
  --evidence-matrix-out artifacts/evidence/production-evidence-matrix.json \
  --goal-audit-out artifacts/evidence/production-goal-readiness-audit.json \
  --bundle-report-out artifacts/evidence/sunday-evidence-bundle.json \
  --dry-run
```

Then rerun without `--dry-run`. The command calls the production readiness gate,
then writes the production evidence matrix and goal audit. It fails if offline
artifacts, the promoted Sunday manifest, realtime JSONL evidence, Cloud Run
config, or API preflight evidence are missing or invalid. If you already know
the realtime session id, you can pass `--realtime-session-id` instead of
`--realtime-smoke-report`. When the smoke report contains `realtimeEventsJsonl`,
that exact JSONL URI is used. Use the live-session report for the 11:30
production gate; use the stabilized smoke report for rehearsal evidence. In
both cases, the realtime JSONL must already include at least one
`gpt-5.5-mini` stable correction event. If the production-readiness validator
exits before writing its report, the bundle writes a minimal failed report and
continues with matrix/audit generation so the operator still gets one status
board. If matrix generation exits before writing its report, the bundle writes a
minimal incomplete matrix and still runs the goal audit.
Alternative model access reports are recorded only as side evidence; do not treat
`gpt-5.5` availability as a substitute for required `gpt-5.5-mini` access.

## Rollback

Use revision rollback when the deployed static app or env vars are wrong:

```bash
gcloud run services update-traffic sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --to-revisions=REVISION_NAME=100
```

Then rerun the Cloud Run smoke commands and confirm the expected revision:

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

If the problem is only a bad artifact prefix, prefer repointing `SERMON_ARTIFACT_PREFIX` to the last known-good prefix and recording the newly created revision. Do not delete failed Sunday artifacts during the incident; keep them for review.

Choose `REVISION_NAME` from the current `gcloud run revisions list` output. At the 2026-06-23 13:29 PT snapshot, recent ready candidates included `sermon-zh-caption-web-00011-2nz`, `sermon-zh-caption-web-00010-54f`, `sermon-zh-caption-web-00009-bqz`, and `sermon-zh-caption-web-00008-frx`.

## Sunday Evidence Log Template

```text
Date:
Operator:
Cloud Run revision before test:
Cloud Run revision after test:
Artifact prefix:
Live source URL:
Generation trigger source:
live_capture_triggered log time PT:
First artifact write time PT:
First usable caption time PT:
Ready/publish time PT:
captions_ready log time PT:
11:30 audience smoke result:
Unique device estimate:
11:50 SLA result:
Rollback used: yes/no
Known issues:
Next fix:
```
