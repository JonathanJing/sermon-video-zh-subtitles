# Diagram Assets

Code baseline: `main@beeda82` (2026-09-04). Runtime evidence is linked in the [readiness report](../../experiments/local-live-poc/benchmarks/SUNDAY_READINESS_20260904.zh.md); diagrams describe contracts, not live health.

These SVG files are the repository's maintained visual summaries. They use bilingual labels where one asset is shared by English and Chinese documentation.

| Asset | Purpose | Primary documents |
|---|---|---|
| `project-map.svg` | Two operator workflows, shared evidence, and Discovery boundary | root READMEs |
| `solution-journey.svg` | Observed bottlenecks, rejected assumption, current hybrid, and gated future enhancement | root READMEs |
| `saturday-chinese-voice-workflow.svg` | Optional speaker-training / Chinese audio extension, inherited Saturday reviews and Sunday playback gates | dubbing plan and audio extension runbook |
| `saturday-post-live-workflow.svg` | Astra Medium weekly profile, dual-PDF QA, automatic export and separate readiness gates | workflow and stable post-live docs |
| `sunday-live-workflow.svg` | Detailed Sunday live path and visible degradation branches | workflow and POC docs |
| `saturday-to-sunday-context-pack-flow.svg` | Guarded Saturday evidence handoff, readiness selection, and Sunday runtime fallback | Context Pack plan and POC docs |
| `local-live-architecture.svg` | Gateway-owned inference/storage, recovery, outbound Firebase and LAN fallback | POC design and streaming docs |
| `live-runtime-sequence.svg` | Gateway-mediated capture/model/render events; latest-connection drain before finalize | workflow and streaming docs |
| `supervisor-control-plane.svg` | Bounded Agent, deterministic tools, human approval, and completion gate | Supervisor docs |
| `evidence-promotion-gates.svg` | Difference between smoke, reviewed reference, Gold, soak, venue, and promotion | benchmark docs |
| `historical-cloud-architecture.svg` | Explicitly historical Cloud/Discovery architecture | historical system-design docs |

Editing rules:

- Keep a `viewBox`, accessible `<title>` and `<desc>`, and a light neutral canvas so GitHub light and dark themes remain readable.
- Do not put live credentials, private URLs, local user paths, or generated sermon content in a diagram.
- Update the relevant prose and SVG in the same change when a workflow contract changes.
- Validate every SVG with `xmllint --noout docs/diagrams/*.svg` and verify the Markdown links before commit.

Source anchors: `backend/live_pipeline.py`, `gateway.py`, `session_store.py`, `firebase_publisher.py`, and `src/App.jsx` under the POC; root `scripts/sermon_production_supervisor.py`, `run_post_live_subtitle_generation.py`, and `export_saturday_live_context.py`. The historical cloud diagram remains explicitly historical.
