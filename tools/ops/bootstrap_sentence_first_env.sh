#!/usr/bin/env bash
# Create or check a locked local environment for the sentence-first tools.
#
# The production package is never editable-installed here: every command reads it from
# this checkout through PYTHONPATH, so a stale .venv editable install cannot leak in.
#
#   tools/ops/bootstrap_sentence_first_env.sh [--check] [--python-version X.Y] [ENV_PATH]
#
# Defaults: ENV_PATH=.venv-sfa, python 3.13. The dependency set is pinned by
# experiments/sentence-first-agent/requirements-sfa.lock (uv pip compile).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
EXP="$ROOT/experiments/sentence-first-agent"
LOCK="$EXP/requirements-sfa.lock"
MARKER_NAME=".sfa-lock-sha256"
MODE="create"
PYTHON_VERSION="3.13"
ENV_PATH=""

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
}

positional=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) MODE="check"; shift ;;
    --python-version) PYTHON_VERSION="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) positional+=("$1"); shift ;;
  esac
done
if [[ ${#positional[@]} -gt 1 ]]; then
  echo "expected at most one ENV_PATH" >&2
  exit 2
fi
if [[ ${#positional[@]} -eq 1 ]]; then
  ENV_PATH="${positional[0]}"
else
  ENV_PATH="$ROOT/.venv-sfa"
fi
[[ "$ENV_PATH" = /* ]] || ENV_PATH="$ROOT/$ENV_PATH"

lock_sha() {
  shasum -a 256 "$LOCK" 2>/dev/null || sha256sum "$LOCK"
}

verify() {
  local python="$1"
  PYTHONPATH="$ROOT/packages/production/src:$ROOT" "$python" - "$ROOT" <<'PY'
import importlib.metadata as metadata
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
sys.path[:0] = [str(root / "packages/production/src"), str(root)]
import tongxing_production  # noqa: E402

resolved = pathlib.Path(tongxing_production.__file__).resolve()
if not resolved.is_relative_to(root):
    raise SystemExit(f"tongxing_production resolved outside the checkout: {resolved}")
print(json.dumps({
    "python": sys.version.split()[0],
    "jsonschema": metadata.version("jsonschema"),
    "reportlab": metadata.version("reportlab"),
    "google-auth": metadata.version("google-auth"),
    "tongxing_production": str(resolved),
}, ensure_ascii=False))
PY
}

if [[ ! -f "$LOCK" ]]; then
  echo "missing lock file: $LOCK" >&2
  exit 1
fi

if [[ "$MODE" == "check" ]]; then
  python="$ENV_PATH/bin/python"
  [[ -x "$python" ]] || { echo "no python in $ENV_PATH (run without --check to create it)" >&2; exit 1; }
  expected="$(lock_sha)"
  if [[ -f "$ENV_PATH/$MARKER_NAME" ]]; then
    actual="$(cat "$ENV_PATH/$MARKER_NAME")"
    [[ "$actual" == "$expected" ]] || {
      echo "environment lock differs: $ENV_PATH was built from another requirements-sfa.lock" >&2
      exit 1
    }
  else
    echo "warning: $ENV_PATH has no $MARKER_NAME; cannot prove it matches the lock" >&2
  fi
  verify "$python"
  echo "environment OK: $ENV_PATH"
  exit 0
fi

command -v uv >/dev/null 2>&1 || { echo "uv is required (brew install uv)" >&2; exit 1; }
uv venv --python "$PYTHON_VERSION" "$ENV_PATH"
uv pip install --python "$ENV_PATH/bin/python" --requirement "$LOCK"
printf '%s\n' "$(lock_sha)" > "$ENV_PATH/$MARKER_NAME"
verify "$ENV_PATH/bin/python"
echo "environment ready: $ENV_PATH"
