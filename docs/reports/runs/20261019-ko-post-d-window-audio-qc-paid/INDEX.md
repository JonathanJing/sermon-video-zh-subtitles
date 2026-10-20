# Run digest 20261019-ko-post-d-window-audio-qc-paid

Generated 2026-10-19T20:55:24+00:00. Redacted copies only; source hashes are in manifest.json.

## aqc

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/ko/aqc`

- summary `summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.4 |
| ko.secondary-asr | pass | 1.0 |
| ko.audio-qc | pass | 0.3 |

Error-like log lines (first 5 per log):

- `spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",

Not copied: 5 .json, 1 .lock, 1 .tsv

## l3

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/ko/l3`


Error-like log lines (first 5 per log):

- `spark-ko-c/spark-output/screen-v1.log`: W1019 20:53:35.250000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `spark-ko-c/spark-output/screen-v1.log`: W1019 20:53:35.263000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `spark-output/render.log`: [0;93m2026-10-19 20:52:00.780770935 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:52:00.933241169 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:52:01.020426517 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:52:01.192299121 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:52:01.519283218 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:53:07.492221+00:00 ERROR run=7e3dfd6c81b046f68976e200c3152e99 stage_finished workflowId=4b5db8a82da24e47b0d40a8b3223f555 stage=layer3.track_assembly spanId=6a980baceb8741cb97cb472126ce19
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:53:07.496236+00:00 ERROR run=7e3dfd6c81b046f68976e200c3152e99 stage_finished workflowId=4b5db8a82da24e47b0d40a8b3223f555 stage=layer3.assemble spanId=6fc14afc45d6475986b3b21f506ff3fb att
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:53:07.500424+00:00 ERROR run=7e3dfd6c81b046f68976e200c3152e99 stage_finished workflowId=4b5db8a82da24e47b0d40a8b3223f555 stage=layer3_formal_render spanId=74872b1c3e5a46f397bad74c0e5e2ba
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:53:07.510158+00:00 ERROR run=7e3dfd6c81b046f68976e200c3152e99 workflow_finished workflowId=4b5db8a82da24e47b0d40a8b3223f555 status=failed

Not copied: 3 .csv, 311 .json, 1 .jsonl, 2 .lock, 2 .mp3, 40 .sha256, 65 .wav

## .api-budget

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/plans/post-d-window-qc-20261019-ko-audio-r2/qc-ko/.api-budget`

- source budget `source-budget.json`: 1 of 1 requests returned; reserved US$0.00; cost unknown: missing_or_invalid_token_counts ×1; invoice not verified

Not copied: 1 .json, 2 .lock
