# Tracker Firebase deployment

Hosting and Firestore configuration for the public four-layer Tracker site. Deploy from this directory; `.firebaserc` (project alias and the `sermonTrackerAdmin` target binding) is local and Git-ignored.

- `firebase.json`: Hosting target `sermonTrackerAdmin`, CSP and cache headers, `public` pointing at the app's build output `../../../apps/tracker-web/dist`; Firestore database `sermon-tracker` with its rules and indexes.
- `firestore.rules`: public read of published snapshots, no client writes.
- `firestore.indexes.json`.

```bash
cd apps/tracker-web && npm ci --ignore-scripts && npm run build && cd -
cd infra/firebase/tracker
firebase target:apply hosting sermonTrackerAdmin YOUR_TRACKER_SITE --project YOUR_PROJECT
firebase deploy --only firestore:sermon-tracker --project YOUR_PROJECT
firebase deploy --only hosting:sermonTrackerAdmin --project YOUR_PROJECT
```

Deploying the rules overwrites the rules of the named database; never point this configuration at the feedback database.
