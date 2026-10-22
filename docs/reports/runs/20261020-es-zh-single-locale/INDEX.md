# Run digest 20261020-es-zh-single-locale

Redacted digest for the es/zh Layer 3 work, the blocked three-locale publish, and the
single-locale Dev publish that followed. Raw artifacts stay in the ignored `artifacts/`
tree; this report commits only summaries.

## Sources

- `artifacts/clip-e2e-20261020-grp-es-full/` — es full L3 + ko/zh attempts + zh human review
- `artifacts/clip-e2e-20261020-es-solo-v2/` — fresh single-locale es L3 and Dev publish

## Outcomes

| Run | Outcome | Spend |
|---|---|---|
| es full L3 (16 units) | pass; machine audio waiver issued | $0.299 |
| ko full L3 / repairs | audio QC failed at `translation-chunk-0005-u007`; 503 reconciled as a definitive failure | $0.357 |
| zh-Hans L3 | audio QC pass; machine waiver refused by calibration coverage; human audio review recorded | $0.360 |
| es single-locale round | text + audio QC pass; published to Dev; live v4 catalog lists one locale | $0.658 |
| **Total settled** | | **$1.674** |

## Publication evidence

- Page: `mockup-dev-clip-20261020-es-solo-v2`
- Live URL: `https://ai-for-god-sermon-audio-dev.web.app/?week=mockup-dev-clip-20261020-es-solo-v2&contentLang=es` (HTTP 200)
- Live v4 catalog: page present with `targets={es}`
- Browser smoke: es passed once after publication (`l4/browser-smoke-retry-1.json`); later reruns failed in the smoke observer (`observer exit 0`), not in page rendering.

## Code

- Merged before this report: PR #1206–#1210 (per-group orchestration and run reports).
- Branch `codex/group-pipeline-orchestration`, draft PR #1218: `d4b8d318`, `ae5408eb`, `825d8241`, `50f1e5a7`, `5f01fe6a`, `211963cc`, `5ebac30a`, `71679bbc`.

## Limits

- Three-locale publication was not completed: ko audio QC failed and zh relied on a human
  audio receipt that the machine-checked L4 path does not consume.
- The Dev publish workflow needed several diagnostic-only contract relaxations; production
  pages still require three locales.
