# Run digest 20261020-pr1065-rebase-local

Generated 2026-10-20T21:05:05+00:00. Redacted copies only; source hashes are in manifest.json.

## pr1065-rebase-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/jolly-galileo-b7ba98/artifacts/pr1065-rebase-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-20T20:50:00+00:00 → 2026-10-20T21:12:00+00:00)
- summary `summary.json`: **passed**

Error-like log lines (first 5 per log):

- `pytest.log`: with self.assertRaises(ValueError):
- `pytest.log`: E       AssertionError: 14 not greater than 16
- `pytest.log`: tests/test_production_concurrency_profile.py:45: AssertionError
- `pytest.log`: FAILED tests/test_production_concurrency_profile.py::ProfileTests::test_23_worker_executor_is_opt_in_and_preserves_source_order
- `pytest.log`: 1 failed, 196 passed, 25 subtests passed in 679.99s (0:11:19)
