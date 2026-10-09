# Run digest 20261009-l3-l4-auto-handoff

Generated 2026-10-09T02:42:17+00:00. Redacted copies only; source hashes are in manifest.json.

## run-01

Source: `~/.codex/worktrees/api-luna-concurrency/sermon-video-zh-subtitles/artifacts/l3-l4-auto-handoff-20261009/run-01`

- outcome `outcome.json`: **succeeded** exit 0 (2026-10-09T02:41:34.452830+00:00 → 2026-10-09T02:41:35.661797+00:00)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | elapsedSeconds | exitCode |
|---|---|---|---|
| targeted_unittest | pass | 0.738 | 0 |
| four_layer_evaluator | pass | 0.47 | 0 |

Error-like log lines (first 5 per log):

- `test.log`: {"schemaVersion": "sermon-backend-dry-run-evaluation-v1", "status": "pass", "simulationOnly": true, "successfulRun": {"events": 29, "sourceUnits": 2, "modelCalls": 12, "sharedControlLoops": {"layer2":
