# Local Live Caption POC

Independent greenfield interface for a MacBook-based live sermon caption feasibility test.

## Current scope

- One desktop page.
- Microphone selection and live input meter.
- Start/stop audio recording in the browser.
- Large Simplified Chinese caption area with a smaller English source line.
- Downloadable audio and JSON event log after stopping.
- Automatic per-recording local session folder with incremental audio and JSONL writes.
- Real microphone PCM streaming through local Whisper ASR and the MiLMMT translation backend.

The live path is now microphone → AudioWorklet PCM → WebSocket gateway → energy VAD → configured `whisper.cpp` English ASR → MiLMMT A0 token stream → Chinese caption. Browser recording remains independent and continues if ASR or translation fails. Offline replay/A-B orchestration remains a later step. The default final cadence is 500 ms of silence or a 3-second maximum speech window; only immutable ASR finals start translation. Chinese token updates are append-only and rate-limited, so ASR partial revisions cannot make the large caption flicker.

Each start automatically creates:

```text
artifacts/sessions/<timestamp>-<random-id>/
  recording.webm   # appended once per MediaRecorder chunk
  asr-audio.pcm    # ordered 16 kHz signed-16 mono PCM
  asr-audio.wav    # finalized replayable ASR input
  events.jsonl     # append-only UI/model/status events
  manifest.json    # status, counts, paths, duration, and audio/PCM SHA-256
```

`events.jsonl` is also the performance log. Every stable segment records ASR queue/processing time, audio-end-to-English-final, translation queue time, MiLMMT TTFT, English-final-to-Chinese-first/final, and audio-end-to-Chinese-first/final. The browser adds `caption_rendered` for the first Chinese token and final Chinese caption, including gateway-to-browser and browser-render timing. Rejected stale or non-append partials are logged as `caption_partial_rejected`. `stream.closed.uxMetrics` contains per-session P50/P95/max aggregates without requiring a separate database.

The gateway syncs recovery recording chunks, batched PCM frames, and events to disk. On stop it wraps PCM as a replayable WAV, marks the manifest completed, and calculates recording/PCM hashes. Browser download links remain available as a recovery copy. Override the storage root with `LOCAL_LIVE_SESSION_ROOT=/absolute/path` when the recordings should live outside the project.

The backend includes a dependency-free Weekly Pack builder, guarded context retriever, localhost REST/WebSocket gateway, Whisper CLI adapter, and Ollama translation adapter. It selects the already-installed MiLMMT A0 by default; the setup script downloads only the pinned local ASR model.

The intentionally small system and context-pack plan is in [DESIGN.zh.md](./DESIGN.zh.md). The researched live transport decision and protocol contract are in [STREAMING.zh.md](./STREAMING.zh.md). The verified desktop design review is in [design-qa.md](./design-qa.md).

## First-time setup

The setup script creates the local Python environment, installs the single WebSocket dependency, verifies `whisper-cli`/Ollama, and downloads the pinned `ggml-base.en` model into the ignored `artifacts/models/` directory:

```bash
./scripts/setup-local.sh
```

The model SHA-256 is pinned by the script. Model files and recordings remain local and are not committed.

## Sunday one-command run

On macOS, double-click `Sunday Live Captions.command` in Finder. It launches the same checked runtime and opens the caption page. A plain web shortcut is not sufficient because browsers cannot start the local Python, Node, Whisper, and Ollama processes.

The equivalent Terminal command is:

```bash
./scripts/sunday-live.sh
```

This command checks the local dependencies, model, writable session directory, and at least 10 GiB of free disk; starts Ollama when needed; prevents display and idle system sleep; starts the REST gateway, WebSocket live audio endpoint, Whisper ASR, MiLMMT adapter, and Vite UI; then opens `http://127.0.0.1:4173/` automatically. It uses `small.en` when that benchmarked model is already installed and otherwise uses the pinned `base.en` installed by setup. Override it explicitly with `LOCAL_LIVE_ASR_MODEL=/absolute/path/to/model.bin`.

The final cadence can be tuned without code changes using `LOCAL_LIVE_VAD_SILENCE_MS` and `LOCAL_LIVE_VAD_MAX_SEGMENT_MS`; both values must be multiples of 100 ms. The defaults are `500` and `3000`.

Keep the Terminal window open. In the page, choose the microphone, start recording, and use **Stop and save** before pressing Control-C in Terminal. Run a non-starting preflight on Saturday night or Sunday morning with:

```bash
./scripts/sunday-live.sh --check
```

To stop everything with one double-click, first use **Stop and save** in the page, then open `Stop Sunday Live Captions.command` in Finder. It stops only the launcher recorded by this project; it does not kill arbitrary processes by port. Closing the browser page alone stops browser recording but does not stop the local backend.

For development, the lower-level command remains `./scripts/run-local.sh`; it does not start Ollama, run the full preflight, prevent sleep, or open the page.

If the live WebSocket, microphone, browser audio context, or incremental storage fails, the page now shows a visible degraded state while the independent browser recording continues. On stop, the gateway marks a session `completed` only after both ASR and translation workers confirm they drained; otherwise it writes an `incomplete` but recoverable manifest. Gateway startup also recovers stale `recording` sessions as `incomplete` instead of silently leaving them open.

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
- `POST /api/sessions/start`
- `POST /api/sessions/{sessionId}/audio?sequence=N`
- `POST /api/sessions/{sessionId}/events`
- `POST /api/sessions/{sessionId}/finalize`
- `POST /api/context/retrieve`
- `POST /api/translate`
- `WS /api/live` on `127.0.0.1:8767`

Both POST endpoints accept `cursorSequence` and `contextPolicy`. The live page should persist the returned `alignment.suggestedCursor` and send it with the next stable English segment:

```json
{"sourceTextEn":"Grace leads us today.","cursorSequence":14,"contextPolicy":"saturday_alignment_v1"}
```

Available policies are `none`, `weekly_terms_v1`, and `saturday_alignment_v1`. The last policy can expose a reviewed Saturday translation as a reference version, but only an exact English match can be used as a directly reusable reviewed example.

If Ollama or the configured model is unavailable, translation returns `503` with `recordingShouldContinue=true`; recording must not depend on translation availability.

## Test strategy

Keep the test stack small and use the standard runners already available:

- **Unit:** content-pack rules, the local session store, and the browser-to-gateway request contract. No server, microphone, Ollama, or network is required.
- **Integration:** a real localhost gateway and temporary session directory with a fake model response. This verifies HTTP, ordered audio/event writes, finalization, and translation fallback without changing real recordings.
- **Browser E2E:** use the actual microphone and actual local Ollama model. Record at least ten seconds, stop, then verify that the visible Chinese/English pair changed, `manifest.json` is completed, `events.jsonl` contains the translation events, and the saved recording decodes. This remains a deliberate manual test because browser microphone permission and the physical audio route are the behavior under test.

Run the complete automated gate with:

```bash
npm test
```

Run an individual layer with:

```bash
npm run test:unit
npm run test:integration
npm run test:backend
```
