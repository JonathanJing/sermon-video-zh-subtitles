# Run digest 20261014-clip-e2e-opus280-20261004-w

Generated 2026-10-14T23:35:10+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-w-es-aqc

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-w-es-aqc`

- summary `textqc-es/out/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r1/summary.json` es: **requires_repair** (text QC failed; repair the failed groups in a new candidate revision)
- summary `textqc-es/out-r2/summary.json` es: **text_waiver_issued**

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
| check-w-preflight | fail(1) | 0 |
| check-w-preflight-with-origin | pass | 1 |
| spark-begin-1 | pass | 4 |
| check-gpu-es | pass | 2 |
| audio-qc.es | fail(1) | 2 |
| spark-finish | pass | 7 |

Failed stages: `check-w-preflight`, `audio-qc.es`

Error-like log lines (first 5 per log):

- `logs/audio-qc.es.log`: rsync: [Receiver] mkdir "~/dgx-spark-benchmark/results/clip-e2e-opus280-20261004-w-es-aqc/mac-artifacts/clip-e2e-20261004-opus-w-es-aqc/aqc/es" failed: No such file or directory (2)
- `logs/audio-qc.es.log`: rsync error: error in file IO (code 11) at main.c(800) [Receiver=3.2.7]
- `logs/audio-qc.es.log`: rsync(55555): error: unexpected end of file
- `logs/audio-qc.es.log`: Traceback (most recent call last):
- `logs/audio-qc.es.log`: raise CalledProcessError(retcode, process.args,
- `logs/check-gpu-es.log`: "failed": [],
- `logs/check-w-preflight-with-origin.log`: "failed": [],
- `logs/check-w-preflight.log`: "status": "fail",
- `logs/check-w-preflight.log`: "failed": [
- `logs/check-w-preflight.log`: "status": "fail",
- `logs/plan-qc-es.log`: == 2026-10-14T23:32:55+00:00 ~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/.venv/bin/python ~/.codex/worktrees/opus-layer1-larger-clip/sermon-video-zh-subtitles/scripts/run_with_openai_envir

Not copied: 48 .json, 5 .lock
