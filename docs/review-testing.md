# Review/Test Notes

Scope: current POC for live-link input, sermon title display, "正在生成" caption state, GCS artifact publishing, and Secret Manager key reference.

## Findings

1. P1 - GCS publishing can leave partial output without a completion marker.
   - File: `scripts/prepare_live_link_playback.py:59`
   - Evidence: artifacts are uploaded first, then `cloud-manifest.json` is written and uploaded after those uploads complete (`scripts/prepare_live_link_playback.py:68`). If any early `gcloud storage cp` succeeds and a later copy fails, GCS may contain partial generated content with no explicit failed/incomplete state. Cloud Run or the operator UI could accidentally read stale/partial files.
   - Suggested fix: publish under a unique run prefix, upload a manifest with `status: "uploading"` first or write to a temp prefix, then atomically publish a final `cloud-manifest.json` with `status: "ready"` only after all files succeed.

2. P2 - GCS upload path and subprocess behavior are only dry-run tested.
   - File: `tests/test_prepare_live_link_playback.py:17`
   - Evidence: current test covers URI construction with `dry_run=True`, but does not simulate `subprocess.run` success/failure for real upload mode. Regression risk remains around failed `gcloud`, duplicate file uploads, and manifest upload ordering.
   - Suggested fix: add tests that monkeypatch `subprocess.run` to assert command order and verify failure behavior.

3. P2 - Frontend playback contract is not covered by automated DOM tests.
   - File: `web/app.js:119`
   - Evidence: `loadPlaybackSimulation()` and `startPlaybackSimulation()` drive the core user-visible requirements: title display, `正在生成`, and caption segment rendering. Existing tests validate generated JS shape, but not browser behavior.
   - Suggested fix: add a small Playwright smoke test that loads `web/index.html`, clicks `模拟播放`, and asserts `#sermonTitle`, `#generationStatus`, `#stableCaption`, and `#segmentCount`.

4. P3 - Secret Manager resource name is exposed in generated playback JS.
   - File: `scripts/build_playback_simulation.py:258`
   - Evidence: `apiKeySecret` is written into `window.SERMON_PLAYBACK_SIMULATION`. This does not include key material, but a public congregation page does not need the secret resource name.
   - Suggested fix: keep secret references in server-side manifests only, or strip `secrets` from the public playback JS before production deployment.

## Suggested Tests

- `test_gcs_upload_invokes_gcloud_in_expected_order`: monkeypatch `subprocess.run`, call `publish_files_to_gcs(..., dry_run=False)`, assert commands and returned `gcsUri` values.
- `test_gcs_upload_failure_does_not_claim_manifest_ready`: simulate one upload raising `CalledProcessError`; assert the command fails before reporting success and no ready manifest is produced.
- `test_cloud_manifest_has_ready_status_and_outputs`: once status is added, assert final manifest includes `status`, `schemaVersion`, `outputs`, and `apiKeyMaterialIncluded: false`.
- `test_public_playback_js_omits_secret_reference`: production-mode build should exclude `secrets.apiKeySecret` from browser-loaded JS.
- Playwright smoke: generated playback data present, click `模拟播放`, assert sermon title is visible, generation status is `正在生成`, and at least one caption segment appears.

## Commands Run

```bash
python3 -m unittest discover -s tests
```

Result: passed, 9 tests.
Current mainline rerun after sub-agent integration: passed, 13 tests.

```bash
python3 -m py_compile scripts/offline_live_sermon_subtitles.py scripts/build_playback_simulation.py scripts/prepare_live_link_playback.py
```

Result: passed.

```bash
node --check web/app.js
```

Result: passed.

```bash
git diff --check
```

Result: passed.

```bash
python3 scripts/build_playback_simulation.py --report artifacts/offline-live-sermon-poc/report.json --out /tmp/review-playback.generated.js --max-segments 3 --api-key-secret projects/p/secrets/openai-api-key/versions/latest
```

Result: passed; generated 3 playback segments and preserved `apiKeyMaterialIncluded: false`.

## Commands To Run Before Production-Like Test

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I' \
  --gcs-bucket sermon-zh-artifacts \
  --gcs-prefix runs/manual-test/FsUijL9uB1I \
  --api-key-secret projects/PROJECT_ID/secrets/openai-api-key/versions/latest
```

Then verify:

- GCS contains all expected VTT/SRT/report/playback files.
- `cloud-manifest.json` exists and is the source of truth for the run.
- No generated file contains raw API key material.
- Browser page shows sermon title, `正在生成`, and moving caption segments.
