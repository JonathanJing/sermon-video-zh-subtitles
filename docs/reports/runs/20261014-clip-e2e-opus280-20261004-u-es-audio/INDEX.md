# Run digest 20261014-clip-e2e-opus280-20261004-u-es-audio

Generated 2026-10-14T22:22:05+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-u-es-audio

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-u-es-audio`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**

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

Timings `timings.tsv`:

| plan-qc-es | pass | 0 |
|---|---|---|
| spark-begin-1 | pass | 4 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 25 |
| compact.es | fail(1) | 6 |
| spark-finish | pass | 6 |

Failed stages: `render.es`, `compact.es`

Error-like log lines (first 5 per log):

- `l3/es/spark-es-c/compact.log`: Traceback (most recent call last):
- `l3/es/spark-es-c/compact.log`: raise ValueError(message)
- `l3/es/spark-es-c/compact.log`: ValueError: Audio operation policy content differs from speech adapter/job hashes
- `l3/es/spark-output/render.log`: Traceback (most recent call last):
- `l3/es/spark-output/render.log`: raise ValueError(message)
- `l3/es/spark-output/render.log`: ValueError: Audio operation policy content differs from speech adapter/job hashes
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:21:29.097286+00:00 ERROR run=89ea95d5504642df9b93acf506d15ea3 stage_finished workflowId=2dd8bd550fd649cd85c5482786605072 stage=layer3.validate_inputs spanId=8e3a3a479e884e878cff845b0c856
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:21:29.102207+00:00 ERROR run=89ea95d5504642df9b93acf506d15ea3 stage_finished workflowId=2dd8bd550fd649cd85c5482786605072 stage=layer3_formal_render spanId=0daf8d1fc1b046a8bf2ffef058a9218
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:21:29.112186+00:00 ERROR run=89ea95d5504642df9b93acf506d15ea3 workflow_finished workflowId=2dd8bd550fd649cd85c5482786605072 status=failed
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:21:29.116860+00:00 ERROR run=89ea95d5504642df9b93acf506d15ea3 run_finished workflowId=2dd8bd550fd649cd85c5482786605072 status=failed
- `logs/check-gpu-es.log`: "failed": [],
- `logs/plan-qc-es.log`: == 2026-10-14T22:20:51+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 3 .csv, 53 .json, 1 .jsonl, 6 .lock
