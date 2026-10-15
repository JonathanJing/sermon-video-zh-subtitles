#!/bin/zsh
# When a locale's re-issued text waiver exists, build a fresh speech job and dispatch its Spark render; one GPU locale at a time.
# Usage: l3_chain_v2.sh <jobdir-name> <code> locale:qc-run[:candidate-root] ...
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; Q=$M/artifacts/weekend-live/text-qc-54475d42
L3=$M/artifacts/weekend-live/layer3-54475d42; RC=$M/artifacts/weekend-live/layer2-54475d42/recovered; P=$M/artifacts/weekend-live/layer2-54475d42/policies
export JOBDIR=$1; CODE=$2; shift 2
for spec in "$@"; do
  parts=(${(s/:/)spec}); L=$parts[1]; RUN=$parts[2]; CAND=${parts[3]:-$RC/$L/candidate.json}
  while true; do
    W=$(ls $Q/$RUN/$L/text-waiver-*.json 2>/dev/null | grep -v inputs.json | head -1)
    [ -n "$W" ] && break
    pgrep -f "out [^ ]*text-qc-54475d42/$RUN " >/dev/null || { echo "L3-CHAIN $L: QC process ended without a waiver $(date +%T)"; break; }
    sleep 15
  done
  [ -z "$W" ] && continue
  echo "L3-CHAIN $L: waiver $W $(date +%T)"
  zsh $L3/start_layer3_v2.sh $L $CAND $W $P/$L-policy-frozen-r5.json $CODE > $L3/$L/layer3-start-$JOBDIR.log 2>&1
  echo "L3-CHAIN $L: start_layer3 exit=$? $(date +%T)"; tail -c 1200 $L3/$L/layer3-start-$JOBDIR.log; echo
done
echo "L3-CHAIN-DONE $(date +%T)"
