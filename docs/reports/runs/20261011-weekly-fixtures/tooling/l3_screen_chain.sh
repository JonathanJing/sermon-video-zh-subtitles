#!/bin/zsh
# After every render has finished (no TTS on the GPU), screen each successful render root with Qwen3-ASR, one locale at a time.
M=~/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles; L3=$M/artifacts/weekend-live/layer3-54475d42
SHIM=/private/tmp/claude-501/-Users-jonathan-jing-SynologyDrive-GitHub-Active-sermon-video-zh-subtitles/59a9f28b-4e1e-4368-ac91-f9155989452b/scratchpad/sshshim
export PATH="$SHIM:$PATH" SPARK_EXCLUSIVE_SESSION_ID=layer1-resi-54475d42-r2-20261011 SPARK_EXCLUSIVE_SESSION_OWNER=codex-layer1-resi-54475d42-r2-20261011 PYTHONPATH=$M
cd $M
until grep -q "L3-DISPATCH-DONE" $L3/l3-dispatch-v2.log 2>/dev/null; do sleep 20; done
for spec in zh-Hans:zh-Hans ko:ko-v2 es:es-v2; do
  L=${spec%%:*}; RN=${spec##*:}
  code=$(python3 -c "import json;print(json.load(open('$L3/$L/dispatch.result.json'))['exitCode'])" 2>/dev/null)
  [ "$code" = "0" ] || { echo "SCREEN $L: render exit=$code, skipped $(date +%T)"; continue; }
  echo "SCREEN $L -> output/$RN $(date +%T)"
  .venv/bin/python $L3/run_spark_asr_screen.py --locale $L --code repo-34b1b607 --remote-name $RN --job $L3/$L/speech-job-v2/job.json > $L3/$L/screen-v1.log 2>&1
  echo "SCREEN $L: exit=$? $(date +%T)"; tail -c 500 $L3/$L/screen-v1.log; echo
done
echo "SCREEN-CHAIN-DONE $(date +%T)"
