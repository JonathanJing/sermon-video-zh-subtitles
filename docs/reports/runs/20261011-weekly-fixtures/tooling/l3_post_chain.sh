#!/bin/zsh
# Per locale, in order: wait for the raw render to finish, wait for a quiet Spark, compact (edge silence, 120 s end-lag budget, mp3), then ASR-screen the compacted root.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; Q=$M/artifacts/weekend-live/text-qc-54475d42
L3=$M/artifacts/weekend-live/layer3-54475d42; RC=$M/artifacts/weekend-live/layer2-54475d42/recovered; P=$M/artifacts/weekend-live/layer2-54475d42/policies
SRC=$M/artifacts/weekend-live/layer1-54475d42/formal/english-source-package.json
ANC=$M/artifacts/weekend-live/layer1-54475d42/output4-rebuild4/anchor-manifest.json
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
CODE=repo-2951f6af
cd $M
wait_quiet() {
  while true; do
    busy=$(ssh -o BatchMode=yes -o ConnectTimeout=8 <spark-user>@<spark-ip> 'docker ps -q | wc -l' 2>/dev/null | tr -d ' ')
    [ "${busy:-1}" = "0" ] && return
    sleep 20
  done
}
for spec in "zh-Hans:v3-zh:zh-Hans:$M/artifacts/weekend-live/layer2-54475d42/text-r12/zh-Hans/candidate.json" "ko:v15-ko:ko-v2:$RC/ko/candidate.json" "es:v15-es:es-v2:$RC/es/candidate.json"; do
  parts=(${(s/:/)spec}); L=$parts[1]; RUN=$parts[2]; RN=$parts[3]; CAND=$parts[4]
  W=$(ls $Q/$RUN/$L/text-waiver-*.json | grep -v inputs.json | head -1)
  until [ -f $L3/$L/dispatch.result.json ]; do sleep 30; done
  wavs=$(ssh -o BatchMode=yes <spark-user>@<spark-ip> "ls ~/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3/output/$RN/speech-job/receipts 2>/dev/null | wc -l" | tr -d ' ')
  echo "POST $L: raw render exit=$(python3 -c "import json;print(json.load(open('$L3/$L/dispatch.result.json'))['exitCode'])") unit receipts=$wavs $(date +%T)"
  [ "$wavs" -ge 461 ] || { echo "POST $L: raw units incomplete, skipped"; continue; }
  wait_quiet
  echo "POST $L: compact -> output/$RN-c $(date +%T)"
  .venv/bin/python $L3/run_spark_compact.py --locale $L --code $CODE --job $L3/$L/speech-job-v2/job.json \
    --source $SRC --anchor $ANC --candidate $CAND --policy $P/$L-policy-frozen-r5.json --human-review-receipt $W \
    --speaker-registry $L3/speaker-voice-registry.json --adapter $L3/adapter-$L.json \
    --source-voice-authorization $L3/$L/source-voice-authorization.json --clip-timeline-map $L3/clip-timeline-map.json \
    --audio-operation-policies $L3/audio-operation-policies.json \
    --raw-name $RN --remote-name $RN-c --max-end-lag-seconds 120 --trim-trailing > $L3/$L/compact-$RN-c.log 2>&1
  rc=$?; echo "POST $L: compact exit=$rc $(date +%T)"; tail -c 400 $L3/$L/compact-$RN-c.log | grep -v "^\s*\^" | tail -3
  [ $rc -eq 0 ] || continue
  wait_quiet
  echo "POST $L: screen output/$RN-c $(date +%T)"
  .venv/bin/python $L3/run_spark_asr_screen.py --locale $L --code $CODE --remote-name $RN-c --job $L3/$L/speech-job-v2/job.json > $L3/$L/screen-$RN-c.log 2>&1
  echo "POST $L: screen exit=$? $(date +%T)"; tail -c 300 $L3/$L/screen-$RN-c.log | tail -2
done
echo "POST-CHAIN-DONE $(date +%T)"
