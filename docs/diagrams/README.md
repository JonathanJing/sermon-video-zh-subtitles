# Diagram Assets

These SVG files are the repository's maintained visual summaries. They use bilingual labels where one asset is shared by English and Chinese documentation.

| Asset | Purpose | Primary documents |
|---|---|---|
| `project-map.svg` | Two operator workflows, shared evidence, and Discovery boundary | root READMEs |
| `solution-journey.svg` | Observed bottlenecks, rejected assumption, current hybrid, and gated future enhancement | root READMEs |
| `saturday-post-live-workflow.svg` | Detailed Saturday dual-PDF gates and retry branches | workflow and stable post-live docs |
| `sunday-live-workflow.svg` | Detailed Sunday live path and visible degradation branches | workflow and POC docs |
| `saturday-to-sunday-context-pack-flow.svg` | Guarded Saturday evidence handoff, readiness selection, and Sunday runtime fallback | Context Pack plan and POC docs |
| `local-live-architecture.svg` | Current localhost components, protocols, providers, and evidence | POC design and streaming docs |
| `live-runtime-sequence.svg` | Runtime event sequence from capture through finalize | workflow and streaming docs |
| `supervisor-control-plane.svg` | Bounded Agent, deterministic tools, human approval, and completion gate | Supervisor docs |
| `evidence-promotion-gates.svg` | Difference between smoke, reviewed reference, Gold, soak, venue, and promotion | benchmark docs |
| `historical-cloud-architecture.svg` | Explicitly historical Cloud/Discovery architecture | historical system-design docs |

Editing rules:

- Keep a `viewBox`, accessible `<title>` and `<desc>`, and a light neutral canvas so GitHub light and dark themes remain readable.
- Do not put live credentials, private URLs, local user paths, or generated sermon content in a diagram.
- Update the relevant prose and SVG in the same change when a workflow contract changes.
- Validate every SVG with `xmllint --noout docs/diagrams/*.svg` and verify the Markdown links before commit.
