#!/bin/zsh
# Resume the ko and es raw renders (cached units are reused); wait for a quiet, memory-rich Spark before each dispatch.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; Q=$M/artifacts/weekend-live/text-qc-54475d42
L3=$M/artifacts/weekend-live/layer3-54475d42; RC=$M/artifacts/weekend-live/layer2-54475d42/recovered; P=$M/artifacts/weekend-live/layer2-54475d42/policies
SRC=$M/artifacts/weekend-live/layer1-54475d42/formal/english-source-package.json
ANC=$M/artifacts/weekend-live/layer1-54475d42/output4-rebuild4/anchor-manifest.json
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
cd $M
wait_quiet() {
  while true; do
    read avail busy llama <<< "$(ssh -o BatchMode=yes -o ConnectTimeout=8 <spark-user>@<spark-ip> 'echo $(awk "/MemAvailable/{print int(\$2/1048576)}" /proc/meminfo) $(docker ps -q | wc -l) $(systemctl --user is-active llama-server.service)')"
    [ "${avail:-0}" -ge 100 ] && [ "${busy:-1}" -eq 0 ] && { echo "spark quiet: ${avail} GiB available, llama-server ${llama} $(date +%T)"; return; }
    echo "waiting: ${avail} GiB available, ${busy} containers, llama-server ${llama} $(date +%T)"; sleep 30
  done
}
for spec in "ko:v15-ko:ko-v2:$RC/ko/candidate.json" "es:v15-es:es-v2:$RC/es/candidate.json"; do
  parts=(${(s/:/)spec}); L=$parts[1]; RUN=$parts[2]; RN=$parts[3]; CAND=$parts[4]
  W=$(ls $Q/$RUN/$L/text-waiver-*.json | grep -v inputs.json | head -1)
  wait_quiet
  echo "L3-RESUME $L -> output/$RN $(date +%T)"
  .venv/bin/python $L3/run_spark_formal_render.py --locale $L --code repo-34b1b607 --remote-name $RN --job $L3/$L/speech-job-v2/job.json \
    --source $SRC --anchor $ANC --candidate $CAND --policy $P/$L-policy-frozen-r5.json --human-review-receipt $W \
    --speaker-registry $L3/speaker-voice-registry.json --adapter $L3/adapter-$L.json \
    --source-voice-authorization $L3/$L/source-voice-authorization.json --clip-timeline-map $L3/clip-timeline-map.json \
    --audio-operation-policies $L3/audio-operation-policies.json > $L3/$L/dispatch-v3.log 2>&1
  echo "L3-RESUME $L: exit=$? $(date +%T)"; grep -o "ReplicaPoolError.*\|ValueError.*" $L3/$L/spark-output/render.log 2>/dev/null | tail -1
done
echo "L3-RESUME-DONE $(date +%T)"
