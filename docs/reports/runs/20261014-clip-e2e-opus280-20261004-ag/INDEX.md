# Run digest 20261014-clip-e2e-opus280-20261004-ag

Generated 2026-10-15T01:11:49+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-ag-zh-audio

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-ag-zh-audio`

- summary `aqc/zh-Hans/summary.json` zh-Hans: **error** (ValueError: source_budget_exhausted)
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.8 |
| zh-Hans.secondary-asr | pass | 1.6 |
| zh-Hans.audio-qc | pass | 0.7 |
| zh-Hans.calibration.prefetch | fail | 477.0 |

Failed stages: `zh-Hans.calibration.prefetch`

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.text-qc.prefetch | pass | 3.3 |
| zh-Hans.text-qc | pass | 3.3 |
| zh-Hans.calibration.prefetch | pass | 45.4 |
| zh-Hans.calibration | pass | 17.9 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| timeline-map | pass | 0 |
|---|---|---|
| plan-qc-zh-Hans | pass | 0 |
| check-ag-preflight | pass | 0 |
| spark-begin-1 | pass | 4 |
| voice-auth.zh-Hans | pass | 0 |
| speech-job.zh-Hans | pass | 0 |
| check-gpu-zh-Hans | pass | 2 |
| render.zh-Hans | fail(1) | 128 |
| compact.zh-Hans | pass | 24 |
| screen.zh-Hans | pass | 45 |
| package.zh-Hans | pass | 9 |
| audio-qc.zh-Hans | fail(1) | 491 |
| spark-finish | pass | 7 |

Failed stages: `render.zh-Hans`, `audio-qc.zh-Hans`
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 514 of 514 requests returned; reserved US$5.51; estimated US$0.93 over 509 priced; cost unknown: missing_or_invalid_token_counts ×5; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/zh-Hans/spark-driver.log`: zh-Hans.calibration.prefetch	fail	477.0
- `aqc/zh-Hans/spark-driver.log`: "status": "error",
- `aqc/zh-Hans/spark-driver.log`: "reason": "ValueError: source_budget_exhausted",
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 01:00:18.174583594 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 01:00:18.202082783 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 01:00:18.327182027 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 01:00:18.690071366 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/render.log`: [0;93m2026-10-15 01:00:19.040298323 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: ... 743 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:01:58.026597+00:00 ERROR run=35039219bd684a78b3830763bba6be30 stage_finished workflowId=6d6db130d9814b2790adb6de8e68e926 stage=layer3.schedule_rejection spanId=3a0a4f00e4344e81b67b7160d6
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:01:58.029900+00:00 ERROR run=35039219bd684a78b3830763bba6be30 stage_finished workflowId=6d6db130d9814b2790adb6de8e68e926 stage=layer3.assemble spanId=32f0f3e2682b47058237fc9efa988537 att
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:01:58.033860+00:00 ERROR run=35039219bd684a78b3830763bba6be30 stage_finished workflowId=6d6db130d9814b2790adb6de8e68e926 stage=layer3_formal_render spanId=954c27ca7db14dc982f8e2c3f2d1311
- `l3/zh-Hans/spark-output/speech-job/accounting/operations.log`: 2026-10-15T01:01:58.043854+00:00 ERROR run=35039219bd684a78b3830763bba6be30 workflow_finished workflowId=6d6db130d9814b2790adb6de8e68e926 status=failed
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1015 01:02:32.805000 1 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() on
- `l3/zh-Hans/spark-zh-Hans-c/spark-output/screen-v1.log`: W1015 01:02:32.819000 1 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant(
- `logs/check-ag-preflight.log`: "failed": [],
- `logs/check-gpu-zh-Hans.log`: "failed": [],
- `logs/plan-qc-zh-Hans.log`: == 2026-10-15T00:59:40+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 3 .csv, 1619 .json, 1 .jsonl, 522 .lock, 2 .mp3, 152 .sha256, 222 .wav
