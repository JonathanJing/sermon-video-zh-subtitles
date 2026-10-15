# @tongxing/fingerprint

The spectral-landmark audio fingerprint shared by three real consumers:

- the listening web client (browser worker and offline worker),
- the production Layer 1 precompute CLI (`bin/build_fingerprint_index.mjs`, run by `scripts/sermon_pipeline.py` and the POC weekly flow),
- the iOS golden-fixture generator and the field/venue benchmarks.

It is the `packages/fingerprint/` target of the [repository layout proposal](../../docs/design/repository-layout-proposal.zh.md) §3.1.

## Layout

| Path | Role |
|---|---|
| `src/fingerprint-core.mjs` | The algorithm. `CONFIG.algorithmVersion` is part of every index and receipt. |
| `bin/build_fingerprint_index.mjs` | Node CLI: `--mode build|precompute|bind`. Flags, stdout JSON, exit behaviour and output bytes are unchanged by the move. |
| `test/core.test.mjs` | Configuration freeze, determinism, self-match, and that the CLI imports only this package. |

## Identity

Python records both files by content hash (`scripts/sermon_pipeline.py` and `scripts/run_post_live_subtitle_generation.py`, keys `scriptSha256` / `algorithmSha256`). The move changed the recorded *paths*; the core's content hash is unchanged, the CLI's changed once because its import line now points at `../src/`. Historical receipts keep their old hashes and are not rewritten.

## Browser copy

The deployed listening bundle imports `./fingerprint-core.mjs` next to the worker, and the staging scripts copy UI files by name from the web source directory. Until a build step assembles the bundle, the web source directory keeps a byte-identical copy of `src/fingerprint-core.mjs`; `tests/test_fingerprint_package.py` fails if the two differ. Edit the package file and copy it over, never the other way round:

```bash
cp packages/fingerprint/src/fingerprint-core.mjs apps/listening-web/fingerprint-core.mjs
```

## Run the tests

```bash
node --test packages/fingerprint/test/*.test.mjs
```
