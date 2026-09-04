# Repository Agent Guide

## Scope and instruction hierarchy

These instructions apply to the entire repository. A more specific `AGENTS.md`
inside a subdirectory supplements or overrides this file for work in that
subtree. In particular, read `experiments/local-live-poc/AGENTS.md` before
changing the local live-caption POC.

Use the English or Chinese README and the linked workflow documents for product
context. Do not copy changing benchmark results, model versions, or temporary
run status into this file.

## Product goal and workflow boundaries

The repository has one product goal: help Chinese-speaking attendees follow an
English sermon. It has two primary operator workflows:

1. **Saturday post-live production:** acquire authorized media, verify the full
   archive, obtain a human-confirmed sermon window, prepare the English source
   and Chinese reading text, and produce two reviewed PDFs with QA evidence.
2. **Sunday local live captions:** capture microphone audio on a MacBook, retain
   a recovery recording and event log, produce local English ASR finals, translate
   stable English into Chinese, and display large Chinese captions with smaller
   English source text.

Keep research, provider comparisons, model benchmarks, post-training work,
historical cloud/realtime prototypes, and incomplete integrations under the
Discovery or evaluation boundary. Do not present them as part of a working
operator path without current end-to-end evidence.

The main workflow source of truth is `docs/workflows/README.zh.md`. Important
workflow-specific references include:

- `docs/stable-post-live-reading-pdf-workflow.md`
- `docs/codex-local-production-runbook.zh.md`
- `docs/sermon-production-supervisor-agent.md`
- `experiments/local-live-poc/README.md`
- `experiments/local-live-poc/DESIGN.zh.md`

## Legal and content boundaries

- This is an independent personal open-source project. It is not affiliated
  with, endorsed by, sponsored by, approved by, or operated by Mariners Church.
- Process only publicly available media or media for which the user has explicit
  authorization.
- Do not bypass authentication, membership restrictions, access controls, DRM,
  platform restrictions, or copyright protections.
- Do not expose credentials, browser cookies, tokens, secret-manager values,
  private media, or personal information in code, logs, fixtures, commits, or
  generated reports.
- Do not describe machine-generated transcripts, translations, interpretations,
  or captions as official, church-approved, human-verified, or verbatim unless
  the corresponding review evidence exists.
- Preserve attribution and source provenance. Do not imply that generated output
  was authored by a speaker, church, publisher, or reviewer who did not approve it.

## Evidence and provenance

- Preserve canonical source URLs, service dates, source IDs, authorization
  context, media hashes, durations, timestamps, model/prompt identifiers, and
  review status when the workflow requires them.
- Keep source media and approved sermon-window evidence separate from generated
  transcripts, translations, and PDFs.
- Existing English subtitles may be the English/timing source. Use paid or local
  transcription for missing source text, risk review, or defined sampling rather
  than silently replacing a stronger source.
- Machine Chinese is candidate material until it is reviewed. Only explicitly
  reviewed or approved bilingual examples may enter a live translation prompt.
- Human-approved `Gold` data is the promotion boundary. Never turn provisional,
  model-reviewed, or machine-reaudited references into human Gold by renaming a
  field or relaxing a validator.
- A dry run, unit test, health endpoint, partial batch, browser screenshot, or
  generated file does not by itself prove a complete production workflow.
- Fail closed when required segments, hashes, receipts, approvals, QA reports, or
  final artifacts are missing. Keep partial results recoverable and out of
  qualified counts.

## Repository and artifact policy

- Make the smallest change that satisfies the request. Do not add unrelated
  features, refactors, dependency upgrades, formatting passes, or file moves.
- Treat unknown working-tree changes as user work. Do not overwrite, revert,
  reformat, or delete them.
- Keep the Saturday PDF workflow, Sunday live-caption POC, and post-training
  experiments structurally separate unless an explicit interface is being added.
- Do not commit generated or machine-local content covered by `.gitignore`,
  including `tmp/`, `artifacts/`, `output/pdf/`, benchmark work directories,
  raw benchmark recordings, virtual environments, build output, and secrets.
- Keep durable, reviewable structured evidence when it is needed for
  reproducibility: manifests, schemas, compact reports, metrics, event samples,
  source hashes, and human-review records.
- Large media, recovery recordings, render previews, contact sheets, downloaded
  archives, and disposable benchmark intermediates belong outside Git history.
- Do not rewrite Git history or purge old blobs unless the user explicitly asks
  for repository-history rewriting and accepts its coordination impact.

## Implementation rules

- Follow existing architecture, naming, and code style.
- Preserve immutable English ASR final events once emitted. Only stable/final
  English should start live translation.
- Recording and event persistence must remain independent of ASR or translation
  success; model failure must not destroy the recovery path.
- Keep safety-relevant validation and completion gates fail closed.
- Preserve backward-compatible artifact schemas unless the task explicitly
  requires a versioned schema change and migration plan.
- Prefer deterministic fixtures and frozen inputs for benchmark comparisons.
  Change one experimental variable at a time and record the changed variable.
- Never generalize one microphone, room, speaker, replay source, or machine result
  to venue readiness without a matching end-to-end test.

## Verification

Run verification proportional to the changed area and inspect exit status and
artifacts, not just command invocation.

For the root Python project, the CI-equivalent test command is:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

When the repository virtual environment is available, the broader local suite is:

```bash
PYTHONPATH="$PWD" .venv/bin/python -m pytest tests -q
```

For changes under `experiments/local-live-poc/`, follow its setup instructions,
then run:

```bash
npm test
```

At minimum, POC changes must cover the relevant frontend tests, backend tests,
integration tests, and a successful production build. Hardware/model changes also
require a real replay or live-path check; mocks alone are insufficient.

For documentation or repository cleanup, run `git diff --check`, verify relative
links and references to removed files, and confirm that no tracked file is also
ignored unintentionally.

If a test cannot run because credentials, models, media, hardware, network access,
or a local environment is unavailable, report exactly what was not verified and
do not claim it passed.

## Git and delivery

- Inspect `git status`, the active branch, and relevant diffs before editing.
- Keep unrelated changes out of the commit.
- Do not commit or push unless the user requests it.
- Before pushing, fetch the destination branch, check divergence, and avoid
  force-pushing unless explicitly authorized.
- After pushing, verify that the remote branch resolves to the intended commit.

## Completion report

Report the outcome first, then include:

- what changed;
- what was actually verified and the result;
- important files or systems affected;
- remaining risks, limitations, or unverified end-to-end behavior;
- commit and remote-ref details when a commit or push was requested.

Clearly distinguish verified facts, evidence-based inference, and unresolved work.
