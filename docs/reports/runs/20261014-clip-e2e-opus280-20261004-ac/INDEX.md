# Run digest 20261014-clip-e2e-opus280-20261004-ac

Generated 2026-10-15T00:40:04+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-ac-zh-aqc

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-ac-zh-aqc`

- outcome `textqc-zh-Hans/state/asr-calls/primary/224bcfcf20bf8cdad9b81be84e59b9e0fb3f806e86cc8e3faffe7ffc6d128d99/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/3ff542e606a5a125d34eea995ce61fa47fefd184297c32e2fe4b481c1105b1cf/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/47e89c75f2b72c8b84f369d82780965674850d96c3772c3c702058d9f0ffb57b/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/aba54044c04b376deb7a4f90a0cad8821a9fa24f75c6700b78be0e0536ea653b/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/bbd62dd5f4cade6f2c8078b6a97f798832116d29196c391d8a5afb092b2c4c8f/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/e0994c4e0ed46dbef16f3cb010e70fa150e04f7d3ca4ffc20a65bd9affd6cad9/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-zh-Hans/state/asr-calls/primary/e48ec9ce072b42b49370a5b63428a06814de0a56fcbea013dca23e1913a94340/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/zh-Hans/summary.json` zh-Hans: **waiver_refused** (Invalid sermon-target-language-machine-text-waiver-v1: Additional properties are not allowed ('humanAcceptance' was unexpected))
- summary `textqc-zh-Hans/out/summary.json` zh-Hans: **text_waiver_issued**

Timings `aqc/zh-Hans/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.track-check | pass | 0.7 |
| zh-Hans.calibration.prefetch | pass | 44.8 |
| zh-Hans.calibration | pass | 252.0 |
| zh-Hans.audio-waiver | fail | 0.0 |

Failed stages: `zh-Hans.audio-waiver`

Timings `textqc-zh-Hans/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| zh-Hans.calibration.prefetch | pass | 48.1 |
| zh-Hans.calibration | pass | 18.0 |
| zh-Hans.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| plan-qc-zh-Hans | pass | 0 |
|---|---|---|
| check-ac-preflight | pass | 0 |
| spark-begin-1 | pass | 4 |
| check-gpu-zh-Hans | pass | 2 |
| audio-qc.zh-Hans | fail(1) | 310 |
| spark-finish | pass | 7 |

Failed stages: `audio-qc.zh-Hans`
- source budget `plans/qc-zh-Hans/qc-zh-Hans/.api-budget/source-budget.json`: 64 of 64 requests returned; reserved US$0.53; estimated US$0.06 over 25 priced; cost unknown: missing_or_invalid_token_counts ×39; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/zh-Hans/spark-driver.log`: W1015 00:37:15.667000 48 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/zh-Hans/spark-driver.log`: W1015 00:37:15.691000 48 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/zh-Hans/spark-driver.log`: [0;93m2026-10-15 00:37:16.277379294 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `aqc/zh-Hans/spark-driver.log`: zh-Hans.audio-waiver	fail	0.0
- `aqc/zh-Hans/spark-driver.log`: "status": "waiver_refused",
- `logs/check-ac-preflight.log`: "failed": [],
- `logs/check-gpu-zh-Hans.log`: "failed": [],
- `logs/plan-qc-zh-Hans.log`: == 2026-10-15T00:33:06+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 128 .json, 69 .lock, 7 .wav
