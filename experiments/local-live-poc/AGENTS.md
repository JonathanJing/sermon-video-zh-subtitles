# Prototype Instructions

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

## Local live caption POC decisions

- This is an independent greenfield POC. Do not import or extend the repository's existing `web/admin.html`, `web/app.js`, or cloud publishing workflow.
- Keep one desktop page for a 15.6-inch MacBook. The only primary actions are microphone selection, start, and stop.
- The main surface is a large Simplified Chinese caption with a smaller English source line below it.
- Make the Chinese caption as large as the available viewport permits for distance reading on both MacBook Pro and iPhone; keep the English caption at its current secondary size.
- Do not add camera, pause, A/B controls, scripture sidebar, timeline review, cloud publishing, PDF/VTT/SRT export, authentication, or dashboards.
- UI prototype recording may use browser `MediaRecorder`; the later local gateway is the source of truth for production PCM capture and model events.
- Simulated captions must be visibly labeled as interface demo data and never presented as real local-model output.
- Saturday livestream audio is immutable provenance and replay input. Its transcript and translation may build a short-lived Weekly Pack, but machine-generated Chinese is never prompt-injectable until reviewed.
- Runtime retrieval may use Saturday English for matching. Translation prompts may inject only approved terms, verified scripture references, and reviewed exact bilingual examples; current live English remains the source of truth.
- The translation A0 is `sermon-milmmt-46-4b-v1-q8:benchmark` through Ollama. For `contextPolicy=none`, preserve the frozen official MiLMMT completion prompt and benchmark decoding settings (`raw=true`, temperature 0, top-k 1).
- Live English must come from the microphone PCM stream and local ASR. Synthetic or replay English is allowed only in clearly labeled automated tests and must never appear as live microphone evidence.
- Saturday workflow interchange is JSONL with one `saturday-sermon-segment-v1` object per stable English segment; keep the source audio separately and pass its SHA-256 to the pack builder.
- Every recording start creates one gateway-owned subdirectory under `artifacts/sessions/`. Persist MediaRecorder chunks and JSONL events incrementally, then finalize an atomic manifest with the audio SHA-256. Keep the browser download links as a recovery copy if gateway storage fails.
- Keep REST as the control plane (`health`, session start/finalize, replay/download) and use one bidirectional WebSocket as the live data plane when ASR is connected. Do not add WebRTC, a message broker, or direct browser-to-model connections for the single-Mac POC.
- Keep `MediaRecorder` as the independent recovery recording. Feed ASR separately with uniform 16 kHz, signed 16-bit, mono PCM frames produced off the main thread; target 100 ms frames and enforce a bounded send queue/backpressure policy.
- The gateway owns VAD, ASR, context retrieval, translation, and event persistence. ASR emits explicit `partial` and immutable `final` events; only `final` English starts translation. Keep MiLMMT non-streaming first, and add Ollama token streaming only if measured translation latency justifies it.
- Sunday operator startup uses the checked `scripts/sunday-live.sh` path and the double-clickable `Sunday Live Captions.command`; a plain browser shortcut is not a process launcher. Keep ASR and translation in separate bounded workers, expose runtime/storage degradation in the UI, and mark a session `completed` only after the live workers confirm drain and storage health.
