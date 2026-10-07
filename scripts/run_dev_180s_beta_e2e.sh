#!/bin/bash
# One-shot 3-minute end-to-end check on the Mac: fixed 180 s clip -> isolated
# Dev page (zero model API, simulated review) -> new TestFlight Beta that reads
# catalog v4/v3 from the same Dev origin. Every stage logs its wall time to
# $OUT/timings.tsv. Publishing steps run only with --execute; without it the
# script stops after the local dry runs.
#
# Usage (repo root, on the frozen candidate commit):
#   scripts/run_dev_180s_beta_e2e.sh            # dry runs only
#   scripts/run_dev_180s_beta_e2e.sh --execute  # Dev publish + archive + TestFlight
# Optional env: TONGXING_EXPORT_OPTIONS (private ExportOptions.plist),
#               DEVELOPER_DIR (full Xcode, default /Applications/Xcode.app).
set -euo pipefail

EXECUTE=0
[[ "${1:-}" == "--execute" ]] && EXECUTE=1

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
RUN_ID="e2e-$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$REPO/artifacts/dev-180s-page-test-20261004/$RUN_ID"
SOURCE_RUN="$REPO/artifacts/dev-full-rerun-20261001"
XCODE="${DEVELOPER_DIR:-/Applications/Xcode.app}"
VERSION="1.26.16"
BUILD="57"
IOS_OUT="$REPO/artifacts/tongxing-ios/beta-$VERSION-build$BUILD"
mkdir -p "$OUT"
printf 'stage\tstatus\tseconds\n' > "$OUT/timings.tsv"

stage() {  # stage <name> <command...>
  local name="$1"; shift
  local start=$SECONDS
  echo "== $name"
  if "$@" > "$OUT/$name.log" 2>&1; then
    printf '%s\tpass\t%s\n' "$name" $((SECONDS - start)) | tee -a "$OUT/timings.tsv"
  else
    printf '%s\tfail\t%s\n' "$name" $((SECONDS - start)) | tee -a "$OUT/timings.tsv"
    echo "Stage $name failed; see $OUT/$name.log"; tail -20 "$OUT/$name.log"; exit 1
  fi
}

# 0. Inputs that only exist on this Mac.
[[ -x "$PY" ]] || { echo "Missing $PY"; exit 1; }
SOURCE_VIDEO="$SOURCE_RUN/dev-candidate/hosting/public/media/dryrun-20261001-dev-full-180s/source.mp4"
[[ -f "$SOURCE_VIDEO" ]] || { echo "Missing $SOURCE_VIDEO (10/1 rerun cache)"; exit 1; }
[[ -d "$REPO/artifacts/unified-cli-acceptance/native-four-product-fixture-v2" ]] || { echo "Missing native four-product fixture"; exit 1; }
git diff --quiet -- apps/tongxing-ios || { echo "Uncommitted iOS changes; archive would refuse"; exit 1; }
COMMIT="$(git rev-parse HEAD)"
echo "Commit $COMMIT  run $RUN_ID  out $OUT"

# 1. Page: fixed clip checks, simulated inputs, live Dev baseline, local preflight.
stage verify-clip   "$PY" -m scripts.verify_dev_180s_page_test --source-run "$SOURCE_RUN" --out "$OUT/preflight"
stage build-inputs  "$PY" scripts/build_dev_180s_simulated_inputs.py --run-id "$RUN_ID" --out "$OUT/inputs"
stage baseline      "$PY" scripts/prepare_dev_simulated_publication.py baseline --out "$OUT/baseline"
DELIVERY=("$PY" scripts/run_dev_simulated_delivery.py --baseline "$OUT/baseline"
          --prepared "$OUT/inputs/work/prepared" --out "$OUT/workflow" --source-video "$SOURCE_VIDEO")
stage delivery-preflight "${DELIVERY[@]}"

# 2. iOS: Apple state and archive dry run.
stage asc-status    python3 apps/tongxing-ios/scripts/testflight.py status
if grep -q "\"$BUILD\"" "$OUT/asc-status.log" || grep -q "build.*$BUILD\b" "$OUT/asc-status.log"; then
  echo "Build $BUILD may already exist on App Store Connect; check $OUT/asc-status.log before --execute"
fi
stage archive-dry   apps/tongxing-ios/scripts/archive-channel.sh --channel beta \
  --expected-commit "$COMMIT" --developer-dir "$XCODE" --output-dir "$IOS_OUT" --dry-run

if [[ $EXECUTE -eq 0 ]]; then
  echo "Dry runs passed. Re-run with --execute to publish to Dev and upload Beta $VERSION ($BUILD)."
  exit 0
fi

# 3. Publish the page to Dev (the origin TongxingBeta reads).
stage delivery-execute "${DELIVERY[@]}" --execute

# 4. Archive, export, upload, wait for Apple, distribute to Rooted.
stage archive       apps/tongxing-ios/scripts/archive-channel.sh --channel beta \
  --expected-commit "$COMMIT" --developer-dir "$XCODE" --output-dir "$IOS_OUT"
RECORD="$IOS_OUT/release-record.json"
ARCHIVE="$("$PY" -c 'import json,sys; print(json.load(open(sys.argv[1]))["archivePath"])' "$RECORD")"
EXPORT_OPTIONS="${TONGXING_EXPORT_OPTIONS:-$IOS_OUT/ExportOptions.plist}"
if [[ ! -f "$EXPORT_OPTIONS" ]]; then
  cat > "$EXPORT_OPTIONS" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>export</string>
  <key>signingStyle</key><string>automatic</string>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict></plist>
PLIST
fi
stage export-ipa    env DEVELOPER_DIR="$XCODE/Contents/Developer" xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" -exportPath "$IOS_OUT/export" -exportOptionsPlist "$EXPORT_OPTIONS" -allowProvisioningUpdates
IPA="$(find "$IOS_OUT/export" -name '*.ipa' | head -1)"
NOTES="$IOS_OUT/what-to-test.txt"
cat > "$NOTES" <<EOF
同行 Beta $VERSION ($BUILD)：读取 catalog v4（机器质检语言）并回退 v3。
测试页：Dev 三分钟测试页（模拟审核，非正式内容），run $RUN_ID。
请检查：测试页可见、三语言字幕随播放变化、语言切换不丢位置。
EOF
stage upload-dry    python3 apps/tongxing-ios/scripts/testflight.py upload --record "$RECORD" --ipa "$IPA" --dry-run
stage upload        python3 apps/tongxing-ios/scripts/testflight.py upload --record "$RECORD" --ipa "$IPA"
stage apple-wait    python3 apps/tongxing-ios/scripts/testflight.py wait --record "$RECORD"
stage distribute    python3 apps/tongxing-ios/scripts/testflight.py distribute --record "$RECORD" --notes "$NOTES" --group Rooted

echo "Done. Timings: $OUT/timings.tsv"
cat "$OUT/timings.tsv"
