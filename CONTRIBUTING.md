# Contributing

Thanks for helping improve the sermon Chinese caption pipeline.

This project is being prepared for broader open-source collaboration. The most
useful contributions are the ones that make the 11:30 PT congregation caption
experience more reliable, readable, accurate, and easy to operate.

## Project Goal

The north star is practical: Chinese-speaking congregants should have usable Chinese captions during the Sunday 11:30 PT sermon. Please evaluate product, model, UI, and infrastructure changes by whether they improve that service-time experience.

## Development Principles

- Keep generated sermon content, transcripts, captions, model outputs, API keys, cookies, and credentials out of Git.
- Use Google Secret Manager for provider keys and sensitive tokens.
- Store generated artifacts in the configured GCS bucket, not in committed files.
- Respect platform permissions and copyright. Do not add code or docs that bypass access controls, DRM, or terms of service.
- Keep the congregation view simple and low-distraction; keep review controls in the operator view.
- Prefer deterministic tests and fixtures over live network calls.

## Good First Contribution Areas

- Improve Chinese terminology consistency for scripture, names, and sermon phrases.
- Add fixtures that test translation quality around Bible references and proper names.
- Improve mobile and tablet reading ergonomics for the congregation view.
- Add provider benchmark cases for OpenAI, Gemini, and OpenRouter.
- Improve Cloud Run, Cloud Scheduler, Cloud Run Job, and GCS deployment examples.
- Improve observability for trigger time, caption-ready time, stage duration, and anonymous device counts.
- Improve bilingual documentation without changing runtime behavior.

## Documentation Language

The repository defaults to English for open-source readability. Chinese documents live beside their English counterparts with `.zh.md` filenames.

When adding or materially changing a public document:

1. Update the English document first.
2. Add or update the Chinese counterpart.
3. Update both `docs/README.md` and `docs/README.zh.md` if the document is part of the core reading path.

## Local Checks

Run the Python test suite before opening a pull request:

```bash
python3 -m unittest discover -s tests
```

For documentation-only changes, also check that links point to existing files and that no generated artifacts are staged.

Before a broad public release, run the [open-source readiness checklist](./docs/open-source-readiness.md).

## Pull Request Checklist

- The change supports the 11:30 congregation caption goal.
- No secret values, cookies, raw transcripts, generated model output, or large media files are committed.
- User-facing docs are updated in English and Chinese where applicable.
- Tests are added or updated for behavior changes.
- The public browser bundle does not expose Secret Manager resource names or secret values.

See the [Security Policy](./SECURITY.md) for reporting vulnerabilities or accidental secret exposure.
