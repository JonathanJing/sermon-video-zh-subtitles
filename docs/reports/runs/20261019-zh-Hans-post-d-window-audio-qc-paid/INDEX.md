# Run digest 20261019-zh-Hans-post-d-window-audio-qc-paid

Generated 2026-10-19T20:55:23+00:00. Redacted copies only; source hashes are in manifest.json.

## aqc

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/zh-Hans/aqc`

- summary `summary.json` zh-Hans: **waiver_refused** (Calibration does not allow a waiver: seeded-error detection below minimum for ['audio.dropped_key_word'])

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.4 |
| zh-Hans.secondary-asr | pass | 0.4 |
| zh-Hans.audio-qc | pass | 0.2 |
| zh-Hans.calibration.prefetch | pass | 3.2 |
| zh-Hans.calibration | pass | 134.6 |
| zh-Hans.audio-waiver | fail | 0.0 |

Failed stages: `zh-Hans.audio-waiver`

Error-like log lines (first 5 per log):

- `spark-driver.log`: W1019 20:49:39.035000 49 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `spark-driver.log`: W1019 20:49:39.047000 49 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `spark-driver.log`: [0;93m2026-10-19 20:49:39.483715169 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-driver.log`: zh-Hans.audio-waiver	fail	0.0
- `spark-driver.log`: "status": "waiver_refused",

Not copied: 7 .json, 1 .lock, 1 .tsv

## l3

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/zh-Hans/l3`


Error-like log lines (first 5 per log):

- `spark-output/render.log`: [0;93m2026-10-19 20:46:27.118030487 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:46:27.191822526 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:46:27.283580651 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:46:27.491968541 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:46:27.852271559 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:47:34.341080+00:00 ERROR run=f2e036292aa5432b93cde0237d4f6ad6 stage_finished workflowId=866256f3cc5b4a909687eda18fa29714 stage=layer3.track_assembly spanId=496640cc773c43aeb7e1e8334a1023
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:47:34.345429+00:00 ERROR run=f2e036292aa5432b93cde0237d4f6ad6 stage_finished workflowId=866256f3cc5b4a909687eda18fa29714 stage=layer3.assemble spanId=e0921d5028c046f4b2679f63cb117555 att
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:47:34.349140+00:00 ERROR run=f2e036292aa5432b93cde0237d4f6ad6 stage_finished workflowId=866256f3cc5b4a909687eda18fa29714 stage=layer3_formal_render spanId=81431da8a9844b529521ccbeb3428d8
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:47:34.356481+00:00 ERROR run=f2e036292aa5432b93cde0237d4f6ad6 workflow_finished workflowId=866256f3cc5b4a909687eda18fa29714 status=failed
- `spark-zh-Hans-c/spark-output/screen-v1.log`: W1019 20:48:03.801000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `spark-zh-Hans-c/spark-output/screen-v1.log`: W1019 20:48:03.814000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(

Not copied: 3 .csv, 275 .json, 1 .jsonl, 2 .lock, 2 .mp3, 32 .sha256, 59 .wav

## .api-budget

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/plans/post-d-window-qc-20261019-es-zh/qc-zh-Hans/.api-budget`

- source budget `source-budget.json`: 236 of 236 requests returned; reserved US$2.40; estimated US$0.36 over 212 priced; cost unknown: missing_or_invalid_token_counts ×24; invoice not verified

Not copied: 236 .json, 237 .lock
