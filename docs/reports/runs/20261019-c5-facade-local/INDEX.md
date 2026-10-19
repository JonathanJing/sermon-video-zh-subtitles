# Run digest 20261019-c5-facade-local

Generated 2026-10-19T21:11:19+00:00. Redacted copies only; source hashes are in manifest.json.

## c5-facade-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/refactor-closure-docs-016c13/artifacts/c5-facade-local`

- outcome `outcome.json`: **passed_with_load_flakes** exit 1 (2026-10-19T19:40:00+00:00 → 2026-10-19T21:10:00+00:00)
- summary `summary.json`: **passed_with_load_flakes**

Error-like log lines (first 5 per log):

- `pytest.log`: >       with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
- `pytest.log`: E       AttributeError: module 'tongxing_production.compute.transports.codex_resources' has no attribute 'contracts'
- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1110 passed, 27 subtests passed in 180.82s (0:03:00)
- `unittest-shards.log`: s4: Ran 603 tests in 1526.017s FAILED (errors=1, skipped=2) exit=1
- `unittest-shards.log`: s7: Ran 615 tests in 1391.726s FAILED (failures=1, skipped=4) exit=1
- `unittest-shards.log`: s8: Ran 615 tests in 1357.322s FAILED (failures=1, skipped=4) exit=1
- `unittest-shards.log`: s9: Ran 616 tests in 2141.204s FAILED (failures=1, errors=1, skipped=5) exit=1
- `unittest-shards.log`: ERROR: test_cloud_run_jobs (unittest.loader._FailedTest.test_cloud_run_jobs)
