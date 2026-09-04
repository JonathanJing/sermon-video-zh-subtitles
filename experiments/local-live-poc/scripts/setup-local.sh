#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
poc_dir="$(cd "$script_dir/.." && pwd)"
model_dir="$poc_dir/artifacts/models"
model_path="$model_dir/ggml-base.en.bin"
model_url="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin"
model_sha256="a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002"

cd "$poc_dir"
command -v whisper-cli >/dev/null || {
  echo "whisper-cli is required. Install whisper-cpp with Homebrew first." >&2
  exit 1
}
command -v ollama >/dev/null || {
  echo "Ollama is required." >&2
  exit 1
}

python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
npm install

mkdir -p "$model_dir"
if [ ! -f "$model_path" ]; then
  temporary_model="$model_path.partial"
  curl --fail --location --retry 3 --output "$temporary_model" "$model_url"
  observed_sha256="$(shasum -a 256 "$temporary_model" | awk '{print $1}')"
  if [ "$observed_sha256" != "$model_sha256" ]; then
    echo "ASR model checksum mismatch: $observed_sha256" >&2
    exit 1
  fi
  mv "$temporary_model" "$model_path"
fi

observed_sha256="$(shasum -a 256 "$model_path" | awk '{print $1}')"
if [ "$observed_sha256" != "$model_sha256" ]; then
  echo "Existing ASR model checksum mismatch: $observed_sha256" >&2
  exit 1
fi

echo "Local live caption dependencies are ready."
echo "ASR model: $model_path"
