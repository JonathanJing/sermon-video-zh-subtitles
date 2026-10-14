# Run digest 20261009-api-luna-concurrency

Generated 2026-10-09T01:15:43+00:00. Redacted copies only; source hashes are in manifest.json.

## run

Source: `~/.codex/worktrees/api-luna-concurrency/sermon-video-zh-subtitles/artifacts/api-luna-concurrency-20261008/run`

- outcome `outcome.json`: **failed** exit 1 (2026-10-09T01:09:46.363359+00:00 → 2026-10-09T01:09:46.408346+00:00), error SessionError: spark_exclusive_session_required

## run-02

Source: `~/.codex/worktrees/api-luna-concurrency/sermon-video-zh-subtitles/artifacts/api-luna-concurrency-20261008/run-02`

- outcome `outcome.json`: **failed** exit 1 (2026-10-09T01:09:53.185090+00:00 → 2026-10-09T01:11:05.377592+00:00), error ValueError: Language plugin rejected a group

Error-like log lines (first 5 per log):

- `accounting/operations.log`: ... 12 lines omitted; 0 error-like lines, 0 kept below ...
- `accounting/operations.log`: 2026-10-09T01:11:05.357961+00:00 ERROR run=2e08b335136a4dbead1a9263f25e452f stage_finished workflowId=589363cd3b454cc4b2f6f6e9ec34568d stage=codex_layer2_diagnostic_test spanId=0f01ce9952bc4805ba6a080
- `accounting/operations.log`: 2026-10-09T01:11:05.359867+00:00 ERROR run=2e08b335136a4dbead1a9263f25e452f workflow_finished workflowId=589363cd3b454cc4b2f6f6e9ec34568d status=failed
- `accounting/operations.log`: 2026-10-09T01:11:05.360060+00:00 ERROR run=2e08b335136a4dbead1a9263f25e452f run_finished workflowId=589363cd3b454cc4b2f6f6e9ec34568d status=failed

Not copied: 3 .csv, 137 .json, 1 .jsonl, 1 .lock

## local-scheduler-tests

Source: `~/.codex/worktrees/api-luna-concurrency/sermon-video-zh-subtitles/artifacts/api-luna-concurrency-20261008/local-scheduler-tests`

- summary `summary.json`: **passed**
