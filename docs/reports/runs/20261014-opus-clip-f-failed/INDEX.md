# Run digest 20261014-opus-clip-f-failed

Generated 2026-10-14T19:02:07+00:00. Redacted copies only; source hashes are in manifest.json.

## opus-e2e-dev216-20261014-f

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-f`

- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 13.6 |
| es.text-qc | pass | 0.5 |
| es.calibration.prefetch | pass | 90.7 |
| es.calibration | pass | 3.7 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 17.8 |
| ko.text-qc | pass | 0.5 |
| ko.calibration.prefetch | pass | 108.5 |
| ko.calibration | pass | 4.8 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 18.9 |
| zh-Hans.text-qc | pass | 0.5 |

Timings `timings.tsv`:

| inputs | pass | 7 |
|---|---|---|
| timeline-map | pass | 0 |
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 1 |
| layer2 | pass | 1 |
| plan-qc-ko | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | pass | 132 |
| plan-qc-es | pass | 1 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 109 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 20 |
| plan-layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 0 |

Failed stages: `text-qc.zh-Hans.out`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 220 of 220 requests returned; reserved US$2.22; estimated US$0.31 over 220 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 215 of 215 requests returned; reserved US$2.32; estimated US$0.37 over 215 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 32 of 32 requests returned; reserved US$0.35; estimated US$0.05 over 32 priced; invoice not verified

Error-like log lines (first 5 per log):

- `l2/layer2-jobs/0b71c060481f74f1f4ff86315d3997c53be0e99fa587a46f576a1724686d6f91/worker.log`: Traceback (most recent call last):
- `l2/layer2-jobs/0b71c060481f74f1f4ff86315d3997c53be0e99fa587a46f576a1724686d6f91/worker.log`: raise ValueError("Layer 2 rule preflight: " + reason)
- `l2/layer2-jobs/0b71c060481f74f1f4ff86315d3997c53be0e99fa587a46f576a1724686d6f91/worker.log`: ValueError: Layer 2 rule preflight: prior model payload does not match cached response
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T19:00:56.914354+00:00 ERROR run=e1e7cce1293b4d15a382fd0c1e49405c stage_finished workflowId=926b138c34ff4efbbf94a8d741d7bba2 stage=layer2.run_admission.zh-Hans spanId=17dc3e4df9114a30a1606bb
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T19:00:56.914854+00:00 ERROR run=e1e7cce1293b4d15a382fd0c1e49405c stage_finished workflowId=926b138c34ff4efbbf94a8d741d7bba2 stage=layer2_models spanId=25601ad61b464f29b91fb2907a0492e9 attem
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T19:00:56.915285+00:00 ERROR run=e1e7cce1293b4d15a382fd0c1e49405c workflow_finished workflowId=926b138c34ff4efbbf94a8d741d7bba2 stage=canonical_layer2_worker spanId=bd06ec4d3f684af7a096f939b
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T19:00:56.915929+00:00 ERROR run=e1e7cce1293b4d15a382fd0c1e49405c stage_finished workflowId=f24a4a8b85ee40e284eabf2268a5b94c stage=canonical_layer2_worker spanId=bd06ec4d3f684af7a096f939b3e9
- `l2-zh-Hans-r1/text/zh-Hans/accounting/operations.log`: 2026-10-14T19:00:56.917007+00:00 ERROR run=e1e7cce1293b4d15a382fd0c1e49405c workflow_finished workflowId=f24a4a8b85ee40e284eabf2268a5b94c status=failed
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-layer2-zh-Hans-r1.log`: == 2026-10-14T19:00:54+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/plan-layer2.log`: == 2026-10-14T18:55:40+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/plan-qc-es.log`: == 2026-10-14T18:58:44+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/plan-qc-ko.log`: == 2026-10-14T18:56:32+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/plan-qc-zh-Hans.log`: == 2026-10-14T19:00:34+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/text-qc.zh-Hans.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 12 .csv, 1434 .json, 4 .jsonl, 514 .lock, 96 .txt
