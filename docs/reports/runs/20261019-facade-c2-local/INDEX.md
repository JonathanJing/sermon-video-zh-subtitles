# Run digest 20261019-facade-c2-local

Generated 2026-10-19T21:47:01+00:00. Redacted copies only; source hashes are in manifest.json.

## facade-c2-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/facade-cli-entry-86e06d/artifacts/facade-c2-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-19T19:25:00+00:00 → 2026-10-19T21:30:00+00:00)
- summary `summary.json`: **passed**

Error-like log lines (first 5 per log):

- `changed-tests.log`: tests/test_layer2_large_fan_in.py :: 1 failed in 14.65s
- `changed-tests.log`: tests/test_observability_diagnostic_driver.py :: 1 failed, 2 passed in 2.55s
- `changed-tests.log`: tests/test_sermon_fresh_full_dag.py :: 1 failed in 8.51s
- `changed-tests.log`: tests/test_sermon_mock_tts_dag.py :: 1 failed in 7.93s
- `changed-tests.log`: tests/test_tongxing_production_package.py :: 1 failed, 4 passed, 318 subtests passed in 10.84s
- `pytest.log`: 2 failed, 1 passed (same utc_clock_discontinuity failure)
- `pytest.log`: tests 13 pass 13 fail 0
- `unittest-shards.log`: FAIL: test_public_cli_round_trip_from_outside_repository (experiments.local_experiment_log.tests.test_cli.FileInterfaceTests.test_public_cli_round_trip_from_outside_repository)
- `unittest-shards.log`: FAILED (failures=1, skipped=4)
- `unittest-shards.log`: ERROR: test_cloud_run_jobs (unittest.loader._FailedTest.test_cloud_run_jobs)
- `unittest-shards.log`: FAIL: test_packaged_bridge_uses_bundled_shared_validator (experiments.local_experiment_log.tests.test_cli.FileInterfaceTests.test_packaged_bridge_uses_bundled_shared_validator)
- `unittest-shards.log`: FAIL: test_moved_module_keeps_a_repository_identity_key (test_tongxing_production_package.ProductionPackageTests.test_moved_module_keeps_a_repository_identity_key)
