# Run digest 20261014-clip-e2e-opus280-20261004-v-es-audio

Generated 2026-10-14T22:38:18+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-v-es-audio

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-v-es-audio`

- summary `aqc/es/summary.json` es: **error** (ValueError: source_budget_exhausted)
- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.7 |
| es.secondary-asr | pass | 2.5 |
| es.audio-qc | pass | 0.7 |
| es.calibration.prefetch | pass | 432.7 |
| es.calibration | fail | 126.2 |

Failed stages: `es.calibration`

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

Timings `timings.tsv`:

| plan-qc-es | pass | 0 |
|---|---|---|
| spark-begin-1 | pass | 4 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 136 |
| compact.es | pass | 25 |
| screen.es | pass | 48 |
| package.es | pass | 9 |
| audio-qc.es | fail(1) | 573 |
| spark-finish | pass | 7 |

Failed stages: `render.es`, `audio-qc.es`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 549 of 549 requests returned; reserved US$5.52; estimated US$0.80 over 533 priced; cost unknown: missing_or_invalid_token_counts ×16; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: es.calibration	fail	126.2
- `aqc/es/spark-driver.log`: "status": "error",
- `aqc/es/spark-driver.log`: "reason": "ValueError: source_budget_exhausted",
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 22:27:20.228000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1014 22:27:20.240000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 22:25:03.314073723 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 22:25:03.315117119 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 22:25:03.522640881 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 22:25:03.972388888 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-14 22:25:04.175887355 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/speech-job/accounting/operations.log`: ... 743 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:26:45.044125+00:00 ERROR run=68f2823f29fe482b843dc349df95f145 stage_finished workflowId=ab6e42597ae74d52846631ea07f2d670 stage=layer3.schedule_rejection spanId=e4ed412d026945abbcd9935c4a
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:26:45.049253+00:00 ERROR run=68f2823f29fe482b843dc349df95f145 stage_finished workflowId=ab6e42597ae74d52846631ea07f2d670 stage=layer3.assemble spanId=fe74320e4e644f6996930d81665348dc att
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:26:45.052818+00:00 ERROR run=68f2823f29fe482b843dc349df95f145 stage_finished workflowId=ab6e42597ae74d52846631ea07f2d670 stage=layer3_formal_render spanId=3136715428ae4a32af1bf616ec06b67
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-14T22:26:45.064123+00:00 ERROR run=68f2823f29fe482b843dc349df95f145 workflow_finished workflowId=ab6e42597ae74d52846631ea07f2d670 status=failed
- `logs/check-gpu-es.log`: "failed": [],
- `logs/plan-qc-es.log`: == 2026-10-14T22:24:20+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 3 .csv, 1751 .json, 1 .jsonl, 559 .lock, 2 .mp3, 174 .sha256, 236 .wav

Publication review additionally omitted 2 `asr-screening-receipt-v1.json` files because they contained per-segment model output; their aggregate status remains represented by the surrounding summary and log evidence.
