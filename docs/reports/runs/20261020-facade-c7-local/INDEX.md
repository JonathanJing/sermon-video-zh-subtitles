# Run digest 20261020-facade-c7-local

Generated 2026-10-20T02:31:41+00:00. Redacted copies only; source hashes are in manifest.json.

## facade-c7-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/facade-cli-entry-86e06d/artifacts/facade-c7-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-19T23:35:00+00:00 → 2026-10-20T02:10:00+00:00)
- summary `summary.json`: **passed**

Error-like log lines (first 5 per log):

- `changed-tests.log`: tests/test_canonical_layer2_runtime_authorization.py :: 1 error in 1.61s
- `changed-tests.log`: tests/test_codex_shared_pool_transport.py :: 1 failed, 1 passed in 6.77s
- `changed-tests.log`: tests/test_sermon_provider_error.py :: 4 passed in 0.98s
- `changed-tests.log`: tests/test_sermon_unified_parallel.py :: 1 failed, 11 passed in 184.70s (0:03:04)
- `changed-tests.log`: tests/test_sermon_provider_error.py :: 4 passed in 0.73s
- `pytest.log`: tests/test_lease_fencing.py + tests/test_sermon_unified_parallel.py: 1 failed, 40 passed (test_100_transitions_with_persistent_intents, 2.586 > 2)
- `pytest.log`: same test on clean origin/dev: 1 failed (same bound)
- `unittest-shards.log`: FAIL: test_hung_renewal_still_terminates_execution_at_local_deadline (test_lease_fencing.SupervisorLeaseExecutionTests.test_hung_renewal_still_terminates_execution_at_local_deadline)
- `unittest-shards.log`: FAILED (failures=1, skipped=5)
- `unittest-shards.log`: FAIL: test_129_group_actual_producer_can_assemble_and_resume_without_calls (test_layer2_large_fan_in.LargeLayer2FanInTests.test_129_group_actual_producer_can_assemble_and_resume_without_calls)
- `unittest-shards.log`: FAILED (failures=1, skipped=5)
- `unittest-shards.log`: FAIL: test_100_transitions_with_persistent_intents (test_sermon_unified_parallel.ParallelOwnerTests.test_100_transitions_with_persistent_intents)
