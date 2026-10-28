# Weekly guide staging

This directory contains only locally generated, ignored content. The application
copies it into Beta builds when it is present. Release requires the payload and
its SHA-256 file and fails if either is absent or the bytes do not match. It
declares both files as Xcode script inputs so Release retains script sandboxing.
The generator never writes here directly. Generate a rich candidate into a fresh
Git-ignored `artifacts/` directory, then verify its receipt, fixed application
bundle hash and illustration hashes before copying its JSON, checksum and both
image files here. Retain the receipt with the release evidence. Replace the
placeholders with the identified local sources and checked evidence directories:

```sh
python3 apps/tongxing-ios/scripts/prepare-weekly-guide.py \
  --rich \
  --source /path/to/revelation-series-guide.zh-Hans.md \
  --cuv /path/to/cuv-1919-revelation.json \
  --english /path/to/revelation-series-guide.en-extracted.txt \
  --evidence-dir /path/to/checked-page-captures \
  --asset-dir /path/to/licensed-original-illustrations \
  --map-evidence-dir /path/to/frozen-pleiades-evidence \
  --output artifacts/weekly-guide-rich/new-run
```

Without `--rich`, the command can reproduce the historical v1 payload only in
a fresh ignored output directory. That payload has known table relationship
errors and is not an active bundle candidate. A self-consistent checksum does
not establish compatibility with the SHA pinned in the application.

Its hash is not covered by a Git commit or
the archive source-commit check. Verify the receipt and bundle bytes for each
candidate. Distribution depends on authorization for the specific content;
local generation does not establish permission or human review.
