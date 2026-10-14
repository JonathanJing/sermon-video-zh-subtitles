# Run digest 20261014-clip-e2e-opus280-20261004-x

Generated 2026-10-14T23:43:44+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-x-es-aqc

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-x-es-aqc`

- outcome `textqc-es/state/asr-calls/primary/12adca5eede6292a01c2d57194e5a3a77b3ea53bd793c34f1023a5eec1d97258/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/50a93751012f29f8d62929beec7753d4ad49faf6c413ff5c05ecc4c441c94086/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/f3655c0224b02741c4168d4f52f7c63ff0bedae5ec825aa817f0ea8b49de3ba6/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/es/summary.json` es: **audio_waiver_issued**
- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.9 |
| es.calibration.prefetch | pass | 11.9 |
| es.calibration | pass | 237.6 |
| es.audio-waiver | pass | 0.0 |

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
| check-x-preflight | pass | 0 |
| spark-begin-1 | pass | 4 |
| check-gpu-es | pass | 2 |
| audio-qc.es | pass | 262 |
| spark-finish | pass | 7 |
| layer4-baseline | pass | 14 |
| layer4-publish | fail(1) | 3 |

Failed stages: `layer4-publish`
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 35 of 35 requests returned; reserved US$0.16; cost unknown: missing_or_invalid_token_counts ×35; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: W1014 23:39:57.100000 51 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/es/spark-driver.log`: W1014 23:39:57.111000 51 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/es/spark-driver.log`: [0;93m2026-10-14 23:39:57.559907259 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `logs/check-gpu-es.log`: "failed": [],
- `logs/check-x-preflight.log`: "failed": [],
- `logs/layer4-publish.log`: Traceback (most recent call last):
- `logs/layer4-publish.log`: raise ValueError(message)
- `logs/layer4-publish.log`: ValueError: Three locales required
- `logs/plan-qc-es.log`: == 2026-10-14T23:36:38+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 6 .css, 82 .html, 1 .jpg, 11 .js, 585 .json, 44 .lock, 75 .mjs, 172 .mp3, 20 .mp4, 4 .pdf, 21 .png, 2 .srt, 6 .svg, 1 .txt, 16 .wav
