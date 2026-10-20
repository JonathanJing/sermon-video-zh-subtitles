# Run digest 20261014-clip-e2e-opus280-20261004-ae

Generated 2026-10-15T00:56:19+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-ae-zh-recal

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-ae-zh-recal`

- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **error** (ValueError: source_budget_exhausted)

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 43.5 |
| zh-Hans.text-qc | pass | 2.5 |
| zh-Hans.calibration.prefetch | fail | 208.8 |

Failed stages: `zh-Hans.calibration.prefetch`

Timings `timings.tsv`:

| plan-qc-zh-Hans | pass | 0 |
|---|---|---|
| check-ae-qc-preflight | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 255 |

Failed stages: `text-qc.zh-Hans.out`
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 511 of 511 requests returned; reserved US$5.52; estimated US$0.93 over 511 priced; invoice not verified

Error-like log lines (first 5 per log):

- `logs/check-ae-qc-preflight.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-qc-zh-Hans.log`: == 2026-10-15T00:51:32+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/text-qc.zh-Hans.out.log`: zh-Hans.calibration.prefetch	fail	208.8
- `logs/text-qc.zh-Hans.out.log`: "status": "error",
- `logs/text-qc.zh-Hans.out.log`: "reason": "ValueError: source_budget_exhausted",

Not copied: 537 .json, 515 .lock
