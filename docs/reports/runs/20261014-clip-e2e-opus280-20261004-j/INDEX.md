# Run digest 20261014-clip-e2e-opus280-20261004-j

Generated 2026-10-14T21:02:17+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-j

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-j`

- summary `summary.json`: **failed_budget_preflight**

Timings `timings.tsv`:

| inputs | pass | 133 |
|---|---|---|
| timeline-map | pass | 0 |
| route-probe | pass | 0 |
| plan-layer2 | fail(1) | 0 |

Failed stages: `plan-layer2`

Error-like log lines (first 5 per log):

- `logs/plan-layer2.log`: == 2026-10-14T21:01:25+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-layer2.log`: Traceback (most recent call last):
- `logs/plan-layer2.log`: raise ValueError(f"Layer 2 {locale} {dimension} cap cannot cover even the initial "
- `logs/plan-layer2.log`: ValueError: Layer 2 es costMicrousd cap cannot cover even the initial 100 calls; use an explicitly approved profile, do not inflate authority implicitly

Not copied: 13 .json
