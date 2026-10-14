# Run digest 20261014-opus-clip-e-failed

Generated 2026-10-14T18:49:36+00:00. Redacted copies only; source hashes are in manifest.json.

## opus-e2e-dev216-20261014-e

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/opus-e2e-dev216-20261014-e`

- outcome `textqc-es/state/asr-calls/primary/05cc6ab3381aaab1ab38f61dc68e174fca69b99ed6bce27440ca1c39caae3653/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/17a166d2cea9561e6d0a33f2d764c532bab2827aea8073dd4bcbda73e836a5ee/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/7d1089071303f8aa1d4cb1df1e3b4f6d668fa7da85d9ee858de200e6df32e748/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/8d10b6859c924f86308bd5ed03dbfc96aee4c0efac2e43ebff178e3505e0c986/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/228f67d4d4c0d9c8faecb4b9d07b0635748e997730ba797277f88f4105480f74/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/230d4cea0d9b35b21dfbdbdd1fe165196ba5fc6e39f981edde1144ca1ad7d621/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/c61e7b76a62641a145924cb9fc3c1b8c32fc3c5c1023c9a527e033e65afa5149/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/c901639e0383cf29755fff3f5ceb10e2348fafb71492e374f0b971992414e7f4/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/dd1f177d83ff16eb9e90422bc36376f5dc87f1864a124effa0ba4d965e0c68b1/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/df5fa3551373b6c25c2f7891086937f38d070e240257a8309f95075f09680277/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/e8434f33c175531ce7dd527b40feb98800d8720f24c404ffca2dcaf8f5b4fd47/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/ed90ce38967ef4b6cbb143cd386f0e932b84188bdecf57b290b5ac88028bc2f0/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/fdae048c86452811cc601e1ecd172935d80577306a0c72077d328df1dbe806bd/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/es/summary.json` es: **audio_waiver_issued**
- summary `aqc/ko/summary.json` ko: **requires_repair** (audio QC failed; re-render the failed units as the repair ladder says)
- summary `aqc/zh-Hans/summary.json` zh-Hans: **waiver_refused** (Calibration does not allow a waiver: seeded-error detection below minimum for ['audio.dropped_key_word'])
- summary `textqc-es/out/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.3 |
| es.secondary-asr | pass | 0.5 |
| es.audio-qc | pass | 0.2 |
| es.calibration.prefetch | pass | 3.2 |
| es.calibration | pass | 125.3 |
| es.audio-waiver | pass | 0.0 |

Timings `aqc/ko/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.3 |
| ko.secondary-asr | pass | 1.5 |
| ko.audio-qc | pass | 0.3 |

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.5 |
| zh-Hans.secondary-asr | pass | 0.4 |
| zh-Hans.audio-qc | pass | 0.2 |
| zh-Hans.calibration.prefetch | pass | 3.0 |
| zh-Hans.calibration | pass | 139.3 |
| zh-Hans.audio-waiver | fail | 0.0 |

Failed stages: `zh-Hans.audio-waiver`

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 16.5 |
| es.text-qc | pass | 0.5 |
| es.calibration.prefetch | pass | 81.7 |
| es.calibration | pass | 4.3 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.text-qc.prefetch | pass | 26.6 |
| ko.text-qc | pass | 0.6 |
| ko.calibration.prefetch | pass | 103.8 |
| ko.calibration | pass | 3.6 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 12.8 |
| zh-Hans.text-qc | pass | 0.5 |
| zh-Hans.calibration.prefetch | pass | 93.7 |
| zh-Hans.calibration | pass | 5.6 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| inputs | pass | 8 |
|---|---|---|
| timeline-map | pass | 0 |
| route-probe | pass | 0 |
| plan-layer2 | pass | 0 |
| check-layer2 | pass | 1 |
| layer2 | pass | 1 |
| layer2 | pass | 1 |
| plan-qc-ko | pass | 0 |
| check-qc-ko-out | pass | 0 |
| text-qc.ko.out | pass | 135 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 103 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | pass | 113 |
| spark-begin-1 | pass | 4 |
| voice-auth.ko | pass | 0 |
| speech-job.ko | pass | 0 |
| check-gpu-ko | pass | 2 |
| render.ko | fail(1) | 104 |
| compact.ko | pass | 17 |
| screen.ko | pass | 40 |
| package.ko | pass | 4 |
| audio-qc.ko | fail(1) | 23 |
| voice-auth.es | pass | 0 |
| speech-job.es | pass | 0 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 90 |
| compact.es | pass | 17 |
| screen.es | pass | 39 |
| package.es | pass | 4 |
| audio-qc.es | pass | 143 |
| voice-auth.zh-Hans | pass | 0 |
| speech-job.zh-Hans | pass | 0 |
| check-gpu-zh-Hans | pass | 3 |
| render.zh-Hans | fail(1) | 92 |
| compact.zh-Hans | pass | 17 |
| screen.zh-Hans | pass | 38 |
| package.zh-Hans | pass | 3 |
| audio-qc.zh-Hans | fail(1) | 154 |
| spark-finish | pass | 7 |

Failed stages: `render.ko`, `audio-qc.ko`, `render.es`, `render.zh-Hans`, `audio-qc.zh-Hans`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 237 of 237 requests returned; reserved US$2.28; estimated US$0.30 over 217 priced; cost unknown: missing_or_invalid_token_counts ×20; invoice not verified
- source budget `plans/qc-ko/qc-ko/.api-budget/source-budget.json`: 218 of 218 requests returned; reserved US$2.34; estimated US$0.38 over 216 priced; cost unknown: missing_or_invalid_token_counts ×2; invoice not verified
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 236 of 236 requests returned; reserved US$2.40; estimated US$0.36 over 212 priced; cost unknown: missing_or_invalid_token_counts ×24; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: W1014 18:41:18.277000 50 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/es/spark-driver.log`: W1014 18:41:18.292000 50 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/es/spark-driver.log`: [0;93m2026-10-14 18:41:18.716202668 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/ko/spark-driver.log`: "reason": "audio QC failed; re-render the failed units as the repair ladder says",
- `aqc/zh-Hans/spark-driver.log`: W1014 18:46:08.814000 50 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/zh-Hans/spark-driver.log`: W1014 18:46:08.830000 50 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/zh-Hans/spark-driver.log`: [0;93m2026-10-14 18:46:09.236275725 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/zh-Hans/spark-driver.log`: zh-Hans.audio-waiver	fail	0.0
- `aqc/zh-Hans/spark-driver.log`: "status": "waiver_refused",
- `l2/text/es/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/ko/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l2/text/zh-Hans/accounting/operations.log`: ... 154 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 18:39:41.209000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 18:39:41.222000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 18:38:04.183740066 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 18:38:04.219344290 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 18:38:04.308663588 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 18:38:04.711704697 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 18:38:04.959910357 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:39:13.243582+00:00 ERROR run=be120b7fb67f4b3c9ce00fa9a20d5777 stage_finished workflowId=ecbe68e72b03432bb77675467648f59d stage=layer3.track_assembly spanId=f292e8312bb54036937ad7acbee8f1
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:39:13.246638+00:00 ERROR run=be120b7fb67f4b3c9ce00fa9a20d5777 stage_finished workflowId=ecbe68e72b03432bb77675467648f59d stage=layer3.assemble spanId=9e91bb31648b4b31ac9deb74ae2a5512 att
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:39:13.250490+00:00 ERROR run=be120b7fb67f4b3c9ce00fa9a20d5777 stage_finished workflowId=ecbe68e72b03432bb77675467648f59d stage=layer3_formal_render spanId=e9518bbd73744211b271d0fb4b7d322
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:39:13.257775+00:00 ERROR run=be120b7fb67f4b3c9ce00fa9a20d5777 workflow_finished workflowId=ecbe68e72b03432bb77675467648f59d status=failed
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 18:36:41.650000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/ko/spark-ko-c/spark-output/screen-v1.log`: W1014 18:36:41.663000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 18:35:06.972910706 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 18:35:07.010612523 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 18:35:07.188017962 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 18:35:07.492646518 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-14 18:35:07.911368899 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:36:14.587546+00:00 ERROR run=4e8a644a977842c68c721a9e616d578a stage_finished workflowId=7a667addd54e497c8f35a0087328f676 stage=layer3.track_assembly spanId=42d69c66b41b45f3919e7651e450e4
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:36:14.591499+00:00 ERROR run=4e8a644a977842c68c721a9e616d578a stage_finished workflowId=7a667addd54e497c8f35a0087328f676 stage=layer3.assemble spanId=0be7ff766adf45e889d9ef286b90d586 att
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:36:14.594929+00:00 ERROR run=4e8a644a977842c68c721a9e616d578a stage_finished workflowId=7a667addd54e497c8f35a0087328f676 stage=layer3_formal_render spanId=1053c59b0e9742d494059d7682191a5
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:36:14.603417+00:00 ERROR run=4e8a644a977842c68c721a9e616d578a workflow_finished workflowId=7a667addd54e497c8f35a0087328f676 status=failed
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 18:43:05.471707458 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 18:43:05.508478423 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 18:43:05.752212286 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 18:43:06.015450813 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-14 18:43:06.192602553 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: ... 97 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:44:14.371156+00:00 ERROR run=a3841b1e2fc14ed6a7c000e62a15dbb5 stage_finished workflowId=5e61271d2efd4829b485ac4ca13b5683 stage=layer3.track_assembly spanId=c4a9986dd7684c64a9b8589f7a8117
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:44:14.374542+00:00 ERROR run=a3841b1e2fc14ed6a7c000e62a15dbb5 stage_finished workflowId=5e61271d2efd4829b485ac4ca13b5683 stage=layer3.assemble spanId=8cc252eb91d247bcba8bcb10bc156c0f att
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:44:14.378605+00:00 ERROR run=a3841b1e2fc14ed6a7c000e62a15dbb5 stage_finished workflowId=5e61271d2efd4829b485ac4ca13b5683 stage=layer3_formal_render spanId=cf8a621a12cd4f7589294922fbfe1ff
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-14T18:44:14.386087+00:00 ERROR run=a3841b1e2fc14ed6a7c000e62a15dbb5 workflow_finished workflowId=5e61271d2efd4829b485ac4ca13b5683 status=failed
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 18:44:41.267000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1014 18:44:41.281000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `logs/check-gpu-es.log`: "failed": [],
- `logs/check-gpu-ko.log`: "failed": [],
- `logs/check-gpu-zh-Hans.log`: "failed": [],
- `logs/check-layer2.log`: "failed": [],
- `logs/check-qc-es-out.log`: "failed": [],
- `logs/check-qc-ko-out.log`: "failed": [],
- `logs/check-qc-zh-Hans-out.log`: "failed": [],
- `logs/plan-layer2.log`: == 2026-10-14T18:26:47+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/plan-qc-es.log`: == 2026-10-14T18:30:34+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/plan-qc-ko.log`: == 2026-10-14T18:28:19+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ
- `logs/plan-qc-zh-Hans.log`: == 2026-10-14T18:32:18+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-e2e-dev-20261014/sermon-video-zh-subtitles/scripts/run_with_openai_environ

Not copied: 18 .csv, 2693 .json, 6 .jsonl, 747 .lock, 6 .mp3, 120 .sha256, 96 .txt, 209 .wav
