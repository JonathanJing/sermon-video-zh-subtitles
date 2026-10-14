# Run digest 20261012-clip-ko-sino-chapter-rerun

Generated 2026-10-12T22:03:32+00:00. Redacted copies only; source hashes are in manifest.json.

## l3e

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-test-20261012/l3e`


Error-like log lines (first 5 per log):

- `ko/spark-ko-c-e/spark-output/screen-v1.log`: W1012 21:58:58.087000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `ko/spark-ko-c-e/spark-output/screen-v1.log`: W1012 21:58:58.100000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `ko/spark-output/render.log`: [0;93m2026-10-12 21:57:25.606257227 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 21:57:25.703056142 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 21:57:26.216286620 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 21:57:26.428640042 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/render.log`: [0;93m2026-10-12 21:57:26.435363188 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `ko/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T21:58:31.952644+00:00 ERROR run=86aa8e9f3a554d7b8eceb704f8773e3f stage_finished workflowId=fdd842cbef0d4ca1b8abc13a3d064704 stage=layer3.track_assembly spanId=adc64335cfea4097acc1a14b671753
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T21:58:31.957037+00:00 ERROR run=86aa8e9f3a554d7b8eceb704f8773e3f stage_finished workflowId=fdd842cbef0d4ca1b8abc13a3d064704 stage=layer3.assemble spanId=780d964c59b241fe98c403feae9ff384 att
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T21:58:31.960707+00:00 ERROR run=86aa8e9f3a554d7b8eceb704f8773e3f stage_finished workflowId=fdd842cbef0d4ca1b8abc13a3d064704 stage=layer3_formal_render spanId=b0a590a51a2f4837a65dddc90502cb0
- `ko/spark-output/speech-job/accounting/operations.log`: 2026-10-12T21:58:31.968883+00:00 ERROR run=86aa8e9f3a554d7b8eceb704f8773e3f workflow_finished workflowId=fdd842cbef0d4ca1b8abc13a3d064704 status=failed

Not copied: 3 .csv, 312 .json, 1 .jsonl, 2 .lock, 2 .mp3, 40 .sha256, 65 .wav

## aqc-out3

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-test-20261012/aqc-out3`

- summary `summary.json` ko: **audio_waiver_issued**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.3 |
| ko.secondary-asr | pass | 0.0 |
| ko.audio-qc | pass | 0.3 |
| ko.calibration.prefetch | pass | 0.8 |
| ko.calibration | pass | 133.8 |
| ko.audio-waiver | pass | 0.1 |

Error-like log lines (first 5 per log):

- `spark-driver.log`: W1012 22:01:44.628000 51 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `spark-driver.log`: W1012 22:01:44.640000 51 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `spark-driver.log`: [0;93m2026-10-12 22:01:45.064164480 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil

Not copied: 9 .json, 1 .lock

## aqc-run2

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-test-20261012/aqc-run2`


Not copied: 8 .json
