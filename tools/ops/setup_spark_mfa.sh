#!/usr/bin/env bash
# Run explicitly on DGX Spark; isolated CPU fallback, no service restarts.
set -euo pipefail
[[ $(uname -s) == Linux && $(uname -m) == aarch64 ]] || { echo 'Requires Linux ARM64' >&2; exit 1; }
R=${1:-/home/achillesjing/sermon-mfa-runtime}
[[ "$R" = /* && "$R" != *' '* ]] || { echo 'Use an absolute path without spaces' >&2; exit 1; }
for tool in curl tar git gcc g++; do command -v "$tool" >/dev/null; done
mkdir -p "$R/bin" "$R/src" "$R/models"
if [[ ! -x "$R/bin/micromamba" ]]; then
  curl -fsSL https://micro.mamba.pm/api/micromamba/linux-aarch64/2.9.0 | tar -xj -C "$R" bin/micromamba
fi
if [[ ! -x "$R/env/bin/python" ]]; then
  "$R/bin/micromamba" create -y -r "$R/mamba" -p "$R/env" -c conda-forge \
    python=3.11 kaldi=5.5.1172 pynini=2.1.7 sqlite ffmpeg pip pybind11 cmake ninja
fi
export PATH="$R/env/bin:$PATH" KALDI_ROOT="$R/env" CMAKE_PREFIX_PATH="$R/env"
export LD_LIBRARY_PATH="$R/env/lib:${LD_LIBRARY_PATH:-}" CMAKE_BUILD_PARALLEL_LEVEL=4
if [[ ! -d "$R/src/kalpy/.git" ]]; then
  git clone --depth 1 --branch v0.10.5 https://github.com/mmcauliffe/kalpy.git "$R/src/kalpy"
fi
[[ $(git -C "$R/src/kalpy" describe --tags --exact-match) == v0.10.5 ]]
[[ -z $(git -C "$R/src/kalpy" status --porcelain) ]]
python -m pip install setuptools_scm wheel 'numpy<3'
python -m pip install --no-build-isolation "$R/src/kalpy"
python -m pip install montreal-forced-aligner==3.4.2 pgvector psycopg2-binary biopython dataclassy jinja2 requests_cache
cat > "$R/bin/mfa-run" <<EOF
#!/bin/sh
ROOT=$R
export PATH="\$ROOT/env/bin:\$PATH"
export LD_LIBRARY_PATH="\$ROOT/env/lib:\${LD_LIBRARY_PATH:-}"
export OPENBLAS_NUM_THREADS=2 OMP_NUM_THREADS=2
exec "\$ROOT/env/bin/mfa" "\$@"
EOF
chmod +x "$R/bin/mfa-run"
"$R/bin/mfa-run" version
"$R/bin/micromamba" list -p "$R/env" --json > "$R/packages.json"
python -m pip freeze > "$R/pip-freeze.txt"
git -C "$R/src/kalpy" rev-parse HEAD > "$R/kalpy-commit.txt"
printf '%s\n' 'Runtime installed. Copy verified dictionary/acoustic/G2P assets into models/; run real alignment before acceptance.'
