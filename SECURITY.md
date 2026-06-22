# Security Policy

## Sensitive Data

Do not commit:

- API keys for OpenAI, Gemini, OpenRouter, YouTube, Bible APIs, alerting, or monitoring.
- OAuth client secrets, cookies, bearer tokens, service account JSON keys, or webhook URLs.
- Generated sermon transcripts, generated captions, model output JSONL, private audio/video, or licensed scripture text.
- GCS manifests that expose secret values or public browser artifacts that expose Secret Manager resource names.

Use Google Secret Manager for runtime secrets and a Cloud Run service account with the narrowest practical IAM permissions.

## Reporting

If you find a vulnerability or accidental secret exposure, open a private security advisory if available, or contact the repository owner directly. Do not open a public issue containing secret values, exploit details, private media, or generated transcript content.

If a secret has been exposed:

1. Revoke or rotate it immediately at the provider.
2. Remove the value from any local artifacts and logs.
3. Audit GCS, Cloud Run logs, Firestore, and generated playback files.
4. Add a regression test or documentation guard if the exposure came from code.

## Platform And Copyright Boundaries

This project must not bypass platform access controls, DRM, or terms of service. Production sources should be public streams/pages, properly authorized audio/video, or operator-provided audio.
