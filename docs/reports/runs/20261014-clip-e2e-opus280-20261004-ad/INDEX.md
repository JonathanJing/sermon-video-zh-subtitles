# Run digest 20261014-clip-e2e-opus280-20261004-ad

Generated 2026-10-15T00:30:22+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-ad-ko-pace

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-ad-ko-pace`

- summary `textqc-ko/out/summary.json` ko: **text_waiver_issued**

Timings `textqc-ko/out/timings.tsv`:

| stage | status | seconds |
|---|---|---|
| discover | pass | 0.0 |
| ko.calibration.prefetch | pass | 43.1 |
| ko.calibration | pass | 18.2 |
| ko.text-waiver | pass | 0.0 |

Timings `timings.tsv`:

| plan-qc-ko | pass | 0 |
|---|---|---|
| check-ad-preflight | fail(1) | 1 |
| check-ad-preflight-no-session | pass | 0 |
| spark-begin-1 | pass | 3 |
| check-gpu-ko | pass | 2 |
| render.ko | fail(1) | 146 |
| compact.ko | fail(1) | 23 |
| spark-finish | pass | 7 |

Failed stages: `check-ad-preflight`, `render.ko`, `compact.ko`

Error-like log lines (first 5 per log):

- `l3/ko/spark-ko-c/compact.log`: Traceback (most recent call last):
- `l3/ko/spark-ko-c/compact.log`: raise ValueError(f"Measured target audio exceeds 1x clip schedule: {plan['issues'][0]}")
- `l3/ko/spark-ko-c/compact.log`: ValueError: Measured target audio exceeds 1x clip schedule: {'unitIndex': 37, 'textGroupId': 'translation-0-u318', 'plannedEnd': 196.46, 'sourceEnd': 141.190064, 'clipDuration': 194.661133, 'maxEndLag
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:27:52.925413804 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:27:52.926933348 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:27:53.036799379 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:27:53.417473695 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/render.log`: [0;93m2026-10-15 00:27:53.837000971 [W:onnxruntime:Default, device_discovery.cc:164 DiscoverDevicesForPlatform] GPU device discovery failed: device_discovery.cc:89 ReadFileContents Failed to open fil
- `l3/ko/spark-output/speech-job/accounting/operations.log`: ... 743 lines omitted; 0 error-like lines, 0 kept below ...
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:29:43.678565+00:00 ERROR run=df7ca9bf341349c78c301438351c5b64 stage_finished workflowId=880288c937fc454fbbdfc9bc54010716 stage=layer3.schedule_rejection spanId=0791f8f85b154b23b93fcd4067
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:29:43.682693+00:00 ERROR run=df7ca9bf341349c78c301438351c5b64 stage_finished workflowId=880288c937fc454fbbdfc9bc54010716 stage=layer3.assemble spanId=eaafe6703ca34665852814ace296265c att
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:29:43.686654+00:00 ERROR run=df7ca9bf341349c78c301438351c5b64 stage_finished workflowId=880288c937fc454fbbdfc9bc54010716 stage=layer3_formal_render spanId=bcc11954fd5149a4a564a4390b10450
- `l3/ko/spark-output/speech-job/accounting/operations.log`: 2026-10-15T00:29:43.698561+00:00 ERROR run=df7ca9bf341349c78c301438351c5b64 workflow_finished workflowId=880288c937fc454fbbdfc9bc54010716 status=failed
- `logs/check-ad-preflight-no-session.log`: "failed": [],
- `logs/check-ad-preflight.log`: "status": "fail",
- `logs/check-ad-preflight.log`: "failed": [
- `logs/check-ad-preflight.log`: "status": "fail",
- `logs/check-gpu-ko.log`: "failed": [],
- `logs/plan-qc-ko.log`: == 2026-10-15T00:27:03+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 3 .csv, 996 .json, 1 .jsonl, 4 .lock, 148 .sha256, 149 .wav
