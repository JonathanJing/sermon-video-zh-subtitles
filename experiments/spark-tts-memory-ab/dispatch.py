#!/usr/bin/env python3
"""Mac-side dispatcher for the Spark TTS memory A/B probe.

Stages this checkout's production code to Spark by content, copies the 2026-10-03
64-sentence sample, and runs one offline GPU container per arm under the held exclusive
session (job hold + read-only admission gateway, as the formal render dispatcher does).
Arms differ only in PYTORCH_CUDA_ALLOC_CONF and the pool's release_cuda_cache option.
Diagnostic only: no speech job, receipts or release eligibility.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packages/production/src"))
from tongxing_production.compute.spark_exclusive_session import Client  # noqa: E402

HOST = "achillesjing@192.168.1.152"
RESULTS = "/home/achillesjing/dgx-spark-benchmark/results"
SAMPLE = RESULTS + "/sunday-production-8x8-dispatch-20261003/inputs.json"
CHECKPOINT = RESULTS + "/sermon-voice-poc-20260905/checkpoints/checkpoint-epoch-0"
IMAGE = "sha256:e615da846c45d026d221bda0f168ae35022af18ac7ec4e5245d04fb62c314f14"  # sermon-qwen-tts:podcast-dual-20261002
LINE = "experiments/spark-tts-memory-ab"
STAGED = ("packages/production/src", "scripts", "config", "schemas", LINE)
ARMS = {
    "baseline": {"env": {}, "release": False},
    "expandable": {"env": {"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}, "release": False},
    "release": {"env": {}, "release": True},
    "both": {"env": {"PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"}, "release": True},
}


def ssh(argv, **kwargs):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                           " ".join(shlex.quote(str(a)) for a in argv)], check=True, **kwargs)


def stage(stage_dir):
    head = subprocess.run(["git", "rev-parse", "--short=8", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--", *STAGED], cwd=ROOT, check=True,
                           capture_output=True, text=True).stdout.strip() != ""
    code = f"repo-{head}{'-dirty' if dirty else ''}"
    ssh(["mkdir", "-p", f"{stage_dir}/output", *(f"{stage_dir}/{code}/{rel}" for rel in STAGED)])
    for rel in STAGED:
        subprocess.run(["rsync", "-a", "--delete", "--exclude", "__pycache__", "--exclude", ".venv",
                        "-e", "ssh", f"{ROOT / rel}/", f"{HOST}:{stage_dir}/{code}/{rel}/"], check=True)
    ssh(["cp", "-n", SAMPLE, f"{stage_dir}/inputs.json"])
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-name", required=True, help="New results directory name on Spark")
    parser.add_argument("--arms", default="baseline,expandable,release,both")
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True, help="Local ignored artifacts directory")
    args = parser.parse_args()
    stage_dir = f"{RESULTS}/{args.stage_name}"
    args.out.mkdir(parents=True, exist_ok=True)
    code = stage(stage_dir)
    session = Client.from_environment()
    session.require_ready()
    summaries = {}
    for arm in args.arms.split(","):
        spec = ARMS[arm]
        local = args.out / arm
        if (local / "dispatch.result.json").exists():
            print(f"{arm}: already dispatched, skipping", flush=True)
            summaries[arm] = json.loads((local / "summary.json").read_text()) if (local / "summary.json").exists() else None
            continue
        local.mkdir(parents=True, exist_ok=True)
        hold = session.start_job("diagnostic-tts-memory-probe." + arm, pid=os.getpid())
        gateway_dir = f"/tmp/tongxing-spark-gateway/{hold['jobId']}"
        env = session.environment
        command = ["docker", "run", "--rm", "--gpus", "all", "--ipc", "host", "--network", "none", "--read-only",
                   "--user", "1000:1000",
                   "--label", "tongxing.spark.session=" + env["SPARK_EXCLUSIVE_SESSION_ID"],
                   "--label", "tongxing.spark.owner=" + env["SPARK_EXCLUSIVE_SESSION_OWNER"],
                   "--label", "tongxing.spark.job=" + hold["jobId"],
                   "-e", "SPARK_EXCLUSIVE_SESSION_ID=" + env["SPARK_EXCLUSIVE_SESSION_ID"],
                   "-e", "SPARK_EXCLUSIVE_SESSION_OWNER=" + env["SPARK_EXCLUSIVE_SESSION_OWNER"],
                   "-e", "SPARK_EXCLUSIVE_SOCKET=/spark-session-gateway/admission.sock",
                   "-v", gateway_dir + ":/spark-session-gateway:ro",
                   "--tmpfs", "/tmp:rw,exec,nosuid,size=2g,mode=1777",
                   "-v", stage_dir + ":/work:rw", "-v", CHECKPOINT + ":/checkpoint:ro",
                   "-e", f"PYTHONPATH=/work/{code}:/work/{code}/packages/production/src",
                   "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1", "-e", "PYTHONDONTWRITEBYTECODE=1",
                   "-e", "XDG_CACHE_HOME=/tmp/cache", "-e", "TRITON_CACHE_DIR=/tmp/triton",
                   "-e", "NUMBA_CACHE_DIR=/tmp/numba", "-e", "HF_HOME=/tmp/hf"]
        for key, value in spec["env"].items():
            command += ["-e", f"{key}={value}"]
        command += ["-w", f"/work/{code}", "--entrypoint", "/usr/bin/python", IMAGE,
                    f"/work/{code}/{LINE}/probe.py", "--inputs", "/work/inputs.json", "--checkpoint", "/checkpoint",
                    "--out", f"/work/output/{arm}", "--arm", arm, "--rounds", str(args.rounds)]
        if spec["release"]:
            command.append("--release-cuda-cache")
        config = {"codeRoot": f"{stage_dir}/{code}", "sessionEnvironment": env, "sparkHold": hold,
                  "gatewayDirectory": gateway_dir, "command": command, "log": f"{stage_dir}/output/{arm}.log"}
        (local / "runner-config.json").write_text(json.dumps(config, indent=1))
        (local / "dispatch.started.json").write_text(json.dumps({"status": "started_unknown_until_readback", "sparkHold": hold}, indent=1))
        subprocess.run(["rsync", "-a", "-e", "ssh", str(local / "runner-config.json"),
                        f"{HOST}:{stage_dir}/output/runner-config-{arm}.json"], check=True)
        print(f"{arm}: running", flush=True)
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                                 f"/usr/bin/python3 {stage_dir}/{code}/{LINE}/spark_runner.py {stage_dir}/output/runner-config-{arm}.json"])
        subprocess.run(["rsync", "-a", "--exclude", "wav", "-e", "ssh", f"{HOST}:{stage_dir}/output/{arm}/",
                        str(local / "spark-output") + "/"], check=False)
        subprocess.run(["rsync", "-a", "-e", "ssh", f"{HOST}:{stage_dir}/output/{arm}.log", str(local / "probe.log")], check=False)
        outcome = "known_terminal" if result.returncode in (0, 1, 2) else "unknown"
        session.end_job(hold, process_exited=True, outcome=outcome)
        (local / "dispatch.result.json").write_text(json.dumps({"exitCode": result.returncode, "outcome": outcome}, indent=1))
        summary_path = local / "spark-output" / "summary.json"
        summaries[arm] = json.loads(summary_path.read_text()) if summary_path.exists() else None
        print(f"{arm}: exit={result.returncode}", flush=True)
    for arm, summary in summaries.items():
        if summary:
            m = summary["memAvailableGiB"]
            print(f"{arm:11s} windows={summary['windows']} load={summary['modelLoadBarrierSeconds']:.0f}s "
                  f"wall={summary['totalWallSeconds']:.0f}s mem before/after-load/min/after-close = "
                  f"{m['beforeLoad']:.1f}/{m['afterLoad']:.1f}/{m['minimum']:.1f}/{m['afterClose']:.1f} GiB")
        else:
            print(f"{arm:11s} no summary")


if __name__ == "__main__":
    main()
