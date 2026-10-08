#!/usr/bin/env bash
# Open a docs-only PR that adds one redacted run report for cloud review.
#
# Usage (repo root):
#   scripts/publish_run_report.sh artifacts/run-reports/<YYYYMMDD-label> [--base dev]
#
# The report comes from scripts/export_run_digest.py. This script re-checks its
# redaction, then commits it as docs/reports/runs/<name>/ on a new branch
# run-report/<name> cut from the base, in a detached temporary worktree, so the
# current checkout and its branches are left untouched. It pushes that branch and opens a
# draft PR with gh when gh is installed; otherwise it prints the compare URL.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <report-dir> [--base <branch>]" >&2; exit 2
fi
REPORT="$(cd "$1" && pwd)"; shift
BASE=dev
while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="$2"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

REPO="$(git rev-parse --show-toplevel)"
PY="$REPO/.venv/bin/python"; [[ -x "$PY" ]] || PY=python3
NAME="$(basename "$REPORT")"
BRANCH="run-report/$NAME"
[[ "$NAME" =~ ^[0-9]{8}-[A-Za-z0-9._-]+$ ]] || { echo "Report name must be YYYYMMDD-<label>: $NAME" >&2; exit 2; }
[[ -f "$REPORT/manifest.json" && -f "$REPORT/INDEX.md" ]] || { echo "$REPORT is not a run report" >&2; exit 2; }

"$PY" "$REPO/scripts/export_run_digest.py" --verify "$REPORT" \
  || { echo "Redaction check failed; fix the report before publishing." >&2; exit 1; }

git -C "$REPO" fetch -q origin "$BASE"
if git -C "$REPO" ls-remote --exit-code --heads origin "$BRANCH" >/dev/null; then
  echo "origin/$BRANCH already exists; pick another report name." >&2; exit 1
fi
WORKTREE="$(mktemp -d)/run-report"
git -C "$REPO" worktree add -q --detach "$WORKTREE" "origin/$BASE"
trap 'git -C "$REPO" worktree remove --force "$WORKTREE"' EXIT

TARGET="$WORKTREE/docs/reports/runs/$NAME"
mkdir -p "$TARGET"
cp -R "$REPORT/." "$TARGET/"
find "$TARGET" -name '*.zip' -delete
git -C "$WORKTREE" add "docs/reports/runs/$NAME"
git -C "$WORKTREE" commit -q -m "Add run report $NAME"
git -C "$WORKTREE" push -q origin "HEAD:refs/heads/$BRANCH"
echo "Pushed $BRANCH ($(git -C "$WORKTREE" rev-parse --short HEAD))"

TITLE="运行报告：$NAME"
BODY="自动生成的脱敏运行报告，供云端复盘。报告目录：docs/reports/runs/$NAME/

$(sed -n '1,60p' "$REPORT/INDEX.md")"
if command -v gh >/dev/null; then
  (cd "$REPO" && gh pr create --base "$BASE" --head "$BRANCH" --draft --title "$TITLE" --body "$BODY")
else
  URL="$(git -C "$REPO" remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)#https://github.com/#; s#\.git$##')"
  echo "Open the PR: $URL/compare/$BASE...$BRANCH?expand=1"
fi
