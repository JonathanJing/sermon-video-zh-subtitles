# Run digest 20261008-pr295-ledger-guard

Generated 2026-10-08T19:33:28+00:00. Redacted copies only; source hashes are in manifest.json.

## pr295-ledger-guard

Source: `~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/pr295-ledger-guard`

- outcome `outcome.json`: **passed** exit 0 (? → ?)

Timings `timings.tsv`:

| stage | status | seconds |
|---|---|---|
| controller-final | pass | 23.070 |

Error-like log lines (first 5 per log):

- `pr295-path-regression.log`: FAIL: test_outputs_cannot_overlap_derived_durable_roots (tests.test_canonical_layer2_controller.CanonicalLayer2ControllerTests.test_outputs_cannot_overlap_derived_durable_roots)
- `pr295-path-regression.log`: ValueError: invalid_execution_paths
- `pr295-path-regression.log`: During handling of the above exception, another exception occurred:
- `pr295-path-regression.log`: Traceback (most recent call last):
- `pr295-path-regression.log`: with self.assertRaisesRegex(ValueError, 'execution_paths_overlap'):
