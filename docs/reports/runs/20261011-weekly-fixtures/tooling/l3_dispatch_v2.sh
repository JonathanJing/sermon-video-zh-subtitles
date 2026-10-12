#!/bin/zsh
# Dispatch the three speech-job-v2 renders to Spark one GPU locale at a time: zh resumes its own output dir, ko/es use fresh ones.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; Q=$M/artifacts/weekend-live/text-qc-54475d42
L3=$M/artifacts/weekend-live/layer3-54475d42; RC=$M/artifacts/weekend-live/layer2-54475d42/recovered; P=$M/artifacts/weekend-live/layer2-54475d42/policies
SRC=$M/artifacts/weekend-live/layer1-54475d42/formal/english-source-package.json
ANC=$M/artifacts/weekend-live/layer1-54475d42/output4-rebuild4/anchor-manifest.json
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
cd $M
for spec in "zh-Hans:v3-zh:zh-Hans:$M/artifacts/weekend-live/layer2-54475d42/text-r12/zh-Hans/candidate.json" "ko:v15-ko:ko-v2:$RC/ko/candidate.json" "es:v15-es:es-v2:$RC/es/candidate.json"; do
  parts=(${(s/:/)spec}); L=$parts[1]; RUN=$parts[2]; RN=$parts[3]; CAND=$parts[4]
  W=$(ls $Q/$RUN/$L/text-waiver-*.json | grep -v inputs.json | head -1)
  echo "L3-DISPATCH $L -> output/$RN  waiver $W  $(date +%T)"
  .venv/bin/python $L3/run_spark_formal_render.py --locale $L --code repo-34b1b607 --remote-name $RN --job $L3/$L/speech-job-v2/job.json \
    --source $SRC --anchor $ANC --candidate $CAND --policy $P/$L-policy-frozen-r5.json --human-review-receipt $W \
    --speaker-registry $L3/speaker-voice-registry.json --adapter $L3/adapter-$L.json \
    --source-voice-authorization $L3/$L/source-voice-authorization.json --clip-timeline-map $L3/clip-timeline-map.json \
    --audio-operation-policies $L3/audio-operation-policies.json > $L3/$L/dispatch-v2.log 2>&1
  echo "L3-DISPATCH $L: exit=$? $(date +%T)"; tail -c 600 $L3/$L/dispatch-v2.log; echo
done
echo "L3-DISPATCH-DONE $(date +%T)"
