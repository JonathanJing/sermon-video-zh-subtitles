# Local Live-Caption POC

Follow the repository guide, then read only the relevant section of [README.md](README.md), [DESIGN.zh.md](DESIGN.zh.md), [STREAMING.zh.md](STREAMING.zh.md) or [PUBLIC_SHARING.zh.md](PUBLIC_SHARING.zh.md). This is a local React/Vite + Python Gateway application; `src/` holds UI and `backend/` holds runtime code. Check `package.json` for actual commands.

## Operator and display contract

- Keep the POC independent of the repository's `web/admin.html` and cloud production app. The default operator controls are microphone selection, start and stop; add features only when the requested task needs them.
- Prioritize large Simplified Chinese for distance reading, with smaller English source text on MacBook and phone. Keep the prior complete bilingual segment above the current segment, muted but readable. No moving marquee/transcript by default.
- When a new ASR final arrives, retain the previous complete pair before showing new English. Never pair that English with the previous segment's Chinese while translation is pending. Preserve the comparison baseline and record presentation-policy changes.
- Use a user-selected mock as the design reference. For substantial visual work, use the applicable currently available design skill and verify the actual preview; do not depend on a removed skill name or add speculative design rules.
- Label simulated/replayed captions as such. Browser/fixture output is not live-microphone proof. Make portrait/landscape layout selection work even if orientation locking is refused.

## Audio, context and recovery contract

- Live English comes from microphone PCM and local ASR. Saturday source audio is immutable replay/provenance input. Candidate machine Chinese is not eligible for live prompts until reviewed.
- Keep the frozen A0 completion prompt/decoding for `contextPolicy=none` (`raw=true`, temperature 0, top-k 1). The selected model/runtime identity belongs in its configuration and benchmark evidence, not a newly guessed default.
- Runtime retrieval may align Saturday English. `weekly_terms_v1` injects approved terms and verified scripture references mentioned in the current source, plus reviewed exact bilingual examples. The experimental `saturday_alignment_v1` may also include up to two reviewed non-exact bilingual segments with retrieval score >= 1.5, labeled as another delivery's reference wording; see the [A2 design](DESIGN.zh.md#把周六内容用作顺序讲章地图). Venue and semantic acceptance require their own evidence. Current live English remains authoritative. Interchange uses one `saturday-sermon-segment-v1` JSONL object per stable segment plus source-audio SHA-256.
- Use REST for lifecycle/health/replay/download and one bidirectional WebSocket for live PCM/events. The Gateway owns VAD, ASR, retrieval, translation and persistence; no direct browser-to-model route, broker or WebRTC for this single-Mac path unless explicitly required.
- Keep `MediaRecorder` independent for recovery; feed ASR uniform 16 kHz signed 16-bit mono PCM off the main thread, targeting 100 ms frames with bounded queues/backpressure. ASR finals are immutable; only final English starts translation. Change non-streaming MiLMMT behavior only with measured benefit and a stated experiment.
- Each start owns a Gateway session folder under `artifacts/sessions/`; persist chunks/events incrementally. Finalize an atomic manifest/hash only after workers drain and storage is healthy. Expose degradation and retain browser recovery downloads.
- Use `scripts/sunday-live.sh` / `Sunday Live Captions.command` for operator startup; a browser shortcut does not start processes. Keep ASR/translation in separate bounded workers.
- Keep the random-token LAN viewer as fallback. Public viewing uses an HTTPS frontend and outbound caption publisher; expose neither the control Gateway nor audio, logs, restart or model endpoints.

## Verification by change

Run from this POC directory after its documented setup. Select the affected tests, not every command for every edit:

| Change | Verification |
|---|---|
| Instructions/docs | Link and command checks plus `git diff --check`. |
| Frontend/display | Relevant `node --test tests/frontend/*.test.mjs` tests, `npm run build`, and actual browser interaction at affected viewport sizes. |
| Backend module | Relevant `.venv/bin/python -m unittest backend.tests.<module> -v`; include integration when its public contract changes. |
| Gateway/protocol integration | `npm run test:integration` plus affected frontend/backend tests. |
| Firebase access rules | `npm run test:firebase-rules`; cloud mutation tests only within an authorized test destination. |
| Cross-layer release | `npm test` (frontend/backend, integration, Firebase rules and build). |
| Hardware/model/audio behavior | Relevant tests plus a comparable real replay/acoustic path; identify its source, model/config and measurement endpoint. |

Run the local preview when needed for UI work and verify the resulting behavior. Preserve distinctions among browser WAV replay, physical microphone capture, actual venue input, device rendering and human semantic acceptance. Report remaining gates rather than calling local automation proof of Sunday readiness.
