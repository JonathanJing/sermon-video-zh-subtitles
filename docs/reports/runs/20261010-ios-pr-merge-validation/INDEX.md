# Run digest 20261010-ios-pr-merge-validation

Generated 2026-10-10T23:06:47+00:00. Redacted copies only; source hashes are in manifest.json.

## ios-pr-merge-20261010

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/ios-pr-merge-20261010`

- outcome `outcome.json`: **passed_after_test_navigation_repair** exit ? (? → ?)

Error-like log lines (first 5 per log):

- `initial-ios.log`: ... 1357 lines omitted; 53 error-like lines, 50 kept below ...
- `initial-ios.log`: [line 535] RegisterExecutionPolicyException /tmp/tongxing-ios-pr-merge-20261010/artifacts/tongxing-ios/2026-10-10/cli/DerivedData/Build/Products/Debug-iphonesimulator/PackageFrameworks/TongxingCore_-2
- `initial-ios.log`: [line 537]     builtin-RegisterExecutionPolicyException /tmp/tongxing-ios-pr-merge-20261010/artifacts/tongxing-ios/2026-10-10/cli/DerivedData/Build/Products/Debug-iphonesimulator/PackageFrameworks/Ton
- `initial-ios.log`: [line 660] /tmp/tongxing-ios-pr-merge-20261010/apps/tongxing-ios/Tests/AudioAlignmentControllerTests.swift:717:100: warning: main actor-isolated static property 'match' can not be referenced from a no
- `initial-ios.log`: [line 671]      |                                                                                                    `- warning: main actor-isolated static property 'match' can not be referenced from 
- `ios-recheck.log`: ... 181 lines omitted; 4 error-like lines, 4 kept below ...
- `ios-recheck.log`: [line 115] /tmp/tongxing-ios-pr-merge-20261010/apps/tongxing-ios/Tests/AudioAlignmentControllerTests.swift:717:100: warning: main actor-isolated static property 'match' can not be referenced from a no
- `ios-recheck.log`: [line 126]      |                                                                                                    `- warning: main actor-isolated static property 'match' can not be referenced from 
- `ios-recheck.log`: [line 130] /tmp/tongxing-ios-pr-merge-20261010/apps/tongxing-ios/Tests/AudioAlignmentControllerTests.swift:834:21: warning: stored property '_count' of 'Sendable'-conforming class 'CallCounter' is mut
- `ios-recheck.log`: [line 134]      |                     `- warning: stored property '_count' of 'Sendable'-conforming class 'CallCounter' is mutable; this is an error in the Swift 6 language mode
- `web.log`: ✔ optional requests have a bounded timeout and abort pending network work (13.090416ms)
- `web.log`: ✔ v4 catalog schema version falls back to the v3 projection and records the error (2.267375ms)
- `web.log`: ✔ v4 catalog missing default page falls back to the v3 projection and records the error (1.27225ms)
- `web.log`: ✔ v4 catalog malformed JSON falls back to the v3 projection and records the error (1.0235ms)
- `web.log`: ✔ v4 catalog malformed page falls back to the v3 projection and records the error (0.9365ms)
