# Run digest 20261014-clip-e2e-opus280-20261004-z

Generated 2026-10-15T00:02:22+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-z-3lang

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-z-3lang`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **error** (ValueError: source_budget_exhausted)
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **error** (ValueError: source_budget_exhausted)

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
| ko.calibration.prefetch | fail | 245.4 |

Failed stages: `ko.calibration.prefetch`

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.calibration.prefetch | fail | 240.4 |

Failed stages: `zh-Hans.calibration.prefetch`

Timings `timings.tsv`:

| plan-qc-ko | pass | 0 |
|---|---|---|
| plan-qc-zh-Hans | pass | 0 |
| check-z-code-route | pass | 0 |
| check-z-budget-ko | pass | 1 |
| check-z-budget-zh-Hans | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | fail(1) | 246 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 241 |

Failed stages: `text-qc.ko.out`, `text-qc.zh-Hans.out`
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 511 of 511 requests returned; reserved US$5.52; estimated US$0.89 over 511 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 511 of 511 requests returned; reserved US$5.52; estimated US$0.93 over 511 priced; invoice not verified

Error-like log lines (first 5 per log):

- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/check-z-budget-ko.log`: "failed": [],
- `logs/check-z-budget-zh-Hans.log`: "failed": [],
- `logs/check-z-code-route.log`: "failed": [],
- `logs/plan-qc-ko.log`: == 2026-10-14T23:53:38+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-zh-Hans.log`: == 2026-10-14T23:53:38+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/text-qc.ko.out.log`: ko.calibration.prefetch	fail	245.4
- `logs/text-qc.ko.out.log`: "status": "error",
- `logs/text-qc.ko.out.log`: "reason": "ValueError: source_budget_exhausted",
- `logs/text-qc.zh-Hans.out.log`: zh-Hans.calibration.prefetch	fail	240.4
- `logs/text-qc.zh-Hans.out.log`: "status": "error",
- `logs/text-qc.zh-Hans.out.log`: "reason": "ValueError: source_budget_exhausted",

Not copied: 1095 .json, 1036 .lock
