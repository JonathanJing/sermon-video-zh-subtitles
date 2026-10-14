#!/bin/zsh
# Listening waiver with the operator's per-unit acceptance: ko, zh-Hans (accepted), then es (first QC, no acceptance yet).
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; WL=$M/artifacts/weekend-live
L3=$WL/layer3-54475d42; Q=$WL/text-qc-54475d42; AQ=$WL/audio-qc-54475d42
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
CODE=repo-44373de
MIR=/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3/mac-artifacts/weekend-live
cd $M
typeset -A SD BUD; SD=(zh-Hans state-zh ko state-v3 es state-es-v4); BUD=(zh-Hans zh-v1 ko ko-v13 es es-v13)
for spec in ko:accept zh-Hans:accept es:none; do
  L=${spec%%:*}; MODE=${spec##*:}; OUT=$AQ/$L-c5a
  mkdir -p $OUT
  rsync -a -e ssh $L3/$L/audio-package-c5.json <spark-user>@<spark-ip>:$MIR/layer3-54475d42/$L/
  rsync -a -e ssh $L3/$L/spark-$([ $L = zh-Hans ] && echo zh-Hans || echo $L-v2)-c5 <spark-user>@<spark-ip>:$MIR/layer3-54475d42/$L/
  rsync -a -e ssh $Q/$SD[$L]/ <spark-user>@<spark-ip>:$MIR/text-qc-54475d42/$SD[$L]/
  rsync -a -e ssh $AQ/ <spark-user>@<spark-ip>:$MIR/audio-qc-54475d42/
  ACC=(); [ $MODE = accept ] && ACC=(--human-acceptance $AQ/$L-human-acceptance-c5.json)
  echo "AQC2 $L ($MODE): start $(date +%T)"
  .venv/bin/python $L3/run_spark_audio_qc.py --locale $L --code $CODE --audio-package $L3/$L/audio-package-c5.json \
    --state-dir $Q/$SD[$L] --api-budget-authorization $Q/api-budget-authorization-$BUD[$L].json --out $OUT \
    --max-api-calls 150 --workers 4 $ACC > $OUT/dispatch.log 2>&1
  echo "AQC2 $L: exit=$? $(date +%T)"; tail -c 900 $OUT/spark-driver.log 2>/dev/null | grep -v "^Run report\|^\s*\^" | tail -14
done
echo "AQC2-DONE $(date +%T)"
