# Run digest 20261014-clip-e2e-dev216-d

Generated 2026-10-14T17:02:01+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-dev216-20261014-d

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev216-20261014-d`

- outcome `textqc-es/state/asr-calls/primary/47bf9368c3b1236c4bed4797ca479bf17397ae9e032207a431444d155cc76460/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/7d1089071303f8aa1d4cb1df1e3b4f6d668fa7da85d9ee858de200e6df32e748/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/8d10b6859c924f86308bd5ed03dbfc96aee4c0efac2e43ebff178e3505e0c986/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/c40ee893d8d87d492a178bfe23af4b99a66b26b9ef4939437bbb8c41b196b017/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/1a98ffed2c349612de27873f81a9d63e27d7b2bf3aad08d8d7120a68d2949d30/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/32697e22b4d6069f0655788efa4379cb1938a743dfb293cba8e119486e7db807/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/70f3ea710dbdfe01d880c2e0a1d71b26115fd2d6b3592bcff68b8a742f9c4ba9/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/805117d3fc2a33c7d2c46ef571da4d729684e4f95487c88b56111b8df005e622/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/8119b1b9bc88bad8088a2ae3f1bfa406ad9712e3f3e8bf843e08d90e20292548/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/8d84b241e332876851788c347917332935ec2a2a1b9089acf1fb3a608da01078/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/b1e8e57ab105b948e43e7119b63077b942c68da06888754c67877bf07921c8af/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/ca54adcc8114d2cbc57db66aee9f87c80be25a97b8a6af04dd9fdf6785d94468/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/cc3dd69138ee811ce24b73d5680d1cc24459a61e124db2cd3248be650443258c/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/d4ee79706b13713b5d891bde004168a763b70803c40162aed7e28a32811d4405/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/fdae048c86452811cc601e1ecd172935d80577306a0c72077d328df1dbe806bd/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/es/summary.json` es: **audio_waiver_issued**
- summary `aqc/ko/summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `aqc/zh-Hans/summary.json` zh-Hans: **audio_waiver_issued**
- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-zh-Hans/out-r1/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.4 |
| es.secondary-asr | pass | 1.2 |
| es.audio-qc | pass | 0.2 |
| es.calibration.prefetch | pass | 3.2 |
| es.calibration | pass | 115.6 |
| es.audio-waiver | pass | 0.0 |

Timings `aqc/ko/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.4 |
| ko.secondary-asr | pass | 0.8 |
| ko.audio-qc | pass | 0.3 |

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.4 |
| zh-Hans.audio-qc | pass | 0.2 |
| zh-Hans.calibration.prefetch | pass | 3.1 |
| zh-Hans.calibration | pass | 141.9 |
| zh-Hans.audio-waiver | pass | 0.0 |

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 12.6 |
| es.text-qc | pass | 0.5 |
| es.calibration.prefetch | pass | 76.1 |
| es.calibration | pass | 4.1 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 17.4 |
| ko.text-qc | pass | 0.6 |
| ko.calibration.prefetch | pass | 97.3 |
| ko.calibration | pass | 4.2 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 16.8 |
| zh-Hans.text-qc | pass | 0.5 |

Timings `textqc-zh-Hans/out-r1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 8.8 |
| zh-Hans.text-qc | pass | 0.5 |
| zh-Hans.calibration.prefetch | pass | 90.8 |
| zh-Hans.calibration | pass | 3.4 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| inputs | pass | 7 |
|---|---|---|
| timeline-map | pass | 0 |
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 1 |
| layer2 | pass | 1 |
| plan-qc-ko | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | pass | 120 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 94 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 18 |
| plan-layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 0 |
| check-qc-zh-Hans-out-r1 | pass | 0 |
| text-qc.zh-Hans.out-r1 | pass | 104 |
| spark-begin-1 | pass | 3 |
| voice-auth.ko | pass | 0 |
| speech-job.ko | pass | 0 |
| check-gpu-ko | pass | 2 |
| render.ko | fail(1) | 92 |
| compact.ko | pass | 16 |
| screen.ko | pass | 40 |
| package.ko | pass | 3 |
| audio-qc.ko | fail(1) | 23 |
| voice-auth.es | pass | 0 |
| speech-job.es | pass | 0 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 87 |
| compact.es | pass | 17 |
| screen.es | pass | 38 |
| package.es | pass | 3 |
| audio-qc.es | pass | 131 |
| voice-auth.zh-Hans | pass | 0 |
| speech-job.zh-Hans | pass | 0 |
| check-gpu-zh-Hans | pass | 2 |
| render.zh-Hans | fail(1) | 88 |
| compact.zh-Hans | pass | 17 |
| screen.zh-Hans | pass | 38 |
| package.zh-Hans | pass | 3 |
| audio-qc.zh-Hans | pass | 157 |
| spark-finish | pass | 7 |

Failed stages: `text-qc.zh-Hans.out`, `render.ko`, `audio-qc.ko`, `render.es`, `render.zh-Hans`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 240 of 240 requests returned; reserved US$2.31; estimated US$0.30 over 220 priced; cost unknown: missing_or_invalid_token_counts ×20; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 216 of 216 requests returned; reserved US$2.32; estimated US$0.36 over 215 priced; cost unknown: missing_or_invalid_token_counts ×1; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 239 of 239 requests returned; reserved US$2.42; estimated US$0.38 over 213 priced; cost unknown: missing_or_invalid_token_counts ×26; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: W1014 16:55:20.088000 50 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/es/spark-driver.log`: W1014 16:55:20.103000 50 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/es/spark-driver.log`: [0;93m2026-10-14 16:55:20.555723991 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/ko/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `aqc/zh-Hans/spark-driver.log`: W1014 16:59:58.571000 51 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/zh-Hans/spark-driver.log`: W1014 16:59:58.588000 51 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/zh-Hans/spark-driver.log`: [0;93m2026-10-14 16:59:59.017151065 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 16:53:48.956000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 16:53:48.968000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:52:15.902740518 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:52:15.911604897 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:52:16.369352876 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:52:16.739027116 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:52:16.741721177 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:53:22.002822+00:00 ERROR run=2b93ac95b1404774a61cc22988dafe15 stage_finished workflowId=1efcec486417455abaf8a3ea0ea3dc99 stage=layer3.track_assembly spanId=6284ae88245f47308490ee133fe320
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:53:22.006250+00:00 ERROR run=2b93ac95b1404774a61cc22988dafe15 stage_finished workflowId=1efcec486417455abaf8a3ea0ea3dc99 stage=layer3.assemble spanId=b97f59e3f57e408da5f93c5d307cc7a0 att
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:53:22.010303+00:00 ERROR run=2b93ac95b1404774a61cc22988dafe15 stage_finished workflowId=1efcec486417455abaf8a3ea0ea3dc99 stage=layer3_formal_render spanId=f6bb4e76ab63478980dbf3ea5a6f715
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:53:22.017792+00:00 ERROR run=2b93ac95b1404774a61cc22988dafe15 workflow_finished workflowId=1efcec486417455abaf8a3ea0ea3dc99 status=failed
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 16:50:56.061000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 16:50:56.075000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:49:23.077407449 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:49:23.080893115 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:49:23.343655079 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:49:23.900612191 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:49:23.938166062 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:50:29.024746+00:00 ERROR run=a56d83fd79544cef930431382ffd2b67 stage_finished workflowId=51d0d97543a141b7b9ce9d9b59596306 stage=layer3.track_assembly spanId=48e051ee0b534a72ba5b5d452bb7b7
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:50:29.029202+00:00 ERROR run=a56d83fd79544cef930431382ffd2b67 stage_finished workflowId=51d0d97543a141b7b9ce9d9b59596306 stage=layer3.assemble spanId=af83476e8c2f4c41a284fd88f877b0d7 att
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:50:29.032743+00:00 ERROR run=a56d83fd79544cef930431382ffd2b67 stage_finished workflowId=51d0d97543a141b7b9ce9d9b59596306 stage=layer3_formal_render spanId=7863f33e480342b08f19225ea095fcf
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:50:29.040831+00:00 ERROR run=a56d83fd79544cef930431382ffd2b67 workflow_finished workflowId=51d0d97543a141b7b9ce9d9b59596306 status=failed
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:56:55.214676948 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:56:55.234826368 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:56:55.644065284 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:56:56.031993030 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:56:56.067237383 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:58:02.251412+00:00 ERROR run=c78016dd10b4483190feb63d4b1654a0 stage_finished workflowId=332e25de0aee431cb4cda6dbb260cf22 stage=layer3.track_assembly spanId=f341fe7f5adf4b5c9e09bc3fbfa41d
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:58:02.254820+00:00 ERROR run=c78016dd10b4483190feb63d4b1654a0 stage_finished workflowId=332e25de0aee431cb4cda6dbb260cf22 stage=layer3.assemble spanId=86df9f3de1c14932aa800566122f2bf7 att
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:58:02.258993+00:00 ERROR run=c78016dd10b4483190feb63d4b1654a0 stage_finished workflowId=332e25de0aee431cb4cda6dbb260cf22 stage=layer3_formal_render spanId=a574050da33e48b4b16333dc7fa1dab
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:58:02.266767+00:00 ERROR run=c78016dd10b4483190feb63d4b1654a0 workflow_finished workflowId=332e25de0aee431cb4cda6dbb260cf22 status=failed
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 16:58:29.139000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 16:58:29.151000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `logs/check-gpu-es.log`: "failed": [],
- `logs/check-gpu-ko.log`: "failed": [],
- `logs/check-gpu-zh-Hans.log`: "failed": [],
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out-r1.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/text-qc.zh-Hans.out.log`: "reason": "text QC failed; repair the failed groups in a new candidate revision",

Not copied: 21 .csv, 2436 .json, 7 .jsonl, 756 .lock, 6 .mp3, 120 .sha256, 209 .wav
