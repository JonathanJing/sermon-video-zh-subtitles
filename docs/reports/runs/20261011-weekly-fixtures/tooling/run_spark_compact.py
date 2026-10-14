#!/usr/bin/env python3
"""Compact one locale's rendered raw units on Spark (measured edge silence only) and assemble the track.

Companion of run_spark_formal_render.py. The raw render root
(output/<raw-name>/speech-job) is immutable; compact_formal_target_audio.py
writes the same job bytes, shortened WAVs, fresh unit receipts, the trim
evidence and the assembled track into output/<remote-name>/speech-job with the
operator-approved end-lag budget recorded in the evidence and the schedule
policy. No model runs; the TTS image is only the verified runtime.
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
# sermon-pytorch-ffmpeg:20260927 (the TTS image has no ffmpeg for the MP3 track); the voice venv supplies torch/qwen deps.
IMAGE = "sha256:06576684aa3e4e2ec7eb2df6ecd2c6afd95e6644608195b8362cad43e51c3690"
VOICE_PACKAGES = "/home/<spark-user>/dgx-spark-benchmark/results/sermon-voice-poc-20260905/venv/lib/python3.12/site-packages"
CHECKPOINT = "/home/<spark-user>/dgx-spark-benchmark/results/sermon-speaker-bank-20260905/steve_bang_lee/checkpoints/checkpoint-epoch-0"
CLI_INPUTS = ("source", "anchor", "candidate", "policy", "human-review-receipt", "speaker-registry", "adapter",
              "source-voice-authorization", "clip-timeline-map", "audio-operation-policies")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    return identity.sha256(path)


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
    parser.add_argument("--code", required=True, help="Staged repo directory name holding the end-lag aware compactor")
    parser.add_argument("--job", type=Path, required=True, help="The local job.json the raw render root holds")
    for name in CLI_INPUTS:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--raw-name", required=True, help="Spark output dir of the raw render, under output/")
    parser.add_argument("--remote-name", required=True, help="New Spark output dir for the compacted render, under output/")
    parser.add_argument("--max-end-lag-seconds", type=float, required=True)
    parser.add_argument("--trim-trailing", action="store_true")
    parser.add_argument("--padding-seconds", type=float, default=None)
    parser.add_argument("--inter-utterance-gap-seconds", type=float, default=None)
    parser.add_argument("--reaction-lag-seconds", type=float, default=None)
    parser.add_argument("--tail-overrun-seconds", type=float, default=None)
    parser.add_argument("--allow-busy", action="store_true", help="Compaction is CPU-only; allow it beside a running GPU container")
    args = parser.parse_args()
    loc = args.locale
    local_out = args.job.parent.parent
    marker = local_out / f"compact-{args.remote_name}.started.json"
    require(not marker.exists(), "unknown_spark_compact_requires_reconciliation")
    path_map = local_out / "path-map.json"
    checkpoint_map = local_out / "checkpoint-map.container.json"
    require(path_map.is_file() and checkpoint_map.is_file(), "raw render dispatch files missing (path-map, checkpoint-map)")
    mapped = json.loads(path_map.read_text())["paths"]
    cli = {name: getattr(args, name.replace("-", "_")).resolve() for name in CLI_INPUTS}
    for path in cli.values():
        require(str(path) in mapped and mapped[str(path)].endswith(sha(path)), f"input not in the raw render's path map: {path}")
    job_sha = sha(args.job)
    raw = f"{STAGE}/output/{args.raw_name}/speech-job"
    dest = f"{STAGE}/output/{args.remote_name}/speech-job"
    probe = ssh_out("set -e; sha256sum %s/job.json | cut -c1-64; test -d %s && echo dest-exists || true; "
                    "grep MemAvailable /proc/meminfo | awk '{print $2}'; docker ps --format '{{.Names}}'"
                    % (shlex.quote(raw), shlex.quote(dest))).split("\n")
    require(probe[0] == job_sha, f"remote_job_differs:{raw}")
    require("dest-exists" not in probe, f"destination_exists:{dest}")
    busy = [p for p in probe[2:] if p and not p.isdigit()]
    require(args.allow_busy or not busy, f"spark_busy:{busy}")

    session = Client.from_environment()
    session.require_ready()
    hold = session.start_job("formal-layer3-compact." + loc, pid=os.getpid())
    gateway_dir = f"/tmp/tongxing-spark-gateway/{hold['jobId']}"
    code = f"/work/{args.code}"
    blob = lambda path: mapped[str(path)]
    command = ["docker", "run", "--rm", "--ipc", "host", "--network", "none", "--read-only",
               "--user", "1000:1000",
               "--label", "tongxing.spark.session=" + session.environment["SPARK_EXCLUSIVE_SESSION_ID"],
               "--label", "tongxing.spark.owner=" + session.environment["SPARK_EXCLUSIVE_SESSION_OWNER"],
               "--label", "tongxing.spark.job=" + hold["jobId"],
               "-e", "SPARK_EXCLUSIVE_SESSION_ID=" + session.environment["SPARK_EXCLUSIVE_SESSION_ID"],
               "-e", "SPARK_EXCLUSIVE_SESSION_OWNER=" + session.environment["SPARK_EXCLUSIVE_SESSION_OWNER"],
               "-e", "SPARK_EXCLUSIVE_SOCKET=/spark-session-gateway/admission.sock",
               "-v", gateway_dir + ":/spark-session-gateway:ro",
               "--tmpfs", "/tmp:rw,exec,nosuid,size=2g,mode=1777", "--tmpfs", "/Users:rw,nosuid,size=64m,mode=1777",
               "--tmpfs", "/private:rw,nosuid,size=64m,mode=1777", "--tmpfs", "/home:rw,nosuid,size=64m,mode=1777",
               "-v", STAGE + ":/work:rw", "-v", CHECKPOINT + ":/checkpoint:ro", "-v", VOICE_PACKAGES + ":/voice-packages:ro",
               "-e", f"PYTHONPATH=/voice-packages:{code}", "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1",
               "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "XDG_CACHE_HOME=/tmp/cache", "-e", "NUMBA_CACHE_DIR=/tmp/numba",
               "-w", code, "--entrypoint", "python", IMAGE,
               f"{code}/scripts/compact_formal_target_audio.py",
               "--source", blob(cli["source"]), "--anchor", blob(cli["anchor"]),
               "--candidate", blob(cli["candidate"]), "--policy", blob(cli["policy"]),
               "--human-review-receipt", blob(cli["human-review-receipt"]), "--adapter", blob(cli["adapter"]),
               "--speaker-registry", blob(cli["speaker-registry"]),
               "--source-voice-authorization", blob(cli["source-voice-authorization"]),
               "--clip-timeline-map", blob(cli["clip-timeline-map"]),
               "--source-job", f"/work/output/{args.raw_name}/speech-job/job.json",
               "--destination-root", f"/work/output/{args.remote_name}/speech-job",
               "--checkpoint-map", f"/work/blobs/{sha(checkpoint_map)}",
               "--audio-operation-policies", blob(cli["audio-operation-policies"]),
               "--path-map", f"/work/blobs/{sha(path_map)}",
               "--max-end-lag-seconds", str(args.max_end_lag_seconds), "--track-format", "mp3"]
    if args.trim_trailing:
        command.append("--trim-trailing")
    tuning = {"padding-seconds": args.padding_seconds, "inter-utterance-gap-seconds": args.inter_utterance_gap_seconds,
              "reaction-lag-seconds": args.reaction_lag_seconds, "tail-overrun-seconds": args.tail_overrun_seconds}
    for name, value in tuning.items():
        if value is not None:
            command += ["--" + name, str(value)]
    started = {"status": "started_unknown_until_complete_readback", "locale": loc, "sparkHold": hold,
               "rawName": args.raw_name, "remoteName": args.remote_name, "jobSha256": job_sha,
               "maxEndLagSeconds": args.max_end_lag_seconds, "trimTrailing": args.trim_trailing, "tuning": tuning,
               "commandSha256": hashlib.sha256(json.dumps(command).encode()).hexdigest()}
    marker.write_text(json.dumps(started, indent=1))
    ssh_out(f"mkdir -p {shlex.quote(STAGE + '/output/' + args.remote_name)}")
    config = {"codeRoot": f"{STAGE}/{args.code}", "sessionEnvironment": session.environment, "sparkHold": hold,
              "gatewayDirectory": gateway_dir, "command": command, "log": f"{STAGE}/output/{args.remote_name}/compact.log"}
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                             "/usr/bin/python3 -c " + shlex.quote(RUNNER) + " " + shlex.quote(json.dumps(config))])
    subprocess.run(["rsync", "-a", "-e", "ssh", "--exclude", "*.wav", f"{HOST}:{STAGE}/output/{args.remote_name}/",
                    str(local_out / f"spark-{args.remote_name}") + "/"], check=False)
    outcome = "known_terminal" if result.returncode in (0, 1, 2) else "unknown"
    session.end_job(hold, process_exited=True, outcome=outcome)
    (local_out / f"compact-{args.remote_name}.result.json").write_text(json.dumps({"exitCode": result.returncode, "outcome": outcome}, indent=1))
    print(json.dumps({"locale": loc, "phase": "compact", "exitCode": result.returncode}))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
