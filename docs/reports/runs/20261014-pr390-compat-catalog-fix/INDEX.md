# Run digest 20261014-pr390-compat-catalog-fix

Generated 2026-10-14T17:09:10+00:00. Redacted copies only; source hashes are in manifest.json.

## pr390-compat-catalog-fix-tests

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/pr390-compat-catalog-fix-tests`

- outcome `outcome.json`: **pass_after_expected-contract-update** exit 0 (2026-10-14T17:07:00Z → 2026-10-14T17:09:01Z)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| python-rollout-before-contract-update | fail | 0.57 |
| python-rollout-after-contract-update | pass | 0.58 |
| python-compile | pass | 0.10 |
| git-diff-check | pass | 0.20 |

Failed stages: `python-rollout-before-contract-update`
