# Run digest 20261019-facade-c1-local

Generated 2026-10-19T21:02:23+00:00. Redacted copies only; source hashes are in manifest.json.

## c1-facade-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/facade-removal-ab-a8ca38/artifacts/c1-facade-local`

- outcome `outcome.json`: **passed_with_one_load_flake** exit 1 (2026-10-19T20:20:00+00:00 → 2026-10-19T21:00:00+00:00)
- summary `summary.json`: **passed_with_one_load_flake**

Error-like log lines (first 5 per log):

- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1110 passed, 27 subtests passed in 194.66s (0:03:14)
- `unittest-shards.log`: s6.log: Ran 606 tests in 1520.407s FAILED (errors=1, skipped=3)  exit=1
- `unittest-shards.log`: s7.log: Ran 615 tests in 2044.278s FAILED (failures=1, skipped=5)  exit=1
- `unittest-shards.log`: s8.log: Ran 614 tests in 1699.035s FAILED (errors=1, skipped=1)  exit=1
- `unittest-shards.log`: ERROR: test_backend_app (unittest.loader._FailedTest.test_backend_app)
- `unittest-shards.log`: ERROR: test_cloud_run_jobs (unittest.loader._FailedTest.test_cloud_run_jobs)
