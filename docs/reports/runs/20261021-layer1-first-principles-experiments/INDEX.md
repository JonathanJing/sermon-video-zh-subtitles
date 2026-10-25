# Run digest 20261021-layer1-first-principles-experiments

Generated 2026-10-21T20:36:19+00:00. Redacted copies only; source hashes are in manifest.json.

## e1-rules-8s.output

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrects-his-own/layer1-fp/e1-rules-8s.output`

- summary `summary.json`: **english_source_candidate**

Not copied: 479 .json, 1 .lock, 119 .txt

## e2c-negated-or.output

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrects-his-own/layer1-fp/e2c-negated-or.output`

- summary `summary.json`: **english_source_candidate**

Not copied: 27 .json, 1 .lock, 6 .txt

## e4c-execute-asr14-judge8.output

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrects-his-own/layer1-fp/e4c-execute-asr14-judge8.output`

- summary `summary.json`: **english_source_candidate**

Error-like log lines (first 5 per log):

- `accounting/operations.log`: 2026-10-21T20:15:56.062469+00:00 ERROR run=da3ca7aa1b2f4953b309ff704ef883e8 stage_finished workflowId=b3a2747feafe437180d3c7a9decb8ea4 stage=unified_source_preparation spanId=29617963ba0f4b7298ceb5e8d
- `accounting/operations.log`: 2026-10-21T20:15:56.065164+00:00 ERROR run=da3ca7aa1b2f4953b309ff704ef883e8 workflow_finished workflowId=b3a2747feafe437180d3c7a9decb8ea4 status=failed
- `accounting/operations.log`: 2026-10-21T20:15:56.065461+00:00 ERROR run=da3ca7aa1b2f4953b309ff704ef883e8 run_finished workflowId=b3a2747feafe437180d3c7a9decb8ea4 status=failed

Not copied: 3 .csv, 364 .json, 1 .jsonl, 2 .lock, 80 .txt, 15 .wav

## layer1-fp-context

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrects-his-own/layer1-fp-context`


Error-like log lines (first 5 per log):

- `e3b-one-chunk-spoken-form.stderr.log`: Traceback (most recent call last):
- `e3b-one-chunk-spoken-form.stderr.log`: raise ValueError(code)
- `e3b-one-chunk-spoken-form.stderr.log`: ValueError: source_budget_identity_changed
- `e3b-one-chunk-spoken-form.stderr.log`: During handling of the above exception, another exception occurred:
- `e3b-one-chunk-spoken-form.stderr.log`: Traceback (most recent call last):
- `e4-execute-asr14-judge8.stderr.log`: Traceback (most recent call last):
- `e4-execute-asr14-judge8.stderr.log`: raise ValueError(code)
- `e4-execute-asr14-judge8.stderr.log`: ValueError: invalid_source_concurrency
- `e4b-execute-asr14-judge8.stderr.log`: Traceback (most recent call last):
- `e4b-execute-asr14-judge8.stderr.log`: raise self._exception
- `e4b-execute-asr14-judge8.stderr.log`: raise ValueError(code)
- `e4b-execute-asr14-judge8.stderr.log`: ValueError: source_budget_execution_binding_changed
- `e4c-execute-asr14-judge8.stderr.log`: Traceback (most recent call last):
- `e4c-execute-asr14-judge8.stderr.log`: raise self._exception
- `e4c-execute-asr14-judge8.stderr.log`: raise ValueError(f'Unknown L1 request outcome; reconcile original response before retry: {marker}')
- `e4c-execute-asr14-judge8.stderr.log`: ValueError: Unknown L1 request outcome; reconcile original response before retry: ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-sends-and-resurrec

Not copied: 20 .json
