# Run digest 20261014-pr390-review-fix

Generated 2026-10-14T17:02:18+00:00. Redacted copies only; source hashes are in manifest.json.

## pr390-review-fix-tests

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/pr390-review-fix-tests`

- outcome `outcome.json`: **pass_after_entrypoint_retry** exit 0 (2026-10-14T17:01:00Z → 2026-10-14T17:02:07Z)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| node-targeted-tests | pass | 2.79 |
| python-root-entrypoint | fail | 0.11 |
| python-test-directory-retry | pass | 0.51 |
| git-diff-check | pass | 0.20 |

Failed stages: `python-root-entrypoint`
