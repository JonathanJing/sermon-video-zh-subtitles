# Run digest 20261014-clip-e2e-opus280-20261004-q

Generated 2026-10-14T21:28:32+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-q

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-q`


Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| route-probe | pass | 0 |
| plan-layer2 | pass | 1 |
| check-layer2 | pass | 2 |
| check-layer2 | fail(1) | 1 |
| plan-layer2 | pass | 1 |
| check-layer2 | pass | 2 |
| layer2 | pass | 5 |
| layer2 | pass | 1 |

Failed stages: `check-layer2`

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/808f5e0ce3746b33c95a61190d83733b10bee6c4751443c10ffa8e3edfdce2c8/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/808f5e0ce3746b33c95a61190d83733b10bee6c4751443c10ffa8e3edfdce2c8/worker.log`: raise ValueError(reason)
- `l2/layer2-jobs/808f5e0ce3746b33c95a61190d83733b10bee6c4751443c10ffa8e3edfdce2c8/worker.log`: ValueError: layer2_auto_repair_stopped
- `l2/text/es/accounting/operations.log`: ... 802 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 1806 lines omitted; 2 error-like lines, 2 kept below ...
- `l2/text/ko/accounting/operations.log`: [line 1022] 2026-10-14T21:27:14.910532+00:00 ERROR run=6661be128fbd4acb88253727859456d0 stage_finished workflowId=0dab9d1141d84477a436d28fdca07b2a stage=layer2_models spanId=a5cb5c5aa6f246918daba67ed0
- `l2/text/ko/accounting/operations.log`: [line 1024] 2026-10-14T21:27:14.912484+00:00 ERROR run=6661be128fbd4acb88253727859456d0 workflow_finished workflowId=0dab9d1141d84477a436d28fdca07b2a stage=canonical_layer2_worker spanId=7c07f4a1c32a4
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:27:45.429589+00:00 ERROR run=6661be128fbd4acb88253727859456d0 stage_finished workflowId=59e01ef9aaa94696aa1b4cbbd0de4df5 stage=layer2_models spanId=115c8ff6913e4d9eae641bffbefcb6b0 attem
- `l2/text/ko/accounting/operations.log`: 2026-10-14T21:27:45.431778+00:00 ERROR run=6661be128fbd4acb88253727859456d0 workflow_finished workflowId=59e01ef9aaa94696aa1b4cbbd0de4df5 stage=canonical_layer2_worker spanId=7c07f4a1c32a46cb8dd4c81b4
- `l2/text/zh-Hans/accounting/operations.log`: ... 802 lines omitted; 0 error-like lines, 0 kept below ...
- `logs/check-layer2.log`: "failed": [],
- `logs/check-layer2.log`: "status": "fail",
- `logs/check-layer2.log`: "failed": [
- `logs/check-layer2.log`: "status": "fail",
- `logs/check-layer2.log`: "failed": [],
- `logs/plan-layer2.log`: == 2026-10-14T21:26:11+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2.log`: == 2026-10-14T21:27:04+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 9 .csv, 1276 .json, 3 .jsonl, 12 .lock, 2 .py, 2 .txt
