#!/usr/bin/env python3
"""Dispatch one locale's Layer 3 Spark stages for a real-model clip E2E under the held exclusive session.

Four subcommands, each one GPU or CPU container on Spark, in order:

- ``render``: the formal renderer (``tools/ops/run.py audio.renderer --spark-production``)
  with every evidence file staged by content hash and mapped with ``--path-map``;
- ``compact``: measured edge-silence compaction of the immutable raw render into a new root and
  the assembled track (``compact_formal_target_audio.py``, CPU);
- ``screen``: the Qwen3-ASR back-transcription screen of that root
  (``tools/ops/run.py audio.screening``);
- ``audio-qc``: the machine listening-waiver driver (``tools/ops/run.py review.qc_audio_run``) with the
  local ASR, the speaker checkpoint and the secondary ``gpt-transcribe`` API through the explicit
  dev environment launcher on Spark. The Mac artifacts tree is mirrored on Spark and mounted at
  its original absolute path, so every hash-bound path in the packages resolves unchanged.

For each stage the Mac starts a session hold, a Spark-side runner binds it to its own PID and
serves the read-only admission socket, and the container runs offline except ``audio-qc``. A
``*.started.json`` marker is written before dispatch; a marker without its result means the
outcome is unknown and the stage refuses to run again until it is reconciled. Host, images and
runtime paths come from ``config/clip-e2e/spark-runtime.json``; the stage directory and staged
code directory are per run. ``tools/development/run_clip_real_e2e.py`` drives these; see
docs/clip-real-e2e.zh.md.
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import tongxing_host  # noqa: F401  binds the production package ports
from tongxing_production.source import sentence_interpretation as identity  # noqa: E402

RUNTIME = ROOT / "config/clip-e2e/spark-runtime.json"
RUNTIME_SCHEMA = "sermon-clip-e2e-spark-runtime-v1"
CLI_INPUTS = ("source", "anchor", "candidate", "policy", "human-review-receipt", "speaker-registry", "adapter",
              "clip-voice-authorization", "clip-timeline-map", "audio-operation-policies")
TERMINAL_EXIT_CODES = (0, 1, 2)
PACKAGE_SRC = "packages/production/src"

RUNNER = r'''import json,os,pathlib,subprocess,sys
c=json.loads(sys.argv[1]);sys.path[:0]=[c["codeRoot"],c["codeRoot"]+"/packages/production/src"]
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


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path: Path) -> str:
    return identity.sha256(path)


def load_runtime(path: Path = RUNTIME) -> dict:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    require(value.get("schemaVersion") == RUNTIME_SCHEMA
            and {"host", "remoteHome", "stageRoot", "openaiEnvFile", "images", "voicePackages", "asrRuntime",
                 "modelRoot", "asrSnapshot", "asrRevision", "speaker"} <= set(value)
            and {"tts", "pytorchFfmpeg"} <= set(value["images"])
            and {"id", "checkpoint", "checkpointRef"} <= set(value["speaker"]), "invalid_spark_runtime")
    return value


class Spark:
    """SSH and rsync to the Spark host; every call is BatchMode with a short connect timeout."""

    def __init__(self, host: str):
        self.host = host

    def _ssh(self, command: str, **kwargs):
        return subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", self.host, command], **kwargs)

    def run(self, argv: list) -> None:
        self._ssh(" ".join(shlex.quote(str(a)) for a in argv), check=True)

    def out(self, script: str) -> str:
        return self._ssh(script, check=True, capture_output=True, text=True).stdout

    def put(self, local: str, remote: str) -> None:
        subprocess.run(["rsync", "-a", "-e", "ssh", local, f"{self.host}:{remote}"], check=True)

    def get(self, remote: str, local: str, *, exclude: tuple = ()) -> None:
        excludes = [arg for pattern in exclude for arg in ("--exclude", pattern)]
        subprocess.run(["rsync", "-a", "-e", "ssh", *excludes, f"{self.host}:{remote}", local], check=False)

    def run_held(self, config: dict) -> int:
        return self._ssh("/usr/bin/python3 -c " + shlex.quote(RUNNER) + " " + shlex.quote(json.dumps(config))).returncode


def container_pythonpath(code: str, *runtime_dirs: str) -> str:
    """PYTHONPATH for a container that runs the staged checkout at ``code`` (its absolute path in the container).

    The images do not ship ``tongxing_production``; the ``scripts/`` facades import it from the staged checkout.
    """
    return ":".join([*runtime_dirs, f"{code}/{PACKAGE_SRC}", code])


def session_labels(session, hold) -> list[str]:
    env = session.environment
    return ["--label", "tongxing.spark.session=" + env["SPARK_EXCLUSIVE_SESSION_ID"],
            "--label", "tongxing.spark.owner=" + env["SPARK_EXCLUSIVE_SESSION_OWNER"],
            "--label", "tongxing.spark.job=" + hold["jobId"],
            "-e", "SPARK_EXCLUSIVE_SESSION_ID=" + env["SPARK_EXCLUSIVE_SESSION_ID"],
            "-e", "SPARK_EXCLUSIVE_SESSION_OWNER=" + env["SPARK_EXCLUSIVE_SESSION_OWNER"],
            "-e", "SPARK_EXCLUSIVE_SOCKET=/spark-session-gateway/admission.sock",
            "-v", f"/tmp/tongxing-spark-gateway/{hold['jobId']}:/spark-session-gateway:ro"]


def checkpoint_map(runtime: dict) -> dict:
    return {"schemaVersion": "sermon-speaker-checkpoint-map-v1", "checkpoints": [
        {"speakerId": runtime["speaker"]["id"], "checkpointRef": runtime["speaker"]["checkpointRef"], "path": "/checkpoint"}]}


def dispatch(spark: Spark, session, name: str, locale: str, *, stage: str, code: str, command_for, log: str,
             marker: Path, started: dict) -> tuple[int, str, dict]:
    """Hold the session, write the started marker, run ``command_for(hold)`` on Spark; return (code, outcome, hold)."""
    session.require_ready()
    hold = session.start_job(f"formal-layer3-{name}." + locale, pid=os.getpid())
    command = command_for(hold)
    marker.write_text(json.dumps({"status": "started_unknown_until_complete_readback", "locale": locale,
                                  "sparkHold": hold, **started,
                                  "commandSha256": hashlib.sha256(json.dumps(command).encode()).hexdigest()}, indent=1))
    config = {"codeRoot": f"{stage}/{code}", "sessionEnvironment": session.environment, "sparkHold": hold,
              "gatewayDirectory": f"/tmp/tongxing-spark-gateway/{hold['jobId']}", "command": command, "log": log}
    returncode = spark.run_held(config)
    return returncode, ("known_terminal" if returncode in TERMINAL_EXIT_CODES else "unknown"), hold


def finish(session, hold, returncode, outcome, result_path: Path, summary: dict) -> int:
    session.end_job(hold, process_exited=True, outcome=outcome)
    result_path.write_text(json.dumps({"exitCode": returncode, "outcome": outcome}, indent=1))
    print(json.dumps({**summary, "exitCode": returncode}))
    return returncode


# ---------------------------------------------------------------- render


def evidence_closure(job: dict, spark: Spark, remote_home: str) -> tuple[dict[str, str], dict[str, str]]:
    """Every evidence path the renderer's materialize_path_map walks, mapped to its file hash.

    Returns (local, remote): files on this Mac, and files that exist only on Spark (the MFA
    runtime the Layer 1 alignment ran with), each verified where it lives."""
    from tongxing_production.audio.renderer import _evidence_paths
    pending, local, remote = _evidence_paths(job["inputs"]), {}, {}
    while pending:
        ref = pending.pop(0)
        if ref["path"] in local or ref["path"] in remote:
            continue
        path = Path(ref["path"])
        require(path.is_absolute(), f"evidence_relative:{path}")
        if not path.exists():
            require("jsonSha256" not in ref and str(path).startswith(remote_home.rstrip("/") + "/"),
                    f"evidence_missing:{path}")
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
        require(spark.out(check).split() == list(remote.values()), "remote_evidence_changed")
    return local, remote


RENDER_PREFIX = ["docker", "run", "--rm", "--gpus", "all", "--ipc", "host", "--network", "none", "--read-only",
                 "--user", "1000:1000"]


def render_command(runtime: dict, stage: str, code: str, blob, job_dir: str, *, max_end_lag: float,
                   unit_instructions: str | None, seed: int = 42) -> list[str]:
    """The render container arguments after the docker prefix and the session labels."""
    command = ["--tmpfs", "/tmp:rw,exec,nosuid,size=2g,mode=1777", "--tmpfs", "/Users:rw,nosuid,size=64m,mode=1777",
               "--tmpfs", "/private:rw,nosuid,size=64m,mode=1777", "--tmpfs", "/home:rw,nosuid,size=64m,mode=1777",
               "-v", stage + ":/work:rw", "-v", runtime["speaker"]["checkpoint"] + ":/checkpoint:ro",
               "-e", "PYTHONPATH=" + container_pythonpath(f"/work/{code}"),
               "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1",
               "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "XDG_CACHE_HOME=/tmp/cache", "-e", "TRITON_CACHE_DIR=/tmp/triton",
               "-e", "NUMBA_CACHE_DIR=/tmp/numba", "-e", "HF_HOME=/tmp/hf",
               "-w", f"/work/{code}", "--entrypoint", "/usr/bin/python", runtime["images"]["tts"],
               f"/work/{code}/tools/ops/run.py", "audio.renderer",
               "--source", blob("source"), "--anchor", blob("anchor"),
               "--candidate", blob("candidate"), "--policy", blob("policy"),
               "--human-review-receipt", blob("human-review-receipt"),
               "--speaker-registry", blob("speaker-registry"), "--adapter", blob("adapter"),
               "--clip-voice-authorization", blob("clip-voice-authorization"),
               "--clip-timeline-map", blob("clip-timeline-map"),
               "--job", job_dir + "/job.json", "--checkpoint-map", blob("checkpoint-map"),
               "--audio-operation-policies", blob("audio-operation-policies"),
               "--path-map", blob("path-map"), "--spark-production",
               "--track-format", "mp3", "--max-end-lag-seconds", str(max_end_lag), "--seed", str(seed)]
    if unit_instructions:
        command += ["--unit-instructions", unit_instructions]
    return command


def render(args, runtime, spark, session) -> int:
    loc, stage = args.locale, args.stage
    require(args.seed >= 0, "render_seed_must_be_nonnegative")
    remote_name = args.remote_name or loc
    local_out = args.job.parent.parent
    require(not (local_out / "dispatch.started.json").exists(), "unknown_spark_dispatch_requires_reconciliation")
    job = json.loads(args.job.read_text())
    files, remote = evidence_closure(job, spark, runtime["remoteHome"])
    cli = {name: getattr(args, name.replace("-", "_")).resolve() for name in CLI_INPUTS}
    extra = [args.unit_instructions.resolve()] if args.unit_instructions else []
    for path in [*cli.values(), args.job.resolve(), *extra]:
        files.setdefault(str(path), sha(path))
    cmap = local_out / "checkpoint-map.container.json"
    cmap.write_text(json.dumps(checkpoint_map(runtime), indent=1))
    path_map = {"schemaVersion": "sermon-deployment-path-map-v1",
                "paths": {original: f"/work/blobs/{digest}" for original, digest in {**files, **remote}.items()}}
    pmap = local_out / "path-map.json"
    pmap.write_text(json.dumps(path_map, indent=1))
    upload = {**files, str(cmap): sha(cmap), str(pmap): sha(pmap)}
    spark.run(["mkdir", "-p", stage + "/blobs"])
    present = set(spark.out(f"ls {shlex.quote(stage + '/blobs')}").split())
    for original, digest in upload.items():
        if digest not in present:
            spark.put(original, f"{stage}/blobs/{digest}")
    # Spark-resident evidence is copied into the blob store on Spark itself, never downloaded.
    for original, digest in remote.items():
        if digest not in present:
            spark.run(["cp", "-n", original, f"{stage}/blobs/{digest}"])
    verify = ("import hashlib,json,pathlib,sys;b=pathlib.Path(sys.argv[1]);"
              "bad=[d for d in json.loads(sys.argv[2]) if hashlib.sha256((b/d).read_bytes()).hexdigest()!=d];"
              "assert not bad,bad")
    spark.run(["/usr/bin/python3", "-c", verify, stage + "/blobs", json.dumps(sorted(set(upload.values()) | set(remote.values())))])
    remote_out = f"{stage}/output/{remote_name}"
    spark.run(["mkdir", "-p", f"{remote_out}/speech-job"])
    job_sha = files[str(args.job.resolve())]
    spark.run(["cp", "-n", f"{stage}/blobs/{job_sha}", f"{remote_out}/speech-job/job.json"])
    # cp -n keeps an earlier job in place; the render root must hold exactly this job.
    observed = spark.out(f"sha256sum {shlex.quote(remote_out + '/speech-job/job.json')} | cut -c1-64").strip()
    require(observed == job_sha, f"remote_job_differs:{remote_out} (use another --remote-name)")
    blobs = {**{name: f"/work/blobs/{sha(path)}" for name, path in cli.items()},
             "checkpoint-map": f"/work/blobs/{sha(cmap)}", "path-map": f"/work/blobs/{sha(pmap)}"}
    tail = render_command(runtime, stage, args.code, blobs.__getitem__, f"/work/output/{remote_name}/speech-job",
                          max_end_lag=args.max_end_lag_seconds,
                          unit_instructions=f"/work/blobs/{sha(extra[0])}" if extra else None,
                          seed=args.seed)
    command_for = lambda hold: [*RENDER_PREFIX, *session_labels(session, hold), *tail]
    returncode, outcome, hold = dispatch(spark, session, "render", loc, stage=stage, code=args.code, command_for=command_for,
                                         log=f"{remote_out}/render.log", marker=local_out / "dispatch.started.json",
                                         started={"stagedFiles": len(upload)})
    spark.get(f"{remote_out}/", str(local_out / "spark-output") + "/")
    return finish(session, hold, returncode, outcome, local_out / "dispatch.result.json", {"locale": loc, "phase": "render"})


# ---------------------------------------------------------------- compact


def compact(args, runtime, spark, session) -> int:
    loc, stage = args.locale, args.stage
    local_out = args.job.parent.parent
    marker = local_out / f"compact-{args.remote_name}.started.json"
    require(not marker.exists(), "unknown_spark_compact_requires_reconciliation")
    path_map, cmap = local_out / "path-map.json", local_out / "checkpoint-map.container.json"
    require(path_map.is_file() and cmap.is_file(), "raw render dispatch files missing (path-map, checkpoint-map)")
    mapped = json.loads(path_map.read_text())["paths"]
    cli = {name: getattr(args, name.replace("-", "_")).resolve() for name in CLI_INPUTS}
    for path in cli.values():
        require(str(path) in mapped and mapped[str(path)].endswith(sha(path)), f"input not in the raw render's path map: {path}")
    job_sha = sha(args.job)
    raw, dest = f"{stage}/output/{args.raw_name}/speech-job", f"{stage}/output/{args.remote_name}/speech-job"
    probe = spark.out("set -e; sha256sum %s/job.json | cut -c1-64; test -d %s && echo dest-exists || true; "
                      "grep MemAvailable /proc/meminfo | awk '{print $2}'; docker ps --format '{{.Names}}'"
                      % (shlex.quote(raw), shlex.quote(dest))).split("\n")
    require(probe[0] == job_sha, f"remote_job_differs:{raw}")
    require("dest-exists" not in probe, f"destination_exists:{dest}")
    busy = [p for p in probe[2:] if p and not p.isdigit()]
    require(args.allow_busy or not busy, f"spark_busy:{busy}")
    code = f"/work/{args.code}"
    blob = lambda name: mapped[str(cli[name])]
    tuning = {"padding-seconds": args.padding_seconds, "inter-utterance-gap-seconds": args.inter_utterance_gap_seconds,
              "reaction-lag-seconds": args.reaction_lag_seconds, "tail-overrun-seconds": args.tail_overrun_seconds}

    def command_for(hold):
        command = ["docker", "run", "--rm", "--ipc", "host", "--network", "none", "--read-only",
                   "--user", "1000:1000", *session_labels(session, hold),
                   "--tmpfs", "/tmp:rw,exec,nosuid,size=2g,mode=1777", "--tmpfs", "/Users:rw,nosuid,size=64m,mode=1777",
                   "--tmpfs", "/private:rw,nosuid,size=64m,mode=1777", "--tmpfs", "/home:rw,nosuid,size=64m,mode=1777",
                   "-v", stage + ":/work:rw", "-v", runtime["speaker"]["checkpoint"] + ":/checkpoint:ro",
                   "-v", runtime["voicePackages"] + ":/voice-packages:ro",
                   "-e", "PYTHONPATH=" + container_pythonpath(code, "/voice-packages"),
                   "-e", "HF_HUB_OFFLINE=1", "-e", "TRANSFORMERS_OFFLINE=1",
                   "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "XDG_CACHE_HOME=/tmp/cache", "-e", "NUMBA_CACHE_DIR=/tmp/numba",
                   "-w", code, "--entrypoint", "python", runtime["images"]["pytorchFfmpeg"],
                   f"{code}/scripts/compact_formal_target_audio.py",
                   "--source", blob("source"), "--anchor", blob("anchor"),
                   "--candidate", blob("candidate"), "--policy", blob("policy"),
                   "--human-review-receipt", blob("human-review-receipt"), "--adapter", blob("adapter"),
                   "--speaker-registry", blob("speaker-registry"),
                   "--clip-voice-authorization", blob("clip-voice-authorization"),
                   "--clip-timeline-map", blob("clip-timeline-map"),
                   "--source-job", f"/work/output/{args.raw_name}/speech-job/job.json",
                   "--destination-root", f"/work/output/{args.remote_name}/speech-job",
                   "--checkpoint-map", f"/work/blobs/{sha(cmap)}",
                   "--audio-operation-policies", blob("audio-operation-policies"),
                   "--path-map", f"/work/blobs/{sha(path_map)}",
                   "--max-end-lag-seconds", str(args.max_end_lag_seconds), "--track-format", "mp3"]
        if args.trim_trailing:
            command.append("--trim-trailing")
        for name, value in tuning.items():
            if value is not None:
                command += ["--" + name, str(value)]
        return command
    spark.run(["mkdir", "-p", f"{stage}/output/{args.remote_name}"])
    returncode, outcome, hold = dispatch(
        spark, session, "compact", loc, stage=stage, code=args.code, command_for=command_for,
        log=f"{stage}/output/{args.remote_name}/compact.log", marker=marker,
        started={"rawName": args.raw_name, "remoteName": args.remote_name, "jobSha256": job_sha,
                 "maxEndLagSeconds": args.max_end_lag_seconds, "trimTrailing": args.trim_trailing, "tuning": tuning})
    spark.get(f"{stage}/output/{args.remote_name}/", str(local_out / f"spark-{args.remote_name}") + "/", exclude=("*.wav",))
    return finish(session, hold, returncode, outcome, local_out / f"compact-{args.remote_name}.result.json",
                  {"locale": loc, "phase": "compact"})


# ---------------------------------------------------------------- screen


def screen(args, runtime, spark, session) -> int:
    loc, stage = args.locale, args.stage
    remote_name = args.remote_name or loc
    local_out = args.job.parent.parent
    marker = local_out / f"screen-{args.tag}.started.json"
    require(not marker.exists(), "unknown_spark_screen_requires_reconciliation")
    job_sha = sha(args.job)
    remote_out = f"{stage}/output/{remote_name}"
    root = f"{remote_out}/speech-job"
    receipt, screened, cache = (f"asr-screening-receipt-{args.tag}.json", f"render-manifest-screened-{args.tag}.json",
                                f"asr-unit-cache-{args.tag}")
    # The render root must hold exactly this job, a complete render manifest and no screening yet.
    probe = spark.out("set -e; R=%s; sha256sum $R/job.json | cut -c1-64; test -f $R/render-manifest.json && echo manifest;"
                      " test -e $R/%s && echo receipt-exists || true; test -e $R/%s && echo screened-exists || true;"
                      " sha256sum %s/%s/model.safetensors | cut -c1-64; test -f %s/qwen_asr/__init__.py && echo runtime;"
                      " grep MemAvailable /proc/meminfo | awk '{print $2}'; docker ps --format '{{.Names}}'"
                      % tuple(shlex.quote(x) for x in (root, receipt, screened, runtime["modelRoot"], runtime["asrSnapshot"],
                                                       runtime["asrRuntime"]))).split("\n")
    require(probe[0] == job_sha, f"remote_job_differs:{root}")
    require("manifest" in probe, f"render_manifest_missing:{root}")
    require("receipt-exists" not in probe and "screened-exists" not in probe, f"screen_exists:{root}/{receipt}")
    require(runtime["asrRevision"].split(":")[-1] in probe, "asr_weights_differ")
    require("runtime" in probe, "asr_runtime_missing")
    containers = [p for p in probe[probe.index("runtime") + 2:] if p]
    require(not containers, f"spark_busy:{containers}")
    code = f"/work/{args.code}"
    work = f"/work/output/{remote_name}/speech-job"
    command_for = lambda hold: [
        "docker", "run", "--rm", "--gpus", "all", "--ipc", "host", "--network", "none", "--read-only",
        "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", *session_labels(session, hold),
        "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=2g,mode=1777",
        "-v", stage + ":/work:rw", "-v", runtime["asrRuntime"] + ":/runtime-asr-v1/site-packages:ro",
        "-v", runtime["voicePackages"] + ":/voice-packages:ro", "-v", runtime["modelRoot"] + ":/model-cache:ro",
        "-e", "PYTHONPATH=" + container_pythonpath(code, "/runtime-asr-v1/site-packages", "/voice-packages"),
        "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HF_HOME=/tmp/hf", "-e", "HF_HUB_OFFLINE=1",
        "-e", "TRANSFORMERS_OFFLINE=1", "-e", "TOKENIZERS_PARALLELISM=false",
        "-e", "OMP_NUM_THREADS=4", "-e", "MKL_NUM_THREADS=4", "-e", "NUMBA_CACHE_DIR=/tmp/numba",
        "-e", "TRITON_CACHE_DIR=/tmp/triton", "-e", "TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor",
        "-e", "XDG_CACHE_HOME=/tmp/cache",
        "-w", code, "--entrypoint", "python", runtime["images"]["pytorchFfmpeg"],
        f"{code}/tools/ops/run.py", "audio.screening",
        "--job", f"{work}/job.json", "--render-manifest", f"{work}/render-manifest.json", "--artifact-root", work,
        "--model-path", f"/model-cache/{runtime['asrSnapshot']}", "--model-revision", runtime["asrRevision"],
        "--batch-size", args.batch_size, "--unit-cache", f"{work}/{cache}",
        "--out-receipt", f"{work}/{receipt}", "--out-manifest", f"{work}/{screened}"]
    returncode, outcome, hold = dispatch(
        spark, session, "screen", loc, stage=stage, code=args.code, command_for=command_for,
        log=f"{remote_out}/screen-{args.tag}.log", marker=marker,
        started={"jobSha256": job_sha, "model": "Qwen/Qwen3-ASR-0.6B", "modelRevision": runtime["asrRevision"],
                 "batchSize": int(args.batch_size)})
    spark.get(f"{remote_out}/", str(local_out / "spark-output") + "/")
    return finish(session, hold, returncode, outcome, local_out / f"screen-{args.tag}.result.json",
                  {"locale": loc, "phase": "asr-screen"})


# ---------------------------------------------------------------- audio QC


def mirrored(path: str | Path, mirror_root: Path) -> str:
    """A Mac path under the mirrored artifacts root, as the container sees it (same absolute path)."""
    resolved = str(Path(path).resolve())
    root = str(Path(mirror_root).resolve())
    require(resolved.startswith(root + "/"), f"not under the mirrored artifacts root {root}: {path}")
    return resolved


def audio_qc(args, runtime, spark, session) -> int:
    loc, stage = args.locale, args.stage
    root = Path(args.mirror_root).resolve()
    mirror = f"{stage}/mac-artifacts"
    run_dir = mirrored(args.run_dir, root)
    out_local = Path(args.out).resolve()
    out_local.mkdir(parents=True, exist_ok=True)
    marker = out_local / "spark-dispatch.started.json"
    require(not marker.exists(), "unknown_spark_audio_qc_requires_reconciliation")
    package, state, auth, out = (mirrored(path, root) for path in (args.audio_package, args.state_dir,
                                                                    args.api_budget_authorization, out_local))
    acceptance = mirrored(args.human_acceptance, root) if args.human_acceptance else None
    relative = lambda path: path[len(str(root)) + 1:]
    probe = spark.out("set -e; test -f %s && echo env-ok; test -s %s/%s && echo mirror-ok; "
                      "sha256sum %s/%s/model.safetensors | cut -c1-64; grep MemAvailable /proc/meminfo | awk '{print $2}'; "
                      "docker ps --format '{{.Names}}'"
                      % (shlex.quote(runtime["openaiEnvFile"]), shlex.quote(mirror), shlex.quote(relative(package)),
                         shlex.quote(runtime["modelRoot"]), shlex.quote(runtime["asrSnapshot"]))).split("\n")
    require("env-ok" in probe, "credential env file missing on Spark")
    require("mirror-ok" in probe, "audio package missing from the Spark mirror; rsync first")
    require(runtime["asrRevision"].split(":")[-1] in probe, "asr_weights_differ")
    busy = [p for p in probe if p and not p.isdigit() and p not in ("env-ok", "mirror-ok") and len(p) != 64]
    require(args.allow_busy or not busy, f"spark_busy:{busy}")
    cmap = out_local / "tts-checkpoint-map.container.json"
    cmap.write_text(json.dumps(checkpoint_map(runtime), indent=1))
    spark.put(str(cmap), f"{mirror}/{relative(out)}/")
    code = f"/work/{args.code}"
    command = ["--rm", "--gpus", "all", "--ipc", "host", "--read-only",
               "--user", "1000:1000", "--cap-drop", "ALL", "--security-opt", "no-new-privileges"]
    tail = ["--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=4g,mode=1777",
            "-v", stage + ":/work:ro", "-v", mirror + ":" + str(root) + ":rw",
            "-v", runtime["asrRuntime"] + ":/runtime-asr-v1/site-packages:ro", "-v", runtime["voicePackages"] + ":/voice-packages:ro",
            "-v", runtime["modelRoot"] + ":/model-cache:ro", "-v", runtime["speaker"]["checkpoint"] + ":/checkpoint:ro",
            "-v", runtime["openaiEnvFile"] + ":/secrets/openai.env:ro",
            "-e", "PYTHONPATH=" + container_pythonpath(code, "/runtime-asr-v1/site-packages", "/voice-packages"),
            "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "HF_HOME=/tmp/hf", "-e", "HF_HUB_OFFLINE=1",
            "-e", "TRANSFORMERS_OFFLINE=1", "-e", "TOKENIZERS_PARALLELISM=false",
            "-e", "NUMBA_CACHE_DIR=/tmp/numba", "-e", "TRITON_CACHE_DIR=/tmp/triton",
            "-e", "TORCHINDUCTOR_CACHE_DIR=/tmp/torchinductor", "-e", "XDG_CACHE_HOME=/tmp/cache",
            "-w", code, "--entrypoint", "python", runtime["images"]["pytorchFfmpeg"],
            f"{code}/scripts/run_with_openai_environment.py", "--environment", args.openai_environment,
            "--env-file", "/secrets/openai.env",
            "python", f"{code}/tools/ops/run.py", "review.qc_audio_run",
            "--run-dir", run_dir, "--out", out, "--state-dir", state, "--locales", loc,
            "--audio-package", f"{loc}={package}", "--backend", "real",
            "--asr-model-path", f"/model-cache/{runtime['asrSnapshot']}",
            "--tts-checkpoint-map", f"{out}/tts-checkpoint-map.container.json",
            "--text-backend", "api", "--api-budget-authorization", auth,
            "--max-api-calls", str(args.max_api_calls), "--workers", str(args.workers)]
    if acceptance:
        tail += ["--human-acceptance", f"{loc}={acceptance}"]
    command_for = lambda hold: ["docker", "run", *command, *session_labels(session, hold), *tail]
    returncode, outcome, hold = dispatch(
        spark, session, "audio-qc", loc, stage=stage, code=args.code, command_for=command_for,
        log=f"{mirror}/{relative(out)}/spark-driver.log", marker=marker,
        started={"audioPackage": package, "stateDir": state, "out": out, "humanAcceptance": acceptance})
    # Read back the driver output, the state dir it wrote (ledgers, receipts, call caches) and the budget root.
    readback = [relative(out), relative(state)]
    budget_root = json.loads(Path(auth).read_text())["budgetRoot"]
    if budget_root.startswith(str(root) + "/"):
        readback.append(relative(budget_root))
    for rel in readback:
        spark.get(f"{mirror}/{rel}/", f"{root}/{rel}/")
    return finish(session, hold, returncode, outcome, out_local / "spark-dispatch.result.json",
                  {"locale": loc, "phase": "audio-qc"})


# ---------------------------------------------------------------- command line


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    top.add_argument("--runtime", type=Path, default=RUNTIME)
    commands = top.add_subparsers(dest="command", required=True)

    def common(name, help_text):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--locale", required=True, choices=["zh-Hans", "ko", "es"])
        sub.add_argument("--stage", required=True, help="Absolute run stage directory on Spark")
        sub.add_argument("--code", required=True, help="Staged code directory under the stage, e.g. repo-1a2b3c4d")
        return sub

    sub = common("render", "formal Layer 3 render (GPU)")
    sub.add_argument("--job", type=Path, required=True)
    for name in CLI_INPUTS:
        sub.add_argument("--" + name, type=Path, required=True)
    sub.add_argument("--max-end-lag-seconds", type=float, default=8.0)
    sub.add_argument("--seed", type=int, default=42, help="Frozen TTS seed; a repair needs a fresh render root")
    sub.add_argument("--unit-instructions", type=Path, default=None)
    sub.add_argument("--remote-name", default=None, help="Spark output directory under output/ (a rebuilt job needs its own)")
    sub = common("compact", "edge-silence compaction and track assembly (CPU)")
    sub.add_argument("--job", type=Path, required=True, help="The local job.json the raw render root holds")
    for name in CLI_INPUTS:
        sub.add_argument("--" + name, type=Path, required=True)
    sub.add_argument("--raw-name", required=True)
    sub.add_argument("--remote-name", required=True)
    sub.add_argument("--max-end-lag-seconds", type=float, required=True)
    sub.add_argument("--trim-trailing", action="store_true")
    for name in ("padding-seconds", "inter-utterance-gap-seconds", "reaction-lag-seconds", "tail-overrun-seconds"):
        sub.add_argument("--" + name, type=float, default=None)
    sub.add_argument("--allow-busy", action="store_true")
    sub = common("screen", "Qwen3-ASR back-transcription screen (GPU)")
    sub.add_argument("--job", type=Path, required=True)
    sub.add_argument("--remote-name", default=None)
    sub.add_argument("--batch-size", default="1", choices=["1", "2", "4", "8"])
    sub.add_argument("--tag", default="v1")
    sub = common("audio-qc", "machine listening-waiver driver (GPU + secondary ASR API)")
    sub.add_argument("--audio-package", required=True)
    sub.add_argument("--state-dir", required=True, help="The locale's text QC state dir (shared repair ledgers)")
    sub.add_argument("--api-budget-authorization", required=True)
    sub.add_argument("--out", required=True)
    sub.add_argument("--run-dir", required=True, help="Directory the driver searches for the package inputs (mirrored)")
    sub.add_argument("--mirror-root", default=str(ROOT / "artifacts"),
                     help="Mac directory mirrored to <stage>/mac-artifacts and mounted at its own path")
    sub.add_argument("--openai-environment", choices=("dev", "prod"), default="dev")
    sub.add_argument("--max-api-calls", type=int, default=150)
    sub.add_argument("--workers", type=int, default=4)
    sub.add_argument("--human-acceptance", default=None)
    sub.add_argument("--allow-busy", action="store_true")
    return top


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    runtime = load_runtime(args.runtime)
    require(args.stage.startswith(runtime["stageRoot"].rstrip("/") + "/"), "stage_outside_runtime_stage_root")
    from scripts.spark_exclusive_session import Client
    session = Client.from_environment()
    handler = {"render": render, "compact": compact, "screen": screen, "audio-qc": audio_qc}[args.command]
    return handler(args, runtime, Spark(runtime["host"]), session)


if __name__ == "__main__":
    raise SystemExit(main())
