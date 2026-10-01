# Private media recovery audit

[中文说明](portable-media-recovery-audit.zh.md)

The current [Layer 3 producer](../scripts/build_target_language_audio_package.py)
records resolved host-absolute media paths. Editing those paths changes the
approved package's JSON hash and invalidates its independent approval receipt.
This additive tool verifies a separately mapped private archive while preserving
the original package and receipt bytes. It does not change the producer or the
staging interface.

## Contract and trust boundary

- Inputs are the **original, human-reviewed Layer 3 Audio Package**, its v1/v2
  independent audio approval receipt, a recovery sidecar, and an explicitly
  chosen local archive root. A path-free evidence snapshot is not the original
  package and cannot substitute for it.
- The [v1 sidecar schema](../schemas/sermon-private-media-recovery-manifest-v1.schema.json)
  binds both file-byte and canonical-JSON SHA-256 of the original package and
  approval. Its identity retains the source package hash, target locale,
  target-language candidate hash (the immutable text revision), speech-job hash,
  package ID, and downstream invalidation key.
- Supply expected source, locale and candidate hashes from the selected run's
  trusted evidence on **every invocation**. Do not derive these expectations
  from an untrusted replacement sidecar. Hashes establish integrity relative to
  trusted inputs; this is not a digital signature or proof of a human's identity.
- Every package unit audio, track, captions and schedule has exactly one explicit
  artifact-ID-to-relative-path mapping. IDs are package locations such as
  `/units/0/audio`, `/track`, `/captions`, `/schedule`. The mapped file must match
  the original package's SHA-256 and its canonical JSON hash when present.
- Archive paths use canonical POSIX spelling under `languages/<targetLocale>/`.
  Choose a revision-specific archive root. `archiveId` is a non-secret logical
  label, not a path or a storage locator; it is not used to find files.
- The original absolute media paths are never opened, copied into the sidecar,
  or printed. There is no filename search, hash-based discovery, environment
  fallback, automatic remote fetch, or best-effort guess. Extra unrelated files
  do not substitute for a missing explicit mapping.
- Traversal, absolute/Windows/URL paths, noncanonical separators, symlinks
  (including archive-root ancestors), duplicate mappings and hard-link aliases
  between mapped artifacts are rejected. Media are read through directory file
  descriptors with `O_NOFOLLOW` to resist directory-symlink replacement races.
  This version requires a POSIX system with those facilities and fails closed
  elsewhere. The archive must be quiescent during the audit; detected file
  changes fail, and a result describes bytes observed during that audit, not a
  lock on later changes.

The sidecar and mapping remain private in an ignored archive/artifact directory.
Do not commit real packages, approvals, mappings, media, private filenames or
reviewer details. Only code, schema, documentation and synthetic tests belong in
Git.

## Prepare a new sidecar

Keep the original package and approval unchanged. Arrange authorized media in a
controlled archive root with the locale-relative layout. The tool never copies
media. Write a private mapping JSON with an `artifacts` array containing one row
per package artifact, including **every** unit:

```json
{
  "artifacts": [
    {"artifactId": "/units/0/audio", "archiveRelativePath": "languages/ko/audio/unit-0000.wav"},
    {"artifactId": "/track", "archiveRelativePath": "languages/ko/audio/track.wav"},
    {"artifactId": "/captions", "archiveRelativePath": "languages/ko/synchronization/captions.json"},
    {"artifactId": "/schedule", "archiveRelativePath": "languages/ko/synchronization/schedule.json"}
  ]
}
```

This example describes a one-unit package. Real rows must match the selected
package exactly. Set the following shell variables locally; they are not remote
URLs or values the tool discovers:

```sh
python3 scripts/audit_portable_media.py prepare \
  --package "$ORIGINAL_PACKAGE" --approval "$ORIGINAL_APPROVAL" \
  --archive-root "$ARCHIVE_ROOT" --mapping "$PRIVATE_MAPPING" \
  --archive-id weekly-ko-r2 \
  --expected-source-sha256 "$EXPECTED_SOURCE_JSON_SHA256" \
  --expected-locale ko \
  --expected-candidate-sha256 "$EXPECTED_CANDIDATE_JSON_SHA256" \
  --out "$NEW_PRIVATE_SIDECAR"
```

Preparation reads and checks all mapped media before creating the new sidecar.
Only this explicit `prepare --out` operation writes a file. The output's parent
directory must already exist. Existing files, including original package,
approval, symlinks and an older sidecar, are never overwritten. On failure no
successful manifest is reported. A failed output write may leave an incomplete
new file; use a fresh output name after correcting the error.

## Audit after relocation

Transfer media and evidence only through an independently authorized private
archive workflow. Select the destination root explicitly; unchanged package,
approval and sidecar bytes are reused on the second machine:

```sh
python3 scripts/audit_portable_media.py audit \
  --package "$ORIGINAL_PACKAGE" --approval "$ORIGINAL_APPROVAL" \
  --manifest "$PRIVATE_SIDECAR" --archive-root "$DESTINATION_ARCHIVE_ROOT" \
  --expected-source-sha256 "$EXPECTED_SOURCE_JSON_SHA256" \
  --expected-locale ko \
  --expected-candidate-sha256 "$EXPECTED_CANDIDATE_JSON_SHA256"
```

Audit performs no application writes and emits a path-free JSON report. Exit 0
means the bound Layer 3 package artifacts were verified. Exit 1 is blocked;
missing/corrupt media are enumerated by artifact ID and stable error code.
Structural/identity failures stop before media reads. CLI syntax errors use
argparse's standard exit 2. Keep terminal arguments private as normal.

## Scope and remaining work

`scope=layer3_package_artifacts_only` and
`releaseEligibilityEstablished=false` are always explicit. A successful audit
checks byte recovery, **not** codec decoding, listening quality, new approval,
voice rights, all upstream packages, ASR screening evidence, original video,
other rendering receipts or a complete production archive. A v1 receipt remains
v1; this tool does not convert it into v2 ASR adjudication. No model, network,
archive upload/download, staging, publication or deployment is performed.

Existing staging still consumes original paths and its complete evidence gates.
A successful sidecar audit does not make that legacy path-based interface
portable. A later explicitly versioned staging consumer must use these verified
mappings without rewriting the approved package and must continue checking all
of its existing gates. The broader recovery backlog remains open.

## Verification

```sh
python3 -m unittest tests.test_audit_portable_media -v
```

Synthetic tests include two-directory relocation after removing the source
media tree, exact original-byte preservation, the actual Layer 3 package and
audio-review producers, missing/corrupt/empty files, path traversal, symlink
roots/parents/files, special files, wrong locale/source/revision, byte-only
package/approval changes, derived identity drift, canonical-JSON hash mismatch,
duplicate/aliased mappings, ignored same-basename alternatives and redacted CLI
failures. Synthetic review fields are fixtures, not actual content approval.
