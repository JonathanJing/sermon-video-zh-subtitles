# Web Prototype

This web path is already working, but it is currently a secondary path in the
repository.

The primary repository workflow today is the stable post-live operator flow
documented in:

- [../README.md](../README.md)
- [../docs/stable-post-live-reading-pdf-workflow.md](../docs/stable-post-live-reading-pdf-workflow.md)
- [../docs/stable-post-live-reading-pdf-workflow.zh.md](../docs/stable-post-live-reading-pdf-workflow.zh.md)

That primary flow is:

1. save a sermon video URL into resumable state
2. manually confirm the sermon start and end time
3. run the post-live subtitle pipeline
4. generate the Chinese-English reading PDF
5. treat the run as complete only after PDF QA passes

This README describes the browser-facing support path around that workflow. It
is not the main operator entrypoint described in the root README.

## Relationship To The Primary Workflow

Use this web path when you need one or more of these:

- a congregation-facing caption page
- an admin/operator browser UI
- playback simulation and public-page QA
- review and observability controls around generated artifacts

The web path can help operators monitor, inspect, simulate, and publish. But
the repository's current stable completion bar is still the reading-PDF path:
saved source, manually confirmed sermon window, generated
`sermon_zh_en_reading.pdf`, passing PDF QA, and written run reports.

## Current Role

Today this web prototype is best understood as:

- a working congregation and admin UI layer
- a useful browser surface around generation and review
- a support path around the stable post-live reading-PDF workflow

It should be documented as working, but not as the repository's main workflow.

Open `index.html` directly in a browser, or serve the `web/` folder with any static server.

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
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

Then reload `index.html` and click `模拟播放`. The caption stage should show the sermon title, generation status, and the currently generated caption segment.

For production-style runs, add `--gcs-bucket <bucket>` and `--api-key-secret projects/<project>/secrets/<name>/versions/latest` from the repository root. Generated playback data and subtitle artifacts are uploaded to GCS; secret values and Secret Manager resource names stay out of public artifacts.

Regenerate the scripture sidebar slice:

```bash
python3 scripts/build_scripture_index.py \
  --out web/scripture-cmn-cu89s.generated.js \
  --full-out data/scripture/cmn-cu89s.json \
  --ref "Numbers 16" \
  --ref "Numbers 16:48"
```

Cloud Run serves the full Bible index through `/api/scripture/cmn-cu89s/...`, while
the generated browser file remains a small static fallback. See
`docs/scripture-source.md` for source and license notes.
