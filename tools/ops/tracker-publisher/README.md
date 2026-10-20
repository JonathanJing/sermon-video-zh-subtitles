# Tracker publisher

The privileged side of the four-layer Tracker: the only process that writes to the dedicated Firestore database, using the machine's Application Default Credentials. It never runs in a browser and the browser bundle (`apps/tracker-web`) imports nothing from here.

| File | Role |
|---|---|
| `publish.mjs` | Validate one snapshot through `packages/tracker-contract` and publish it, or `--watch` a local ledger via `tools/ops/run.py observability.projections.four_layer_tracker_snapshot` and republish on semantic change. Dry run unless `--execute`. |
| `publisher-control.mjs` | `start` / `stop` / `status` for one detached watcher; health, runtime, lock and log files sit beside the watch config and are Git-ignored. |
| `bridge-mock.mjs` | Dev-only Firestore → local transport probe (`mock_ping`); applies no review. |
| `watch-config.example.json`, `fingerprint-evidence.example.json` | Templates; copy to an ignored `artifacts/` run directory. |

Paths in a watch config (`ledger`, `out`, evidence files) are relative to the repository root, as before the move. Operating instructions, including the LaunchAgent on the production MacBook, are in [apps/tracker-web/README.zh.md](../../../apps/tracker-web/README.zh.md).

```bash
cd tools/ops/tracker-publisher
npm ci --ignore-scripts
npm test
node publish.mjs --project YOUR_PROJECT --database sermon-tracker --snapshot ../../../artifacts/my-run/public-tracker-snapshot.json
```
