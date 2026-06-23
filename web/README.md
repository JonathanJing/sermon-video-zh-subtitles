# Web Prototype

This is a frontend-only prototype for preparing and publishing Chinese captions for the Mariners Church 11:30 service congregation.

Open `index.html` directly in a browser, or serve the `web/` folder with any static server.

Prototype scope:

- Live source monitoring flow for 8:30 PT first, 10:00 PT fallback, so captions are ready before the 11:30 service.
- Realtime Chinese caption workspace focused on what congregants can use while listening to the sermon.
- Live-link playback simulation using `playback-simulation.generated.js` from the offline POC.
- Scripture sidebar, glossary, notes placeholder.
- Review/publish timeline controls and VTT/SRT export buttons for fallback and archival use.

From the repository root, test with a live archive link:

```bash
python3 scripts/prepare_live_link_playback.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I'
```

Then reload `index.html` and click `模拟播放`. The caption stage should show the sermon title, generation status, and the currently generated caption segment.

For production-style runs, add `--gcs-bucket <bucket>` and `--api-key-secret projects/<project>/secrets/<name>/versions/latest` from the repository root. Generated playback data and subtitle artifacts are uploaded to GCS; secret values and Secret Manager resource names stay out of public artifacts.
