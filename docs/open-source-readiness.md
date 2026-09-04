# Open-Source Readiness

Chinese version: [open-source-readiness.zh.md](./open-source-readiness.zh.md)

Use this checklist for ongoing public-repository hygiene and before any release or visibility change. Repository visibility must be verified on GitHub; this document does not infer it from a remote URL.

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
sermon, subtitles, captions, chinese, translation, accessibility, local-first, apple-silicon, mlx, ollama
```

## Safety Checks

- `git status --short` is clean before publishing.
- No `.env`, cookies, service-account JSON, provider API keys, OAuth secrets, bearer tokens, webhook URLs, or private media are tracked.
- Per-run recordings, private or unreviewed transcripts/captions, session artifacts, and sermon media are not tracked. Sanitized benchmark/reference derivatives may be tracked only with authorization, provenance, and explicit review state.
- Public browser files do not include raw secret values or Secret Manager resource names.
- Docs do not publish raw secret values. Use placeholders such as `projects/PROJECT_NUMBER/secrets/openai-api-key/versions/latest` for Secret Manager references.
- If a cloud path is used, its artifacts and logs have been checked for accidental secret or generated-content exposure.
- `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md`, and Chinese counterparts are present.
- `AGENTS.md` contains contributor-agent guidance without credentials, private paths, or claims that conflict with the workflow source of truth.

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
- Add human-reviewed ASR Gold fixtures whose media rights permit repository use.
- Improve frozen replay and context-pack ablation fixtures.
- Improve local runtime observability for caption latency, drops, queue depth, and resource pressure.
