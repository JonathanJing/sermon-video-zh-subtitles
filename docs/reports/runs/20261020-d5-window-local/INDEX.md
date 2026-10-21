# Run digest 20261020-d5-window-local

Generated 2026-10-21T01:04:36+00:00. Redacted copies only; source hashes are in manifest.json.

## d5-window-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/kind-poitras-a1f6f0/artifacts/d5-window-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-20T20:35:00+00:00 → 2026-10-21T01:04:36+00:00)

Timings `timings.tsv`:

| phase | seconds |
|---|---|
| first full run | 3150 |
| second full run | 3150 |
| final full run | 2680 |

Failed stages: `first full run`, `second full run`, `final full run`

Error-like log lines (first 5 per log):

- `pytest.log`: 2 failed, 1112 passed, 27 subtests passed in 277.15s (0:04:37)
- `pytest.log`: FAILED tests/test_audio_calibration_short_truncation.py::test_all_short_preflight_has_no_truncation_but_other_kinds_are_available
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `unittest-shards.log`: shard 8: Ran 634 tests in 2772.417s FAILED (failures=1, skipped=3)
- `unittest-shards.log`: FAIL: test_100_transitions_with_persistent_intents (test_sermon_unified_parallel.ParallelOwnerTests.test_100_transitions_with_persistent_int
- `unittest-shards.log`: AssertionError: 2.608472 not less than or equal to 2
