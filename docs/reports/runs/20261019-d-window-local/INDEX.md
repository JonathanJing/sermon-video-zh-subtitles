# Run digest 20261019-d-window-local

Generated 2026-10-19T19:45:56+00:00. Redacted copies only; source hashes are in manifest.json.

## d-window-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/facade-d-window-0ab4fe/artifacts/d-window-local`

- outcome `outcome.json`: **passed_with_one_load_flake** exit 1 (2026-10-19T17:05:00+00:00 → 2026-10-19T19:50:00+00:00)
- summary `summary.json`: **passed_with_one_load_flake**

Error-like log lines (first 5 per log):

- `pytest.log`: >       with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
- `pytest.log`: E       AttributeError: module 'tongxing_production.compute.transports.codex_resources' has no attribute 'contracts'
- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1110 passed, 27 subtests passed in 48.55s
- `unittest-shards.log`: s7.log: Ran 619 tests in 792.033s FAILED (failures=1, skipped=3)  exit 1
- `unittest-shards.log`: FAIL: test_129_group_actual_producer_can_assemble_and_resume_without_calls (test_layer2_large_fan_in.LargeLayer2FanInTests.test_129_group_actual_producer_can_assemble_and_resume_without_calls)

Not copied: 1 .json
