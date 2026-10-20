# Run digest 20261020-d5-window-local

Generated 2026-10-20T23:49:57+00:00. Redacted copies only; source hashes are in manifest.json.

## d5-window-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/kind-poitras-a1f6f0/artifacts/d5-window-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-20T20:35:00+00:00 → 2026-10-20T23:49:57+00:00)

Timings `timings.tsv`:

| phase | seconds |
|---|---|
| first full run | 3150 |
| second full run | 3150 |
| final full run | 2680 |

Failed stages: `first full run`, `second full run`, `final full run`

Error-like log lines (first 5 per log):

- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1113 passed, 27 subtests passed in 288.08s (0:04:48)
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `unittest-shards.log`: shard 8: Ran 633 tests in 1721.256s FAILED (failures=1, skipped=4)
- `unittest-shards.log`: FAIL: test_100_transitions_with_persistent_intents (test_sermon_unified_parallel.ParallelOwnerTests.test_100_transitions_with_persistent_int
- `unittest-shards.log`: AssertionError: 3.237415 not less than or equal to 2
