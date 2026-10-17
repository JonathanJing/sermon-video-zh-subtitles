# Run digest 20261017-project-credit-move-env-fail

Generated 2026-10-17T22:51:14+00:00. Redacted copies only; source hashes are in manifest.json.

## project-credit-usage-move-20261017

Source: `/private/tmp/sermon-project-credit-usage-move-20261017/artifacts/project-credit-usage-move-20261017`

- outcome `outcome.json`: **failed** exit 1 (2026-10-17T22:51:12.217182+00:00 → 2026-10-17T22:51:12.312367+00:00)

Timings `timings.tsv`:

| stage | seconds | status |
|---|---|---|
| focused_unittest | 0.095 | failed |

Failed stages: `focused_unittest`

Error-like log lines (first 5 per log):

- `test.log`: test_project_codex_credit_usage (unittest.loader._FailedTest.test_project_codex_credit_usage) ... ERROR
- `test.log`: ERROR: test_project_codex_credit_usage (unittest.loader._FailedTest.test_project_codex_credit_usage)
- `test.log`: ImportError: Failed to import test module: test_project_codex_credit_usage
- `test.log`: Traceback (most recent call last):
- `test.log`: ModuleNotFoundError: No module named 'tongxing_production'
