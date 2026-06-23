# Open-Source Readiness

Chinese version: [open-source-readiness.zh.md](./open-source-readiness.zh.md)

This repository is intended to become a public, community-improvable project for Chinese sermon caption support. Before making the GitHub repository public, run this checklist.

## Public Positioning

- Keep the project described as an independent open-source project.
- Do not imply affiliation with, endorsement by, or operation by Mariners Church.
- Keep the product north star clear: help Chinese-speaking congregants follow the 11:30 PT sermon while it is happening.
- Invite contributors to improve caption quality, latency, accessibility, mobile/tablet UX, deployment reliability, scripture terminology, and documentation.

## Repository Metadata

Suggested GitHub description:

```text
Open-source pipeline and PWA for usable Chinese captions during Sunday English sermons.
```

Suggested topics:

```text
sermon, subtitles, captions, chinese, translation, accessibility, pwa, cloud-run, gcs, openai, gemini
```

Keep the repository private until the checks below pass.

## Safety Checks

- `git status --short` is clean before publishing.
- No `.env`, cookies, service-account JSON, provider API keys, OAuth secrets, bearer tokens, webhook URLs, or private media are tracked.
- Generated transcripts, generated captions, model JSONL, and sermon media are not tracked.
- Public browser files do not include raw secret values or Secret Manager resource names.
- Docs do not publish raw secret values. Use placeholders such as `projects/PROJECT_NUMBER/secrets/openai-api-key/versions/latest` for Secret Manager references.
- GCS artifacts and Cloud Run logs have been checked for accidental secret or generated-content exposure.
- `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, and Chinese counterparts are present.

## Useful Local Commands

```bash
git status --short
git ls-files
git diff --check
python3 -m unittest discover -s tests
node --check web/app.js
```

Quick tracked-file scan:

```bash
git ls-files | rg '(^|/)(artifacts|secrets|data/raw)/|\.env|cookies|service-account|credentials|generated\.js'
```

Quick text scan:

```bash
rg -n 'sk-[A-Za-z0-9]|AIza[0-9A-Za-z_-]|OPENAI_API_KEY=|GEMINI_API_KEY=|OPENROUTER_API_KEY=|Authorization: Bearer|BEGIN PRIVATE KEY'
```

Treat matches as review prompts. Some docs intentionally mention environment variable names; raw values must never appear.

## Contributor-Friendly First Issues

- Improve Chinese terminology consistency for sermon phrases.
- Add test fixtures for scripture and proper-name translation.
- Improve mobile and tablet caption reading ergonomics.
- Add Cloud Scheduler and Cloud Run Job deployment examples.
- Add provider benchmark fixtures for OpenAI, Gemini, and OpenRouter.
- Improve observability dashboards for trigger time, caption-ready time, and anonymous device counts.
