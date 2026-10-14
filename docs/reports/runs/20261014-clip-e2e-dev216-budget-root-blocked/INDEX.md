# Run digest 20261014-clip-e2e-dev216-budget-root-blocked

Generated 2026-10-14T16:40:52+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-dev216-20261014-c

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev216-20261014-c`

- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 11.0 |
| es.text-qc | pass | 0.6 |
| es.calibration.prefetch | pass | 77.6 |
| es.calibration | pass | 4.4 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 20.1 |
| ko.text-qc | pass | 1.5 |
| ko.calibration.prefetch | pass | 94.8 |
| ko.calibration | pass | 4.3 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 15.9 |
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
| text-qc.ko.out | pass | 121 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 94 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 17 |
| plan-layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 0 |

Failed stages: `text-qc.zh-Hans.out`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 220 of 220 requests returned; reserved US$2.22; estimated US$0.30 over 220 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 214 of 214 requests returned; reserved US$2.31; estimated US$0.36 over 214 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 32 of 32 requests returned; reserved US$0.35; estimated US$0.05 over 32 priced; invoice not verified

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/c3b64d0a6e4f5fc5c0e577e8126132c7012d31bed098b222054ff85553e50fe4/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/c3b64d0a6e4f5fc5c0e577e8126132c7012d31bed098b222054ff85553e50fe4/worker.log`: raise self._exception
- `l2/layer2-jobs/c3b64d0a6e4f5fc5c0e577e8126132c7012d31bed098b222054ff85553e50fe4/worker.log`: if not condition: raise ContractError(code)
- `l2/layer2-jobs/c3b64d0a6e4f5fc5c0e577e8126132c7012d31bed098b222054ff85553e50fe4/worker.log`: scripts.sermon_review_contracts.ContractError: budget_authority_changed
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:39:23.909339+00:00 ERROR run=92e2383df5d54a79a10ba648b2cd8601 stage_finished workflowId=160e1f9106a945e6ad83b945dbe907d5 stage=layer2.translator.zh-Hans.group-0001 spanId=5ec4cb506f42449
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:39:23.910436+00:00 ERROR run=92e2383df5d54a79a10ba648b2cd8601 stage_finished workflowId=160e1f9106a945e6ad83b945dbe907d5 stage=layer2.group.zh-Hans.0001 spanId=d98af719be2d4cda91e1818320
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:39:23.911991+00:00 ERROR run=92e2383df5d54a79a10ba648b2cd8601 stage_finished workflowId=160e1f9106a945e6ad83b945dbe907d5 stage=layer2_models spanId=af70d519410f4f8e9ae4a9ee26fc61e9 attem
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:39:23.913887+00:00 ERROR run=92e2383df5d54a79a10ba648b2cd8601 workflow_finished workflowId=160e1f9106a945e6ad83b945dbe907d5 stage=canonical_layer2_worker spanId=acdbf4c251474723872349f6f
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T16:39:23.915262+00:00 ERROR run=92e2383df5d54a79a10ba648b2cd8601 stage_finished workflowId=8e4d9cd4f6c2498ea607761aa19a9867 stage=canonical_layer2_worker spanId=acdbf4c251474723872349f6f716
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/text-qc.zh-Hans.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 12 .csv, 1146 .json, 4 .jsonl, 513 .lock
