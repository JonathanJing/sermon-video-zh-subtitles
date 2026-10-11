#!/usr/bin/env python3
"""Dispatch one locale's Qwen3-ASR back-transcription screen to Spark under the held exclusive session.

Companion of run_spark_formal_render.py: the render root on Spark
(output/<remote-name>/speech-job) already holds the immutable job.json, the
renderer's render-manifest.json and every unit WAV. The screen runs in the
same offline GPU container layout the 2026-10-04 week used
(sermon-pytorch-ffmpeg + the pinned qwen_asr runtime), writes the v2 screening
receipt and the screened manifest next to the manifest, and the whole render
root is read back to this Mac for the audio-package builder.
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
from scripts import sermon_sentence_interpretation as identity  # noqa: E402

HOST = "<spark-user>@<spark-ip>"
STAGE = "/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261011-resi-54475d42-l3"
IMAGE = "sha256:06576684aa3e4e2ec7eb2df6ecd2c6afd95e6644608195b8362cad43e51c3690"  # sermon-pytorch-ffmpeg:20260927
ASR_RUNTIME = ("/home/<spark-user>/dgx-spark-benchmark/results/weekly-20261004-resi-69ba7a66-formal8-d190535-v3/"
               "runtime-asr-v1/site-packages")
VOICE_PACKAGES = "/home/<spark-user>/dgx-spark-benchmark/results/sermon-voice-poc-20260905/venv/lib/python3.12/site-packages"
MODEL_ROOT = "/home/<spark-user>/.cache/huggingface/hub"
MODEL_SNAPSHOT = "models--Qwen--Qwen3-ASR-0.6B/snapshots/deba00eb976b8daf9805ffd5d0fdcd7cafbb21b2"
ASR_REVISION = "model.safetensors:sha256:79d6cbd4c98c7bbffe9db2edac07f56cd6637d0d5944b27f6c2b8353840323ea"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def ssh(argv, **kwargs):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                           " ".join(shlex.quote(str(a)) for a in argv)], check=True, **kwargs)


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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", required=True)
    parser.add_argument("--code", required=True, help="Staged repo directory name, e.g. repo-34b1b607")
    parser.add_argument("--job", type=Path, required=True, help="The local job.json the render root holds")
    parser.add_argument("--remote-name", default=None, help="Spark output directory name under output/ (default: the locale)")
    parser.add_argument("--batch-size", default="1", choices=["1", "2", "4", "8"])
    parser.add_argument("--tag", default="v1", help="Suffix of the receipt/manifest/cache names")
    args = parser.parse_args()
    loc = args.locale
    remote_name = args.remote_name or loc
    local_out = args.job.parent.parent
    marker = local_out / f"screen-{args.tag}.started.json"
    require(not marker.exists(), "unknown_spark_screen_requires_reconciliation")
    job_sha = identity.sha256(args.job)
    remote_out = f"{STAGE}/output/{remote_name}"
    root = f"{remote_out}/speech-job"
    receipt = f"asr-screening-receipt-{args.tag}.json"
    screened = f"render-manifest-screened-{args.tag}.json"
    cache = f"asr-unit-cache-{args.tag}"

    # The render root must hold exactly this job, a complete render manifest and no screening yet.
    probe = ssh_out("set -e; R=%s; sha256sum $R/job.json | cut -c1-64; test -f $R/render-manifest.json && echo manifest;"
                    " test -e $R/%s && echo receipt-exists || true; test -e $R/%s && echo screened-exists || true;"
                    " sha256sum %s/%s/model.safetensors | cut -c1-64; test -f %s/qwen_asr/__init__.py && echo runtime;"
                    " grep MemAvailable /proc/meminfo | awk '{print $2}'; docker ps --format '{{.Names}}'"
                    % tuple(shlex.quote(x) for x in (root, receipt, screened, MODEL_ROOT, MODEL_SNAPSHOT, ASR_RUNTIME))).split("\n")
    require(probe[0] == job_sha, f"remote_job_differs:{root}")
    require("manifest" in probe, f"render_manifest_missing:{root}")
    require("receipt-exists" not in probe and "screened-exists" not in probe, f"screen_exists:{root}/{receipt}")
    require(ASR_REVISION.split(":")[-1] in probe, "asr_weights_differ")
    require("runtime" in probe, "asr_runtime_missing")
    containers = [p for p in probe[probe.index("runtime") + 2:] if p]
    require(not containers, f"spark_busy:{containers}")

    session = Client.from_environment()
    session.require_ready()
    hold = session.start_job("formal-layer3-screen." + loc, pid=os.getpid())
    gateway_dir = f"/tmp/tongxing-spark-gateway/{hold['jobId']}"
    code = f"/work/{args.code}"
    command = ["docker", "run", "--rm", "--gpus", "all", "--ipc", "host", "--network", "none", "--read-only",
               "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--label", "tongxing.spark.session=" + session.environment["SPARK_EXCLUSIVE_SESSION_ID"],
               "--label", "tongxing.spark.owner=" + session.environment["SPARK_EXCLUSIVE_SESSION_OWNER"],
               "--label", "tongxing.spark.job=" + hold["jobId"],
               "-e", "SPARK_EXCLUSIVE_SESSION_ID=" + session.environment["SPARK_EXCLUSIVE_SESSION_ID"],
               "-e", "SPARK_EXCLUSIVE_SESSION_OWNER=" + session.environment["SPARK_EXCLUSIVE_SESSION_OWNER"],
               "-e", "SPARK_EXCLUSIVE_SOCKET=/spark-session-gateway/admission.sock",
               "-v", gateway_dir + ":/spark-session-gateway:ro",
               "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=2g,mode=1777",
               "-v", STAGE + ":/work:rw", "-v", ASR_RUNTIME + ":/runtime-asr-v1/site-packages:ro",
               "-v", VOICE_PACKAGES + ":/voice-packages:ro", "-v", MODEL_ROOT + ":/model-cache:ro",
               "-e", f"PYTHONPATH=/runtime-asr-v1/site-packages:/voice-packages:{code}",
               "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HF_HOME=/tmp/hf", "-e", "HF_HUB_OFFLINE=1",
               "-e", "TRANSFORMERS_OFFLINE=1", "-e", "TOKENIZERS_PARALLELISM=false",
               "-e", "OMP_NUM_THREADS=4", "-e", "MKL_NUM_THREADS=4", "-e", "NUMBA_CACHE_DIR=/tmp/numba",
               "-e", "TRITON_CACHE_DIR=/tmp/triton", "-e", "TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor",
               "-e", "XDG_CACHE_HOME=/tmp/cache",
               "-w", code, "--entrypoint", "python", IMAGE,
               f"{code}/scripts/screen_target_language_audio_units.py",
               "--job", f"/work/output/{remote_name}/speech-job/job.json",
               "--render-manifest", f"/work/output/{remote_name}/speech-job/render-manifest.json",
               "--artifact-root", f"/work/output/{remote_name}/speech-job",
               "--model-path", f"/model-cache/{MODEL_SNAPSHOT}", "--model-revision", ASR_REVISION,
               "--batch-size", args.batch_size,
               "--unit-cache", f"/work/output/{remote_name}/speech-job/{cache}",
               "--out-receipt", f"/work/output/{remote_name}/speech-job/{receipt}",
               "--out-manifest", f"/work/output/{remote_name}/speech-job/{screened}"]
    started = {"status": "started_unknown_until_complete_readback", "locale": loc, "sparkHold": hold,
               "jobSha256": job_sha, "model": "Qwen/Qwen3-ASR-0.6B", "modelRevision": ASR_REVISION,
               "batchSize": int(args.batch_size),
               "commandSha256": hashlib.sha256(json.dumps(command).encode()).hexdigest()}
    marker.write_text(json.dumps(started, indent=1))
    config = {"codeRoot": f"{STAGE}/{args.code}", "sessionEnvironment": session.environment, "sparkHold": hold,
              "gatewayDirectory": gateway_dir, "command": command, "log": f"{remote_out}/screen-{args.tag}.log"}
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                             "/usr/bin/python3 -c " + shlex.quote(RUNNER) + " " + shlex.quote(json.dumps(config))])
    subprocess.run(["rsync", "-a", "-e", "ssh", f"{HOST}:{remote_out}/", str(local_out / "spark-output") + "/"], check=False)
    outcome = "known_terminal" if result.returncode in (0, 1, 2) else "unknown"
    session.end_job(hold, process_exited=True, outcome=outcome)
    (local_out / f"screen-{args.tag}.result.json").write_text(json.dumps({"exitCode": result.returncode, "outcome": outcome}, indent=1))
    print(json.dumps({"locale": loc, "phase": "asr-screen", "exitCode": result.returncode}))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
