#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
runtime_env="$poc_dir/firebase/runtime.env"

if [ ! -f "$runtime_env" ]; then
  echo "Missing $runtime_env; copy firebase/runtime.env.example and configure it first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "$runtime_env"
set +a

cd "$poc_dir"
python_bin="${LOCAL_LIVE_PYTHON:-.venv/bin/python}"
if [ ! -x "$python_bin" ]; then
  echo "Python environment is unavailable: $python_bin" >&2
  exit 1
fi

PYTHONPATH="$poc_dir" "$python_bin" scripts/test-firebase-cloud.py
