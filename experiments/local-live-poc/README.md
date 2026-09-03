# Local Live Caption POC

Independent greenfield interface for a MacBook-based live sermon caption feasibility test.

## Current scope

- One desktop page.
- Microphone selection and live input meter.
- Start/stop audio recording in the browser.
- Large Simplified Chinese caption area with a smaller English source line.
- Downloadable audio and JSON event log after stopping.
- Clearly labeled simulated captions for UI verification.

The local ASR, canonical PCM writer, and offline replay runner are intentionally not implemented yet. The UI never presents simulated captions as real model output.

The backend now includes a dependency-free Weekly Pack builder, guarded context retriever, localhost gateway, and Ollama translation adapter. It does not download or select a model automatically.

The intentionally small system and context-pack plan is in [DESIGN.zh.md](./DESIGN.zh.md). The verified desktop design review is in [design-qa.md](./design-qa.md).

## Run

```bash
npm run dev -- --host 0.0.0.0 --port 4173 --strictPort
```

Open the local page in a browser and allow microphone access when starting a recording.

## Saturday Weekly Pack

Prepare one JSON object per caption segment:

```json
{"segmentId":"seg_000001","startMs":0,"endMs":4200,"sourceTextEn":"God's people are approaching the promised land.","targetTextZh":"神的百姓正在接近应许之地。","translationStatus":"machine_generated","scriptureRefs":["Numbers 13-14"],"terms":[{"source":"promised land","preferredZh":"应许之地","status":"approved"}]}
```

Build the short-lived pack using the real Saturday recording as provenance:

```bash
python3 -m backend.build_weekly_pack \
  --segments /absolute/path/saturday-segments.jsonl \
  --service-date 2026-09-05 \
  --source-id saturday-livestream-2026-09-05 \
  --audio /absolute/path/saturday-audio.m4a \
  --valid-until 2026-09-07 \
  --output artifacts/weekly-pack.json
```

Machine-generated Chinese is retained as a candidate but cannot be inserted into a live translation prompt. Only `reviewed`, `corrected`, or `approved` translations and terms are injectable.
String-only scripture references are also candidates; use `{"reference":"Numbers 13-14","status":"approved"}` only after review if the reference may be injected.

## Local gateway

```bash
LOCAL_LIVE_OLLAMA_MODEL=translategemma:4b \
python3 -m backend.gateway --pack artifacts/weekly-pack.json
```

Endpoints:

- `GET /api/health`
- `POST /api/context/retrieve`
- `POST /api/translate`

If Ollama or the configured model is unavailable, translation returns `503` with `recordingShouldContinue=true`; recording must not depend on translation availability.

Run backend tests with:

```bash
npm run test:backend
```
