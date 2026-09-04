# Local Live Caption POC

Independent greenfield interface for a MacBook-based live sermon caption feasibility test.

## Current scope

- One desktop page.
- Microphone selection and live input meter.
- Start/stop audio recording in the browser.
- Large Simplified Chinese caption area with a smaller English source line.
- Downloadable audio and JSON event log after stopping.
- Automatic per-recording local session folder with incremental audio and JSONL writes.
- Real microphone PCM streaming through Qwen3-ASR/MLX (with Whisper fallback) and MiLMMT.
- A tokenized, read-only phone viewer on the same Wi-Fi; control and recording APIs stay localhost-only.

The live path is microphone → AudioWorklet PCM → WebSocket gateway → energy VAD → configured local English ASR (`Qwen3-ASR` through MLX Audio or `whisper.cpp`) → MiLMMT token stream → Chinese caption. Browser recording remains independent and continues if ASR or translation fails. The default final cadence is 500 ms of silence or a 3-second maximum speech window; only immutable ASR finals start translation. Chinese token updates are append-only and rate-limited, so ASR revisions cannot make the large caption flicker. Frozen-English replay/A-B is now executable and does not rerun ASR.

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

For the intended room/PA capture path, the page requests browser echo cancellation, noise suppression, and automatic gain control **off**. The requested and applied track settings are written into each session manifest so a replay can distinguish capture changes from model changes. The saved browser recording is never rewritten by ASR-side processing.

The backend includes a dependency-free Weekly Pack builder, guarded context retriever, localhost REST/WebSocket gateway, Whisper CLI adapter, and Ollama translation adapter. It selects the already-installed MiLMMT A0 by default; the setup script downloads only the pinned local ASR model.

The intentionally small system and context-pack plan is in [DESIGN.zh.md](./DESIGN.zh.md). The researched live transport decision and protocol contract are in [STREAMING.zh.md](./STREAMING.zh.md).

## First-time setup

The setup script creates the local Python environment, installs the single WebSocket dependency, verifies `whisper-cli`/Ollama, and downloads the pinned `ggml-base.en` model into the ignored `artifacts/models/` directory:

```bash
./scripts/setup-local.sh
```

The model SHA-256 is pinned by the script. Model files and recordings remain local and are not committed.

Qwen3-ASR uses a separate, pinned MLX Audio runtime:

```bash
.venv/bin/python -m pip install -r requirements-qwen-asr.txt
```

When both the MLX runtime and the cached Qwen model are present, the Sunday launcher selects Qwen automatically. Otherwise it falls back to the installed `whisper.cpp` model. `LOCAL_LIVE_ASR_PROVIDER` remains an explicit override. Gateway readiness remains degraded until the selected provider completes a real model handshake.

## Sunday one-command run

On macOS, double-click `Sunday Live Captions.command` in Finder. It launches the same checked runtime and opens the caption page. A plain web shortcut is not sufficient because browsers cannot start the local Python, Node, Whisper, and Ollama processes.

The equivalent Terminal command is:

```bash
./scripts/sunday-live.sh
```

This command checks the local dependencies, selected ASR, writable session directory, and at least 10 GiB of free disk; starts Ollama when needed; prevents display and idle system sleep; starts the localhost control gateway, live audio WebSocket, read-only LAN viewer, MiLMMT adapter, and Vite UI; then opens `http://127.0.0.1:4173/`. Qwen is preferred when installed; Whisper `small.en`/`base.en` is the fallback.

After recording starts, the operator page shows a QR code. Phones on the same Wi-Fi can scan it to open large Chinese captions over SSE. The token expires after the session ends; the viewer exposes no microphone, restart, session-write, log, or model-control endpoint. This LAN POC does not add an Internet tunnel or authentication service.

With Qwen MLX enabled, the launcher supervises `mlx_audio.server`. If it exits, the launcher records stdout/stderr in `${TMPDIR}/sermon-live-caption-poc/mlx-audio.log` and attempts up to three automatic restarts while the independent browser recording continues. A short MLX finalization timeout is logged as `asr.empty`, not translated, and does not become a persistent page error. A third consecutive identical short ASR result is logged as `asr.suppressed/repeated_short_result` and held out of translation; any different or longer result immediately resets the guard. This generic guard avoids streaming hundreds of music-induced one-word hallucinations without blacklisting a specific word.

The final cadence can be tuned without code changes using `LOCAL_LIVE_VAD_SILENCE_MS` and `LOCAL_LIVE_VAD_MAX_SEGMENT_MS`; both values must be multiples of 100 ms. The defaults are `500` and `3000`.

If `artifacts/weekly-pack.json` is a genuine active Saturday pack with non-example source/audio provenance, the launcher automatically selects `saturday_alignment_v1`; otherwise it fails safely to `none`. Override with `LOCAL_LIVE_CONTEXT_POLICY=none|weekly_terms_v1|saturday_alignment_v1`.

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

## Replay A/B and ASR Gold gate

Replay the immutable English finals from any completed session. This produces `run.json`, `results.jsonl`, and a blind `review.csv`:

```bash
./scripts/replay-ab.py artifacts/sessions/<session-id> --policies none,saturday_alignment_v1
```

Prepare the six existing acoustic cases for human word-level review and validate them fail-closed:

```bash
./scripts/prepare-asr-gold-review.py artifacts/benchmarks/acoustic-e2e-20260903/small-en-report.json \
  --output benchmarks/asr-gold-review-queue-20260904.jsonl
./scripts/validate-asr-gold.py benchmarks/asr-gold-review-queue-20260904.jsonl
```

The checked-in queue is intentionally `pending_human_review`; provisional GPT-transcribe references are not called human Gold. After every row is corrected and approved, pass it to `scripts/score-acoustic-e2e.py --gold ...` to emit formal rather than provisional WER.

## Recording retention

Sessions are never deleted at startup. Preview the default 30-day policy (always preserving the newest ten and every active/unknown session), then opt in explicitly if the plan is correct:

```bash
./scripts/manage-sessions.py
./scripts/manage-sessions.py --apply
```

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
- read-only phone viewer `GET /view/{token}` and `GET /api/view/{token}/events` on LAN port `8780`

Both POST endpoints accept `cursorSequence` and `contextPolicy`. The live page should persist the returned `alignment.suggestedCursor` and send it with the next stable English segment:

```json
{"sourceTextEn":"Grace leads us today.","cursorSequence":14,"contextPolicy":"saturday_alignment_v1"}
```

Available policies are `none`, `weekly_terms_v1`, and `saturday_alignment_v1`. The last policy can expose a reviewed Saturday translation as a reference version, but only an exact English match can be used as a directly reusable reviewed example.

If Ollama or the configured model is unavailable, translation returns `503` with `recordingShouldContinue=true`; recording must not depend on translation availability.

## Test strategy

Keep the test stack small and use the standard runners already available:

- **Unit:** content-pack rules, session storage, replay, Gold gate, retention planning, viewer projection, and the browser-to-gateway contract.
- **Integration:** real localhost HTTP/WebSocket/SSE servers with temporary storage and fake models; verifies ordered writes, finalization, translation fallback, viewer isolation, and caption fan-out.
- **Browser E2E:** use the actual microphone and actual local Ollama model. Record at least ten seconds, stop, then verify that the visible Chinese/English pair changed, `manifest.json` is completed, `events.jsonl` contains the translation events, and the saved recording decodes. This remains a deliberate manual test because browser microphone permission and the physical audio route are the behavior under test.
- **Long soak:** replay a fixed source through the actual speaker/microphone path for 50–60 minutes, then score latency, availability, repeated short outputs, language drift, process RSS/Swap, failures, and artifact hashes with `scripts/score-soak-e2e.py`. The scorer accepts an independent health sampler with `--health-telemetry`. The 2026-09-04 baseline, targeted recovery regression, and completed fixed 60-minute run are documented in [benchmarks/SOAK_E2E_20260904.zh.md](./benchmarks/SOAK_E2E_20260904.zh.md).

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
