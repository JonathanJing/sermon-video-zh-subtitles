# Run digest 20261012-weekly-clip-refused-attempts

Generated 2026-10-12T05:13:09+00:00. Redacted copies only; source hashes are in manifest.json.

## clip-20261012T045611Z

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/wt-clip/artifacts/dev-180s-page-test-20261004/clip-20261012T045611Z`


## clip-20261012T045656Z

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/wt-clip/artifacts/dev-180s-page-test-20261004/clip-20261012T045656Z`


Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| build-inputs | pass | - |
| baseline | pass | 10 |
| delivery-preflight | pass | 3 |
| delivery-execute | fail | 92 |
| delivery-execute-resume | fail | 2 |
| baseline2 | pass | 7 |
| delivery-preflight2 | pass | 2 |
| delivery-execute2 | fail | 6 |

Failed stages: `delivery-execute`, `delivery-execute-resume`, `delivery-execute2`

Error-like log lines (first 5 per log):

- `delivery-execute-resume.log`: Traceback (most recent call last):
- `delivery-execute-resume.log`: raise ValueError(message)
- `delivery-execute-resume.log`: ValueError: Workflow inputs changed; use a new run directory
- `delivery-execute.log`: Traceback (most recent call last):
- `delivery-execute.log`: raise ValueError(message)
- `delivery-execute.log`: ValueError: Default or existing page changed
- `delivery-execute2.log`: Traceback (most recent call last):
- `delivery-execute2.log`: raise ValueError(message)
- `delivery-execute2.log`: ValueError: Source-video collision

Not copied: 1 .cache, 26 .css, 319 .html, 6 .jpg, 53 .js, 1896 .json, 4 .lock, 1 .md, 290 .mjs, 867 .mp3, 102 .mp4, 24 .pdf, 116 .png, 12 .srt, 21 .svg, 3 .txt, 78 .wav
