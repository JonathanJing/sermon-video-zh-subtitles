#!/usr/bin/env python3
"""Execute/resume a prepared weekly job on the existing isolated Spark runtime.

This command never approves audio, sends messages, or deploys automatically.
The final review candidate remains bound to the existing Saturday evidence.
"""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

from poc import sha256, write_json
from weekly_dubbing import read, validate_frozen, assemble

HERE = Path(__file__).resolve().parent
REMOTE_ROOT = "/home/achillesjing/dgx-spark-benchmark/results"
RUNTIME = REMOTE_ROOT + "/sermon-voice-poc-20260905"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--remote-checkpoint", required=True)
    p.add_argument("--host", default="achillesjing@192.168.1.152")
    p.add_argument("--mlx-python", type=Path, default=Path.home() / ".local/share/uv/tools/mlx-audio/bin/python")
    args = p.parse_args()
    work = args.work.resolve()
    job = read(work / "job.json")
    validate_frozen(job)
    checkpoint = Path(args.remote_checkpoint)
    if not checkpoint.is_absolute() or not str(checkpoint).startswith(REMOTE_ROOT + "/sermon-") or ".." in checkpoint.parts:
        raise ValueError("Use a checkpoint in the isolated sermon results directory")
    remote = f'{REMOTE_ROOT}/sermon-weekly-{job["week"]}-{sha256(work / "job.json")[:12]}'
    imported_render = (work / "render/report.json").exists()
    def ssh(command):
        subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=30", args.host, command], check=True)
    if not (work / "render/report.json").exists():
        ssh("mkdir -p " + shlex.quote(remote))
        subprocess.run(["scp", "-q", str(work / "job.json"), str(HERE / "render_weekly_audio.py"), str(HERE / "retry_weekly_unit.py"), str(HERE / "run_qwen_training_smoke.py"), args.host + ":" + remote + "/"], check=True)
        if (work / "render/identity.json").exists():
            exists = subprocess.run(["ssh", "-o", "BatchMode=yes", args.host, "test -d " + shlex.quote(remote + "/render")])
            if exists.returncode == 1:
                subprocess.run(["scp", "-q", "-r", str(work / "render"), args.host + ":" + remote + "/"], check=True)
            elif exists.returncode != 0:
                raise ValueError("Cannot inspect the remote resume directory")
        command = ["docker", "run", "--rm", "--name", "sermon-voice-weekly-" + sha256(work / "job.json")[:12], "--gpus", "all", "--memory", "24g", "--memory-swap", "28g", "--cpus", "6", "--shm-size", "1g", "--user", "1000:1000",
            "-v", remote + ":/work", "-v", RUNTIME + "/venv:/work/venv:ro", "-v", str(checkpoint) + ":/checkpoint:ro", "-v", RUNTIME + "/model-cache:/cache", "-w", "/work", "-e", "HF_HOME=/cache", "-e", "USE_TF=0", "-e", "PYTHONUNBUFFERED=1",
            "nvcr.io/nvidia/pytorch:26.06-py3", "/work/venv/bin/python", "/work/render_weekly_audio.py", "--job", "/work/job.json", "--checkpoint", "/checkpoint", "--out", "/work/render"]
        for attempt in range(6):
            try:
                ssh(shlex.join(command) + " >> " + shlex.quote(remote + "/runner.log") + " 2>&1")
                break
            except subprocess.CalledProcessError:
                if attempt == 5:
                    raise
                failure = json.loads(subprocess.check_output(["ssh", "-o", "BatchMode=yes", args.host, "cat " + shlex.quote(remote + "/render/failure.json")], text=True))
                if failure.get("reason") != "duration_or_signal" or not isinstance(failure.get("unit"), int) or not 0 <= failure["unit"] < len(job["units"]):
                    raise ValueError("Failure needs inspection; automatic recovery is limited to an identified audio unit")
                index = command.index("/work/render_weekly_audio.py")
                repair = command[:index] + ["/work/retry_weekly_unit.py"] + command[index + 1:] + ["--unit", str(failure["unit"]), "--seed", str(142 + attempt)]
                ssh(shlex.join(repair) + " >> " + shlex.quote(remote + "/recovery.log") + " 2>&1")
        subprocess.run(["scp", "-q", "-r", args.host + ":" + remote + "/render", str(work)], check=True)
    if not (work / "audio/library.json").exists():
        assemble(work)
    for script, report in [("align_weekly_source.py", "source-alignment/report.json"), ("screen_weekly_audio.py", "audio/asr-screening.json"), ("check_weekly_timing.py", "synchronization/report.json")]:
        if not (work / report).exists():
            subprocess.run([str(args.mlx_python), str(HERE / script), "--work", str(work)], check=True)
    render = read(work / "render/report.json")
    if render["jobSha256"] != sha256(work / "job.json") or sha256(work / "render/chinese.raw.wav") != render["sha256"]:
        raise ValueError("Completed audio render changed")
    validate_frozen(job)
    write_json(work / "workflow-receipt.json", {"status": "candidate_ready_for_extended_saturday_review", "jobSha256": sha256(work / "job.json"), "mp3Sha256": sha256(work / "audio/zh-natural.mp3"),
        "remoteWork": None if imported_render else remote, "renderImported": imported_render, "remoteCheckpoint": str(checkpoint), "sourceAlignmentSha256": sha256(work / "source-alignment/report.json"), "audioScreeningSha256": sha256(work / "audio/asr-screening.json"), "humanAudioReview": "pending"})
    print(f"Candidate ready: {work / 'audio/zh-natural.mp3'}\nContinue the Saturday review in {work / 'audio-review.json'}")


if __name__ == "__main__":
    main()
