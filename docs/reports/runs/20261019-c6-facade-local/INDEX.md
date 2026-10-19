# Run digest 20261019-c6-facade-local

Generated 2026-10-19T22:13:12+00:00. Redacted copies only; source hashes are in manifest.json.

## c6-facade-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/refactor-closure-docs-016c13/artifacts/c6-facade-local`

- outcome `outcome.json`: **passed_with_load_flakes** exit 1 (2026-10-19T21:20:00+00:00 → 2026-10-19T22:20:00+00:00)
- summary `summary.json`: **passed_with_load_flakes**

Error-like log lines (first 5 per log):

- `fixture-compare.log`: harness: 232 tests, 2 v3_update mutation tests fail identically in all runs (rmtree disabled to keep temp dirs)
- `pytest.log`: >       with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
- `pytest.log`: E       AttributeError: module 'tongxing_production.compute.transports.codex_resources' has no attribute 'contracts'
- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1110 passed, 27 subtests passed in 50.87s
- `unittest-shards.log`: s7: Ran 619 tests in 679.018s FAILED (failures=1, skipped=5) exit=1
- `unittest-shards.log`: FAIL: test_129_group_actual_producer_can_assemble_and_resume_without_calls (test_layer2_large_fan_in.LargeLayer2FanInTests.test_129_group_actual_producer_can_assemble_and_resume_without_calls)
- `unittest-shards.log`: s9: Ran 620 tests in 1111.926s FAILED (failures=1, skipped=3) exit=1
- `unittest-shards.log`: FAIL: test_65_group_worker_and_cache_only_recovery_preserve_every_dependency (test_layer2_large_fan_in.LargeLayer2FanInTests.test_65_group_worker_and_cache_only_recovery_preserve_every_dependency)
