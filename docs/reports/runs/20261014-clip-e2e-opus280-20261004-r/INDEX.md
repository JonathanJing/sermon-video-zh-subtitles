# Run digest 20261014-clip-e2e-opus280-20261004-r

Generated 2026-10-14T21:40:25+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-r

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-r`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **waiver_refused** (Calibration does not allow a waiver: calibration has no trials for ['text.swapped_quantity'])
- summary `textqc-ko/out/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 41.5 |
| es.text-qc | pass | 3.6 |

Timings `textqc-es/out-r1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 16.0 |
| es.text-qc | pass | 2.9 |
| es.calibration.prefetch | pass | 210.6 |
| es.calibration | pass | 19.3 |
| es.text-waiver | fail | 0.0 |

Failed stages: `es.text-waiver`

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 49.2 |
| ko.text-qc | pass | 3.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 54.5 |
| zh-Hans.text-qc | pass | 4.0 |

Timings `timings.tsv`:

| timeline-map | pass | 2 |
|---|---|---|
| route-probe | pass | 0 |
| plan-layer2 | pass | 2 |
| layer2 | pass | 3 |
| plan-qc-ko | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | fail(1) | 53 |
| plan-layer2-ko-r1 | pass | 0 |
| layer2-ko-r1 | pass | 1 |
| layer2-ko-r1 | pass | 0 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | fail(1) | 46 |
| plan-layer2-es-r1 | pass | 0 |
| layer2-es-r1 | pass | 1 |
| layer2-es-r1 | pass | 0 |
| check-qc-es-out-r1 | pass | 0 |
| text-qc.es.out-r1 | fail(1) | 249 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 59 |
| plan-layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 0 |
| layer2-ko-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 0 |

Failed stages: `text-qc.ko.out`, `text-qc.es.out`, `text-qc.es.out-r1`, `text-qc.zh-Hans.out`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 537 of 537 requests returned; reserved US$5.49; estimated US$0.80 over 537 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.08; estimated US$0.15 over 99 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.08; estimated US$0.15 over 99 priced; invoice not verified

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/2ca643dfdb1e973ea1efdb4d477ad49bdbba3f93e14a5881dd560f862e000acf/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/2ca643dfdb1e973ea1efdb4d477ad49bdbba3f93e14a5881dd560f862e000acf/worker.log`: raise ValueError(reason)
- `l2/layer2-jobs/2ca643dfdb1e973ea1efdb4d477ad49bdbba3f93e14a5881dd560f862e000acf/worker.log`: ValueError: layer2_auto_repair_stopped
- `l2/layer2-jobs/6b97c47adf8bf675ace24fb5b3a6085f15f624c5f413e673fbf266f62d2dc773/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/6b97c47adf8bf675ace24fb5b3a6085f15f624c5f413e673fbf266f62d2dc773/worker.log`: raise ValueError(reason)
- `l2/layer2-jobs/6b97c47adf8bf675ace24fb5b3a6085f15f624c5f413e673fbf266f62d2dc773/worker.log`: ValueError: layer2_auto_repair_stopped
- `l2-es-r1/text/es/accounting/operations.log`: ... 230 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-ko-r1/text/ko/accounting/operations.log`: ... 206 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:32:05.090368+00:00 ERROR run=9629d5dd25654d3788078956a08b8bed stage_finished workflowId=1a35547e59bf4c86ad2150fddbf0db3c stage=canonical_layer2_worker spanId=e569d95e8c824afa887eb193b2ea
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:32:05.093025+00:00 ERROR run=9629d5dd25654d3788078956a08b8bed workflow_finished workflowId=1a35547e59bf4c86ad2150fddbf0db3c status=failed
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T21:32:05.093887+00:00 ERROR run=9629d5dd25654d3788078956a08b8bed run_finished workflowId=1a35547e59bf4c86ad2150fddbf0db3c status=failed
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: ... 220 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:39:17.406733+00:00 ERROR run=7a51c957d9c64d8cbc7bdf0bd6aeca74 stage_finished workflowId=4db2a316c8d44b82bd93240dbfd5636b stage=canonical_layer2_worker spanId=8189910ea0d34bf191539334a9b6
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:39:17.407988+00:00 ERROR run=7a51c957d9c64d8cbc7bdf0bd6aeca74 workflow_finished workflowId=4db2a316c8d44b82bd93240dbfd5636b status=failed
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T21:39:17.408137+00:00 ERROR run=7a51c957d9c64d8cbc7bdf0bd6aeca74 run_finished workflowId=4db2a316c8d44b82bd93240dbfd5636b status=failed
- `logs/check-qc-es-out-r1.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-layer2-es-r1.log`: == 2026-10-14T21:33:18+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-ko-r1.log`: == 2026-10-14T21:31:46+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-zh-Hans-r1.log`: == 2026-10-14T21:38:49+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2.log`: == 2026-10-14T21:30:29+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-es.log`: == 2026-10-14T21:32:32+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-ko.log`: == 2026-10-14T21:30:52+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-zh-Hans.log`: == 2026-10-14T21:37:49+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/text-qc.es.out-r1.log`: es.text-waiver	fail	0.0
- `logs/text-qc.es.out-r1.log`: "status": "waiver_refused",
- `logs/text-qc.es.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.ko.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.zh-Hans.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 9 .csv, 3044 .json, 3 .jsonl, 760 .lock, 2 .py, 10 .txt
