# Run digest 20261014-clip-e2e-opus280-20261004-t

Generated 2026-10-14T22:14:14+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-t

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-t`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-ko/out-r1/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 40.1 |
| es.text-qc | pass | 2.8 |

Timings `textqc-es/out-r1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 39.4 |
| es.text-qc | pass | 2.6 |

Timings `textqc-es/out-r2/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 15.0 |
| es.text-qc | pass | 3.2 |
| es.calibration.prefetch | pass | 202.1 |
| es.calibration | pass | 16.4 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 46.6 |
| ko.text-qc | pass | 2.8 |

Timings `textqc-ko/out-r1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 40.0 |
| ko.text-qc | pass | 2.6 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 40.9 |
| zh-Hans.text-qc | pass | 2.6 |

Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| route-probe | pass | 0 |
| plan-qc-ko | pass | 0 |
| plan-layer2-ko-r1 | pass | 0 |
| layer2-ko-r1 | pass | 1 |
| layer2-ko-r1 | pass | 0 |
| check-qc-ko-out-r1 | pass | 0 |
| text-qc.ko.out-r1 | fail(1) | 43 |
| plan-layer2-ko-r2 | pass | 0 |
| layer2-ko-r2 | pass | 1 |
| layer2-ko-r2 | pass | 0 |
| plan-qc-es | pass | 0 |
| plan-layer2-es-r1 | pass | 0 |
| layer2-es-r1 | pass | 1 |
| layer2-es-r1 | pass | 0 |
| check-qc-es-out-r1 | pass | 0 |
| text-qc.es.out-r1 | fail(1) | 43 |
| plan-layer2-es-r2 | pass | 0 |
| layer2-es-r2 | pass | 1 |
| layer2-es-r2 | pass | 0 |
| check-qc-es-out-r2 | pass | 0 |
| text-qc.es.out-r2 | pass | 237 |
| plan-qc-zh-Hans | pass | 0 |
| plan-layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 0 |
| spark-begin-1 | pass | 4 |
| voice-auth.es | fail(1) | 0 |
| spark-finish | pass | 8 |

Failed stages: `text-qc.ko.out-r1`, `text-qc.es.out-r1`, `voice-auth.es`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 534 of 534 requests returned; reserved US$5.46; estimated US$0.79 over 534 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.08; estimated US$0.15 over 99 priced; invoice not verified

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/0359d98fef008970ab42ad77cf4afa191f482188ff83c13c940ba0eb4efad3bc/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/0359d98fef008970ab42ad77cf4afa191f482188ff83c13c940ba0eb4efad3bc/worker.log`: raise ValueError(reason)
- `l2/layer2-jobs/0359d98fef008970ab42ad77cf4afa191f482188ff83c13c940ba0eb4efad3bc/worker.log`: ValueError: layer2_auto_repair_stopped
- `l2/layer2-jobs/4c117cbaa5ab1fb6b3fefb406516f1f7122263e87605843ca331ecf1a70ef667/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/4c117cbaa5ab1fb6b3fefb406516f1f7122263e87605843ca331ecf1a70ef667/worker.log`: raise ValueError(reason)
- `l2/layer2-jobs/4c117cbaa5ab1fb6b3fefb406516f1f7122263e87605843ca331ecf1a70ef667/worker.log`: ValueError: layer2_auto_repair_stopped
- `l2-es-r1/text/es/accounting/operations.log`: ... 216 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-es-r2/text/es/accounting/operations.log`: ... 216 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-ko-r1/text/ko/accounting/operations.log`: ... 258 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-ko-r2/text/ko/accounting/operations.log`: ... 220 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-ko-r2/text/ko/accounting/operations.log`: 2026-10-14T22:07:30.620886+00:00 ERROR run=c048ac250dda4270996eb092e38cd3e9 stage_finished workflowId=601dc189fe824e85a6914cd79ea72ca3 stage=canonical_layer2_worker spanId=d3517637edda48ad90337e031b1b
- `l2-ko-r2/text/ko/accounting/operations.log`: 2026-10-14T22:07:30.622395+00:00 ERROR run=c048ac250dda4270996eb092e38cd3e9 workflow_finished workflowId=601dc189fe824e85a6914cd79ea72ca3 status=failed
- `l2-ko-r2/text/ko/accounting/operations.log`: 2026-10-14T22:07:30.622605+00:00 ERROR run=c048ac250dda4270996eb092e38cd3e9 run_finished workflowId=601dc189fe824e85a6914cd79ea72ca3 status=failed
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: ... 248 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T22:13:22.762893+00:00 ERROR run=6c29d70f26e348059bbe5c154cb7ef8d stage_finished workflowId=5cc3c98677544fc08d6575c0fd71a446 stage=canonical_layer2_worker spanId=71c36c6f021d499dad5d0da31aeb
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T22:13:22.764275+00:00 ERROR run=6c29d70f26e348059bbe5c154cb7ef8d workflow_finished workflowId=5cc3c98677544fc08d6575c0fd71a446 status=failed
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T22:13:22.764441+00:00 ERROR run=6c29d70f26e348059bbe5c154cb7ef8d run_finished workflowId=5cc3c98677544fc08d6575c0fd71a446 status=failed
- `logs/check-qc-es-out-r1.log`: "failed": [],
- `logs/check-qc-es-out-r2.log`: "failed": [],
- `logs/check-qc-ko-out-r1.log`: "failed": [],
- `logs/plan-layer2-es-r1.log`: == 2026-10-14T22:07:33+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-es-r2.log`: == 2026-10-14T22:08:32+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-ko-r1.log`: == 2026-10-14T22:05:52+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-ko-r2.log`: == 2026-10-14T22:07:07+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-zh-Hans-r1.log`: == 2026-10-14T22:12:52+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-es.log`: == 2026-10-14T22:07:33+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-ko.log`: == 2026-10-14T22:05:52+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-zh-Hans.log`: == 2026-10-14T22:12:51+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/text-qc.es.out-r1.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.ko.out-r1.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/voice-auth.es.log`: Traceback (most recent call last):
- `logs/voice-auth.es.log`: raise ValueError(message)
- `logs/voice-auth.es.log`: ValueError: User attestation does not authorize this Dev clip voice

Not copied: 15 .csv, 3677 .json, 5 .jsonl, 669 .lock, 2 .py, 24 .txt
