# Run digest 20261019-es-post-d-window-audio-qc-paid

Generated 2026-10-19T20:55:22+00:00. Redacted copies only; source hashes are in manifest.json.

## aqc

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/es/aqc`

- summary `summary.json` es: **audio_waiver_issued**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.4 |
| es.secondary-asr | pass | 1.6 |
| es.audio-qc | pass | 0.2 |
| es.calibration.prefetch | pass | 3.4 |
| es.calibration | pass | 125.9 |
| es.audio-waiver | pass | 0.0 |

Error-like log lines (first 5 per log):

- `spark-driver.log`: W1019 20:44:20.348000 47 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `spark-driver.log`: W1019 20:44:20.363000 47 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `spark-driver.log`: [0;93m2026-10-19 20:44:20.841969513 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil

Not copied: 9 .json, 1 .lock, 1 .tsv

## l3

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/es/l3`


Error-like log lines (first 5 per log):

- `spark-es-r2-c/spark-output/screen-v1.log`: W1019 20:42:29.698000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `spark-es-r2-c/spark-output/screen-v1.log`: W1019 20:42:29.723000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `spark-output/render.log`: [0;93m2026-10-19 20:40:52.092250098 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:40:52.382212706 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:40:52.625994695 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:40:52.635659569 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/render.log`: [0;93m2026-10-19 20:40:53.045172166 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:41:58.754051+00:00 ERROR run=d14b0b15756b48ef9dbccde0e8d225ab stage_finished workflowId=ed6109281d6742c791b4cd74dbb95842 stage=layer3.track_assembly spanId=e560797ef3e24043927113b51e080c
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:41:58.757279+00:00 ERROR run=d14b0b15756b48ef9dbccde0e8d225ab stage_finished workflowId=ed6109281d6742c791b4cd74dbb95842 stage=layer3.assemble spanId=4cd5682b236e4f3c83976135d66e432f att
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:41:58.761211+00:00 ERROR run=d14b0b15756b48ef9dbccde0e8d225ab stage_finished workflowId=ed6109281d6742c791b4cd74dbb95842 stage=layer3_formal_render spanId=66276ab623974d45badba6e4ef0e76d
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:41:58.768043+00:00 ERROR run=d14b0b15756b48ef9dbccde0e8d225ab workflow_finished workflowId=ed6109281d6742c791b4cd74dbb95842 status=failed

Not copied: 3 .csv, 287 .json, 1 .jsonl, 2 .lock, 2 .mp3, 34 .sha256, 61 .wav

## failed-attempt-1-replica-unbound

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/post-d-window-qc-20261019/es/failed-attempt-1-replica-unbound`


Error-like log lines (first 5 per log):

- `spark-es-c/compact.log`: Traceback (most recent call last):
- `spark-es-c/compact.log`: raise ValueError(message)
- `spark-es-c/compact.log`: ValueError: Raw committed unit missing: 0
- `spark-output/render.log`: Traceback (most recent call last):
- `spark-output/render.log`: Traceback (most recent call last):
- `spark-output/render.log`: Traceback (most recent call last):
- `spark-output/render.log`: raise EOFError
- `spark-output/render.log`: EOFError
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:32:06.432291+00:00 ERROR run=9c01c9fcf3824fd9bb8977f16e2baa5e stage_finished workflowId=a6c7b2cffcfe4d1fb53083f1caaf6363 stage=layer3.model_load.es spanId=87ae9ecc98234c7da6022ade657d71b
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:32:06.437115+00:00 ERROR run=9c01c9fcf3824fd9bb8977f16e2baa5e stage_finished workflowId=a6c7b2cffcfe4d1fb53083f1caaf6363 stage=layer3.unit.es.0000 spanId=f74a5124e6ea4178a40ce7872d8809d2
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:32:06.446898+00:00 ERROR run=9c01c9fcf3824fd9bb8977f16e2baa5e stage_finished workflowId=a6c7b2cffcfe4d1fb53083f1caaf6363 stage=layer3.render_units spanId=c9ecc7f864a14dc184dd7f2de465845e
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:32:06.452019+00:00 ERROR run=9c01c9fcf3824fd9bb8977f16e2baa5e stage_finished workflowId=a6c7b2cffcfe4d1fb53083f1caaf6363 stage=layer3_formal_render spanId=22fe8a95ea584fe49307f02d2255f9c
- `spark-output/speech-job/accounting/operations.log`: 2026-10-19T20:32:06.461980+00:00 ERROR run=9c01c9fcf3824fd9bb8977f16e2baa5e workflow_finished workflowId=a6c7b2cffcfe4d1fb53083f1caaf6363 status=failed

Not copied: 3 .csv, 26 .json, 1 .jsonl, 2 .lock

## .api-budget

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g/plans/post-d-window-qc-20261019-es-zh/qc-es/.api-budget`

- source budget `source-budget.json`: 240 of 240 requests returned; reserved US$2.31; estimated US$0.30 over 220 priced; cost unknown: missing_or_invalid_token_counts ×20; invoice not verified

Not copied: 240 .json, 241 .lock
