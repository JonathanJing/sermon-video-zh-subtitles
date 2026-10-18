# Run digest 20261014-clip-e2e-opus280-20261004-af

Generated 2026-10-15T00:58:50+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-af-zh-textcont

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-af-zh-textcont`

- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 3.3 |
| zh-Hans.text-qc | pass | 3.3 |
| zh-Hans.calibration.prefetch | pass | 45.4 |
| zh-Hans.calibration | pass | 17.9 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| plan-qc-zh-Hans | pass | 0 |
|---|---|---|
| check-af-qc-preflight | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | pass | 71 |
| spark-begin-1 | pass | 3 |
| voice-auth.zh-Hans | pass | 0 |
| speech-job.zh-Hans | fail(1) | 0 |
| spark-finish | pass | 7 |

Failed stages: `speech-job.zh-Hans`
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 24 of 24 requests returned; reserved US$0.34; estimated US$0.05 over 24 priced; invoice not verified

Error-like log lines (first 5 per log):

- `logs/check-af-qc-preflight.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-qc-zh-Hans.log`: == 2026-10-15T00:56:58+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/speech-job.zh-Hans.log`: Traceback (most recent call last):
- `logs/speech-job.zh-Hans.log`: raise ValueError(message)
- `logs/speech-job.zh-Hans.log`: ValueError: Missing input: ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-af-zh-textcont/l3/clip-timeline-map.json

Not copied: 56 .json, 27 .lock
