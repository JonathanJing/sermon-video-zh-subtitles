# Run digest 20261014-clip-e2e-opus280-20261004-y-es-dev

Generated 2026-10-14T23:49:10+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-e2e-20261004-opus-y-es-dev

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/clip-e2e-20261004-opus-y-es-dev`

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

| check-y-preflight | pass | 0 |
|---|---|---|
| layer4-baseline | pass | 10 |
| layer4-publish | pass | 165 |
| layer4-smoke | pass | 18 |

Error-like log lines (first 5 per log):

- `logs/check-y-preflight.log`: "failed": [],
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-20261011-u216-231-d.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-real-20261013.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /alignment/mockup-dev-clip-20261012T050250Z-u216.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /english-reference/mockup-dev-clip-20261011-u216-231-d.json: Failed to load resource: the server responded with a status of 404 ()
- `logs/layer4-smoke.log`: warning: optional resource failed: /english-reference/mockup-dev-clip-real-20261013.json: Failed to load resource: the server responded with a status of 404 ()

Not copied: 2 .cache, 22 .css, 406 .html, 5 .jpg, 44 .js, 2418 .json, 9 .lock, 247 .mjs, 860 .mp3, 100 .mp4, 20 .pdf, 97 .png, 10 .srt, 18 .svg, 1 .txt, 65 .wav
