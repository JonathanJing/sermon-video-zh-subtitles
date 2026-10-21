# Run digest 20261019-facade-removal-ab-local

Generated 2026-10-19T18:59:46+00:00. Redacted copies only; source hashes are in manifest.json.

## facade-removal-ab-local

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.claude/worktrees/facade-removal-ab-a8ca38/artifacts/facade-removal-ab-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-19T17:20:00+00:00 → 2026-10-19T19:55:00+00:00)
- summary `summary.json`: **passed**

Error-like log lines (first 5 per log):

- `pytest.log`: >       with patch.object(slots.Admission, 'reserve', side_effect=slots.contracts.ContractError('resource_broker_busy')):
- `pytest.log`: E       AttributeError: module 'tongxing_production.compute.transports.codex_resources' has no attribute 'contracts'
- `pytest.log`: tests/test_codex_shared_pool_transport.py:62: AttributeError
- `pytest.log`: FAILED tests/test_codex_shared_pool_transport.py::test_busy_before_started_is_proven_no_dispatch
- `pytest.log`: 1 failed, 1112 passed, 1 warning, 3 subtests passed in 82.46s (0:01:22)
- `unittest-shards.log`: ... 3563 lines omitted; 77 error-like lines, 50 kept below ...
- `unittest-shards.log`: [line 113] .....................................SERMON_LOGGING_WRITE_FAILED errorType=AccountingWriteError
- `unittest-shards.log`: [line 213]   "reason": "every shorten group failed its checks; those groups stay subtitle-only in the dub",
- `unittest-shards.log`: [line 217]   "failedGroupIds": [
- `unittest-shards.log`: [line 276] runtime_tts_mac.py: error: this bounded diagnostic writes only its declared output directory
