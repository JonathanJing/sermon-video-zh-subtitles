# Legacy Operator Web Support Path

This browser UI supports the legacy source-discovery, caption and post-live
reading-PDF path. The repository's current prepared-content path is four-layer
multilingual weekly production:

- [Root README](../../README.md)
- [Four-layer contract](../../docs/multilingual-production-interfaces.zh.md)
- [Local production runbook](../../docs/codex-local-production-runbook.zh.md)

The separate reading-PDF delivery remains documented in the
[stable post-live workflow](../../docs/stable-post-live-reading-pdf-workflow.md)
and its [Chinese version](../../docs/stable-post-live-reading-pdf-workflow.zh.md).
It requires the saved source, a human-confirmed sermon window, reading-text QA,
both PDFs and their QA reports. That completion bar applies to `dual_pdf`,
not to a four-layer release or a Sunday `live_session`.

## Supported scope

Use this path for the legacy congregation caption page, admin/operator UI,
playback simulation, public-page QA and review or observability controls around
generated artifacts. The current multilingual reader lives in
`apps/listening-web/`; this directory is a separate support surface.

This directory was `web/` until 2026-10 (layout stage 2; audit: [operator-web-audit.zh.md](../../docs/design/operator-web-audit.zh.md)). Files, URLs and behavior are unchanged. `backend/app.py` serves it as static files from the Cloud Run service `sermon-zh-caption-web`: `/` is the public congregation entry and `/admin` is the operator entry. `index.html` and `admin.html` share one `app.js`, `styles.css` and `manifest.webmanifest`, so keep the public page free of operator controls (`tests/test_public_admin_boundary.py`). This is not the Sunday `live_session` public viewer, which is in `experiments/local-live-poc`.

Open `index.html` directly in a browser, or serve this folder with any static server.

Pages:

- `index.html`: public congregation caption page.
- `admin.html`: operator/Admin page for source status, manual trigger, pipeline stages, settings, and observability evidence.

Prototype scope:

- Public congregation view with captions, disclaimer, full transcript, and scripture/sidebar content.
- Admin live source monitoring flow for 8:30 PT first, 10:00 PT fallback, so captions are ready before the 11:30 service.
- Realtime Chinese caption workspace focused on what congregants can use while listening to the sermon.
- Live-link playback simulation using `playback-simulation.generated.js` from the offline POC.
- Scripture sidebar backed by `scripture-cmn-cu89s.generated.js`, generated from the public-domain eBible `cmn-cu89s` Chinese Union Version slice.
- Admin review/publish timeline controls and VTT/SRT export buttons for fallback and archival use.

From the repository root, test with a live archive link:

```bash
python3 tools/ops/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

Then reload `index.html` and click `模拟播放`. The caption stage should show the sermon title, generation status, and the currently generated caption segment.

For production-style runs, add `--gcs-bucket <bucket>` and `--api-key-secret projects/<project>/secrets/<name>/versions/latest` from the repository root. Generated playback data and subtitle artifacts are uploaded to GCS; secret values and Secret Manager resource names stay out of public artifacts.

Regenerate the scripture sidebar slice:

```bash
python3 scripts/build_scripture_index.py \
  --out apps/operator-web/scripture-cmn-cu89s.generated.js \
  --full-out data/scripture/cmn-cu89s.json \
  --ref "Numbers 16" \
  --ref "Numbers 16:48"
```

Cloud Run serves the full Bible index through `/api/scripture/cmn-cu89s/...`, while
the generated browser file remains a small static fallback. See
`docs/scripture-source.md` for source and license notes.
