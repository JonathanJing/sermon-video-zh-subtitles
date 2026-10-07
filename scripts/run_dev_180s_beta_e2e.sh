#!/bin/bash
# One-shot 3-minute end-to-end check on the Mac: fixed 180 s clip -> isolated
# Dev page (zero model API, simulated review) -> new TestFlight Beta that reads
# catalog v4/v3 from the same Dev origin. Every stage logs its wall time to
# $OUT/timings.tsv. Publishing steps run only with --execute; without it the
# script stops after the local dry runs.
#
# Usage (repo root, on the frozen candidate commit):
#   scripts/run_dev_180s_beta_e2e.sh                        # dry runs only
#   scripts/run_dev_180s_beta_e2e.sh --execute              # publish the page to Dev
#   scripts/run_dev_180s_beta_e2e.sh --execute --with-beta  # also archive + TestFlight
# The current Beta already reads Dev release/catalog v3, so this simulated page
# needs no new build. --with-beta is only for clients that must read catalog v4
# (machine-checked locales).
# Optional env: TONGXING_EXPORT_OPTIONS (private ExportOptions.plist),
#               DEVELOPER_DIR (full Xcode, default /Applications/Xcode.app).
set -euo pipefail

EXECUTE=0
WITH_BETA=0
for argument in "$@"; do
  case "$argument" in
    --execute) EXECUTE=1 ;;
    --with-beta) WITH_BETA=1 ;;
    *) echo "Unknown argument: $argument"; exit 2 ;;
  esac
done

REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"
PY="$REPO/.venv/bin/python"
RUN_ID="e2e-$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$REPO/artifacts/dev-180s-page-test-20261004/$RUN_ID"
SOURCE_RUN="$REPO/artifacts/dev-full-rerun-20261001"
XCODE="${DEVELOPER_DIR:-/Applications/Xcode.app}"
XCODE="${XCODE%/}"; XCODE="${XCODE%/Contents/Developer}"  # accept either form
# --with-beta archives the TongxingBeta app's BetaRelease version/build as
# committed in project.yml; bump them first to a number App Store Connect has
# not used.
read -r VERSION BUILD < <(python3 - apps/tongxing-ios/project.yml <<'PARSE'
import re, sys
block, found = None, {}
for line in open(sys.argv[1], encoding="utf-8"):
    indent = len(line) - len(line.lstrip())
    if re.fullmatch(r" +BetaRelease:\n", line):
        block, values = indent, {}
        continue
    if block is not None and line.strip() and indent <= block:
        if values.get("PRODUCT_BUNDLE_IDENTIFIER") == "com.jonathanjing.tongxing.beta":
            found = values
        block = None
    if block is not None:
        match = re.match(r' *(\w+): "?([^"\n]*)"?$', line)
        if match:
            values[match[1]] = match[2]
print(found.get("MARKETING_VERSION", ""), found.get("CURRENT_PROJECT_VERSION", ""))
PARSE
)
if [[ $WITH_BETA -eq 1 && ( -z "$VERSION" || -z "$BUILD" ) ]]; then
  echo "Could not read the TongxingBeta BetaRelease version/build from project.yml"; exit 1
fi
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
# The recorded commit must be what builds and publishes the page (and the app).
if [[ $EXECUTE -eq 1 || $WITH_BETA -eq 1 ]]; then
  git diff --quiet HEAD -- scripts schemas experiments apps/tongxing-ios \
    || { echo "Uncommitted changes to page, publish or app inputs; commit or stash them first"; exit 1; }
fi
COMMIT="$(git rev-parse HEAD)"
echo "Commit $COMMIT  run $RUN_ID  out $OUT"

# 1. Page: fixed clip checks, simulated inputs, live Dev baseline, local preflight.
stage verify-clip   "$PY" -m scripts.verify_dev_180s_page_test --source-run "$SOURCE_RUN" --out "$OUT/preflight"
stage build-inputs  "$PY" scripts/build_dev_180s_simulated_inputs.py --run-id "$RUN_ID" --out "$OUT/inputs"
stage baseline      "$PY" scripts/prepare_dev_simulated_publication.py baseline --out "$OUT/baseline"
DELIVERY=("$PY" scripts/run_dev_simulated_delivery.py --baseline "$OUT/baseline"
          --prepared "$OUT/inputs/work/prepared" --out "$OUT/workflow" --source-video "$SOURCE_VIDEO")
stage delivery-preflight "${DELIVERY[@]}"

# 2. iOS: Apple state and archive dry run (only with --with-beta).
if [[ $WITH_BETA -eq 1 ]]; then
stage asc-status    python3 apps/tongxing-ios/scripts/testflight.py status
# testflight.py prints only its private evidence directory; the build list is in
# that directory's apple-state.json. Stop before archiving on a used build number.
SNAPSHOT="$(sed -n 's/.*private evidence: //p' "$OUT/asc-status.log" | tail -1)/apple-state.json"
[[ -f "$SNAPSHOT" ]] || { echo "No Apple snapshot at $SNAPSHOT"; exit 1; }
# App Store Connect scopes build numbers by version, as fastlane's beta_builds query does.
USED="$("$PY" - "$SNAPSHOT" "$VERSION" "$BUILD" <<'CHECK'
import json, sys
builds = json.load(open(sys.argv[1], encoding="utf-8"))["builds"]
print(" ".join(f"{b['version']}({b['build']})" for b in builds
               if str(b["version"]) == sys.argv[2] and str(b["build"]) == sys.argv[3]))
CHECK
)"
if [[ -n "$USED" ]]; then
  echo "$VERSION ($BUILD) is already on App Store Connect; bump the TongxingBeta BetaRelease build first"; exit 1
fi
# archive-channel.sh builds the generated Tongxing.xcodeproj, so it must carry
# the same version/build that the collision check and notes use.
read -r BUILT_VERSION BUILT_BUILD < <(env DEVELOPER_DIR="$XCODE/Contents/Developer" xcodebuild \
  -project apps/tongxing-ios/Tongxing.xcodeproj -scheme TongxingBeta -configuration BetaRelease \
  -showBuildSettings 2>/dev/null | awk '!v && $1=="MARKETING_VERSION" {v=$3}
                                        !b && $1=="CURRENT_PROJECT_VERSION" {b=$3} END {print v, b}')
if [[ "$BUILT_VERSION $BUILT_BUILD" != "$VERSION $BUILD" ]]; then
  echo "Tongxing.xcodeproj builds '$BUILT_VERSION ($BUILT_BUILD)' but project.yml says $VERSION ($BUILD); regenerate the project"; exit 1
fi
stage archive-dry   apps/tongxing-ios/scripts/archive-channel.sh --channel beta \
  --expected-commit "$COMMIT" --developer-dir "$XCODE" --output-dir "$IOS_OUT" --dry-run

fi

if [[ $EXECUTE -eq 0 ]]; then
  echo "Dry runs passed. Re-run with --execute to publish the page to Dev."
  exit 0
fi

# 3. Publish the page to Dev (the origin TongxingBeta reads).
stage delivery-execute "${DELIVERY[@]}" --execute

if [[ $WITH_BETA -eq 0 ]]; then
  echo "Page published to Dev. Timings: $OUT/timings.tsv"
  cat "$OUT/timings.tsv"
  exit 0
fi

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
测试页：Dev 三分钟测试页（模拟审核，非正式内容），run ${RUN_ID}。
请检查：测试页可见、三语言字幕随播放变化、语言切换不丢位置。
EOF
stage upload-dry    python3 apps/tongxing-ios/scripts/testflight.py upload --record "$RECORD" --ipa "$IPA" --dry-run
stage upload        python3 apps/tongxing-ios/scripts/testflight.py upload --record "$RECORD" --ipa "$IPA"
stage apple-wait    python3 apps/tongxing-ios/scripts/testflight.py wait --record "$RECORD"
stage distribute    python3 apps/tongxing-ios/scripts/testflight.py distribute --record "$RECORD" --notes "$NOTES" --group Rooted

echo "Done. Timings: $OUT/timings.tsv"
cat "$OUT/timings.tsv"
