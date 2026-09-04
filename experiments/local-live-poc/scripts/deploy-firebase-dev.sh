#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
firebase_dir="$poc_dir/firebase"
project_id="ai-for-god-caption-dev"
database_url="https://ai-for-god-caption-dev.firebaseio.com"

gcloud projects describe "$project_id" --format='value(projectId)' | grep -qx "$project_id"

firebase_oauth_token="$(gcloud auth print-access-token)"
curl -fsS -X PUT \
  -H "Authorization: Bearer ${firebase_oauth_token}" \
  -H 'Content-Type: application/json' \
  --data-binary "@$firebase_dir/database.rules.json" \
  "$database_url/.settings/rules.json" >/dev/null

cd "$firebase_dir"
GOOGLE_CLOUD_QUOTA_PROJECT="$project_id" \
  npx --yes firebase-tools@15.29.0 deploy \
    --only hosting \
    --project "$project_id" \
    --message "Deploy public caption dev viewer and RTDB rules"

echo "Firebase dev deployment complete: https://ai-for-god-caption-dev.web.app"
