# Run digest 20261024-sat400-prep

Generated 2026-10-25T01:09:02+00:00. Redacted copies only; source hashes are in manifest.json.

## sat400-prep

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/weekend-live/2026-10-25/sat400-prep`

- outcome `outcome.json`: **completed_partial** exit 0 (2026-10-24T17:55:47-07:00 → 2026-10-24T18:12:00-07:00)

Timings `timings.tsv`:

| stage | result | seconds |
|---|---|---|
| P1-asr-spark | pass | 281.6 |
| P2-P4-terms-scripture | pass |  |
| P6-warmup-pack | pass |  |
| P7-start-check | fail |  |
| P5-term-decisions | waiting |  |
| P8-broadcast-diff | waiting |  |

Failed stages: `P7-start-check`, `P5-term-decisions`, `P8-broadcast-diff`

Not copied: 5 .json, 1 .md, 1 .sha256, 1 .txt, 67 .wav
