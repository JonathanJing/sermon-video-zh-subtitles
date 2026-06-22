# Web Prototype

This is a frontend-only prototype for preparing and publishing Chinese captions for the Mariners Church 11:30 service congregation.

Open `index.html` directly in a browser, or serve the `web/` folder with any static server.

Prototype scope:

- Live source monitoring flow for 8:30 PT first, 10:00 PT fallback, so captions are ready before the 11:30 service.
- Realtime Chinese caption workspace focused on what congregants can use while listening to the sermon.
- Live-link playback simulation using `playback-simulation.generated.js` from the offline POC.
- Scripture sidebar, glossary, notes placeholder.
- Review/publish timeline controls and VTT/SRT export buttons for fallback and archival use.

To test with a live archive link:

```bash
python3 ../scripts/offline_live_sermon_subtitles.py \
  --live-url 'https://www.youtube.com/watch?v=FsUijL9uB1I' \
  --out-dir ../artifacts/offline-live-sermon-poc

python3 ../scripts/build_playback_simulation.py \
  --report ../artifacts/offline-live-sermon-poc/report.json \
  --out ./playback-simulation.generated.js
```

Then reload `index.html` and click `模拟播放`.
