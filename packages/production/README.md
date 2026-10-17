# tongxing-production

The installable Python package for the sermon four-layer pipeline. It is the
`packages/production/` target of the [repository layout proposal](../../docs/design/repository-layout-proposal.zh.md);
the [current map](../../docs/design/repository-current-map.zh.md) records what still lives in `scripts/`.

## Install

The package is part of every environment through `requirements.txt` and
`requirements-prefect.txt` (`-e ./packages/production`). For an existing
virtualenv:

```bash
python -m pip install -e packages/production
```

To import the mobile PDF renderer from a standalone package installation,
install its optional PDF dependency:

```bash
python -m pip install -e 'packages/production[pdf]'
```

The repository's `requirements.txt` already includes ReportLab for its PDF
commands; text-only and orchestration installs can keep the base package.

The post-live timeline uses the optional HTTP client. Install its extra for a
standalone package, or combine it with PDF rendering when both are needed:

```bash
python -m pip install -e 'packages/production[timeline]'
python -m pip install -e 'packages/production[pdf,timeline]'
```

The repository's `requirements.txt` already includes `requests` for this path.

## Rules

- Nothing under `src/tongxing_production/` imports `scripts`, `backend`,
  `apps`, `tools` or `experiments`, or locates files through `__file__`
  relative to a checkout. `tests/test_tongxing_production_package.py` checks
  both and that the package imports from a directory outside the repository.
- A module moves here with `git mv`, byte for byte. Its old `scripts/` path
  becomes a facade that aliases itself in `sys.modules` to the package module,
  so old and new import paths are one object. Behaviour changes go in their
  own pull request, never in a move.
- The moved file keeps a repository identity key: `sermon_accounting`
  records it as `packages/production/src/tongxing_production/<path>.py` when
  the package is loaded from under the checkout (the editable install every
  environment uses today). The key changes with the move; the content hash
  does not. Identity for a wheel installed outside the checkout is a later
  batch, together with `importlib.resources` loading.

## Moved so far

| Module | Old path | Since |
|---|---|---|
| `tongxing_production.compute.provider_limits` | `scripts/sermon_provider_limits.py` (facade kept) | 2026-10-15 |
| `tongxing_production.orchestration.unified` (`contracts`, `adapters`, `resources`, `runtime`, `backend`) | `scripts/sermon_unified/` (facade kept: binds the `Backend` and aliases the four modules) | 2026-10-15 |

## Injected collaborators

`orchestration.unified` never imports the job store, filesystem helpers, stage
implementations or the checkout. The host builds one
`orchestration.unified.backend.Backend` and calls `configure()`; the package
reads it at call time (`backend.current()`), so importing the package has no
host dependency and a missing host fails with `BackendUnbound`. Today the only
host is `scripts/sermon_unified/__init__.py`.
