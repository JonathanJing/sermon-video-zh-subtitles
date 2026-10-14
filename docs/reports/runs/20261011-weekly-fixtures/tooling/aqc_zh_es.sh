#!/bin/zsh
# After ko finishes on Spark, run the listening waiver with the operator's acceptance for zh-Hans, then es.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; W=$M/artifacts/weekend-live; AQ=$W/audio-qc-54475d42; Q=$W/text-qc-54475d42; L3=$W/layer3-54475d42
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
MIR=/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3/mac-artifacts/weekend-live
cd $M
until [ -f $AQ/ko-c5b/spark-dispatch.result.json ]; do sleep 20; done
echo "AQC3 ko finished: $(tr -d '\n ' < $AQ/ko-c5b/spark-dispatch.result.json) $(date +%T)"
typeset -A SD BUD RN; SD=(zh-Hans state-zh es state-es-v4); BUD=(zh-Hans zh-v1 es es-v13); RN=(zh-Hans zh-Hans es es-v2)
for L in zh-Hans es; do
  rsync -a -e ssh $L3/$L/audio-package-c5.json <spark-user>@<spark-ip>:$MIR/layer3-54475d42/$L/
  rsync -a -e ssh $L3/$L/spark-$RN[$L]-c5 <spark-user>@<spark-ip>:$MIR/layer3-54475d42/$L/
  rsync -a -e ssh $Q/$SD[$L]/ <spark-user>@<spark-ip>:$MIR/text-qc-54475d42/$SD[$L]/
  rsync -a -e ssh $AQ/ <spark-user>@<spark-ip>:$MIR/audio-qc-54475d42/
  echo "AQC3 $L: start $(date +%T)"
  .venv/bin/python $L3/run_spark_audio_qc.py --locale $L --code repo-44373de --audio-package $L3/$L/audio-package-c5.json \
    --state-dir $Q/$SD[$L] --api-budget-authorization $Q/api-budget-authorization-$BUD[$L].json --out $AQ/$L-c5b \
    --max-api-calls 150 --workers 4 --human-acceptance $AQ/$L-human-acceptance-c5.json > $AQ/$L-c5b.dispatch.log 2>&1
  echo "AQC3 $L: exit=$? $(date +%T)"; tail -c 900 $AQ/$L-c5b/spark-driver.log 2>/dev/null | grep -v "^Run report\|^\s*\^" | tail -14
done
echo "AQC3-DONE $(date +%T)"
