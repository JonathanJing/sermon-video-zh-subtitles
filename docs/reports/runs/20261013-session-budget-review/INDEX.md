# Run digest 20261013-session-budget-review

Generated 2026-10-13T17:17:29+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261013-pr379-readback-review

Source: `/private/tmp/sermon-fix-379/artifacts/run/20261013-pr379-readback-review`

- outcome `outcome.json`: **pass** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| publish-related-five-modules | pass | 0.57 |

Error-like log lines (first 5 per log):

- `development-fixture.log`: now, timeouts = [0.0], []
- `development-fixture.log`: def download(req, *, timeout):
- `development-fixture.log`: timeouts.append(timeout)
- `development-fixture.log`: if len(timeouts) == 1: raise http.client.IncompleteRead(b'partial', 10)
- `development-fixture.log`: monkeypatch.setattr(publication.publisher, 'PROPAGATION_TIMEOUT_SECONDS', 12)
- `development-negative.log`: now, timeouts = [0.0], []
- `development-negative.log`: def download(req, *, timeout):
- `development-negative.log`: timeouts.append(timeout)
- `development-negative.log`: if len(timeouts) == 1: raise http.client.IncompleteRead(b'partial', 10)
- `development-negative.log`: monkeypatch.setattr(publication.publisher, 'PROPAGATION_TIMEOUT_SECONDS', 12)
- `initial.log`: contract.require(timeout > 0 and interval > 0, 'Propagation timeout and interval must be positive')
- `initial.log`: ok = False, message = 'Propagation timeout and interval must be positive'
- `initial.log`: >           raise ValueError(message)
- `initial.log`: E           ValueError: Propagation timeout and interval must be positive
- `initial.log`: scripts/delivery_contract.py:18: ValueError

## 20261013-pr380-api-outcomes

Source: `/private/tmp/sermon-fix-380/artifacts/run/20261013-pr380-api-outcomes`

- outcome `outcome.json`: **pass** exit ? (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 3.46 |

Not copied: 1 .md, 1 .txt

## 20261013-pr381-reuse-safety

Source: `/private/tmp/sermon-fix-381/artifacts/run/20261013-pr381-reuse-safety`

- outcome `outcome.json`: **pass** exit ? (? → ?)

Timings `timings.tsv`:

| stage | status | elapsedSeconds |
|---|---|---|
| pytest | pass | 0.59 |

Error-like log lines (first 5 per log):

- `pytest-initial-fixture-fail.log`: E       FileNotFoundError: [Errno 2] No such file or directory: '/private/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/pytest-of-jonathan_jing/pytest-104/test_legacy_ledgers_keep_their0/dest'
- `pytest-initial-fixture-fail.log`: scripts/sermon_workflow_jobs.py:56: FileNotFoundError
- `pytest-initial-fixture-fail.log`: E       FileNotFoundError: [Errno 2] No such file or directory: '/private/var/folders/s2/0bt6pz_51h1899zqs32x4vm80000gn/T/pytest-of-jonathan_jing/pytest-104/test_legacy_ledgers_keep_their1/dest'
- `pytest-initial-fixture-fail.log`: scripts/sermon_workflow_jobs.py:56: FileNotFoundError
- `pytest-initial-fixture-fail.log`: FAILED tests/test_source_budget_reuse_safety.py::test_legacy_ledgers_keep_their_contract_and_require_explicit_reuse_upgrade[sermon-source-budget-ledger-v2]

Not copied: 1 .md

## 20261013-session-budget-integration

Source: `~/.codex/worktrees/merge-qc-dev-prs/sermon-video-zh-subtitles/artifacts/run/20261013-session-budget-integration`

- outcome `outcome.json`: **pass** exit 0 (? → ?)
- summary `summary.json`: **pass**

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| integration_pytest | pass | 3.55 |
