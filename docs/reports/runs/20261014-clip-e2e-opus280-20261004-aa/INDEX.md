# Run digest 20261014-clip-e2e-opus280-20261004-aa

Generated 2026-10-15T00:07:35+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-aa-3lang

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-aa-3lang`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

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
| ko.calibration.prefetch | pass | 43.1 |
| ko.calibration | pass | 18.2 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.calibration.prefetch | pass | 48.1 |
| zh-Hans.calibration | pass | 18.0 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| plan-qc-ko | pass | 0 |
|---|---|---|
| check-aa-budget-ko | pass | 0 |
| plan-qc-zh-Hans | pass | 0 |
| check-aa-budget-zh-Hans | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | pass | 62 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | pass | 67 |
| spark-begin-1 | pass | 3 |
| voice-auth.ko | pass | 0 |
| speech-job.ko | fail(1) | 0 |
| spark-finish | pass | 7 |

Failed stages: `speech-job.ko`
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 20 of 20 requests returned; reserved US$0.28; estimated US$0.04 over 20 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 23 of 23 requests returned; reserved US$0.33; estimated US$0.05 over 23 priced; invoice not verified

Error-like log lines (first 5 per log):

- `logs/check-aa-budget-ko.log`: "failed": [],
- `logs/check-aa-budget-zh-Hans.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-qc-ko.log`: == 2026-10-15T00:03:47+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-zh-Hans.log`: == 2026-10-15T00:03:47+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/speech-job.ko.log`: Traceback (most recent call last):
- `logs/speech-job.ko.log`: raise ValueError(message)
- `logs/speech-job.ko.log`: ValueError: Verified speech adapter lacks production authorization or human-reviewed locale capability

Not copied: 125 .json, 54 .lock
