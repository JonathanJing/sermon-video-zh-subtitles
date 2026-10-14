#!/usr/bin/env python3
"""Run the machine listening-waiver driver for one locale on Spark under the held exclusive session.

The driver needs the local Qwen3-ASR weights, the speaker's TTS checkpoint
(for dropped-key-word calibration audio) and the OpenAI transcription API
(secondary ASR), so it runs in a GPU container with network access. The Mac
artifact tree is mirrored on Spark and bind-mounted at its original absolute
path, so every hash-bound path inside the packages resolves unchanged; the
state dir and output dir are written there and read back to this Mac. The
prod credential comes from a 0600 env file on Spark read by the explicit
environment launcher; it is never passed on a command line.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.spark_exclusive_session import Client  # noqa: E402

HOST = "<spark-user>@<spark-ip>"
STAGE = "/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3"
MIRROR = f"{STAGE}/mac-artifacts/weekend-live"
MAC_WEEKEND_LIVE = str(ROOT / "artifacts/weekend-live")
IMAGE = "sha256:06576684aa3e4e2ec7eb2df6ecd2c6afd95e6644608195b8362cad43e51c3690"  # sermon-pytorch-ffmpeg:20260927
ASR_RUNTIME = ("/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261004-resi-69ba7a66-formal8-d190535-v3/"
               "runtime-asr-v1/site-packages")
VOICE_PACKAGES = "/home/<spark-user>/dgx-spark-benchmark/results/sermon-voice-poc-20260905/venv/lib/python3.12/site-packages"
MODEL_ROOT = "/home/<spark-user>/.cache/huggingface/hub"
MODEL_SNAPSHOT = "models--Qwen--Qwen3-ASR-0.6B/snapshots/deba00eb976b8daf9805ffd5d0fdcd7cafbb21b2"
CHECKPOINT = "/home/<spark-user>/dgx-spark-benchmark/results/sermon-speaker-bank-20260905/steve_bang_lee/checkpoints/checkpoint-epoch-0"
CHECKPOINT_REF = ("speaker-voice://qwen3-tts-12hz-1.7b-base/steve_bang_lee/"
                  "b480bc6ab05863ccf1971bb7d968d99b31f64c5570d21d9cb7d10d4c993953a9")
ENV_FILE = "/home/<spark-user>/.config/tongxing/openai-prod.env"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def ssh_out(script: str) -> str:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST, script],
                          check=True, capture_output=True, text=True).stdout


RUNNER = r'''import json,os,pathlib,subprocess,sys
c=json.loads(sys.argv[1]);sys.path.insert(0,c["codeRoot"])
os.environ.update(c["sessionEnvironment"]);os.environ["SPARK_EXCLUSIVE_REMOTE_LOCAL"]="1"
from scripts.spark_exclusive_session import Client
from scripts.experiments.run_spark_diagnostic_audio import AdmissionGateway
session=Client.from_environment();session.require_ready();session.bind_job(c["sparkHold"],pid=os.getpid())
gateway=AdmissionGateway(c["gatewayDirectory"],session,c["sparkHold"],runner_pid=os.getpid())
try:
 session.require_ready()
 with open(c["log"],"ab") as log:
  result=subprocess.run(c["command"],stdout=log,stderr=subprocess.STDOUT)
finally:gateway.close()
sys.exit(result.returncode)
'''


def mac(path: str) -> str:
    """A Mac path under artifacts/weekend-live, as the container sees it (same absolute path)."""
    p = str(Path(path).resolve())
    require(p.startswith(MAC_WEEKEND_LIVE + "/"), f"not under artifacts/weekend-live: {path}")
    return p


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", required=True, choices=["zh-Hans", "ko", "es"])
    parser.add_argument("--code", required=True)
    parser.add_argument("--audio-package", required=True)
    parser.add_argument("--state-dir", required=True, help="The locale's text QC state dir (shared repair ledgers)")
    parser.add_argument("--api-budget-authorization", required=True)
    parser.add_argument("--out", required=True, help="Output dir under artifacts/weekend-live/audio-qc-54475d42")
    parser.add_argument("--max-api-calls", type=int, default=150)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--human-acceptance", default=None, help="audio_qc_human_acceptance record under artifacts/weekend-live")
    parser.add_argument("--allow-busy", action="store_true")
    args = parser.parse_args()
    loc = args.locale
    out_local = Path(args.out).resolve()
    out_local.mkdir(parents=True, exist_ok=True)
    marker = out_local / "spark-dispatch.started.json"
    require(not marker.exists(), "unknown_spark_audio_qc_requires_reconciliation")
    package = mac(args.audio_package)
    state = mac(args.state_dir)
    auth = mac(args.api_budget_authorization)
    out = mac(str(out_local))
    acceptance = mac(args.human_acceptance) if args.human_acceptance else None

    probe = ssh_out("set -e; test -f %s && echo env-ok; test -s %s/%s && echo mirror-ok; "
                    "sha256sum %s/%s/model.safetensors | cut -c1-64; grep MemAvailable /proc/meminfo | awk '{print $2}'; "
                    "docker ps --format '{{.Names}}'"
                    % (shlex.quote(ENV_FILE), shlex.quote(MIRROR), shlex.quote(package[len(MAC_WEEKEND_LIVE) + 1:]),
                       shlex.quote(MODEL_ROOT), shlex.quote(MODEL_SNAPSHOT))).split("\n")
    require("env-ok" in probe, "prod credential env file missing on Spark")
    require("mirror-ok" in probe, "audio package missing from the Spark mirror; rsync first")
    require("79d6cbd4c98c7bbffe9db2edac07f56cd6637d0d5944b27f6c2b8353840323ea" in probe, "asr_weights_differ")
    busy = [p for p in probe if p and not p.isdigit() and p not in ("env-ok", "mirror-ok") and len(p) != 64]
    require(args.allow_busy or not busy, f"spark_busy:{busy}")

    checkpoint_map = out_local / "tts-checkpoint-map.container.json"
    checkpoint_map.write_text(json.dumps({"schemaVersion": "sermon-speaker-checkpoint-map-v1", "checkpoints": [
        {"speakerId": "steve_bang_lee", "checkpointRef": CHECKPOINT_REF, "path": "/checkpoint"}]}, indent=1))
    subprocess.run(["rsync", "-a", "-e", "ssh", str(checkpoint_map), f"{HOST}:{MIRROR}/{out[len(MAC_WEEKEND_LIVE) + 1:]}/"], check=True)

    session = Client.from_environment()
    session.require_ready()
    hold = session.start_job("formal-layer3-audio-qc." + loc, pid=os.getpid())
    gateway_dir = f"/tmp/tongxing-spark-gateway/{hold['jobId']}"
    code = f"/work/{args.code}"
    command = ["docker", "run", "--rm", "--gpus", "all", "--ipc", "host", "--read-only",
               "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--label", "tongxing.spark.session=" + session.environment["SPARK_EXCLUSIVE_SESSION_ID"],
               "--label", "tongxing.spark.owner=" + session.environment["SPARK_EXCLUSIVE_SESSION_OWNER"],
               "--label", "tongxing.spark.job=" + hold["jobId"],
               "-e", "SPARK_EXCLUSIVE_SESSION_ID=" + session.environment["SPARK_EXCLUSIVE_SESSION_ID"],
               "-e", "SPARK_EXCLUSIVE_SESSION_OWNER=" + session.environment["SPARK_EXCLUSIVE_SESSION_OWNER"],
               "-e", "SPARK_EXCLUSIVE_SOCKET=/spark-session-gateway/admission.sock",
               "-v", gateway_dir + ":/spark-session-gateway:ro",
               "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=4g,mode=1777",
               "-v", STAGE + ":/work:ro", "-v", MIRROR + ":" + MAC_WEEKEND_LIVE + ":rw",
               "-v", ASR_RUNTIME + ":/runtime-asr-v1/site-packages:ro", "-v", VOICE_PACKAGES + ":/voice-packages:ro",
               "-v", MODEL_ROOT + ":/model-cache:ro", "-v", CHECKPOINT + ":/checkpoint:ro",
               "-v", ENV_FILE + ":/secrets/openai.env:ro",
               "-e", f"PYTHONPATH=/runtime-asr-v1/site-packages:/voice-packages:{code}",
               "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HF_HOME=/tmp/hf", "-e", "HF_HUB_OFFLINE=1",
               "-e", "TRANSFORMERS_OFFLINE=1", "-e", "TOKENIZERS_PARALLELISM=false",
               "-e", "NUMBA_CACHE_DIR=/tmp/numba", "-e", "TRITON_CACHE_DIR=/tmp/triton",
               "-e", "TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor", "-e", "XDG_CACHE_HOME=/tmp/cache",
               "-w", code, "--entrypoint", "python", IMAGE,
               f"{code}/scripts/run_with_openai_environment.py", "--environment", "prod", "--env-file", "/secrets/openai.env",
               "python", f"{code}/scripts/run_machine_qc_audio_test.py",
               "--run-dir", MAC_WEEKEND_LIVE, "--out", out, "--state-dir", state, "--locales", loc,
               "--audio-package", f"{loc}={package}", "--backend", "real",
               "--asr-model-path", f"/model-cache/{MODEL_SNAPSHOT}",
               "--tts-checkpoint-map", f"{out}/tts-checkpoint-map.container.json",
               "--text-backend", "api", "--api-budget-authorization", auth,
               "--max-api-calls", str(args.max_api_calls), "--workers", str(args.workers)]
    if acceptance:
        command += ["--human-acceptance", f"{loc}={acceptance}"]
    started = {"status": "started_unknown_until_complete_readback", "locale": loc, "sparkHold": hold,
               "audioPackage": package, "stateDir": state, "out": out, "humanAcceptance": acceptance,
               "commandSha256": hashlib.sha256(json.dumps(command).encode()).hexdigest()}
    marker.write_text(json.dumps(started, indent=1))
    config = {"codeRoot": f"{STAGE}/{args.code}", "sessionEnvironment": session.environment, "sparkHold": hold,
              "gatewayDirectory": gateway_dir, "command": command, "log": f"{MIRROR}/{out[len(MAC_WEEKEND_LIVE) + 1:]}/spark-driver.log"}
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                             "/usr/bin/python3 -c " + shlex.quote(RUNNER) + " " + shlex.quote(json.dumps(config))])
    # Read back the driver output and the state dir it wrote (ledgers, receipts, call caches).
    for rel in (out[len(MAC_WEEKEND_LIVE) + 1:], state[len(MAC_WEEKEND_LIVE) + 1:]):
        subprocess.run(["rsync", "-a", "-e", "ssh", f"{HOST}:{MIRROR}/{rel}/", f"{MAC_WEEKEND_LIVE}/{rel}/"], check=False)
    budget_root = json.loads(Path(auth).read_text())["budgetRoot"]
    if budget_root.startswith(MAC_WEEKEND_LIVE + "/"):
        rel = budget_root[len(MAC_WEEKEND_LIVE) + 1:]
        subprocess.run(["rsync", "-a", "-e", "ssh", f"{HOST}:{MIRROR}/{rel}/", f"{MAC_WEEKEND_LIVE}/{rel}/"], check=False)
    outcome = "known_terminal" if result.returncode in (0, 1, 2) else "unknown"
    session.end_job(hold, process_exited=True, outcome=outcome)
    (out_local / "spark-dispatch.result.json").write_text(json.dumps({"exitCode": result.returncode, "outcome": outcome}, indent=1))
    print(json.dumps({"locale": loc, "phase": "audio-qc", "exitCode": result.returncode}))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
