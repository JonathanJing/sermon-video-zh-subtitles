# @tongxing/tracker-contract

The closed public projection for the four-layer Tracker, shared by the two real consumers the layout proposal (§3.2) keeps apart:

- `tools/ops/tracker-publisher/publish.mjs` runs `sanitizeSnapshot` before the only Firestore write, so unknown fields never leave the machine;
- `apps/tracker-web/src/snapshot-state.js` runs the same function on every document it renders, so the browser trusts nothing the sanitizer did not pass.

| File | Role |
|---|---|
| `src/sanitize.mjs` | `sanitizeSnapshot`: field-allowlisted projection of `sermon-public-tracker-snapshot-v1/v2`; v1 input is upgraded to v2 with missing counters kept `null`. |
| `src/dag-contract.js` | `sanitizeDag` and the enumerations of `sermon-public-tracker-dag-v1`: executors, model allowlist, statuses, reason codes; rejects cycles and oversized graphs. |

No dependencies, no Node APIs, no file or network access. Tests for both functions live beside the consumers (`apps/tracker-web/tests/dag.test.mjs`, `tools/ops/tracker-publisher/tests/publish.test.mjs`) until a shared positive/negative fixture set exists here.
