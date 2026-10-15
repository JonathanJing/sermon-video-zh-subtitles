# Run digest 20261014-clip-e2e-opus280-20261004-ab

Generated 2026-10-15T00:23:39+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-ab-3lang

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-ab-3lang`

- summary `aqc/zh-Hans/summary.json` zh-Hans: **error** (ValueError: source_budget_exhausted)
- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**
- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.8 |
| zh-Hans.secondary-asr | pass | 1.8 |
| zh-Hans.audio-qc | pass | 0.7 |
| zh-Hans.calibration.prefetch | fail | 473.2 |

Failed stages: `zh-Hans.calibration.prefetch`

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 40.1 |
| es.text-qc | pass | 2.8 |

Timings `textqc-es/out-r1/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 39.4 |
| es.text-qc | pass | 2.6 |

Timings `textqc-es/out-r2/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 15.0 |
| es.text-qc | pass | 3.2 |
| es.calibration.prefetch | pass | 202.1 |
| es.calibration | pass | 16.4 |
| es.text-waiver | pass | 0.0 |

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.calibration.prefetch | pass | 43.1 |
| ko.calibration | pass | 18.2 |
| ko.text-waiver | pass | 0.0 |

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.calibration.prefetch | pass | 48.1 |
| zh-Hans.calibration | pass | 18.0 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| plan-qc-ko | pass | 0 |
|---|---|---|
| check-ab-budget-ko | pass | 0 |
| plan-qc-zh-Hans | pass | 0 |
| check-ab-budget-zh-Hans | pass | 0 |
| spark-begin-1 | pass | 3 |
| check-gpu-ko | pass | 2 |
| render.ko | fail(1) | 147 |
| compact.ko | fail(1) | 23 |
| check-gpu-zh-Hans | pass | 2 |
| render.zh-Hans | fail(1) | 122 |
| compact.zh-Hans | pass | 24 |
| screen.zh-Hans | pass | 49 |
| package.zh-Hans | pass | 9 |
| audio-qc.zh-Hans | fail(1) | 487 |
| spark-finish | pass | 8 |

Failed stages: `render.ko`, `compact.ko`, `render.zh-Hans`, `audio-qc.zh-Hans`
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 514 of 514 requests returned; reserved US$5.51; estimated US$0.92 over 509 priced; cost unknown: missing_or_invalid_token_counts ×5; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/zh-Hans/spark-driver.log`: zh-Hans.calibration.prefetch	fail	473.2
- `aqc/zh-Hans/spark-driver.log`: "status": "error",
- `aqc/zh-Hans/spark-driver.log`: "reason": "ValueError: source_budget_exhausted",
- `l3/ko/spark-ko-c/compact.log`: Traceback (most recent call last):
- `l3/ko/spark-ko-c/compact.log`: raise ValueError(f"Measured target audio exceeds 1x clip schedule: {plan['issues'][0]}")
- `l3/ko/spark-ko-c/compact.log`: ValueError: Measured target audio exceeds 1x clip schedule: {'unitIndex': 37, 'textGroupId': 'translation-0-u318', 'plannedEnd': 197.32, 'sourceEnd': 141.190064, 'clipDuration': 194.661133, 'maxEndLag
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:09:31.901680812 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:09:31.925841879 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:09:31.935358689 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:09:32.449491926 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:09:32.794825584 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/speech-job/accounting/operations.log`: ... 743 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:11:23.257711+00:00 ERROR run=c38ec750bff8432bad6c4ffafc902700 stage_finished workflowId=c6b16477d19d4dfbb91d3d2d8c637aaf stage=layer3.schedule_rejection spanId=abb5c39a104d4f788802feb13e
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:11:23.260800+00:00 ERROR run=c38ec750bff8432bad6c4ffafc902700 stage_finished workflowId=c6b16477d19d4dfbb91d3d2d8c637aaf stage=layer3.assemble spanId=49ea4662e3d64f4380f1868b61260152 att
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:11:23.264676+00:00 ERROR run=c38ec750bff8432bad6c4ffafc902700 stage_finished workflowId=c6b16477d19d4dfbb91d3d2d8c637aaf stage=layer3_formal_render spanId=2ea9e47ea72f44bba629c0aaad922cf
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:11:23.272494+00:00 ERROR run=c38ec750bff8432bad6c4ffafc902700 workflow_finished workflowId=c6b16477d19d4dfbb91d3d2d8c637aaf status=failed
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 00:12:10.134020123 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 00:12:10.134021851 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 00:12:10.175295209 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 00:12:10.626664014 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 00:12:10.699007642 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: ... 743 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:13:51.107144+00:00 ERROR run=d31896ec7b3a4468b2ea3b3314a47f3c stage_finished workflowId=514eba67ed2641a487ac54e7fd875250 stage=layer3.schedule_rejection spanId=b06bf7b2f6a646deb9a62399dd
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:13:51.111314+00:00 ERROR run=d31896ec7b3a4468b2ea3b3314a47f3c stage_finished workflowId=514eba67ed2641a487ac54e7fd875250 stage=layer3.assemble spanId=8939286fa3e04b8d9e90dcf468f5d5ef att
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:13:51.114963+00:00 ERROR run=d31896ec7b3a4468b2ea3b3314a47f3c stage_finished workflowId=514eba67ed2641a487ac54e7fd875250 stage=layer3_formal_render spanId=2660e2029a594898ade35cee97764b4
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:13:51.124031+00:00 ERROR run=d31896ec7b3a4468b2ea3b3314a47f3c workflow_finished workflowId=514eba67ed2641a487ac54e7fd875250 status=failed
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1015 00:14:27.052000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1015 00:14:27.077000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `logs/check-ab-budget-ko.log`: "failed": [],
- `logs/check-ab-budget-zh-Hans.log`: "failed": [],
- `logs/check-gpu-ko.log`: "failed": [],
- `logs/check-gpu-zh-Hans.log`: "failed": [],
- `logs/plan-qc-ko.log`: == 2026-10-15T00:08:47+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir
- `logs/plan-qc-zh-Hans.log`: == 2026-10-15T00:08:48+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 6 .csv, 2628 .json, 2 .jsonl, 531 .lock, 2 .mp3, 299 .sha256, 372 .wav
