# Run digest 20261012-weekly-clip-rehearsal-u216

Generated 2026-10-12T05:13:08+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261012T050250Z-u216

Source: `/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/wt-clip/artifacts/dev-180s-page-test-20261004/20261012T050250Z-u216`


Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| build-inputs | pass | 18 |
| baseline | pass | 7 |
| delivery-preflight | pass | 2 |
| delivery-execute | fail | 63 |
| delivery-execute-resume | fail | 4 |
| delivery-execute-resume2 | pass | 100 |
| browser-smoke-no-session | pass | - |

Failed stages: `delivery-execute`, `delivery-execute-resume`

Error-like log lines (first 5 per log):

- `delivery-execute-resume.log`: Traceback (most recent call last):
- `delivery-execute-resume.log`: raise ValueError(message)
- `delivery-execute-resume.log`: ValueError: Use a new baseline output directory
- `delivery-execute.log`: Traceback (most recent call last):
- `delivery-execute.log`: return fut.result(timeout)
- `delivery-execute.log`: raise self._exception
- `delivery-execute.log`: with urlopen(Request(origin + '/' + quote(str(relative), safe='/'), headers={'Accept-Encoding': 'gzip', 'Cache-Control': 'no-cache'}), timeout=120) as response:
- `delivery-execute.log`: return opener.open(url, data, timeout)

Not copied: 2 .cache, 22 .css, 286 .html, 5 .jpg, 48 .js, 1802 .json, 4 .lock, 1 .md, 254 .mjs, 740 .mp3, 90 .mp4, 24 .pdf, 99 .png, 12 .srt, 20 .svg, 3 .txt, 68 .wav
