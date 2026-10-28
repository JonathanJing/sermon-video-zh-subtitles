# Weekly guide staging

This directory contains only locally generated, ignored content. The application
copies it into Beta builds when it is present; production configurations remove
it from the bundle. Generate it from the identified local sources (replace the
placeholder with their local folder), and retain the receipt with the release evidence:

```sh
python3 apps/tongxing-ios/scripts/prepare-weekly-guide.py \
  --source /path/to/revelation-series-guide.zh-Hans.md \
  --cuv /path/to/cuv-1919-revelation.json
```

Its hash is not covered by a Git commit or
the archive source-commit check. Verify the receipt and bundle bytes for each
candidate. Distribution depends on authorization for the specific content;
local generation does not establish permission or human review.
