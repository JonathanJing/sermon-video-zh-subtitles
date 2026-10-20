# Run digest 20261020-app-pr-integration-local

Generated 2026-10-20T21:43:19+00:00. Redacted copies only; source hashes are in manifest.json.

## pr475-ios-local

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles--claude-worktrees-scripts-r1-131a68/266830db-8a19-4348-949f-54599e83d292/scratchpad/runs/pr475-ios-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-20T20:20:00+00:00 → 2026-10-20T20:35:00+00:00)

Error-like log lines (first 5 per log):

- `swift-test.log`: ... 61 lines omitted; 0 error-like lines, 0 kept below ...

## pr1081-web-local

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles--claude-worktrees-scripts-r1-131a68/266830db-8a19-4348-949f-54599e83d292/scratchpad/runs/pr1081-web-local`

- outcome `outcome.json`: **passed** exit 0 (2026-10-20T20:36:00+00:00 → 2026-10-20T20:50:00+00:00)

## pr1082-local

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles--claude-worktrees-scripts-r1-131a68/266830db-8a19-4348-949f-54599e83d292/scratchpad/runs/pr1082-local`

- outcome `outcome.json`: **passed_with_limits** exit 0 (2026-10-20T20:50:00+00:00 → 2026-10-20T23:10:00+00:00)

Error-like log lines (first 5 per log):

- `pr1082-py-2.log`: E                   AssertionError: Regex didn't match: '\\btests\\.test_mixed_source_catalog_v5\\b' not found in '  native_contracts:\n    name: Native and shared client contracts\n    needs: changes
- `pr1082-py-2.log`: tests/test_ci_change_scope.py:166: AssertionError
- `pr1082-py-2.log`: SUBFAILED(consumer='test_mixed_source_catalog_v5.py') tests/test_ci_change_scope.py::CIChangeScopeTests::test_native_suite_covers_every_current_shared_native_dependency
- `pr1082-py-2.log`: 1 failed, 313 passed, 2 skipped, 1015 subtests passed in 486.84s (0:08:06)
- `pr1082-swift-infra.log`: /private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles--claude-worktrees-scripts-r1-131a68/266830db-8a19-4348-949f-54599e83d292/scratchpad/wt/pr1082/apps/to
- `pr1082-swift-infra.log`: [0;36m|[0;0m                                    `- [1;33mwarning: [1;39minstance method 'makeIterator' is unavailable from asynchronous contexts; this is an error in the Swift 6 language mode[0;0
- `pr1082-swift-infra.log`: ◇ Test damagedPreferredCatalogCacheFallsBackAndPreservesNetworkError() started.
- `pr1082-swift-infra.log`: ✔ Test damagedPreferredCatalogCacheFallsBackAndPreservesNetworkError() passed after 0.158 seconds.
- `pr1082-swift-infra.log`: ◇ Test failedUploadRetriesCumulativeAndDayRotatesIdentity() started.
- `pr1082-swift.log`: ... 73 lines omitted; 0 error-like lines, 0 kept below ...
- `pr1082-web.log`: ✔ a media load error retains click-to-retry and reloads before native play (0.820541ms)
- `pr1082-web.log`: ✔ startup timeout leaves a usable retry and ignores the timed-out promise rejection (0.849ms)
- `pr1082-web.log`: ✔ alignment timeout that pauses before rejecting still shows manual follow-up (0.729125ms)
- `pr1082-web.log`: ✔ real alignment helper timeout pauses audio while adapter still displays manual recovery (0.970042ms)
- `pr1082-web.log`: ... 397 lines omitted; 36 error-like lines, 36 kept below ...
