# Run digest 20261014-clip-e2e-dev101-audio-gates

Generated 2026-10-14T16:33:09+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-dev101-20261014-b

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev101-20261014-b`

- outcome `textqc-ko/state/asr-calls/primary/1a3f07e599320e1deabfc073e161636fcade850717ff06e64434dadf22feb8d1/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/2ea62c57027e4514f18ec9ded92f5c0d9f81c08e0108e45a5ab751ffdb0cd89e/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/6f4b8b3cdf4e2214bc0d77dc299cfd81fac6e0b063931e3dcb8e7e530f37ec41/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/7b1184774b6477b2f4dab1875916c0e9d655ae23935a2788cd79bc6313c0cba6/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/e2f3219e8e68f12d00a1661c777d5103e66162c6580cf1b6781801de3db44487/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/f706b98068c097b88e2d82b55050f9232a5d978f72a337c446e5f6b7699a07eb/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/041c622d78f2bf15fc2d09c708732255210b5ae8d3e7462b723c6579cc45f3e7/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/897f757545ab694a09935a234f55971003adb7e5007a68d6e9ae7224642d2424/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/8983126a123c058a5df993d3e0a67235b168fb84cdde08253949cb98aabf44d9/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/8fd27d689e163fb7c878cd066754955cd937f3ac3a5427e43cad4507a0e3262d/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/aa2d8225c1a5eb1cf025aef8fe42d22d4b215ee0527f3aa56c55a1bf65492ad4/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/bd45422610e84261399a1da4f3f0d3f0dfc5bb8cf355e4a441fc0841b9ccdb4b/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/cb46b0628125a4ec79465f68f15b67b2041ea23abbc150e1679dd6e7bc95adc7/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/cd1ad9eb1e8318bbc80a93396c8691f1c3d86055bf2d74cc8aa1cfadc9edb532/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/ko/summary.json` ko: **waiver_refused** (Calibration does not allow a waiver: seeded-error detection below minimum for ['audio.dropped_key_word'])
- summary `aqc/zh-Hans/summary.json` zh-Hans: **waiver_refused** (Calibration does not allow a waiver: seeded-error detection below minimum for ['audio.dropped_key_word'])
- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/ko/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.3 |
| ko.audio-qc | pass | 0.3 |
| ko.calibration.prefetch | pass | 3.3 |
| ko.calibration | pass | 159.4 |
| ko.audio-waiver | fail | 0.0 |

Failed stages: `ko.audio-waiver`

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.3 |
| zh-Hans.audio-qc | pass | 0.2 |
| zh-Hans.calibration.prefetch | pass | 3.2 |
| zh-Hans.calibration | pass | 148.0 |
| zh-Hans.audio-waiver | fail | 0.0 |

Failed stages: `zh-Hans.audio-waiver`

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 13.6 |
| es.text-qc | pass | 0.6 |
| es.calibration.prefetch | pass | 83.5 |
| es.calibration | pass | 4.5 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 18.3 |
| ko.text-qc | pass | 0.6 |
| ko.calibration.prefetch | pass | 103.6 |
| ko.calibration | pass | 4.3 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 19.6 |
| zh-Hans.text-qc | pass | 0.6 |
| zh-Hans.calibration.prefetch | pass | 108.3 |
| zh-Hans.calibration | pass | 4.2 |
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
| text-qc.ko.out | pass | 127 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 103 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | pass | 133 |
| spark-begin-1 | pass | 5 |
| voice-auth.ko | pass | 0 |
| speech-job.ko | pass | 0 |
| check-gpu-ko | pass | 2 |
| render.ko | fail(1) | 94 |
| compact.ko | pass | 17 |
| screen.ko | pass | 40 |
| package.ko | pass | 4 |
| spark-finish | pass | 7 |
| spark-begin-1 | pass | 3 |
| check-gpu-ko | pass | 2 |
| audio-qc.ko | fail(1) | 188 |
| voice-auth.es | pass | 0 |
| speech-job.es | pass | 0 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 89 |
| compact.es | fail(1) | 15 |
| voice-auth.zh-Hans | pass | 0 |
| speech-job.zh-Hans | pass | 0 |
| check-gpu-zh-Hans | pass | 2 |
| render.zh-Hans | fail(1) | 87 |
| compact.zh-Hans | pass | 17 |
| screen.zh-Hans | pass | 38 |
| package.zh-Hans | pass | 4 |
| audio-qc.zh-Hans | fail(1) | 163 |
| spark-finish | pass | 6 |

Failed stages: `render.ko`, `audio-qc.ko`, `render.es`, `compact.es`, `render.zh-Hans`, `audio-qc.zh-Hans`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 223 of 223 requests returned; reserved US$2.27; estimated US$0.32 over 223 priced; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 237 of 237 requests returned; reserved US$2.44; estimated US$0.38 over 216 priced; cost unknown: missing_or_invalid_token_counts ×21; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 240 of 240 requests returned; reserved US$2.46; estimated US$0.39 over 216 priced; cost unknown: missing_or_invalid_token_counts ×24; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/ko/spark-driver.log`: W1014 16:18:44.918000 50 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/ko/spark-driver.log`: W1014 16:18:44.933000 50 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/ko/spark-driver.log`: [0;93m2026-10-14 16:18:45.349033170 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/ko/spark-driver.log`: ko.audio-waiver	fail	0.0
- `aqc/ko/spark-driver.log`: "status": "waiver_refused",
- `aqc/zh-Hans/spark-driver.log`: W1014 16:25:43.980000 51 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/zh-Hans/spark-driver.log`: W1014 16:25:43.997000 51 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/zh-Hans/spark-driver.log`: [0;93m2026-10-14 16:25:44.423537790 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/zh-Hans/spark-driver.log`: zh-Hans.audio-waiver	fail	0.0
- `aqc/zh-Hans/spark-driver.log`: "status": "waiver_refused",
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-es-c/compact.log`: Traceback (most recent call last):
- `l3/es/spark-es-c/compact.log`: raise ValueError(f"Measured target audio exceeds 1x clip schedule: {plan['issues'][0]}")
- `l3/es/spark-es-c/compact.log`: ValueError: Measured target audio exceeds 1x clip schedule: {'unitIndex': 15, 'textGroupId': 'translation-chunk-0002-u032', 'plannedEnd': 76.739999, 'sourceEnd': 67.040008, 'clipDuration': 75.04, 'max
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:20:52.510084515 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:20:52.572209269 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:20:52.896295438 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:20:53.164714235 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 16:20:53.361789430 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:22:01.580512+00:00 ERROR run=72080b47ab944548bb7de5de6340d3c1 stage_finished workflowId=f588a25df5074486b8d9c3fd932e679a stage=layer3.schedule_rejection spanId=13a586c5d2614a60aeccbd5733
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:22:01.584485+00:00 ERROR run=72080b47ab944548bb7de5de6340d3c1 stage_finished workflowId=f588a25df5074486b8d9c3fd932e679a stage=layer3.assemble spanId=70e53d4b941f41abb0e61411cb6a6f4e att
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:22:01.588075+00:00 ERROR run=72080b47ab944548bb7de5de6340d3c1 stage_finished workflowId=f588a25df5074486b8d9c3fd932e679a stage=layer3_formal_render spanId=7513b141346d45259be7c8917c90760
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:22:01.597393+00:00 ERROR run=72080b47ab944548bb7de5de6340d3c1 workflow_finished workflowId=f588a25df5074486b8d9c3fd932e679a status=failed
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 16:16:19.014000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 16:16:19.026000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:14:43.911700354 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:14:43.983327146 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:14:44.401143546 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:14:44.608902671 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 16:14:44.758055570 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:15:51.946048+00:00 ERROR run=ed2c622e41dc4bcebe476fc53a2d5d29 stage_finished workflowId=8c08ee03399b4158b6d0c91f44c0fef8 stage=layer3.schedule_rejection spanId=407371508aed4058a12bd0ed74
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:15:51.949301+00:00 ERROR run=ed2c622e41dc4bcebe476fc53a2d5d29 stage_finished workflowId=8c08ee03399b4158b6d0c91f44c0fef8 stage=layer3.assemble spanId=85086fea30b84a07ad77979b13e9d55b att
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:15:51.953758+00:00 ERROR run=ed2c622e41dc4bcebe476fc53a2d5d29 stage_finished workflowId=8c08ee03399b4158b6d0c91f44c0fef8 stage=layer3_formal_render spanId=a5411748f492466cbab2b945f4cc908
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:15:51.962816+00:00 ERROR run=ed2c622e41dc4bcebe476fc53a2d5d29 workflow_finished workflowId=8c08ee03399b4158b6d0c91f44c0fef8 status=failed
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:22:39.724025084 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:22:39.913018967 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:22:40.063812719 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:22:40.282889027 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 16:22:40.610818382 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:23:46.074344+00:00 ERROR run=b31ae48f8a664495abac927c64b918a0 stage_finished workflowId=33768c4fa474410db21d24db8e5fbe0c stage=layer3.schedule_rejection spanId=f193d436214e453d9d4d412983
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:23:46.079027+00:00 ERROR run=b31ae48f8a664495abac927c64b918a0 stage_finished workflowId=33768c4fa474410db21d24db8e5fbe0c stage=layer3.assemble spanId=ad9ed480f07e4b088c0c8b350fd6ef02 att
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:23:46.083955+00:00 ERROR run=b31ae48f8a664495abac927c64b918a0 stage_finished workflowId=33768c4fa474410db21d24db8e5fbe0c stage=layer3_formal_render spanId=352f2b7eb9e24b969eddc4d8dca4c7a
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T16:23:46.094275+00:00 ERROR run=b31ae48f8a664495abac927c64b918a0 workflow_finished workflowId=33768c4fa474410db21d24db8e5fbe0c status=failed
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 16:24:12.852000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 16:24:12.865000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `logs/check-gpu-es.log`: "failed": [],
- `logs/check-gpu-ko.log`: "failed": [],
- `logs/check-gpu-ko.log`: "failed": [],
- `logs/check-gpu-zh-Hans.log`: "failed": [],
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],

Not copied: 18 .csv, 2362 .json, 6 .jsonl, 754 .lock, 4 .mp3, 140 .sha256, 201 .wav
