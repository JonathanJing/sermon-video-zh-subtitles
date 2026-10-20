# Run digest 20261014-clip-e2e-opus280-20261004-ai

Generated 2026-10-15T01:26:49+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-ai-es-recal

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-ai-es-recal`

- summary `textqc-es/out/summary.json` es: **text_waiver_issued**

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 36.6 |
| es.text-qc | pass | 2.6 |
| es.calibration.prefetch | pass | 191.5 |
| es.calibration | pass | 15.9 |
| es.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| plan-qc-es | pass | 0 |
| check-ai-qc-preflight | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 247 |
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 534 of 534 requests returned; reserved US$5.46; estimated US$0.78 over 534 priced; invoice not verified

Error-like log lines (first 5 per log):

- `logs/check-ai-qc-preflight.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/plan-qc-es.log`: == 2026-10-15T01:22:26+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 560 .json, 537 .lock
