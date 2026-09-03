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
