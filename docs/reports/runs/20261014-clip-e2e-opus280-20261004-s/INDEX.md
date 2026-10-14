# Run digest 20261014-clip-e2e-opus280-20261004-s

Generated 2026-10-14T22:02:37+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-s

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-s`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-ko/out/summary.json` ko: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 40.1 |
| es.text-qc | pass | 2.8 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 46.6 |
| ko.text-qc | pass | 2.8 |

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
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | fail(1) | 50 |
| plan-layer2-ko-r1 | fail(1) | 0 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 1 |
| text-qc.es.out | fail(1) | 44 |
| plan-layer2-es-r1 | fail(1) | 0 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 44 |
| plan-layer2-zh-Hans-r1 | fail(1) | 0 |

Failed stages: `text-qc.ko.out`, `plan-layer2-ko-r1`, `text-qc.es.out`, `plan-layer2-es-r1`, `text-qc.zh-Hans.out`, `plan-layer2-zh-Hans-r1`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.01; estimated US$0.12 over 99 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.08; estimated US$0.15 over 99 priced; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 99 of 99 requests returned; reserved US$1.08; estimated US$0.15 over 99 priced; invoice not verified

Error-like log lines (first 5 per log):

- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-layer2-es-r1.log`: == 2026-10-14T22:01:26+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-es-r1.log`: Traceback (most recent call last):
- `logs/plan-layer2-es-r1.log`: raise ValueError(reason)
- `logs/plan-layer2-es-r1.log`: ValueError: invalid_execution_configuration
- `logs/plan-layer2-ko-r1.log`: == 2026-10-14T22:00:42+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-ko-r1.log`: Traceback (most recent call last):
- `logs/plan-layer2-ko-r1.log`: raise ValueError(reason)
- `logs/plan-layer2-ko-r1.log`: ValueError: invalid_execution_configuration
- `logs/plan-layer2-zh-Hans-r1.log`: == 2026-10-14T22:02:11+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2-zh-Hans-r1.log`: Traceback (most recent call last):
- `logs/plan-layer2-zh-Hans-r1.log`: raise ValueError(reason)
- `logs/plan-layer2-zh-Hans-r1.log`: ValueError: invalid_execution_configuration
- `logs/plan-qc-es.log`: == 2026-10-14T22:00:42+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-ko.log`: == 2026-10-14T21:59:51+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-zh-Hans.log`: == 2026-10-14T22:01:27+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/text-qc.es.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.ko.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",
- `logs/text-qc.zh-Hans.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 1582 .json, 306 .lock, 2 .py
