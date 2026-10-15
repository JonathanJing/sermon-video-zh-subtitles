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
  records it as `packages/production/src/tongxing_production/<path>.py`
  whether it was loaded from the checkout or from site-packages. The key
  changes with the move; the content hash does not.

## Moved so far

| Module | Old path | Since |
|---|---|---|
| `tongxing_production.compute.provider_limits` | `scripts/sermon_provider_limits.py` (facade kept) | 2026-10-15 |
