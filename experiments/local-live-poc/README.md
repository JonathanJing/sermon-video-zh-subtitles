# Local Live Caption POC

Independent greenfield interface for a MacBook-based live sermon caption feasibility test.

## Current scope

- One desktop page.
- Microphone selection and live input meter.
- Start/stop audio recording in the browser.
- Large Simplified Chinese caption area with a smaller English source line.
- Downloadable audio and JSON event log after stopping.
- Clearly labeled stable-English replay through the real local translation backend.

The Chinese captions now come from the real localhost gateway and MiLMMT A0 model. The English input is still a clearly labeled replay fixture until local ASR is connected. Browser microphone recording remains real and continues if translation fails. The canonical PCM writer and offline replay runner are not implemented yet.

The backend includes a dependency-free Weekly Pack builder, guarded context retriever, localhost gateway, and Ollama translation adapter. It selects the already-installed MiLMMT A0 by default but never downloads a model automatically.

The intentionally small system and context-pack plan is in [DESIGN.zh.md](./DESIGN.zh.md). The verified desktop design review is in [design-qa.md](./design-qa.md).

## Run

```bash
npm run dev -- --host 0.0.0.0 --port 4173 --strictPort
```

Open the local page in a browser and allow microphone access when starting a recording.

## Saturday Weekly Pack

Prepare one JSON object per stable caption segment. The interchange format is JSONL: one complete `saturday-sermon-segment-v1` object per line, ordered by time.

```json
{"schemaVersion":"saturday-sermon-segment-v1","segmentId":"seg_000001","sectionId":"opening","sectionTitle":"At the border","startMs":0,"endMs":4200,"sourceTextEn":"God's people are approaching the promised land.","targetTextZh":"神的百姓正在接近应许之地。","transcriptStatus":"machine_generated","translationStatus":"machine_generated","scriptureRefs":[{"reference":"Numbers 13-14","status":"candidate"}],"terms":[{"source":"promised land","preferredZh":"应许之地","status":"approved"}]}
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
The builder assigns every segment a one-based `sequence`, creating an ordered Saturday sermon map. Optional section fields are useful for logs but are not required.

Keep the original audio, `saturday-segments.jsonl`, and generated `weekly-pack.json` together. The builder records the source ID, service date, and audio SHA-256. The normative field definition is [backend/schemas/saturday-sermon-segment-v1.schema.json](./backend/schemas/saturday-sermon-segment-v1.schema.json); a copy-ready file is in [backend/examples/saturday-segments.example.jsonl](./backend/examples/saturday-segments.example.jsonl).

## Local gateway

```bash
python3 -m backend.gateway --pack artifacts/weekly-pack.json
```

The gateway defaults to the selected A0 model, `sermon-milmmt-46-4b-v1-q8:benchmark`. `contextPolicy=none` preserves the frozen official MiLMMT prompt and benchmark decoding settings. A future model or post-trained artifact can replace it with `LOCAL_LIVE_OLLAMA_MODEL` without changing the browser contract.

Endpoints:

- `GET /api/health`
- `POST /api/context/retrieve`
- `POST /api/translate`

Both POST endpoints accept `cursorSequence` and `contextPolicy`. The live page should persist the returned `alignment.suggestedCursor` and send it with the next stable English segment:

```json
{"sourceTextEn":"Grace leads us today.","cursorSequence":14,"contextPolicy":"saturday_alignment_v1"}
```

Available policies are `none`, `weekly_terms_v1`, and `saturday_alignment_v1`. The last policy can expose a reviewed Saturday translation as a reference version, but only an exact English match can be used as a directly reusable reviewed example.

If Ollama or the configured model is unavailable, translation returns `503` with `recordingShouldContinue=true`; recording must not depend on translation availability.

Run backend tests with:

```bash
npm run test:backend
```
