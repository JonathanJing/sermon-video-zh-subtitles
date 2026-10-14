#!/bin/zsh
# Wait for the prod credential file on Spark, then run the listening-waiver driver for ko, zh-Hans, es in turn.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; L3=$M/artifacts/weekend-live/layer3-54475d42; Q=$M/artifacts/weekend-live/text-qc-54475d42; AQ=$M/artifacts/weekend-live/audio-qc-54475d42
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
cd $M
until ssh -o BatchMode=yes -o ConnectTimeout=8 <spark-user>@<spark-ip> 'test -s ~/.config/tongxing/openai-prod.env' 2>/dev/null; do sleep 20; done
echo "AQC: credential file present $(date +%T)"
for spec in "ko:c3:state-v3:ko-v13" "zh-Hans:c4:state-zh:zh-v1" "es:c4:state-es-v4:es-v13"; do
  parts=(${(s/:/)spec}); L=$parts[1]; T=$parts[2]; SD=$parts[3]; B=$parts[4]
  # mirror the latest local state/out before the run (the driver reads its own earlier receipts there)
  rsync -a -e ssh $Q/$SD/ <spark-user>@<spark-ip>:/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3/mac-artifacts/weekend-live/text-qc-54475d42/$SD/
  rsync -a -e ssh $AQ/ <spark-user>@<spark-ip>:/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3/mac-artifacts/weekend-live/audio-qc-54475d42/
  echo "AQC $L: start $(date +%T)"
  .venv/bin/python $L3/run_spark_audio_qc.py --locale $L --code repo-31c048ac --audio-package $L3/$L/audio-package-$T.json --state-dir $Q/$SD --api-budget-authorization $Q/api-budget-authorization-$B.json --out $AQ/$L-v1 --max-api-calls 150 --workers 4 > $AQ/$L-v1/dispatch.log 2>&1
  echo "AQC $L: exit=$? $(date +%T)"; tail -c 600 $AQ/$L-v1/spark-driver.log 2>/dev/null | grep -v "^\s*\^" | tail -6
done
echo "AQC-CHAIN-DONE $(date +%T)"
