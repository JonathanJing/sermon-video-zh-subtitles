# Architecture SVG rendering / 架构图再生成

The six current architecture diagrams use the existing native SVG renderer and `diagram-specs.json`. Node labels, geometry, edge routes, status and accessibility descriptions are editable in that JSON; no bitmap, remote font or script is embedded. The Markdown documents retain matching Mermaid topology as copyable plain-text source in a disclosure. Static SVG is the default because GitHub rich Mermaid preview returned “Unable to render rich display” during verification.

```sh
python3 docs/diagrams/render_diagrams.py --spec docs/diagrams/diagram-specs.json --out-dir /tmp/tongxing-diagrams-check
```

Compare the six generated files with their checked-in counterparts. For documentation-only PRs, the existing docs CI gate regenerates all diagrams whenever the spec changes and rejects differences. Renderer changes trigger full code CI instead; run the same regeneration comparison explicitly. Existing historical diagram content and geometry remain unchanged. The renderer accepts an optional `arrowStroke` fallback for the six new diagrams so static rasterizers show their arrowheads; older specs retain their previous output.

| SVG | Document / editable topology |
|---|---|
| architecture-dag-en.svg | [English technical overview](../project-technical-overview.md) |
| review-revision-dag-en.svg | [English technical overview](../project-technical-overview.md) |
| architecture-dag-zh-en.svg | [Bilingual backend](../backend-workflow-system-design.zh-en.md) |
| review-revision-dag-zh-en.svg | [Bilingual backend](../backend-workflow-system-design.zh-en.md) |
| app-system-architecture.svg | [App](../app-system-design.zh.md) |
| execution-environments.svg | [Environments](../execution-environment-design.zh.md) |

Preserve identical English/bilingual node IDs and edges. Verify acyclicity, each locale's mandatory Audio Package (including explicit audio_unavailable), and review/repair status. Each return-shaped repair arrow goes to a **new revision** in the next column; it never returns to a previous node. For visual checks, render the SVG at its full viewBox and README width, check text against data-box bounds, and inspect arrows and labels. The standard renderer's small bilingual maintenance footer is shared with the existing diagram family; English DAG business labels remain English.
