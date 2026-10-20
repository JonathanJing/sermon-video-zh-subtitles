# Run digest 20261017-deepseek-translation-review-low

Generated 2026-10-17T21:49:37+00:00. Redacted copies only; source hashes are in manifest.json.

## deepseek-translation-review-low-20261017

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/deepseek-translation-review-low-20261017`

- outcome `outcome.json`: **succeeded** exit 0 (2026-10-17T21:46:54+00:00 → 2026-10-17T21:49:21.474633+00:00)
- summary `summary.json`: **completed**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| deepseek-low-translate | pass | 25.083445 |
| deepseek-low-review | pass | 89.879946 |
| blind-judge-schema-preflight | failed | 0 |
| blind-judge | pass | 16.038058 |

Failed stages: `blind-judge-schema-preflight`

Not copied: 10 .json, 4 .jsonl, 1 .py, 1 .pyc, 4 .txt
