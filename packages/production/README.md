# tongxing-production

The installable Python package for the sermon four-layer pipeline. It is the
`packages/production/` target of the [repository layout proposal](../../docs/design/repository-layout-proposal.zh.md);
the [repository map](../../docs/design/repository-current-map.zh.md) separates the dated migration snapshot from current paths. `scripts/` retains hosts, compatibility facades and frozen legacy files.

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

## Package areas and operator entrypoint

The current source tree includes `source`, `text`, `audio`, `delivery`, `review`,
`orchestration`, `compute`, `observability`, `storage`, `contracts`, `adapters`
and `workflows`. This replaces the early two-module migration inventory;
individual moves and facade closures retain their original dated records.
See the [four-layer contract](../../docs/multilingual-production-interfaces.zh.md)
and [facade plan](../../docs/design/facade-removal-plan.zh.md) for boundaries.

Invoke a command module from the repository with the host bound:

```bash
.venv/bin/python tools/ops/run.py <area.module> [arguments ...]
```

For example, `text.candidate --help` selects
`tongxing_production.text.candidate`. See the
[package CLI guide](../../docs/design/package-cli-entry.zh.md).

## Injected collaborators

`orchestration.unified` never imports the job store, filesystem helpers, stage
implementations or the checkout. The host builds one
`orchestration.unified.backend.Backend` and calls `configure()`; the package
reads it at call time (`backend.current()`), so importing the package has no
host dependency and a missing host fails with `BackendUnbound`. The unified orchestration host is `scripts/sermon_unified/__init__.py`;
`tools/ops/run.py` binds it for the command families that require it, after
binding the shared production and Tracker hosts.
