# Run digest 20261014-clip-e2e-opus216-20261014-g

Generated 2026-10-14T19:37:22+00:00. Redacted copies only; source hashes are in manifest.json.

## opus-e2e-dev216-20261014-g

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-g`

- outcome `textqc-es/state/asr-calls/primary/47bf9368c3b1236c4bed4797ca479bf17397ae9e032207a431444d155cc76460/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/5cd4afa5aeac693635b97b9b7cb0b73d9b7e6a5894459f6d417525c0a755904b/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/7d1089071303f8aa1d4cb1df1e3b4f6d668fa7da85d9ee858de200e6df32e748/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/8d10b6859c924f86308bd5ed03dbfc96aee4c0efac2e43ebff178e3505e0c986/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/50a3ed45faaa8e331805a0c74f2efd657e42096686c8650145e8a797c152c56c/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/6b6876e0ac7b8c245b57a07fd6ba7ce195bfde7ee993145c1a7517620932d6da/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/bb0e827f6f62387de90422d9898a882527f801be47918a32808bd322fc9fc5ca/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/fcba8028a14c1b6b1370926995d6749e53c9ea2ece7129eb8e0378b89b991fd0/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-ko/state/asr-calls/primary/feacdc80d9ae4cbd509d80031f84c945a068798e9b529106a53e8ba70524998a/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/03740b639a46b354b95cd2420a41f21a0ae0a40babc55b839c0157e2cb4e9dff/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/6a9c5097ce5547cd679f9256d490c7f63ddcac48e95ac75e9511e9f971db7a1f/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/ca99bddd119e3bfaa5ff8f40557133725813d53325f5d7455cb376b33cf02cf4/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/dd1f177d83ff16eb9e90422bc36376f5dc87f1864a124effa0ba4d965e0c68b1/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/df5fa3551373b6c25c2f7891086937f38d070e240257a8309f95075f09680277/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/fdae048c86452811cc601e1ecd172935d80577306a0c72077d328df1dbe806bd/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/es/summary.json` es: **audio_waiver_issued**
- summary `aqc/ko/summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `aqc/ko-seed-44/summary.json` ko: **audio_waiver_issued**
- summary `aqc/zh-Hans/summary.json` zh-Hans: **audio_waiver_issued**
- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.4 |
| es.secondary-asr | pass | 0.4 |
| es.audio-qc | pass | 0.2 |
| es.calibration.prefetch | pass | 3.3 |
| es.calibration | pass | 118.4 |
| es.audio-waiver | pass | 0.0 |

Timings `aqc/ko/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.4 |
| ko.secondary-asr | pass | 1.4 |
| ko.audio-qc | pass | 0.3 |

Timings `aqc/ko-seed-44/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.3 |
| ko.audio-qc | pass | 0.3 |
| ko.calibration.prefetch | pass | 208.5 |
| ko.calibration | pass | 139.0 |
| ko.audio-waiver | pass | 0.2 |

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.4 |
| zh-Hans.secondary-asr | pass | 0.4 |
| zh-Hans.audio-qc | pass | 0.2 |
| zh-Hans.calibration.prefetch | pass | 3.0 |
| zh-Hans.calibration | pass | 118.5 |
| zh-Hans.audio-waiver | pass | 0.0 |

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 20.0 |
| es.text-qc | pass | 0.5 |
| es.calibration.prefetch | pass | 90.4 |
| es.calibration | pass | 5.2 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 19.9 |
| ko.text-qc | pass | 0.5 |
| ko.calibration.prefetch | pass | 109.7 |
| ko.calibration | pass | 3.7 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 17.9 |
| zh-Hans.text-qc | pass | 0.5 |
| zh-Hans.calibration.prefetch | pass | 98.7 |
| zh-Hans.calibration | pass | 3.6 |
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
| text-qc.ko.out | pass | 134 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 116 |
| plan-qc-zh-Hans | pass | 1 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | pass | 121 |
| spark-begin-1 | pass | 4 |
| voice-auth.ko | pass | 0 |
| speech-job.ko | pass | 0 |
| check-gpu-ko | pass | 3 |
| render.ko | fail(1) | 101 |
| compact.ko | pass | 18 |
| screen.ko | pass | 38 |
| package.ko | pass | 3 |
| audio-qc.ko | fail(1) | 23 |
| voice-auth.es | pass | 0 |
| speech-job.es | pass | 0 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 88 |
| compact.es | pass | 17 |
| screen.es | pass | 36 |
| package.es | pass | 3 |
| audio-qc.es | pass | 134 |
| voice-auth.zh-Hans | pass | 0 |
| speech-job.zh-Hans | pass | 0 |
| check-gpu-zh-Hans | pass | 2 |
| render.zh-Hans | fail(1) | 88 |
| compact.zh-Hans | pass | 17 |
| screen.zh-Hans | pass | 39 |
| package.zh-Hans | pass | 3 |
| audio-qc.zh-Hans | pass | 133 |
| spark-finish | pass | 7 |
| plan-qc-ko-audio-seed-44 | pass | 0 |
| spark-begin-1 | pass | 3 |
| check-gpu-ko-seed-44 | pass | 2 |
| render.ko.seed-44 | fail(1) | 86 |
| compact.ko.seed-44 | pass | 17 |
| screen.ko.seed-44 | pass | 41 |
| package.ko.seed-44 | pass | 3 |
| audio-qc.ko.seed-44 | pass | 373 |
| spark-finish | pass | 7 |
| layer4-baseline | pass | 12 |
| layer4-publish | pass | 184 |
| layer4-smoke | pass | 54 |

Failed stages: `render.ko`, `audio-qc.ko`, `render.es`, `render.zh-Hans`, `render.ko.seed-44`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 239 of 239 requests returned; reserved US$2.30; estimated US$0.30 over 219 priced; cost unknown: missing_or_invalid_token_counts ×20; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 217 of 217 requests returned; reserved US$2.34; estimated US$0.37 over 216 priced; cost unknown: missing_or_invalid_token_counts ×1; invoice not verified
- source budget `plans/qc-ko-audio-seed-44/qc-ko/.api-budget/source-budget.json`: 237 of 237 requests returned; reserved US$2.43; estimated US$0.37 over 216 priced; cost unknown: missing_or_invalid_token_counts ×21; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 234 of 234 requests returned; reserved US$2.39; estimated US$0.36 over 212 priced; cost unknown: missing_or_invalid_token_counts ×22; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: W1014 19:17:41.361000 48 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/es/spark-driver.log`: W1014 19:17:41.378000 48 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/es/spark-driver.log`: [0;93m2026-10-14 19:17:41.797587033 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/ko/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `aqc/ko-seed-44/spark-driver.log`: W1014 19:31:28.007000 49 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/ko-seed-44/spark-driver.log`: W1014 19:31:28.023000 49 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/ko-seed-44/spark-driver.log`: [0;93m2026-10-14 19:31:28.468188019 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/zh-Hans/spark-driver.log`: W1014 19:22:17.627000 53 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/zh-Hans/spark-driver.log`: W1014 19:22:17.642000 53 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/zh-Hans/spark-driver.log`: [0;93m2026-10-14 19:22:18.067814868 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 19:16:09.792000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 19:16:09.804000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 19:14:35.867978598 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 19:14:35.872548013 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 19:14:36.041526565 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 19:14:36.364700060 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 19:14:36.395456770 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:15:43.233750+00:00 ERROR run=a6fa25944eae4395bfddc74f9196d1c4 stage_finished workflowId=34e96c2b98c8471db55dee075a1b5941 stage=layer3.track_assembly spanId=d0eea26c64524fe7994eb4fe0ed590
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:15:43.237052+00:00 ERROR run=a6fa25944eae4395bfddc74f9196d1c4 stage_finished workflowId=34e96c2b98c8471db55dee075a1b5941 stage=layer3.assemble spanId=c9d004153c054070b0c9d9486624e05f att
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:15:43.240811+00:00 ERROR run=a6fa25944eae4395bfddc74f9196d1c4 stage_finished workflowId=34e96c2b98c8471db55dee075a1b5941 stage=layer3_formal_render spanId=8c5f1738f5654423990f584ad59143d
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:15:43.247502+00:00 ERROR run=a6fa25944eae4395bfddc74f9196d1c4 workflow_finished workflowId=34e96c2b98c8471db55dee075a1b5941 status=failed
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 19:13:16.192000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 19:13:16.205000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 19:11:38.707273891 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 19:11:38.717628790 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 19:11:39.024547154 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 19:11:39.522167339 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 19:11:39.528537723 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:12:45.984016+00:00 ERROR run=d51ad16e4ede4772886b066f5a4e2c04 stage_finished workflowId=8c3cc4cdb03c46928875e6d23ecfbe20 stage=layer3.track_assembly spanId=c1d38724e12b4c22812057d5b84d4b
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:12:45.987387+00:00 ERROR run=d51ad16e4ede4772886b066f5a4e2c04 stage_finished workflowId=8c3cc4cdb03c46928875e6d23ecfbe20 stage=layer3.assemble spanId=40283c0a68fa41f0b9fc2481432e8a52 att
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:12:45.991641+00:00 ERROR run=d51ad16e4ede4772886b066f5a4e2c04 stage_finished workflowId=8c3cc4cdb03c46928875e6d23ecfbe20 stage=layer3_formal_render spanId=0373a2c9f0654a1a8953b6e8b95a39e
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:12:45.999782+00:00 ERROR run=d51ad16e4ede4772886b066f5a4e2c04 workflow_finished workflowId=8c3cc4cdb03c46928875e6d23ecfbe20 status=failed
- `l3/ko-repair-seed-44/spark-ko-seed-44-c/spark-output/screen-v1.log`: W1014 19:26:05.136000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/ko-repair-seed-44/spark-ko-seed-44-c/spark-output/screen-v1.log`: W1014 19:26:05.149000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/ko-repair-seed-44/spark-output/render.log`: [0;93m2026-10-14 19:24:30.546072945 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko-repair-seed-44/spark-output/render.log`: [0;93m2026-10-14 19:24:30.667876455 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko-repair-seed-44/spark-output/render.log`: [0;93m2026-10-14 19:24:30.937707886 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko-repair-seed-44/spark-output/render.log`: [0;93m2026-10-14 19:24:31.193071729 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko-repair-seed-44/spark-output/render.log`: [0;93m2026-10-14 19:24:31.262151898 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko-repair-seed-44/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko-repair-seed-44/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:25:37.935843+00:00 ERROR run=be842df90d6e464296d1dd3e4dadc89e stage_finished workflowId=5d049d5311234d0ab1f2ce2b75f17a55 stage=layer3.track_assembly spanId=0c8f306faa0d4bfea12ff3c182a882
- `l3/ko-repair-seed-44/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:25:37.939875+00:00 ERROR run=be842df90d6e464296d1dd3e4dadc89e stage_finished workflowId=5d049d5311234d0ab1f2ce2b75f17a55 stage=layer3.assemble spanId=f98ecbe475944a15800a19b99fe4f465 att
- `l3/ko-repair-seed-44/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:25:37.943335+00:00 ERROR run=be842df90d6e464296d1dd3e4dadc89e stage_finished workflowId=5d049d5311234d0ab1f2ce2b75f17a55 stage=layer3_formal_render spanId=b9ef7dd4af66462a898b05d91d57307
- `l3/ko-repair-seed-44/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:25:37.951018+00:00 ERROR run=be842df90d6e464296d1dd3e4dadc89e workflow_finished workflowId=5d049d5311234d0ab1f2ce2b75f17a55 status=failed
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 19:19:16.581891071 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 19:19:16.617414186 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 19:19:16.898886532 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 19:19:17.090679711 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 19:19:17.440344481 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:20:24.008370+00:00 ERROR run=7b8bb4b39e4d4508889c04fb379c7a1a stage_finished workflowId=f470630bb82f4ac6a3406659fda56732 stage=layer3.track_assembly spanId=a2357721705b42649239e31ef0598f
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:20:24.011332+00:00 ERROR run=7b8bb4b39e4d4508889c04fb379c7a1a stage_finished workflowId=f470630bb82f4ac6a3406659fda56732 stage=layer3.assemble spanId=d142ec44775d4fbe85cc495101fe4d1d att
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:20:24.015295+00:00 ERROR run=7b8bb4b39e4d4508889c04fb379c7a1a stage_finished workflowId=f470630bb82f4ac6a3406659fda56732 stage=layer3_formal_render spanId=fd26813c1188421481ef2e8031f08ac
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T19:20:24.022476+00:00 ERROR run=7b8bb4b39e4d4508889c04fb379c7a1a workflow_finished workflowId=f470630bb82f4ac6a3406659fda56732 status=failed
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 19:20:50.669000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 19:20:50.682000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `logs/check-gpu-es.log`: "failed": [],
- `logs/check-gpu-ko-seed-44.log`: "failed": [],
- `logs/check-gpu-ko.log`: "failed": [],
- `logs/check-gpu-zh-Hans.log`: "failed": [],
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/if-i-had-more-time-jesus-is-worthy.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /english-reference/if-i-had-more-time-jesus-is-worthy.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-real-20261013.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /english-reference/mockup-dev-clip-real-20261013.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-v4-20261013.json: Failed to load resource: the server responded with a status of 404 ()

Not copied: 2 .cache, 22 .css, 21 .csv, 401 .html, 5 .jpg, 44 .js, 5619 .json, 7 .jsonl, 991 .lock, 247 .mjs, 863 .mp3, 100 .mp4, 20 .pdf, 97 .png, 154 .sha256, 10 .srt, 18 .svg, 97 .txt, 336 .wav
