#!/bin/zsh
# Layer 4 prepare for this week's machine-checked locales (release v4 + content v3 + study products).
# Usage: prepare_release.sh <locale ...>   — needs: audio waiver, study reviews, metadata approval.
set -euo pipefail
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; WL=$M/artifacts/weekend-live
L4=$WL/layer4-54475d42; L3=$WL/layer3-54475d42; Q=$WL/text-qc-54475d42; ST=$WL/study-54475d42; AQ=$WL/audio-qc-54475d42
SRC=$WL/layer1-54475d42/formal/english-source-package.json
typeset -A CAND WAIVER PKG
CAND=(zh-Hans $WL/layer2-54475d42/text-r12/zh-Hans/candidate.json ko $WL/layer2-54475d42/recovered/ko/candidate.json es $WL/layer2-54475d42/recovered/es/candidate.json)
WAIVER=(zh-Hans $Q/v3-zh/zh-Hans/text-waiver-b364ef215fcb255e.json ko $Q/v15-ko/ko/text-waiver-6bf4791566c2b8b3.json es $Q/v15-es/es/text-waiver-7a18087538a44402.json)
PKG=(zh-Hans $L3/zh-Hans/audio-package-c4.json ko $L3/ko/audio-package-c3.json es $L3/es/audio-package-c4.json)
cd $M
args=(prepare --require-study --source $SRC --metadata-approval $L4/metadata-approval-v1.json --metadata-proposal $L4/metadata-proposal-v1.json --locales "$@" --page-id resi-20261011-54475d42 --date 2026-10-11 --out $L4/prepared-v1)
for L in "$@"; do
  AW=$(ls $AQ/$L-v1/$L/audio-waiver-*.json | grep -v inputs | head -1); SCR=$(python3 -c "import json;print(json.load(open('$AQ/$L-v1/$L/preflight.json'))['paths']['screening'])")
  for f in $AW $SCR $ST/$L/outline-review.json $ST/$L/meditation-review.json $L4/content/$L.json; do [ -f "$f" ] || { echo "missing $f"; exit 2; }; done
  args+=(--full-candidate $L=$CAND[$L] --full-review-receipt $L=$WAIVER[$L] --spoken-candidate $L=$CAND[$L] --spoken-review-receipt $L=$WAIVER[$L]
         --audio-package $L=$PKG[$L] --audio-review-receipt $L=$AW --audio-screening-receipt $L=$SCR --full-content $L=$L4/content/$L.json
         --outline $L=$ST/$L/outline-artifact.json --outline-review $L=$ST/$L/outline-review.json
         --meditation $L=$ST/$L/meditation-artifact.json --meditation-review $L=$ST/$L/meditation-review.json)
done
.venv/bin/python scripts/build_full_video_app_release.py "${args[@]}"
