# Run digest 20261015-clip-e2e-opus280-20261004-ak-es-aqc

Generated 2026-10-15T01:48:58+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-ak-es-aqc

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-ak-es-aqc`

- outcome `textqc-es/state/asr-calls/primary/12adca5eede6292a01c2d57194e5a3a77b3ea53bd793c34f1023a5eec1d97258/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/50a93751012f29f8d62929beec7753d4ad49faf6c413ff5c05ecc4c441c94086/outcome.json`: **completed** exit ? (? → ?)
- outcome `textqc-es/state/asr-calls/primary/f3655c0224b02741c4168d4f52f7c63ff0bedae5ec825aa817f0ea8b49de3ba6/outcome.json`: **completed** exit ? (? → ?)
- summary `aqc/es/summary.json` es: **audio_waiver_issued**
- summary `textqc-es/out/summary.json` es: **text_waiver_issued**

Timings `aqc/es/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| es.track-check | pass | 0.7 |
| es.calibration.prefetch | pass | 12.0 |
| es.calibration | pass | 237.0 |
| es.audio-waiver | pass | 0.0 |

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
| check-ak-preflight | pass | 0 |
| spark-begin-1 | pass | 3 |
| check-gpu-es | pass | 2 |
| audio-qc.es | pass | 262 |
| spark-finish | pass | 7 |
| layer4-baseline | pass | 11 |
| layer4-publish | pass | 170 |
| layer4-smoke | pass | 19 |
- source budget `plans/qc-es/qc-es/.api-budget/source-budget.json`: 35 of 35 requests returned; reserved US$0.16; cost unknown: missing_or_invalid_token_counts ×35; invoice not verified

Error-like log lines (first 5 per log):

- `aqc/es/spark-driver.log`: W1015 01:44:05.013000 51 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `aqc/es/spark-driver.log`: W1015 01:44:05.025000 51 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `aqc/es/spark-driver.log`: [0;93m2026-10-15 01:44:05.443618223 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `logs/check-ak-preflight.log`: "failed": [],
- `logs/check-gpu-es.log`: "failed": [],
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-real-20261013.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /english-reference/mockup-dev-clip-real-20261013.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-e2e-20261013T034422Z.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-20261012T050250Z-u216.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-20261004-u280-329-opus-y-es.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/plan-qc-es.log`: == 2026-10-15T01:40:52+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 2 .cache, 22 .css, 416 .html, 5 .jpg, 44 .js, 2521 .json, 44 .lock, 247 .mjs, 870 .mp3, 100 .mp4, 20 .pdf, 97 .png, 10 .srt, 18 .svg, 1 .txt, 68 .wav
