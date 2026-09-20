# Repository Agent Guide

## Start with the task

Help Chinese-speaking attendees follow an English sermon. The operator paths are Saturday post-live dual-PDF production and Sunday MacBook live captions. Benchmarks, post-training, historical cloud prototypes and incomplete integrations remain Discovery until their own acceptance evidence exists.

Read the relevant entry below first, then follow links only when the task needs that detail. [The workflow map](docs/workflows/README.zh.md) is the product-level source of truth; dated reports describe observed runs, not current service health.

| Task | First reference |
|---|---|
| Weekly production, resume, approval or delivery | [Local production runbook](docs/codex-local-production-runbook.zh.md) |
| Manual archive-to-PDF run | [Stable post-live workflow](docs/stable-post-live-reading-pdf-workflow.md) |
| Supervisor state/tools | [Supervisor contract](docs/sermon-production-supervisor-agent.md) |
| Local live-caption code/UI | [POC instructions](experiments/local-live-poc/AGENTS.md), then its relevant README/design section |
| Offline timed-subtitle backup | [Fallback skill](skills/live-caption-zh-fallback/SKILL.md), also discoverable through `.agents/skills/` |
| Architecture, benchmarks or post-training | README Discovery links and the specific experiment's contract/report |

Subdirectory `AGENTS.md` applies within its subtree. Keep changing model versions, run metrics and temporary task state in the referenced documents, not this file.

Before producing or reviewing series pages, subtitles, reading text, outlines or dubbing, read [the shared series terminology table](docs/series-terminology.zh.md). Reuse its established translations and follow its contextual usage and pre-dubbing checks. When a verified new series enters production, automatically append it to that same table with source evidence; preserve existing entries and active runs. The table documents current script-integration limits; do not claim a stage consumed it without evidence.

## Source and acceptance invariants

- This independent personal project is not affiliated with or endorsed/operated by Mariners Church. Preserve source attribution; label generated content accurately, without claims of official, human-verified or verbatim status lacking evidence.
- Use public or user-authorized media without bypassing access restrictions. Keep credentials, cookies, private media and personal information out of code, logs, public artifacts and Git.
- Preserve canonical URL/ID, service date, media hash/duration, timestamps, model/prompt identity and review state as required by the workflow. Separate source media, approved boundaries and generated outputs.
- Existing English subtitles may supply text and timing. Use ASR for missing text, defined sampling or risk review, retaining provenance; reading-block timing is not synchronized subtitle timing.
- Human sermon-window approval is bound to the source and timeline evidence. Reuse a still-valid approval; changed inputs invalidate it. Machine review never becomes human Gold through relabeling or a weaker validator.
- Only reviewed/approved bilingual examples may enter live translation prompts; machine Chinese remains candidate material. Current live English/audio is authoritative, and optional Saturday material must fail down by capability.
- Preserve immutable English ASR finals, translate only stable/final English, and keep recording/event persistence independent of model success. Recovery recordings must survive model failure.
- Missing required hashes, segments, approvals, QA or publication evidence prevents completion. Keep partial work recoverable and outside qualified counts. A test, health check, screenshot or replay alone does not prove production/venue readiness.

## Work and artifacts

Inspect the current branch and relevant diffs before editing; preserve unrelated user work. Follow existing architecture and schema contracts, changing schemas only with an explicit version/migration when required. Keep Saturday production, live POC and post-training separate unless the requested interface joins them.

Resume from verified artifacts rather than restarting paid stages. Delegate independent exploration/review when useful; keep state-changing Supervisor stages sequential and lease-protected. For comparisons, freeze inputs and record the changed experimental variable. Do not replace intentionally selected workload models merely to standardize on Astra.

Keep ignored media, `artifacts/`, `tmp/`, `output/pdf/`, recordings, environments and build outputs outside Git. Commit only the compact schemas/manifests/review evidence needed for reproducibility. History rewriting requires explicit authorization.

## Verify the changed area

| Change | Relevant verification |
|---|---|
| Documentation/instructions only | `git diff --check`, affected links, command/path references, skill metadata/discovery. No full model or hardware run. |
| Root Python code | Targeted affected tests first. CI suite: `python -m unittest discover -s tests -p "test_*.py"`; broader local suite when needed: `PYTHONPATH="$PWD" .venv/bin/python -m pytest tests -q`. |
| Supervisor prompt/state contract | `.venv/bin/python -m unittest tests.test_run_sermon_production_supervisor_agent tests.test_sermon_production_supervisor tests.test_run_codex_local_sermon_production` |
| POC code, UI, model or hardware | Use its scoped verification table. Cross-layer release changes need the full POC suite and relevant real-path evidence. |

Inspect exit status and artifacts. After relevant checks pass, widen/repeat only for new changes, failures or unresolved risks. Distinguish synthetic tests, file replay, acoustic input and real-venue/mobile acceptance. If a required environment is unavailable, report the exact unverified path and how to run it.

## Weekly poster delivery

A poster is a default weekly deliverable after the content release and its HTTP verification, without requiring a fresh weekly request. Follow [the poster delivery procedure](docs/tongxing-weekly-release.zh.md#每周海报交付) and reuse verified artifacts. Codex uses the built-in ImageGen tool for the main artwork; `scripts/build_sermon_poster.py` composes catalog-derived Chinese metadata and a real QR code for the exact `?week=<page-id>` link. Without `--art`, prepare the brief/prompt only; render with `--art`, `--art-prompt` and a valid `--verification` receipt (or the release-local default `http-verification.json`). Verify decoding of both `poster.png` and `poster-preview.png`, then visually inspect both. Only after that inspection, repeat the same rendering arguments with `--visual-reviewed` to record Codex visual QA in `poster-receipt.json`, retaining `humanApproval: false`. Keep poster QA separate from publication, listening and live-sync acceptance. Preparation/composition must not automatically call paid APIs, upload the poster or send messages; report and retain any unfinished generation/QA stage rather than claiming completion. Do not alter the page's review status through promotional wording.

## Delivery

Report the result, meaningful verification and remaining limits. Do not commit or push unless requested. Keep commits scoped; before a requested push, fetch/check divergence, then verify the remote commit. Force-push requires explicit authorization.
