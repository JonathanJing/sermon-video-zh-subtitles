# Run digest 20261014-clip-e2e-dev216-d-final

Generated 2026-10-14T17:29:56+00:00. Redacted copies only; source hashes are in manifest.json.

## report-final

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev216-20261014-d/report-final`


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
| text-qc.ko.out | pass | 120 |
| plan-qc-es | pass | 0 |
| check-qc-es-out | pass | 0 |
| text-qc.es.out | pass | 94 |
| plan-qc-zh-Hans | pass | 0 |
| check-qc-zh-Hans-out | pass | 0 |
| text-qc.zh-Hans.out | fail(1) | 18 |
| plan-layer2-zh-Hans-r1 | pass | 0 |
| layer2-zh-Hans-r1 | pass | 1 |
| layer2-zh-Hans-r1 | pass | 0 |
| check-qc-zh-Hans-out-r1 | pass | 0 |
| text-qc.zh-Hans.out-r1 | pass | 104 |
| spark-begin-1 | pass | 3 |
| voice-auth.ko | pass | 0 |
| speech-job.ko | pass | 0 |
| check-gpu-ko | pass | 2 |
| render.ko | fail(1) | 92 |
| compact.ko | pass | 16 |
| screen.ko | pass | 40 |
| package.ko | pass | 3 |
| audio-qc.ko | fail(1) | 23 |
| voice-auth.es | pass | 0 |
| speech-job.es | pass | 0 |
| check-gpu-es | pass | 2 |
| render.es | fail(1) | 87 |
| compact.es | pass | 17 |
| screen.es | pass | 38 |
| package.es | pass | 3 |
| audio-qc.es | pass | 131 |
| voice-auth.zh-Hans | pass | 0 |
| speech-job.zh-Hans | pass | 0 |
| check-gpu-zh-Hans | pass | 2 |
| render.zh-Hans | fail(1) | 88 |
| compact.zh-Hans | pass | 17 |
| screen.zh-Hans | pass | 38 |
| package.zh-Hans | pass | 3 |
| audio-qc.zh-Hans | pass | 157 |
| spark-finish | pass | 7 |
| check-pre-repair-ko | fail(1) | 0 |
| plan-qc-ko-audio-seed-43 | pass | 0 |
| check-pre-repair-ko-seed-43 | pass | 0 |
| spark-begin-1 | pass | 3 |
| check-gpu-ko-seed-43 | pass | 2 |
| render.ko.seed-43 | fail(1) | 84 |
| compact.ko.seed-43 | pass | 17 |
| screen.ko.seed-43 | pass | 40 |
| package.ko.seed-43 | pass | 3 |
| audio-qc.ko.seed-43 | fail(1) | 23 |
| spark-finish | pass | 8 |
| plan-qc-ko-audio-seed-44 | pass | 0 |
| check-pre-repair-ko-seed-44 | pass | 1 |
| spark-begin-1 | pass | 4 |
| check-gpu-ko-seed-44 | pass | 2 |
| render.ko.seed-44 | fail(1) | 87 |
| compact.ko.seed-44 | pass | 17 |
| screen.ko.seed-44 | pass | 39 |
| package.ko.seed-44 | pass | 3 |
| audio-qc.ko.seed-44 | pass | 375 |
| spark-finish | pass | 7 |
| layer4-baseline | pass | 13 |
| layer4-publish | pass | 198 |
| layer4-smoke | fail(1) | 20 |

Failed stages: `text-qc.zh-Hans.out`, `render.ko`, `audio-qc.ko`, `render.es`, `render.zh-Hans`, `check-pre-repair-ko`, `render.ko.seed-43`, `audio-qc.ko.seed-43`, `render.ko.seed-44`, `layer4-smoke`

## l4

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev216-20261014-d/l4`


Not copied: 2 .cache, 22 .css, 386 .html, 5 .jpg, 44 .js, 2288 .json, 4 .lock, 247 .mjs, 840 .mp3, 100 .mp4, 20 .pdf, 97 .png, 10 .srt, 18 .svg, 1 .txt, 65 .wav

## ko-seed-44

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-dev216-20261014-d/aqc/ko-seed-44`

- summary `summary.json` ko: **audio_waiver_issued**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.track-check | pass | 0.4 |
| ko.secondary-asr | pass | 0.8 |
| ko.audio-qc | pass | 0.3 |
| ko.calibration.prefetch | pass | 207.4 |
| ko.calibration | pass | 141.3 |
| ko.audio-waiver | pass | 0.2 |

Error-like log lines (first 5 per log):

- `spark-driver.log`: W1014 17:17:30.877000 50 torch/utils/_pytree.py:630] <enum 'KernelPreference'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant() o
- `spark-driver.log`: W1014 17:17:30.894000 50 torch/utils/_pytree.py:630] <enum 'ScaleCalculationMode'> is an Enum subclass and is now natively supported by torch.compile as an opaque value type. Calling register_constant
- `spark-driver.log`: [0;93m2026-10-14 17:17:31.308809252 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil

Not copied: 9 .json, 1 .lock
