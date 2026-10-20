# Run digest 20261018-es-r4-zero-call-provenance-fix

Generated 2026-10-18T06:41:19+00:00. Redacted copies only; source hashes are in manifest.json.

## 20261018-es-r4-zero-call

Source: `~/.codex/worktrees/layer2-plugin-policy-budget-provenance/artifacts/production-runs/20261018-es-r4-zero-call`

- outcome `outcome.json`: **failed** exit 1 (2026-10-18T06:34:22.290632+00:00 → ?)
- summary `summary.json`: **failed**

Timings `timings.tsv`:

| stage | seconds | status |
|---|---|---|
| layer2-es-r4-admission | 2.000 | failed |

Failed stages: `layer2-es-r4-admission`

Error-like log lines (first 5 per log):

- `worker.log`: Traceback (most recent call last):
- `worker.log`: raise ValueError(code)
- `worker.log`: ValueError: layer2_reuse_operation_missing

## 20261018-plugin-policy-budget-provenance

Source: `~/.codex/worktrees/layer2-plugin-policy-budget-provenance/artifacts/test-runs/20261018-plugin-policy-budget-provenance`

- outcome `outcome.json`: **passed** exit 0 (2026-10-18T06:38:54.753082+00:00 → ?)
- summary `summary.json`: **passed**

Timings `timings.tsv`:

| stage | seconds | status |
|---|---|---|
| layer2-provenance-targeted-tests | 30.604 | passed |

Failed stages: `layer2-provenance-targeted-tests`
