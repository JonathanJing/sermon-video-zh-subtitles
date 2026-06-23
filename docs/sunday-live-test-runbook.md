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

Verified on 2026-06-23 around 11:34 PT:

- The public Cloud Run URL returns `HTTP 200` with `content-type: text/html`.
- Static assets `/app.js` and `/playback-simulation.generated.js` return `HTTP 200`.
- Cloud Run service status is `Ready`.
- Traffic was `100%` to revision `sermon-zh-caption-web-00002-58c` at snapshot time. Re-check the live revision before each deploy or Sunday test.
- Current public env vars are `APP_TIMEZONE=America/Los_Angeles`, `SERMON_ARTIFACT_BUCKET=sermon-zh-artifacts-ai-for-god`, and `SERMON_ARTIFACT_PREFIX=runs/2026-06-23/openai-translation-e2e-FsUijL9uB1I`.
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
| 10:10 | Check first usable caption segments. | Report/playback data has nonzero segments and no secret material flag. |
| 10:45 | Check translation completeness. | `translationStatus=ready` or an explicit fallback decision is recorded. |
| 11:10 | Operator review pass. | Sermon title, source, and first screen captions look correct. |
| 11:20 | Publish/freeze the 11:30 audience artifact set. | The artifact prefix is stable and matches the Cloud Run env or selected manifest. |
| 11:30 | Audience smoke test. | A clean browser session can load captions for the published Sunday set. |
| 11:50 | Post-SLA check. | Caption experience is still usable; failures and fallback timing are logged. |
| After service | Capture evidence. | Record revision, prefix, object generations, and any rollback or fallback action. |

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

## Rollback

Use revision rollback when the deployed static app or env vars are wrong:

```bash
gcloud run services update-traffic sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --to-revisions=sermon-zh-caption-web-00001-mqg=100
```

Then rerun the Cloud Run smoke commands and confirm the expected revision:

```bash
gcloud run services describe sermon-zh-caption-web \
  --project=ai-for-god \
  --region=us-west1 \
  --format=json
```

If the problem is only a bad artifact prefix, prefer repointing `SERMON_ARTIFACT_PREFIX` to the last known-good prefix and recording the newly created revision. Do not delete failed Sunday artifacts during the incident; keep them for review.

## Sunday Evidence Log Template

```text
Date:
Operator:
Cloud Run revision before test:
Cloud Run revision after test:
Artifact prefix:
Live source URL:
First artifact write time PT:
First usable caption time PT:
Ready/publish time PT:
11:30 audience smoke result:
11:50 SLA result:
Rollback used: yes/no
Known issues:
Next fix:
```
