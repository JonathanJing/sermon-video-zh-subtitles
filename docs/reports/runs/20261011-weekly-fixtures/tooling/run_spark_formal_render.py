#!/usr/bin/env python3
"""Dispatch one locale's formal Layer 3 render to Spark under the held exclusive session.

Follows scripts/experiments/run_spark_diagnostic_audio.py: the Mac starts a
session hold, a Spark-side runner binds it to its own PID, serves the
read-only admission socket, and runs the formal renderer in an offline GPU
container with --path-map. Every file the job binds is staged by content hash;
nothing is overwritten. An unknown dispatch is left for reconciliation.
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
IMAGE = "sha256:e615da846c45d026d221bda0f168ae35022af18ac7ec4e5245d04fb62c314f14"
CHECKPOINT = "/home/<spark-user>/dgx-spark-benchmark/results/sermon-speaker-bank-20260905/steve_bang_lee/checkpoints/checkpoint-epoch-0"
CHECKPOINT_REF = ("speaker-voice://qwen3-tts-12hz-1.7b-base/steve_bang_lee/"
                  "b480bc6ab05863ccf1971bb7d968d99b31f64c5570d21d9cb7d10d4c993953a9")
CLI_INPUTS = ("source", "anchor", "candidate", "policy", "human-review-receipt", "speaker-registry", "adapter",
              "source-voice-authorization", "clip-timeline-map", "audio-operation-policies")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    return identity.sha256(path)


def ssh(argv, **kwargs):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                           " ".join(shlex.quote(str(a)) for a in argv)], check=True, **kwargs)


def closure(job: dict) -> tuple[dict[str, str], dict[str, str]]:
    """Every evidence path the renderer's materialize_path_map walks, mapped to its file hash.

    Returns (local, remote): files on this Mac, and files that exist only on Spark
    (the MFA runtime the Layer 1 alignment ran with), each verified where it lives."""
    from scripts.render_formal_target_language_speech import _evidence_paths
    pending, local, remote = _evidence_paths(job["inputs"]), {}, {}
    while pending:
        ref = pending.pop(0)
        if ref["path"] in local or ref["path"] in remote:
            continue
        path = Path(ref["path"])
        require(path.is_absolute(), f"evidence_relative:{path}")
        if not path.exists():
            require("jsonSha256" not in ref and str(path).startswith("/home/<spark-user>/"), f"evidence_missing:{path}")
            remote[ref["path"]] = ref["sha256"]
            continue
        require(path.is_file() and sha(path) == ref["sha256"], f"evidence_changed:{path}")
        local[ref["path"]] = ref["sha256"]
        if "jsonSha256" in ref:
            value = json.loads(path.read_text(encoding="utf-8"))
            if identity.json_sha256(value) != ref["jsonSha256"]:
                print(f"warning: recorded jsonSha256 does not canonicalize the byte-verified file: {path}", file=sys.stderr)
            pending.extend(_evidence_paths(value))
    if remote:
        check = "; ".join(f"test -f {shlex.quote(p)} && sha256sum {shlex.quote(p)} | cut -c1-64" for p in remote)
        observed = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST, check],
                                  check=True, capture_output=True, text=True).stdout.split()
        require(observed == list(remote.values()), "remote_evidence_changed")
    return local, remote


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
    parser.add_argument("--code", required=True, help="Staged repo directory name, e.g. repo-b4f4724c")
    parser.add_argument("--job", type=Path, required=True)
    for name in CLI_INPUTS:
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--max-end-lag-seconds", type=float, default=8.0)
    parser.add_argument("--remote-name", default=None,
                        help="Spark output directory name under output/ (default: the locale); a rebuilt job needs its own")
    args = parser.parse_args()
    loc = args.locale
    remote_name = args.remote_name or loc
    local_out = args.job.parent.parent
    require(not (local_out / "dispatch.started.json").exists(), "unknown_spark_dispatch_requires_reconciliation")
    job = json.loads(args.job.read_text())
    files, remote = closure(job)
    cli = {name: getattr(args, name.replace("-", "_")).resolve() for name in CLI_INPUTS}
    for path in [*cli.values(), args.job.resolve()]:
        files.setdefault(str(path), sha(path))
    checkpoint_map = local_out / "checkpoint-map.container.json"
    checkpoint_map.write_text(json.dumps({"schemaVersion": "sermon-speaker-checkpoint-map-v1", "checkpoints": [
        {"speakerId": "steve_bang_lee", "checkpointRef": CHECKPOINT_REF, "path": "/checkpoint"}]}, indent=1))
    path_map = {"schemaVersion": "sermon-deployment-path-map-v1",
                "paths": {original: f"/work/blobs/{digest}" for original, digest in files.items()}}
    (local_out / "path-map.json").write_text(json.dumps(path_map, indent=1))
    upload = {**files, str(checkpoint_map): sha(checkpoint_map), str(local_out / "path-map.json"): sha(local_out / "path-map.json")}
    present = set(ssh(["ls", STAGE + "/blobs"], capture_output=True, text=True).stdout.split())
    for original, digest in upload.items():
        if digest not in present:
            subprocess.run(["rsync", "-a", "-e", "ssh", original, f"{HOST}:{STAGE}/blobs/{digest}"], check=True)
    # Spark-resident evidence is copied into the blob store on Spark itself, never downloaded.
    for original, digest in remote.items():
        if digest not in present:
            ssh(["cp", "-n", original, f"{STAGE}/blobs/{digest}"])
    path_map["paths"].update({original: f"/work/blobs/{digest}" for original, digest in remote.items()})
    (local_out / "path-map.json").write_text(json.dumps(path_map, indent=1))
    upload[str(local_out / "path-map.json")] = sha(local_out / "path-map.json")
    subprocess.run(["rsync", "-a", "-e", "ssh", str(local_out / "path-map.json"), f"{HOST}:{STAGE}/blobs/{upload[str(local_out / 'path-map.json')]}"], check=True)
    upload.update(remote)
    verify = ("import hashlib,json,pathlib,sys;b=pathlib.Path(sys.argv[1]);"
              "bad=[d for d in json.loads(sys.argv[2]) if hashlib.sha256((b/d).read_bytes()).hexdigest()!=d];"
              "assert not bad,bad")
    ssh(["/usr/bin/python3", "-c", verify, STAGE + "/blobs", json.dumps(sorted(set(upload.values())))])
    # The job's own blob is the one the path map was built from; the map blob must match the uploaded file.
    remote_out = f"{STAGE}/output/{remote_name}"
    job_dir = f"/work/output/{remote_name}/speech-job"
    ssh(["mkdir", "-p", f"{remote_out}/speech-job"])
    ssh(["cp", "-n", f"{STAGE}/blobs/{files[str(args.job.resolve())]}", f"{remote_out}/speech-job/job.json"])
    # cp -n keeps an earlier job in place; the render root must hold exactly this job.
    observed = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                               f"sha256sum {shlex.quote(remote_out + '/speech-job/job.json')} | cut -c1-64"],
                              check=True, capture_output=True, text=True).stdout.strip()
    require(observed == files[str(args.job.resolve())], f"remote_job_differs:{remote_out} (use another --remote-name)")

    session = Client.from_environment()
    session.require_ready()
    hold = session.start_job("formal-layer3-render." + loc, pid=os.getpid())
    gateway_dir = f"/tmp/tongxing-spark-gateway/{hold['jobId']}"
    blob = lambda path: f"/work/blobs/{sha(path)}"
    command = ["docker", "run", "--rm", "--gpus", "all", "--ipc", "host", "--network", "none", "--read-only",
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
               "-v", STAGE + ":/work:rw", "-v", CHECKPOINT + ":/checkpoint:ro",
               "-e", f"PYTHONPATH=/work/{args.code}", "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1",
               "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "XDG_CACHE_HOME=/tmp/cache", "-e", "TRITON_CACHE_DIR=/tmp/triton",
               "-e", "NUMBA_CACHE_DIR=/tmp/numba", "-e", "HF_HOME=/tmp/hf",
               "-w", f"/work/{args.code}", "--entrypoint", "/usr/bin/python", IMAGE,
               f"/work/{args.code}/scripts/render_formal_target_language_speech.py",
               "--source", blob(cli["source"]), "--anchor", blob(cli["anchor"]),
               "--candidate", blob(cli["candidate"]), "--policy", blob(cli["policy"]),
               "--human-review-receipt", blob(cli["human-review-receipt"]),
               "--speaker-registry", blob(cli["speaker-registry"]), "--adapter", blob(cli["adapter"]),
               "--source-voice-authorization", blob(cli["source-voice-authorization"]),
               "--clip-timeline-map", blob(cli["clip-timeline-map"]),
               "--job", job_dir + "/job.json", "--checkpoint-map", blob(checkpoint_map),
               "--audio-operation-policies", blob(cli["audio-operation-policies"]),
               "--path-map", blob(local_out / "path-map.json"), "--spark-production",
               "--track-format", "mp3", "--max-end-lag-seconds", str(args.max_end_lag_seconds)]
    started = {"status": "started_unknown_until_complete_readback", "locale": loc, "sparkHold": hold,
               "commandSha256": hashlib.sha256(json.dumps(command).encode()).hexdigest(), "stagedFiles": len(upload)}
    (local_out / "dispatch.started.json").write_text(json.dumps(started, indent=1))
    config = {"codeRoot": f"{STAGE}/{args.code}", "sessionEnvironment": session.environment, "sparkHold": hold,
              "gatewayDirectory": gateway_dir, "command": command, "log": f"{remote_out}/render.log"}
    result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", HOST,
                             "/usr/bin/python3 -c " + shlex.quote(RUNNER) + " " + shlex.quote(json.dumps(config))])
    subprocess.run(["rsync", "-a", "-e", "ssh", f"{HOST}:{remote_out}/", str(local_out / "spark-output") + "/"], check=False)
    outcome = "known_terminal" if result.returncode in (0, 1, 2) else "unknown"
    session.end_job(hold, process_exited=True, outcome=outcome)
    (local_out / "dispatch.result.json").write_text(json.dumps({"exitCode": result.returncode, "outcome": outcome}, indent=1))
    print(json.dumps({"locale": loc, "exitCode": result.returncode}))
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
