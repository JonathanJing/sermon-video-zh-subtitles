# Run digest 20261012-clip-ko-layer3-audio-qc

Generated 2026-10-12T20:43:48+00:00. Redacted copies only; source hashes are in manifest.json.

## l3d

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-test-20261012/l3d`


Error-like log lines (first 5 per log):

- `ko/spark-ko-c-d/spark-output/screen-v1.log`: W1012 20:40:14.980000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `ko/spark-ko-c-d/spark-output/screen-v1.log`: W1012 20:40:14.993000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `ko/spark-output/render.log`: [0;93m2026-10-12 20:38:42.656765215 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 20:38:42.852120179 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 20:38:43.191484466 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 20:38:43.546850719 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 20:38:43.555805371 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T20:39:48.298857+00:00 ERROR run=c2bf0dd5acfe4413b863b0e221586338 stage_finished workflowId=4a4a5926b0b14626b0cced987fee1e2a stage=layer3.track_assembly spanId=18943d309332492e8ce798d4a2e612
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T20:39:48.302602+00:00 ERROR run=c2bf0dd5acfe4413b863b0e221586338 stage_finished workflowId=4a4a5926b0b14626b0cced987fee1e2a stage=layer3.assemble spanId=5aa403526f6946a28032d7a156aa7894 att
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T20:39:48.305657+00:00 ERROR run=c2bf0dd5acfe4413b863b0e221586338 stage_finished workflowId=4a4a5926b0b14626b0cced987fee1e2a stage=layer3_formal_render spanId=cf07033c85494d2697db9d385658473
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T20:39:48.312540+00:00 ERROR run=c2bf0dd5acfe4413b863b0e221586338 workflow_finished workflowId=4a4a5926b0b14626b0cced987fee1e2a status=failed

Not copied: 3 .csv, 314 .json, 1 .jsonl, 2 .lock, 2 .mp3, 40 .sha256, 65 .wav

## aqc-out2

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-test-20261012/aqc-out2`

- summary `summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.4 |
| ko.secondary-asr | pass | 1.5 |
| ko.audio-qc | pass | 0.3 |

Error-like log lines (first 5 per log):

- `spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",

Not copied: 5 .json, 1 .lock

## aqc-run

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-test-20261012/aqc-run`


Not copied: 8 .json
