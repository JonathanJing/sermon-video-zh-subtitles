# Live Caption Chinese Fallback Skill

Use this skill when the user provides a live service, livestream archive, or sermon video link and wants a reliable backup path to produce time-coded subtitles and Chinese translation for the sermon subtitle project.

This skill is intentionally operational rather than decorative: the output should be files the operator can inspect, publish to the local playback simulation, upload to GCS, or use as a fallback when the primary live translation path is not ready.

## Scope

- Input: a user-provided livestream URL, live archive URL, or sermon VOD URL.
- Step 1: extract existing captions when available, or start an authorized ASR/listening workflow when captions are unavailable.
- Step 2: translate the time-coded subtitle track into Chinese.
- Output: original-language subtitles, Chinese subtitles, a report, and a clear readiness summary.

Keep the project split between realtime and offline paths:

- Realtime path: used when the service is live or the operator needs subtitles before the 11:30 PT congregation service.
- Offline/archive path: used when a public VOD or live archive is available and the operator needs a backup or quality pass.

## Safety And Source Rules

- Do not bypass access controls, DRM, paywalls, private links, login walls, or platform restrictions.
- Do not store API keys, cookies, raw service credentials, Secret Manager resource names, or private account identifiers in public/generated browser files.
- Quote live/video URLs in shell commands. Query strings can be interpreted by `zsh` if unquoted.
- Treat public VOD captions as fallback/cross-check material, not proof that the realtime service path is complete.
- Keep generated transcripts and subtitles under ignored artifact paths unless the user explicitly asks to publish a sanitized sample.

## Inputs To Ask For Or Infer

Required:

- `live_url`: the livestream, live archive, or sermon URL.

Useful optional inputs:

- `sermon_url`: edited sermon VOD URL when it is already known.
- `sermon_start`: manual sermon start in the live timeline, such as `00:23:25`.
- `target_date`: Sunday service date.
- `service_time`: service time, such as `10:00 PT` or `11:30 PT`.
- `output_prefix`: run folder under `artifacts/`.
- `publish_target`: local only, GCS dry run, or GCS publish.
- `translation_provider`: preferred translation model/provider if the user has one.

If the user only gives a URL, proceed with conservative defaults and report which assumptions were used.

## Phase 1: Caption Extraction

First try existing caption tracks before ASR.

1. Confirm the URL is reachable and inspect metadata.
2. Prefer caption languages in this order: `zh-Hans`, `en-orig`, `en`.
3. If the URL is a live archive, attempt to align the sermon segment back to the live timeline.
4. If an edited sermon VOD is discoverable from the same channel, use it as a caption source only when the title/date/source evidence matches.
5. Generate both local sermon timeline files and live-aligned files when possible.

Preferred local command for this repo:

```bash
python3 scripts/offline_live_sermon_subtitles.py \
  --live-url 'PASTE_LIVE_OR_ARCHIVE_URL_HERE'
```

With a known edited sermon URL:

```bash
python3 scripts/offline_live_sermon_subtitles.py \
  --live-url 'PASTE_LIVE_OR_ARCHIVE_URL_HERE' \
  --sermon-url 'PASTE_SERMON_VOD_URL_HERE'
```

With a known sermon start:

```bash
python3 scripts/offline_live_sermon_subtitles.py \
  --live-url 'PASTE_LIVE_OR_ARCHIVE_URL_HERE' \
  --sermon-start 00:23:25
```

Expected Phase 1 artifacts:

- `artifacts/offline-live-sermon-poc/report.json`
- `artifacts/offline-live-sermon-poc/report.md`
- `*.local.vtt`
- `*.local.srt`
- `*.live-aligned.vtt`
- `*.live-aligned.srt`

If the report status is `needs_asr`, continue to Phase 1B.

## Phase 1B: ASR / Listening Fallback

Use this when no usable caption track exists.

The ASR source must be authorized. Acceptable sources include:

- an official public live/archive audio stream available to the operator,
- an exported audio file the user provides,
- a local recording the operator is permitted to use,
- a provider-supported realtime audio session explicitly configured by the user.

ASR requirements:

- Preserve timestamps at segment level.
- Keep the original-language transcript as the source of truth.
- Mark uncertain words, scripture references, names, and theology terms for review.
- Avoid producing a single untimed paragraph; the backup must remain VTT/SRT-capable.
- If realtime ASR is used, write rolling partials to an artifact file and periodically checkpoint confirmed cues.

Minimum ASR output shape:

```json
{
  "status": "needs_translation",
  "source": {
    "type": "asr",
    "url": "redacted-or-user-provided-url",
    "authorized": true
  },
  "segments": [
    {
      "start": "00:00:00.000",
      "end": "00:00:04.200",
      "text": "Original-language transcript text.",
      "confidence": 0.86
    }
  ],
  "warnings": []
}
```

If ASR cannot be started because credentials, audio permission, or provider setup is missing, stop and report the exact blocker. Do not invent transcript content.

## Phase 2: Chinese Translation

Translate only after a time-coded original-language track exists.

Translation rules:

- Preserve cue timing exactly unless a cue is too long for readable Chinese subtitles.
- Keep scripture references faithful and easy for Chinese church readers to recognize.
- Preserve proper nouns when translating would confuse retrieval or review.
- Prefer natural Simplified Chinese for congregation reading, not word-for-word subtitleese.
- Keep English sidecar/source text available for review.
- Flag uncertain theology terms, names, book/chapter references, and jokes/idioms in the report.

Preferred local command when playback data already exists:

```bash
python3 scripts/translate_playback_with_openai.py \
  --input web/playback-simulation.generated.js \
  --output web/playback-simulation.generated.js
```

If using a different translation provider, keep the same output contract: Chinese subtitle text must remain attached to the original cue timing and must not leak secrets into generated browser files.

## Playback Simulation

After caption extraction, rebuild the local playback simulation so the operator can inspect timing before publishing:

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'PASTE_LIVE_OR_ARCHIVE_URL_HERE'
```

Then open `web/index.html` or use the existing local web verification workflow. The public page should stay simple; operator controls belong in `web/admin.html`.

## Publishing Backup Artifacts

For a dry run:

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'PASTE_LIVE_OR_ARCHIVE_URL_HERE' \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --gcs-prefix runs/YYYY-MM-DD/SERVICE_OR_VIDEO_ID \
  --gcs-dry-run
```

For real GCS publish, only proceed when the user confirms credentials and destination:

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'PASTE_LIVE_OR_ARCHIVE_URL_HERE' \
  --gcs-bucket sermon-zh-artifacts-ai-for-god \
  --gcs-prefix runs/YYYY-MM-DD/SERVICE_OR_VIDEO_ID \
  --api-key-secret projects/PROJECT_ID/secrets/SECRET_ID/versions/latest
```

Before publishing or deploying, scan generated browser files and manifests for raw keys and Secret Manager resource-name-like strings.

## Verification Checklist

Before saying the backup is ready, verify:

- `report.json` status is `ok`, `needs_translation`, or a clearly explained blocked state.
- At least one original-language VTT/SRT exists with nonzero cues.
- Chinese subtitles exist or the report clearly says translation is blocked.
- Cue timing is plausible relative to the sermon start.
- `web/playback-simulation.generated.js` does not contain API keys or Secret Manager resource names.
- The public page has the brief AI-assisted subtitle disclaimer and no operator-only controls.
- Any GCS or Cloud Run claim is backed by an actual command result, not just local file generation.

## Response Contract

When reporting back to the user, include:

- Source URL used.
- Caption route: existing captions, matching VOD captions, ASR/listening fallback, or blocked.
- Translation route: provider/script used or blocker.
- Output files generated.
- Readiness state: `ready`, `ready-needs-review`, `blocked-needs-asr`, `blocked-needs-translation`, or `blocked-needs-publish-confirmation`.
- Next operator action, if any.

Keep the answer concise and in Chinese unless the user asks otherwise. Preserve English file names, script names, provider names, and source titles.
