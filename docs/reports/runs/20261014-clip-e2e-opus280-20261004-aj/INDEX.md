# Run digest 20261014-clip-e2e-opus280-20261004-aj

Generated 2026-10-15T01:40:19+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-aj-es-audio

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-aj-es-audio`

- summary `aqc/es/summary.json` es: **error** (ValueError: source_budget_exhausted)
- summary `textqc-es/out/summary.json` es: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.9 |
| es.secondary-asr | pass | 1.5 |
| es.audio-qc | pass | 0.7 |
| es.calibration.prefetch | pass | 384.7 |
| es.calibration | fail | 127.8 |

Failed stages: `es.calibration`

Timings `textqc-es/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.text-qc.prefetch | pass | 36.6 |
| es.text-qc | pass | 2.6 |
| es.calibration.prefetch | pass | 191.5 |
| es.calibration | pass | 15.9 |
| es.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| plan-qc-es | pass | 0 |
| check-aj-preflight | pass | 1 |
| spark-begin-1 | pass | 4 |
| voice-auth.es | pass | 0 |
| speech-job.es | pass | 0 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 137 |
| compact.es | pass | 25 |
| screen.es | pass | 45 |
| package.es | pass | 9 |
| audio-qc.es | fail(1) | 527 |
| spark-finish | pass | 7 |

Failed stages: `render.es`, `audio-qc.es`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 551 of 551 requests returned; reserved US$5.52; estimated US$0.79 over 532 priced; cost unknown: missing_or_invalid_token_counts ×19; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: es.calibration	fail	127.8
- `aqc/es/spark-driver.log`: "status": "error",
- `aqc/es/spark-driver.log`: "reason": "ValueError: source_budget_exhausted",
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1015 01:30:26.607000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/es/spark-es-c/spark-output/screen-v1.log`: W1015 01:30:26.619000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `l3/es/spark-output/render.log`: [0;93m2026-10-15 01:28:09.081438379 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-15 01:28:09.116016896 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-15 01:28:09.251298020 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-15 01:28:09.620641872 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/render.log`: [0;93m2026-10-15 01:28:09.870479201 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/es/spark-output/speech-job/accounting/operations.log`: ... 743 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:29:51.155446+00:00 ERROR run=25bc55070ec44428b25cb41c00384dcb stage_finished workflowId=2fb34fc328834243946a77888549f0e0 stage=layer3.schedule_rejection spanId=9979ccf8987e4430930581287c
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:29:51.160606+00:00 ERROR run=25bc55070ec44428b25cb41c00384dcb stage_finished workflowId=2fb34fc328834243946a77888549f0e0 stage=layer3.assemble spanId=4e0308fb8abb48d9b22a9d1ec46b1414 att
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:29:51.165625+00:00 ERROR run=25bc55070ec44428b25cb41c00384dcb stage_finished workflowId=2fb34fc328834243946a77888549f0e0 stage=layer3_formal_render spanId=8d42b91b9deb40e3b952d2332ace1af
- `l3/es/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:29:51.176291+00:00 ERROR run=25bc55070ec44428b25cb41c00384dcb workflow_finished workflowId=2fb34fc328834243946a77888549f0e0 status=failed
- `logs/check-aj-preflight.log`: "failed": [],
- `logs/check-gpu-es.log`: "failed": [],
- `logs/plan-qc-es.log`: == 2026-10-15T01:27:23+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 3 .csv, 1735 .json, 1 .jsonl, 559 .lock, 2 .mp3, 174 .sha256, 236 .wav
