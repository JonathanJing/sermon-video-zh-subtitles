# Run digest 20261029-tongxing-production-1-26-32-asc

Generated 2026-10-29T00:09:01+00:00. Redacted copies only; source hashes are in manifest.json.

## production-1.26.32-asc

Source: `~/.codex/worktrees/ios-ui-fixes-20261028/sermon-video-zh-subtitles/artifacts/tongxing-ios/production-1.26.32-asc`

- outcome `outcome.json`: **submitted_waiting_for_review** exit 0 (2026-10-28T23:43:41Z → 2026-10-29T00:07:56Z)
- summary `summary.json`: **WAITING_FOR_REVIEW**

Error-like log lines (first 5 per log):

- `processing.log`: [17:00:06]:     114:	    UI.user_error!('Apple rejected the build') if build &&
- `processing.log`: [17:00:06]:     115:	      (build.expired || ['FAILED', 'INVALID'].include?(build.processing_state))
- `processing.log`: [17:00:06]:  => 116:	    UI.user_error!('Apple processing timed out; reconcile before retrying upload') if
- `processing.log`: [!] Apple processing timed out; reconcile before retrying upload

Not copied: 1 (none), 24 .json, 2 .md, 1 .xml
