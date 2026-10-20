# Run digest 20261019-facade-c8-local

Generated 2026-10-20T00:29:37+00:00. Redacted copies only; source hashes are in manifest.json.

## c8-facade-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/facade-removal-ab-a8ca38/artifacts/c8-facade-local`

- outcome `outcome.json`: **passed_with_load_timing_failures** exit 1 (2026-10-19T22:10:00+00:00 → 2026-10-20T00:20:00+00:00)
- summary `summary.json`: **passed_with_load_timing_failures**

Error-like log lines (first 5 per log):

- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1111 passed, 27 subtests passed in 220.92s (0:03:40)
- `unittest-shards.log`: s8.log: Ran 619 tests in 1488.358s FAILED (failures=1, skipped=2)
- `unittest-shards.log`: s9.log: Ran 620 tests in 1137.950s FAILED (failures=1, skipped=4)
- `unittest-shards.log`: FAIL: test_65_group_worker_and_cache_only_recovery_preserve_every_dependency (test_layer2_large_fan_in.LargeLayer2FanInTests.test_65_group_worker_and_cache_only_recovery_preserve_every_dependency)
- `unittest-shards.log`: FAIL: test_100_transitions_with_persistent_intents (test_sermon_unified_parallel.ParallelOwnerTests.test_100_transitions_with_persistent_intents)
