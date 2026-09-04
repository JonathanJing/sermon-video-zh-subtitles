#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "$0")" && pwd)"
"$project_dir/scripts/stop-sunday-live.sh"

echo
echo "This window will close in 3 seconds."
sleep 3
