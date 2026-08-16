# Sermon Reading-PDF Production Supervisor Agent

## Summary

The post-live reading-PDF workflow now has one OpenAI Agents SDK supervisor:

- Cloud Scheduler still wakes the workflow.
- Existing Python scripts and Cloud Run Jobs remain the deterministic execution layer.
- GCS state, run-status, and QA JSON remain the source of truth.
- `Sermon Production Supervisor` reads evidence, selects the next safe action, and calls bounded tools.
- An operator must still confirm the absolute sermon start and end.

The agent does not implement downloading, clipping, transcription, translation, or PDF rendering. It invokes the existing tested and resumable workflow.

## Architecture

```mermaid
flowchart TD
    A[Cloud Scheduler] --> B[production-supervisor endpoint]
    B --> C[Cloud Run Job: Supervisor Agent]
    C --> D[Read backend state, timeline, approval, run status, and QA]
    D --> E{recommendedAction}
    E -- run_timeline_probe --> F[Deterministic timeline job]
    F --> G[requires_operator_review]
    G --> H[Operator confirms absolute start/end]
    H --> I[Write operator-window-approval.json]
    I --> C
    E -- run_reading_pdf_generation --> J[Deterministic reading-PDF pipeline]
    J --> K{Reading quality and PDF QA pass?}
    K -- No --> L[Blocked for human review]
    K -- Yes --> M[Complete]
```

Cloud Scheduler does not pass one HTTP target's response into another target. The automatic handoff uses durable state instead:

1. the discovery Scheduler job writes the canonical livestream URL to `LIVE_SOURCE_MONITOR_STATE_URI`
2. a separate Supervisor Scheduler job calls the production-supervisor endpoint
3. the endpoint starts the configured Cloud Run Job through the Cloud Run `jobs:run` API
4. the Agent reads the URL and all subsequent evidence from GCS

The maximum handoff delay is the Supervisor Scheduler interval. A five- or ten-minute cadence is sufficient for the post-live workflow.

## Entrypoints

- Agent runner: `scripts/run_sermon_production_supervisor_agent.py`
- Deterministic state/tool contract: `scripts/sermon_production_supervisor.py`
- Timeline tool: `scripts/run_post_live_timeline_job.py`
- Reading-PDF tool: `scripts/run_post_live_subtitle_generation.py`
- API: `POST /api/admin/sundays/<date>/production-supervisor`

The Python dependency is bounded to:

```text
openai-agents>=0.19.1,<0.20
```

## Modes

`shadow` exposes only the read-only `inspect_production_state` tool. Use it to validate decisions without starting jobs.

`execute` additionally exposes:

- `run_timeline_probe`
- `run_approved_reading_pdf_generation`

Both mutation tools validate durable state before execution. The PDF tool reads times only from a valid human approval artifact; it has no model-controlled start/end parameters.

Local shadow example:

```bash
.venv/bin/python scripts/run_sermon_production_supervisor_agent.py \
  --sunday 2026-08-02 \
  --state-file artifacts/live-source-monitor/state.json \
  --work-root artifacts/post-live-runs \
  --gcs-bucket '' \
  --mode shadow
```

## Human window approval

After independently reviewing the completed livestream:

```bash
.venv/bin/python scripts/run_sermon_production_supervisor_agent.py \
  --sunday 2026-08-02 \
  --state-file 'gs://sermon-zh-artifacts-ai-for-god/sundays/live-source-monitor/backend-state.json' \
  --work-root /tmp/sermon-post-live-subtitles \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --api-key-secret 'projects/ai-for-god/secrets/openai-api-key/versions/latest' \
  --approve-window \
  --start-time 00:29:35 \
  --end-time 01:00:55 \
  --approved-by 'Jony' \
  --mode execute
```

The approval binds the Sunday, source URL hash, approved times, approver, and current timeline-report SHA-256. A new source or timeline report invalidates the old approval.

## Scheduler integration

Configure the API trigger in shadow mode first:

```bash
python3 scripts/configure_live_source_scheduler.py \
  --project ai-for-god \
  --location us-west1 \
  --service-url 'https://sermon-zh-caption-web-...' \
  --job-id sermon-production-supervisor-shadow \
  --action production-supervisor \
  --sunday upcoming \
  --schedule '*/10 18-23 * * SAT' \
  --timezone America/Los_Angeles \
  --supervisor-mode shadow \
  --agent-model gpt-5.6
```

When inline work is disabled and the following environment variables are configured, the endpoint dispatches a Cloud Run Job instead of executing the long workflow inside the web request:

```text
SERMON_SUPERVISOR_JOB_PROJECT=ai-for-god
SERMON_SUPERVISOR_JOB_LOCATION=us-west1
SERMON_SUPERVISOR_JOB_NAME=sermon-production-supervisor
SERMON_SUPERVISOR_JOB_TIMEOUT_SECONDS=14400
SERMON_SUPERVISOR_MODE=shadow
```

`SERMON_SUPERVISOR_JOB_CONTAINER` is optional and is needed only when the Job has multiple containers or a specifically named container override. The Cloud Run service identity needs `roles/run.developer` on the target Job to execute it with overrides; the Job service account separately needs access to GCS and Secret Manager. The Job container must be configured with `python` as its command; the API supplies the Agent runner and bounded arguments for each execution.

If Scheduler calls the endpoint without a configured Job and inline execution is disabled, the endpoint returns HTTP 503. This makes the missing dispatch visible and retryable instead of silently acknowledging a no-op.

## Completion rule

The agent may return `complete` only when:

- the generation report is `completed`
- `reading-edition-v2/reading_quality_report.json` is `pass`
- `sermon_zh_en_reading.qa.json` is `pass`
- `sermon_interpretation_zh.qa.json` is `pass`

Partial ASR, a standalone PDF file, or model judgment is not completion.

## Safety boundaries

- The agent has no tool that writes human approval.
- Scheduler/API payloads cannot supply sermon start/end to the agent.
- Shadow mode exposes no mutation tools.
- GCS access errors are recorded as `accessIssues`, not treated as missing files.
- The live-source state reader propagates GCS authentication and network failures.
- Once GCS is configured, only GCS evidence can establish production state; local files are execution cache.
- GCS generation preconditions provide one active timeline or PDF-generation lease per Sunday/source.
- The final Agent status is reconciled against a fresh deterministic snapshot; model output alone cannot establish completion.
- Raw secret material is excluded from reports and sensitive trace data is disabled.
- Existing quality gates, caching, and resumability remain authoritative.
