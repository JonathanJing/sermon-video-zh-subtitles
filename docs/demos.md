# Two 60-second demos

Two presentation reels show one continuous sermon clip while the audio switches English original → Chinese → Korean → Spanish, about 15 seconds per language. The English section has English subtitles only; the dubbed sections keep the English source above the target line.

- Watch both: <https://ai-for-god-sermon-audio-dev.web.app/demos/>
- Eric Geiger: [`eric-geiger-2026-09-20-demo-720p.mp4`](https://storage.googleapis.com/ai-for-god-sermon-media-dev/demos/eric-geiger-2026-09-20-demo-720p.mp4)
- Steve Bang Lee: [`steve-bang-lee-2026-10-18-demo-720p.mp4`](https://storage.googleapis.com/ai-for-god-sermon-media-dev/demos/steve-bang-lee-2026-10-18-demo-720p.mp4)
- Hashes: [`SHA256SUMS.txt`](https://ai-for-god-sermon-audio-dev.web.app/demos/SHA256SUMS.txt)

These are **Dev previews**, not Production pages. The page and posters are served by Dev Hosting; the MP4s stream from the Dev media bucket.

## Timeline

| Seconds | Audio | Subtitles |
|---|---|---|
| 0–15 | English original | English only |
| 15–30 | Chinese dub | English source above Chinese |
| 30–45 | Korean dub | English source above Korean |
| 45–60 | Spanish dub | English source above Spanish |

Eric's reel is 60.6 seconds and uses 15.15-second sections so the last sentence completes. Steve's reel is 60.0 seconds with 15-second sections.

## Eric Geiger, 2026-09-20

- Source: Mariners Church weekend service, 2026-09-20, Revelation 2–3 (Laodicea, lukewarm).
- Approved source clip window: 38:07.32–40:25.32; the clip is 138.0 seconds.
- Demo selection: 77.17–137.77 of that clip, 60.6 seconds. It runs from “This world has seduced you away from your Savior” through the dog Rosco / coffee / cold-milk illustration to “The seduction of the world by the world is a tool of the enemy.”
- Production path: formal four-layer clip packages. English source, three target candidates and audio packages are human-approved in the 2026-09-20 artifacts (English and trilingual review approval recorded 2026-09-24).
- Voice: Eric Geiger Qwen3-TTS checkpoint `75d28ce6…`; all three target locales were reviewed.
- The 60-second edit itself is a presentation cut, not a new release.

## Steve Bang Lee, 2026-10-18

- Source: Mariners Church weekend service, 2026-10-18, Revelation 10:8–11. Approved window start 1963.0 s; anchor units 175–207.
- Demo selection: the first 60 seconds of the 3:06 sentence-first clip, covering the college-evangelism story through the start of the coffee/milk application.
- Production path: sentence-first agent route. The three dubs were listened to and approved by the user on 2026-10-22. The text was reused from a machine-reviewed sentence candidate; it was not independently human-translated.
- Voice: Steve Bang Lee Qwen3-TTS checkpoint `b480bc6a…`.
- The 60-second edit itself is a presentation cut, not a new release.

## What is and is not verified

- Verified: 1280×720, 29.97 fps, AAC stereo, duration, section audio provenance (cross-correlation against the source/target tracks), Dev HTTP delivery, MP4 Range requests.
- Not verified: sentence-level synchronization with the original picture, lip sync, full-sermon coverage, device playback, venue acceptance, or a new formal release package for either edit.
- A 15-second cut can land mid-sentence. Subtitles follow the dubbed audio, not the original picture.
- The Dev host is a test environment; these links are previews, not Production delivery.

## Regeneration

The renders read local artifacts that are not committed to Git:

- Steve: `python3 experiments/sentence-first-agent/make_multilingual_demo.py`
- Eric: `python3 experiments/sentence-first-agent/make_eric_demo.py`

Both scripts write under `artifacts/sentence-first-agent/`; models, checkpoints and source media stay outside Git.

## Attribution

Source footage: Mariners Church weekend services, 2026-09-20 and 2026-10-18. This personal project is not affiliated with, endorsed by, or operated by Mariners Church. Generated translations and speech are labelled with their review status; they are not presented as human translation or human performance.
