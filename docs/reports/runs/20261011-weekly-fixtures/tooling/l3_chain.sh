#!/bin/zsh
# As soon as a locale's text waiver exists, start its Layer 3 (speech job + Spark render); one GPU locale at a time.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; Q=$M/artifacts/weekend-live/text-qc-54475d42
L3=$M/artifacts/weekend-live/layer3-54475d42; RC=$M/artifacts/weekend-live/layer2-54475d42/recovered; P=$M/artifacts/weekend-live/layer2-54475d42/policies
for spec in "ko:v11-ko" "es:v11-es"; do
  L=${spec%%:*}; RUN=${spec##*:}
  while true; do
    W=$(ls $Q/$RUN/$L/text-waiver-*.json 2>/dev/null | grep -v inputs.json | head -1)
    [ -n "$W" ] && break
    pgrep -f "out $Q/$RUN " >/dev/null || { echo "L3-CHAIN $L: QC process ended without a waiver $(date +%T)"; python3 -c "import json;r=json.load(open('$Q/$RUN/summary.json'))['locales']['$L'];print(r.get('status'),(r.get('reason') or '')[:200]);print('misses',{k:(v.get('rate'),v.get('trials')) for k,v in (r.get('calibrationMisses') or {}).items()})"; break; }
    sleep 15
  done
  [ -z "$W" ] && continue
  echo "L3-CHAIN $L: waiver $W $(date +%T)"
  zsh $L3/start_layer3.sh $L $RC/$L/candidate.json $W $P/$L-policy-frozen-r5.json repo-e3b50486 > $L3/$L/layer3-start.log 2>&1
  echo "L3-CHAIN $L: start_layer3 exit=$? $(date +%T)"; tail -c 1500 $L3/$L/layer3-start.log
done
echo "L3-CHAIN-DONE $(date +%T)"
