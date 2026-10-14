#!/bin/zsh
# 96k delivery MP3: re-assemble each locale from its raw render (CPU), screen (GPU), build the package, then run the listening waiver.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; WL=$M/artifacts/weekend-live
L3=$WL/layer3-54475d42; Q=$WL/text-qc-54475d42; P=$WL/layer2-54475d42/policies; RC=$WL/layer2-54475d42/recovered; AQ=$WL/audio-qc-54475d42
SRC=$WL/layer1-54475d42/formal/english-source-package.json; ANC=$WL/layer1-54475d42/output4-rebuild4/anchor-manifest.json
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
CODE=repo-e72dcbd9; TAG=c5; ST=/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3; MIR=$ST/mac-artifacts/weekend-live
cd $M
typeset -A RAW CAND WV SD BUD
RAW=(zh-Hans zh-Hans ko ko-v2 es es-v2)
CAND=(zh-Hans $WL/layer2-54475d42/text-r12/zh-Hans/candidate.json ko $RC/ko/candidate.json es $RC/es/candidate.json)
WV=(zh-Hans $Q/v3-zh/zh-Hans/text-waiver-b364ef215fcb255e.json ko $Q/v15-ko/ko/text-waiver-6bf4791566c2b8b3.json es $Q/v15-es/es/text-waiver-7a18087538a44402.json)
SD=(zh-Hans state-zh ko state-v3 es state-es-v4); BUD=(zh-Hans zh-v1 ko ko-v13 es es-v13)
LOCS=(ko zh-Hans es)
# 1. compact all three in parallel (CPU only)
for L in $LOCS; do
  ( .venv/bin/python $L3/run_spark_compact.py --locale $L --code $CODE --job $L3/$L/speech-job-v2/job.json \
      --source $SRC --anchor $ANC --candidate $CAND[$L] --policy $P/$L-policy-frozen-r5.json --human-review-receipt $WV[$L] \
      --speaker-registry $L3/speaker-voice-registry.json --adapter $L3/adapter-$L.json \
      --source-voice-authorization $L3/$L/source-voice-authorization.json --clip-timeline-map $L3/clip-timeline-map.json \
      --audio-operation-policies $L3/audio-operation-policies.json --raw-name $RAW[$L] --remote-name $RAW[$L]-$TAG \
      --max-end-lag-seconds 120 --tail-overrun-seconds 1.0 --trim-trailing --padding-seconds 0.03 \
      --inter-utterance-gap-seconds 0 --reaction-lag-seconds 0 --allow-busy > $L3/$L/compact-$RAW[$L]-$TAG.log 2>&1
    echo "FINAL $L: compact exit=$? $(date +%T)" ) &
done
wait
for L in $LOCS; do
  DEST=$RAW[$L]-$TAG
  [ "$(python3 -c "import json;print(json.load(open('$L3/$L/compact-$DEST.result.json'))['exitCode'])" 2>/dev/null)" = 0 ] || { echo "FINAL $L: compact failed, skipped"; grep -o "ValueError.*" $L3/$L/spark-$DEST/compact.log | tail -1; continue; }
  # 2. screen (GPU, one at a time)
  while [ "$(ssh -o BatchMode=yes <spark-user>@<spark-ip> 'docker ps -q | wc -l' | tr -d ' ')" != "0" ]; do sleep 15; done
  .venv/bin/python $L3/run_spark_asr_screen.py --locale $L --code $CODE --remote-name $DEST --tag $TAG --job $L3/$L/speech-job-v2/job.json > $L3/$L/screen-$DEST.log 2>&1
  echo "FINAL $L: screen exit=$? $(date +%T)"
  # 3. pull the root and build the package
  rsync -a -e ssh --exclude "asr-unit-cache*" <spark-user>@<spark-ip>:$ST/output/$DEST/ $L3/$L/spark-$DEST/
  .venv/bin/python scripts/build_target_language_audio_package.py --source $SRC --anchor $ANC --candidate $CAND[$L] \
    --job $L3/$L/spark-$DEST/speech-job/job.json --adapter $L3/adapter-$L.json --policy $P/$L-policy-frozen-r5.json \
    --human-review-receipt $WV[$L] --speaker-registry $L3/speaker-voice-registry.json \
    --source-voice-authorization $L3/$L/source-voice-authorization.json --clip-timeline-map $L3/clip-timeline-map.json \
    --render-manifest $L3/$L/spark-$DEST/speech-job/render-manifest-screened-$TAG.json --artifact-root $L3/$L/spark-$DEST/speech-job \
    --out $L3/$L/audio-package-$TAG.json > $L3/$L/package-$TAG.log 2>&1
  echo "FINAL $L: package exit=$? $(date +%T)"; tail -c 200 $L3/$L/package-$TAG.log
  # 4. mirror and run the listening waiver
  rsync -a -e ssh $L3/$L/spark-$DEST $L3/$L/audio-package-$TAG.json <spark-user>@<spark-ip>:$MIR/layer3-54475d42/$L/
  rsync -a -e ssh $Q/$SD[$L]/ <spark-user>@<spark-ip>:$MIR/text-qc-54475d42/$SD[$L]/
  mkdir -p $AQ/$L-$TAG
  rsync -a -e ssh $AQ/ <spark-user>@<spark-ip>:$MIR/audio-qc-54475d42/
  .venv/bin/python $L3/run_spark_audio_qc.py --locale $L --code $CODE --audio-package $L3/$L/audio-package-$TAG.json \
    --state-dir $Q/$SD[$L] --api-budget-authorization $Q/api-budget-authorization-$BUD[$L].json --out $AQ/$L-$TAG \
    --max-api-calls 150 --workers 4 > $AQ/$L-$TAG/dispatch.log 2>&1
  echo "FINAL $L: audio-qc exit=$? $(date +%T)"; tail -c 700 $AQ/$L-$TAG/spark-driver.log 2>/dev/null | grep -v "^Run report\|^\s*\^" | tail -12
done
echo "FINAL-CHAIN-DONE $(date +%T)"
