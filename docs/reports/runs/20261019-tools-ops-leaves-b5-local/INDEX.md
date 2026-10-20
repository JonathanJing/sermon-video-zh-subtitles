# Run digest 20261019-tools-ops-leaves-b5-local

Generated 2026-10-19T18:33:06+00:00. Redacted copies only; source hashes are in manifest.json.

## tools-ops-leaves-b5-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/opus-haiku-translation-review-4a3b7c/artifacts/tools-ops-leaves-b5-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-19T18:09:29.946530+00:00 → 2026-10-19T18:14:02.506530+00:00)
- summary `summary.json`: **passed**

Error-like log lines (first 5 per log):

- `dag-fanin-rerun.log`: second=models.run_accounted(f.source,f.anchor,f.policy,out,'',lambda *_:self.fail('cache called transport'),None,
- `dag-fanin-rerun.log`: E   AssertionError: 'partial' != 'projected'
- `dag-fanin-rerun.log`: FAILED tests/test_layer2_large_fan_in.py::LargeLayer2FanInTests::test_129_group_actual_producer_can_assemble_and_resume_without_calls
- `dag-fanin-rerun.log`: 1 failed, 22 passed, 15 subtests passed in 175.24s (0:02:55)
- `full-shard0.log`: FAIL: test_129_group_actual_producer_can_assemble_and_resume_without_calls (test_layer2_large_fan_in.LargeLayer2FanInTests.test_129_group_actual_producer_can_assemble_and_resume_without_calls)
- `full-shard0.log`: FAIL: test_65_group_worker_and_cache_only_recovery_preserve_every_dependency (test_layer2_large_fan_in.LargeLayer2FanInTests.test_65_group_worker_and_cache_only_recovery_preserve_every_dependency)
- `full-shard0.log`: FAILED (failures=2, skipped=8)
- `full-shard3.log`: FAIL: test_two_real_commits_accept_new_authorization_without_code_gate_mock (test_sermon_diagnostic_dag_session.CrossCommitMigrationTests.test_two_real_commits_accept_new_authorization_without_code_ga
- `full-shard3.log`: FAILED (failures=1, skipped=11, expected failures=1)
