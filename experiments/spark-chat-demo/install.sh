#!/usr/bin/env bash
# Install the throwaway Qwen3.8 chat demo on the DGX Spark host.
# Everything lands under DEMO_ROOT (default ~/spark-chat-demo); no system packages,
# no systemd units, no docker. cleanup.sh removes all of it again.
set -euo pipefail

DEMO_ROOT="${DEMO_ROOT:-$HOME/spark-chat-demo}"
LLAMA_TAG="${LLAMA_TAG:-}"   # empty = llama.cpp default branch
HF_REPO="${HF_REPO:-}"
HF_FILE="${HF_FILE:-}"
MODEL_NAME="${MODEL_NAME:-qwen3.8-demo}"
N_CTX="${N_CTX:-8192}"

say() { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[install] %s\033[0m\n' "$*" >&2; exit 1; }

mkdir -p "$DEMO_ROOT"/{build,models,logs,state,scripts}

# ---------------------------------------------------------------- prerequisites
command -v nvidia-smi >/dev/null || die "nvidia-smi missing: this demo expects the GB10 host"
command -v cmake  >/dev/null || die "cmake missing (apt: cmake)"
command -v git    >/dev/null || die "git missing"
command -v curl   >/dev/null || die "curl missing"

if [ -z "$HF_REPO" ] || [ -z "$HF_FILE" ]; then
  die "set HF_REPO and HF_FILE, e.g. HF_REPO=unsloth/Qwen3.8-4B-Instruct-GGUF HF_FILE=Qwen3.8-4B-Instruct-Q4_K_M.gguf bash install.sh"
fi
MODEL_PATH="$DEMO_ROOT/models/$(basename "$HF_FILE")"

# ---------------------------------------------------------------- llama.cpp (CUDA)
if [ ! -x "$DEMO_ROOT/build/llama.cpp/build/bin/llama-server" ]; then
  say "building llama.cpp $LLAMA_TAG with CUDA (this is the slow part, ~10-15 min)"
  export PATH="/usr/local/cuda/bin:$PATH"
  export CUDACXX="${CUDACXX:-/usr/local/cuda/bin/nvcc}"
  if [ ! -d "$DEMO_ROOT/build/llama.cpp/.git" ]; then
    if [ -n "$LLAMA_TAG" ]; then
      git clone --depth 1 --branch "$LLAMA_TAG" https://github.com/ggml-org/llama.cpp "$DEMO_ROOT/build/llama.cpp" \
        || git clone --depth 1 https://github.com/ggml-org/llama.cpp "$DEMO_ROOT/build/llama.cpp"
    else
      git clone --depth 1 https://github.com/ggml-org/llama.cpp "$DEMO_ROOT/build/llama.cpp"
    fi
  fi
  "$CUDACXX" --version | tail -2
  cmake -S "$DEMO_ROOT/build/llama.cpp" -B "$DEMO_ROOT/build/llama.cpp/build" \
    -DGGML_CUDA=ON -DGGML_NATIVE=ON -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CUDA_ARCHITECTURES=native >/dev/null
  cmake --build "$DEMO_ROOT/build/llama.cpp/build" --target llama-server -j "$(nproc)" \
    >"$DEMO_ROOT/logs/build.log" 2>&1 || { tail -40 "$DEMO_ROOT/logs/build.log"; die "llama.cpp build failed"; }
else
  say "llama-server already built"
fi
"$DEMO_ROOT/build/llama.cpp/build/bin/llama-server" --version 2>&1 | head -2

# ---------------------------------------------------------------- model weights
if [ ! -s "$MODEL_PATH" ]; then
  say "downloading $HF_FILE from $HF_REPO"
  curl -fL --retry 3 --continue-at - \
    "https://huggingface.co/$HF_REPO/resolve/main/$HF_FILE" -o "$MODEL_PATH.part"
  mv "$MODEL_PATH.part" "$MODEL_PATH"
else
  say "model already present"
fi
MODEL_SHA="$(sha256sum "$MODEL_PATH" | cut -d' ' -f1)"
MODEL_BYTES="$(stat -c%s "$MODEL_PATH")"
say "model $(numfmt --to=iec "$MODEL_BYTES") sha256=${MODEL_SHA:0:16}…"

# ---------------------------------------------------------------- scripts + state
cp "$(dirname "$0")/serve.py"     "$DEMO_ROOT/scripts/serve.py"
cp "$(dirname "$0")/index.html"   "$DEMO_ROOT/scripts/index.html"
cp "$(dirname "$0")/run.sh"       "$DEMO_ROOT/scripts/run.sh"
cp "$(dirname "$0")/cleanup.sh"   "$DEMO_ROOT/scripts/cleanup.sh"
chmod +x "$DEMO_ROOT/scripts/"*.sh

python3 - "$DEMO_ROOT" "$MODEL_PATH" "$MODEL_SHA" "$HF_REPO" "$HF_FILE" "$MODEL_NAME" "$N_CTX" <<'PY'
import json, sys
root, model, sha, repo, file, name, nctx = sys.argv[1:8]
state = {
    "schema": "spark-chat-demo-install-v1",
    "demoRoot": root,
    "model": {"name": name, "path": model, "sha256": sha, "hfRepo": repo, "hfFile": file, "nCtx": int(nctx)},
}
open(f"{root}/state/install.json", "w").write(json.dumps(state, indent=2) + "\n")
print(json.dumps(state, indent=2))
PY

say "installed. next: bash $DEMO_ROOT/scripts/run.sh"
