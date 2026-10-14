# Run digest 20261014-clip-e2e-dev101-gate4-blocked

Generated 2026-10-14T16:06:42+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-dev101-20261014-a

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev101-20261014-a`

- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 13.1 |
| es.text-qc | pass | 0.6 |
| es.calibration.prefetch | pass | 78.0 |
| es.calibration | pass | 4.7 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 19.3 |
| ko.text-qc | pass | 0.6 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 19.7 |
| zh-Hans.text-qc | pass | 0.6 |

Timings `timings.tsv`:

| inputs | pass | 8 |
|---|---|---|
| timeline-map | pass | 0 |
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 1 |
| layer2 | pass | 1 |
| plan-qc-ko | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | fail(1) | 20 |
| plan-layer2-ko-r1 | pass | 0 |
| layer2-ko-r1 | pass | 1 |
| layer2-ko-r1 | pass | 0 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 97 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 21 |
| plan-layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 0 |

Failed stages: `text-qc.ko.out`, `text-qc.zh-Hans.out`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 221 of 221 requests returned; reserved US$2.25; estimated US$0.31 over 221 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 32 of 32 requests returned; reserved US$0.35; estimated US$0.05 over 32 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 32 of 32 requests returned; reserved US$0.35; estimated US$0.05 over 32 priced; invoice not verified

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/c8eb29a063b96345720c9b6d45ed9dd49488ec3461715c115ff9a5fc07da2d78/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/c8eb29a063b96345720c9b6d45ed9dd49488ec3461715c115ff9a5fc07da2d78/worker.log`: raise ValueError("Layer 2 rule preflight: " + reason)
- `l2/layer2-jobs/c8eb29a063b96345720c9b6d45ed9dd49488ec3461715c115ff9a5fc07da2d78/worker.log`: ValueError: Layer 2 rule preflight: prior model payload does not match cached response
- `l2/layer2-jobs/db8afe5eb3709463396918f8118cebc4dc170e810ec2125390cfc81ed4eaab1b/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/db8afe5eb3709463396918f8118cebc4dc170e810ec2125390cfc81ed4eaab1b/worker.log`: raise ValueError("Layer 2 rule preflight: " + reason)
- `l2/layer2-jobs/db8afe5eb3709463396918f8118cebc4dc170e810ec2125390cfc81ed4eaab1b/worker.log`: ValueError: Layer 2 rule preflight: prior model payload does not match cached response
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T16:02:14.430510+00:00 ERROR run=f1f093635831483bb9fe790efc781e4b stage_finished workflowId=0de3c4e1f7de4e2ba1d2baba6ae79613 stage=layer2.run_admission.ko spanId=6d21675b89b743978d43b405ea08
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T16:02:14.431127+00:00 ERROR run=f1f093635831483bb9fe790efc781e4b stage_finished workflowId=0de3c4e1f7de4e2ba1d2baba6ae79613 stage=layer2_models spanId=9e3b5cc0e4894efda93d7d153d903f0b attem
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T16:02:14.431664+00:00 ERROR run=f1f093635831483bb9fe790efc781e4b workflow_finished workflowId=0de3c4e1f7de4e2ba1d2baba6ae79613 stage=canonical_layer2_worker spanId=f8180ae0563f423d9322a887e
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T16:02:14.432456+00:00 ERROR run=f1f093635831483bb9fe790efc781e4b stage_finished workflowId=cec58b3e8bfe4643b3d2232e9b6b84f4 stage=canonical_layer2_worker spanId=f8180ae0563f423d9322a887e2bc
- `l2-ko-r1/text/ko/accounting/operations.log`: 2026-10-14T16:02:14.433866+00:00 ERROR run=f1f093635831483bb9fe790efc781e4b workflow_finished workflowId=cec58b3e8bfe4643b3d2232e9b6b84f4 status=failed
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:04:19.234864+00:00 ERROR run=282af50496d94c49ab1912b3a9493d97 stage_finished workflowId=62de0ca11eff4ddd9e9b446761b41424 stage=layer2.run_admission.zh-Hans spanId=fd3c45afec034142a47de5b
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:04:19.235406+00:00 ERROR run=282af50496d94c49ab1912b3a9493d97 stage_finished workflowId=62de0ca11eff4ddd9e9b446761b41424 stage=layer2_models spanId=f5a04f85471e463aa4f609350169f696 attem
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:04:19.235973+00:00 ERROR run=282af50496d94c49ab1912b3a9493d97 workflow_finished workflowId=62de0ca11eff4ddd9e9b446761b41424 stage=canonical_layer2_worker spanId=e6da70dbfa664762b57b60798
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:04:19.236776+00:00 ERROR run=282af50496d94c49ab1912b3a9493d97 stage_finished workflowId=62ad35cb8af649858b77c777b41c5334 stage=canonical_layer2_worker spanId=e6da70dbfa664762b57b607980a5
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:04:19.238349+00:00 ERROR run=282af50496d94c49ab1912b3a9493d97 workflow_finished workflowId=62ad35cb8af649858b77c777b41c5334 status=failed
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/text-qc.ko.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.zh-Hans.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 15 .csv, 874 .json, 5 .jsonl, 335 .lock
