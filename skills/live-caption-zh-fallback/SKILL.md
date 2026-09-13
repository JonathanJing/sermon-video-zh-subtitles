---
name: live-caption-zh-fallback
description: Produce or resume offline time-coded English/Chinese subtitle backups from a sermon URL. Use for archive/VOD subtitle fallback, not Sunday microphone capture or the weekly reading-PDF workflow.
---

# Offline Sermon Subtitle Fallback

Use existing captions first, then authorized ASR only when timed source text is unavailable. Produce reviewable original-language and Chinese subtitles with provenance. This legacy playback/archive route does not prove Sunday live-caption readiness.

Run the commands from the repository root. Infer routine defaults and reuse known URL, source date, sermon-window evidence, provider and output location; ask only for a missing decision that affects correctness or an unapproved external action. Keep generated files in ignored artifact paths.

## Extract or resume timed source

Inspect existing reports and artifacts before acquiring media again. For a new source:

```bash
python3 scripts/offline_live_sermon_subtitles.py --live-url 'LIVE_OR_ARCHIVE_URL' \
  --out-dir 'artifacts/offline-live-sermon-poc/DATE-SOURCE_ID'
```

Prefer `en-orig`, then `en`. Both automatically discovered VODs and explicit `--sermon-url 'MATCHING_VOD_URL'` need matching title/date/source evidence. Verify absolute archive offsets before accepting live alignment; an inferred offset or a `live-aligned` filename is not synchronization evidence. Pass known boundaries with `--sermon-start HH:MM:SS` / `--sermon-end HH:MM:SS`. Platform `zh-Hans` is a cross-check, never a prerequisite.

Inspect the emitted `report.json`/`report.md`, `*.local.vtt`/`*.local.srt`, and any `*.live-aligned.vtt`/`*.live-aligned.srt`. The default report directory is `artifacts/offline-live-sermon-poc/`; honor explicit run locations and preserve unrelated outputs.

When the status is `needs_asr`, use an authorized local/stream audio source and an available timed-ASR pipeline. Preserve segment start/end and original English; flag uncertain names, scripture and terminology. Keep partials separate from confirmed cues. If media, permission or provider setup is missing, report that exact blocker instead of inventing text. Ordinary subtitle extraction does not authorize recording live input or starting a different provider.

## Translate and preview when needed

Translate only time-coded source cues. Preserve canonical cue IDs and timing exactly. Shorten/wrap long Chinese for readability; any requested resegmentation belongs in a separate derivative with a source-cue mapping and timing validation. Keep English sidecar text and report terminology/scripture uncertainty.

For a requested legacy playback preview, reuse the verified report and its existing caption files:

```bash
python3 scripts/build_playback_simulation.py \
  --report 'artifacts/offline-live-sermon-poc/DATE-SOURCE_ID/report.json' \
  --out web/playback-simulation.generated.js
python3 scripts/translate_playback_with_openai.py \
  --input web/playback-simulation.generated.js \
  --out web/playback-simulation.generated.js \
  --api-key-secret projects/PROJECT_ID/secrets/SECRET_ID/versions/latest
```

Use `prepare_live_link_playback.py` only when extraction is still needed: it re-extracts before building. Carry forward the verified URL, VOD, start/end and run directory. For separately completed ASR, use its actual timed output and compatible report; do not restart extraction to manufacture a report. Use the existing authorized provider/credential route; the secret reference is a template, not a request to create credentials. Check the overwrite target against existing work first. The playback data output is not automatically a Chinese VTT/SRT file: inspect or produce the requested timed subtitle artifact before claiming delivery. Translation exit code 3 / `partial` preserves incomplete work and is not ready for publication.

Open the local page for requested UI/timing review. Preserve the public AI-assisted disclaimer and keep operator controls in `web/admin.html`.

## Optional publication

Publish already verified files with the existing artifact uploader (`scripts/upload_file_to_gcs.py --help`) to the authorized destination. `prepare_live_link_playback.py --gcs-bucket BUCKET --gcs-prefix runs/DATE/ID` is for runs that still need extraction; `--gcs-dry-run` previews uploads but still performs extraction/build. Reuse an already approved destination and credential route. Ask only if publication itself lacks authorization or its destination is unresolved.

Before public delivery, check generated browser files/manifests for raw secrets, private identifiers and Secret Manager resource names. Verify the actual remote result; local generation or a dry-run is not publication. Preserve source access restrictions and avoid cookie exports.

## Completion

`ready` requires non-empty original and Chinese timed subtitles, source/cue alignment, requested review checks, and secret-free requested delivery artifacts. Extraction `ok` alone is insufficient. Use `ready-needs-review` only when both languages exist and review remains; use `blocked-needs-asr` or `blocked-needs-translation` for missing stages. Unapproved requested publication is `blocked-needs-publish-confirmation`; a requested local-only result needs no publication approval.

Report the source, actual caption/translation route, requested output paths, checks and remaining operator action. Distinguish partial progress from a ready backup and from a proven live path.
