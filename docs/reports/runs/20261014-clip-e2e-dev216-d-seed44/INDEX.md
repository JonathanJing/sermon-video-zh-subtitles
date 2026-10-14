# Run digest 20261014-clip-e2e-dev216-d-seed44

Generated 2026-10-14T17:19:26+00:00. Redacted copies only; source hashes are in manifest.json.

## ko-seed-44

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev216-20261014-d/aqc/ko-seed-44`

- summary `summary.json` ko: **audio_waiver_issued**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.4 |
| ko.secondary-asr | pass | 0.8 |
| ko.audio-qc | pass | 0.3 |
| ko.calibration.prefetch | pass | 207.4 |
| ko.calibration | pass | 141.3 |
| ko.audio-waiver | pass | 0.2 |

Error-like log lines (first 5 per log):

- `spark-driver.log`: W1014 17:17:30.877000 50 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `spark-driver.log`: W1014 17:17:30.894000 50 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `spark-driver.log`: [0;93m2026-10-14 17:17:31.308809252 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil

Not copied: 9 .json, 1 .lock

## ko-repair-seed-44

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev216-20261014-d/l3/ko-repair-seed-44`


Error-like log lines (first 5 per log):

- `spark-ko-seed-44-c/spark-output/screen-v1.log`: W1014 17:12:15.266000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `spark-ko-seed-44-c/spark-output/screen-v1.log`: W1014 17:12:15.278000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `spark-output/render.log`: [0;93m2026-10-14 17:10:40.113152674 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-14 17:10:40.156759837 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-14 17:10:40.412232613 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-14 17:10:40.775111243 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-14 17:10:40.966075279 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `spark-output/speech-job/accounting/operations.log`: 2026-10-14T17:11:47.565313+00:00 ERROR run=d7e06b73f0414c0dae812a2ff8d663cc stage_finished workflowId=6485272c0cbf443fbbb46b53d2323c7b stage=layer3.track_assembly spanId=06f0bf5fc43f4f788aa29422e76fb3
- `spark-output/speech-job/accounting/operations.log`: 2026-10-14T17:11:47.569297+00:00 ERROR run=d7e06b73f0414c0dae812a2ff8d663cc stage_finished workflowId=6485272c0cbf443fbbb46b53d2323c7b stage=layer3.assemble spanId=c598382b16e24197a5e5b89d1deab919 att
- `spark-output/speech-job/accounting/operations.log`: 2026-10-14T17:11:47.572655+00:00 ERROR run=d7e06b73f0414c0dae812a2ff8d663cc stage_finished workflowId=6485272c0cbf443fbbb46b53d2323c7b stage=layer3_formal_render spanId=90ab9a7a513a48269b5bbdd0c7aaaeb
- `spark-output/speech-job/accounting/operations.log`: 2026-10-14T17:11:47.580134+00:00 ERROR run=d7e06b73f0414c0dae812a2ff8d663cc workflow_finished workflowId=6485272c0cbf443fbbb46b53d2323c7b status=failed

Not copied: 3 .csv, 311 .json, 1 .jsonl, 2 .lock, 2 .mp3, 40 .sha256, 65 .wav
