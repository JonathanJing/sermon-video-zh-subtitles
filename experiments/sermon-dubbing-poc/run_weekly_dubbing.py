#!/usr/bin/env python3
"""Execute/resume a prepared weekly job on the existing isolated Spark runtime.

This command never approves audio, sends messages, or deploys automatically.
The final review candidate remains bound to the existing Saturday evidence.
"""
import argparse
import difflib
import json
import math
from pathlib import Path
import shlex
import subprocess
import sys

from poc import sha256, write_json
from weekly_dubbing import read, validate_frozen, assemble
from render_weekly_audio import render_identity
from prepare_voice_candidates import ASR, ALIGNER
from screen_audio import normalize

HERE = Path(__file__).resolve().parent
REMOTE_ROOT = "/home/achillesjing/dgx-spark-benchmark/results"
RUNTIME = REMOTE_ROOT + "/sermon-voice-poc-20260905"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same_seconds(left, right, tolerance=.001):
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in [left, right]) and abs(left - right) <= tolerance


def stage_check(stage, action, check):
    try:
        return check()
    except (ValueError, OSError, KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError(f"{stage} cache is incomplete or stale: {exc}. Artifacts preserved; {action}.") from exc


def validated_job(work):
    job = read(work / "job.json")
    validate_frozen(job)
    return job


def validate_render(work, job, complete=True):
    identity = render_identity(work / "job.json", job["voice"]["checkpointSha256"])
    folder = work / "render"
    require(read(folder / "identity.json") == identity, "render job/checkpoint/settings changed; create a new job")
    records = []
    expected_names = {f"unit-{i:04d}" for i in range(len(job["units"]))}
    require(all(p.stem in expected_names for p in folder.glob("unit-*.*")), "render contains unknown unit files")
    for i, unit in enumerate(job["units"]):
        raw = folder / f"unit-{i:04d}.wav"
        receipt = raw.with_suffix(".json")
        if not complete and not raw.exists() and not receipt.exists():
            continue
        saved = read(receipt)
        require(saved["unit"] == unit and saved["identity"] == identity and saved["sha256"] == sha256(raw), f"unit {i} audio/text/settings differ from its receipt")
        records.append(saved)
    if not complete:
        require(not (folder / "chinese.raw.wav").exists(), "assembled WAV has no render/report.json receipt")
        return None
    report = read(folder / "report.json")
    require(all(report.get(k) == v for k, v in identity.items()) and report.get("status") == "complete_candidate_render", "render completion identity changed")
    require(report["sha256"] == sha256(folder / "chinese.raw.wav"), "assembled WAV changed")
    require(len(report["cues"]) == len(job["units"]), "render cue coverage differs from job")
    cursor = 0
    for i, (unit, saved, cue) in enumerate(zip(job["units"], records, report["cues"])):
        require(cue["unitId"] == i and cue["blockId"] == unit["blockId"] and cue["text"] == unit["text"], f"cue {i} no longer maps to its unit")
        require(same_seconds(cue["start"], cursor) and saved["durationSeconds"] > 0 and same_seconds(cue["end"] - cue["start"], saved["durationSeconds"]), f"cue {i} duration differs from generated audio")
        cursor = cue["end"] + (unit["gapAfterSeconds"] if i + 1 < len(records) else 0)
    require(same_seconds(report["durationSeconds"], cursor), "render total duration changed")
    return report


def validate_natural(work, job, render):
    library, assembly = read(work / "audio/library.json"), read(work / "assembly-report.json")
    require(library.get("schemaVersion") == "sermon-audio-library-v1" and library["date"] == job["week"] and len(library["tracks"]) == 1, "natural library is for another week or has incomplete tracks")
    track = library["tracks"][0]
    digest = sha256(work / "audio/zh-natural.mp3")
    require(track["file"] == "zh-natural.mp3" and track["sha256"] == digest, "natural MP3 differs from library")
    require(assembly["jobSha256"] == sha256(work / "job.json") and assembly["sha256"] == digest and assembly.get("fullDecode") == "pass", "natural assembly receipt is missing its job/audio/decode binding")
    cues = [{k: c[k] for k in ["start", "end", "text", "blockId"]} for c in render["cues"]]
    require(track["cues"] == cues and same_seconds(track["durationSeconds"], render["durationSeconds"]), "natural captions/duration differ from rendered units")
    require(same_seconds(assembly["durationSeconds"], render["durationSeconds"], .2), "encoded MP3 duration differs from render")
    review = read(work / "audio-review.json")
    require(review["jobSha256"] == sha256(work / "job.json") and review["mp3Sha256"] == digest and review["checkpointSha256"] == job["voice"]["checkpointSha256"], "natural review template belongs to changed inputs")
    return track


def validate_alignment(work, job):
    from check_weekly_timing import load_anchors
    report = read(work / "source-alignment/report.json")
    require(report.get("schemaVersion") == "sermon-acoustic-anchors-v1" and report.get("asr") == list(ASR) and report.get("aligner") == list(ALIGNER), "acoustic model/revision changed")
    return load_anchors(work, job, sha256(work / "job.json"))


def validate_alignment_cache(work, job):
    folder = work / "source-alignment"
    offsets = set(range(0, int(job["sourceDurationSeconds"]), 50))
    names = {p.name.split(".")[0] for p in folder.glob("window-*")}
    for name in names:
        require(name.removeprefix("window-").isdigit() and int(name.removeprefix("window-")) in offsets, "acoustic cache contains a window outside this source")
        wav = folder / (name + ".wav")
        receipt = read(wav.with_suffix(".asr.json"))
        identity = {"audioSha256": sha256(wav), "sourceSha256": job["inputs"]["sourceAudio"]["sha256"], "model": ASR[0], "revision": ASR[1]}
        require(receipt["identity"] == identity and isinstance(receipt["text"], str), f"acoustic {name} source/audio/model differs from its receipt")
        aligned = wav.with_suffix(".alignment.json")
        if aligned.exists():
            row = read(aligned)
            require(row["audioSha256"] == identity["audioSha256"] and row["model"] == ALIGNER[0] and row["revision"] == ALIGNER[1], f"acoustic {name} alignment settings changed")
    if (folder / "report.json").exists():
        validate_alignment(work, job)
    else:
        require(not (folder / "anchor-review.json").exists(), "anchor review has no acoustic report receipt")


def validate_screening_units(work, job, render, complete):
    issues = []
    folder = work / "audio/unit-screening"
    expected_names = {f"unit-{i:04d}.json" for i in range(len(job["units"]))}
    require(all(p.name in expected_names for p in folder.glob("unit-*.json")), "screening contains unknown unit receipts")
    for i, unit in enumerate(job["units"]):
        path = folder / f"unit-{i:04d}.json"
        if not complete and not path.exists():
            continue
        check = read(path)
        expected_text = unit.get("spokenText", unit["text"])
        identity = {"audioSha256": sha256(work / f"render/unit-{i:04d}.wav"), "expected": expected_text, "model": ASR[0], "revision": ASR[1]}
        require(check["identity"] == identity and check["unitId"] == i and check["blockId"] == unit["blockId"], f"ASR unit {i} is for changed audio/text/model")
        expected, actual = normalize(expected_text), normalize(check["recognized"])
        matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
        differences = [{"kind": op, "expected": expected[a:b], "recognized": actual[c:d]} for op, a, b, c, d in matcher.get_opcodes() if op != "equal"]
        require(check["differences"] == differences and same_seconds(check["similarity"], matcher.ratio(), 1e-9), f"ASR unit {i} difference evidence changed")
        if render is not None:
            issues.extend({"unitId": i, "blockId": unit["blockId"], "audioStart": render["cues"][i]["start"], **d} for d in differences)
    return issues


def validate_screening(work, job, render, track):
    report = read(work / "audio/asr-screening.json")
    require(report["jobSha256"] == sha256(work / "job.json") and report.get("status") == "machine_screening_only" and report.get("model") == ASR[0] and report.get("revision") == ASR[1], "ASR screening job/model changed")
    require(len(report["results"]) == 1, "ASR screening has incomplete or extra results")
    result = report["results"][0]
    require(result["id"] == track["id"] and result["sha256"] == track["sha256"] and result["fullDecode"] == "pass", "ASR screening is for changed MP3")
    require(result["screenedUnits"] == result["expectedUnits"] == len(job["units"]) and same_seconds(result["durationSeconds"], render["durationSeconds"]), "ASR coverage or duration is incomplete")
    require(result["reviewCandidates"] == validate_screening_units(work, job, render, complete=True), "ASR summary no longer matches unit receipts")


def validate_timing(work, job, render):
    from check_weekly_timing import budgets, load_anchors, load_placements
    anchors, approval_hash = load_anchors(work, job, sha256(work / "job.json"))
    placements, placement_hash = load_placements(work, job, render, anchors)
    rows, failures = budgets(job["blocks"], anchors, render["cues"], job["sourceDurationSeconds"], placements)
    report = read(work / "synchronization/report.json")
    require(report.get("schemaVersion") == "sermon-video-sync-budget-v1" and report["jobSha256"] == sha256(work / "job.json"), "timing report belongs to a changed job")
    require(report["alignmentSha256"] == sha256(work / "source-alignment/report.json") and report.get("anchorReviewSha256") == approval_hash, "timing alignment or anchor review changed")
    require(report.get("placementReviewSha256") == placement_hash, "timing playback placement changed")
    require(report["sourceVideoOffsetSeconds"] == job["sourceStartSeconds"] and report["durationSeconds"] == job["sourceDurationSeconds"], "timing source window changed")
    require(report["blocks"] == rows and report["failures"] == failures and report["status"] == ("needs_timing_review" if failures else "natural_timing_fits"), "timing budget no longer matches current audio/anchors")


RENDER_RECOVERY = "restore the matching render receipts, or create a new job and rerun run_weekly_dubbing.py"
NATURAL_RECOVERY = "restore the matching library/assembly/review receipts, or create a new job and rerun weekly_dubbing.py assemble"
ALIGNMENT_RECOVERY = "create a new job or preserve and restore the matching source-alignment cache before running align_weekly_source.py"
SCREENING_RECOVERY = "preserve the old screening directory and rerun screen_weekly_audio.py --work with the current job"
TIMING_RECOVERY = "preserve the old synchronization report and rerun check_weekly_timing.py --work with the current anchor review"


def validate_candidate(work):
    """Read-only, complete cache verification; never grants human approval."""
    work = Path(work).resolve()
    job = stage_check("Job", "restore the frozen inputs or prepare a new job", lambda: validated_job(work))
    render = stage_check("Render", RENDER_RECOVERY, lambda: validate_render(work, job))
    track = stage_check("Natural audio", NATURAL_RECOVERY, lambda: validate_natural(work, job, render))
    stage_check("Source alignment", ALIGNMENT_RECOVERY, lambda: validate_alignment_cache(work, job))
    stage_check("ASR screening", SCREENING_RECOVERY, lambda: validate_screening(work, job, render, track))
    stage_check("Timing", TIMING_RECOVERY, lambda: validate_timing(work, job, render))
    return {"jobSha256": sha256(work / "job.json"), "mp3Sha256": track["sha256"], "renderSha256": sha256(work / "render/report.json"),
        "sourceAlignmentSha256": sha256(work / "source-alignment/report.json"), "audioScreeningSha256": sha256(work / "audio/asr-screening.json"), "timingReportSha256": sha256(work / "synchronization/report.json")}


def validate_cached_stages(work, job):
    """Reject stale saved stages before any SSH or model work is started."""
    render, track = None, None
    folder = work / "render"
    if folder.exists() and any(folder.iterdir()):
        render = stage_check("Render", RENDER_RECOVERY, lambda: validate_render(work, job, complete=(folder / "report.json").exists()))
    if any((work / name).exists() for name in ["audio/library.json", "audio/zh-natural.mp3", "assembly-report.json", "audio-review.json"]):
        require(render is not None, "Natural audio has no completed render receipt; artifacts preserved; " + RENDER_RECOVERY)
        track = stage_check("Natural audio", NATURAL_RECOVERY, lambda: validate_natural(work, job, render))
    stage_check("Source alignment", ALIGNMENT_RECOVERY, lambda: validate_alignment_cache(work, job))
    if (work / "audio/asr-screening.json").exists():
        require(render is not None and track is not None, "ASR screening has no completed natural audio; artifacts preserved; " + NATURAL_RECOVERY)
        stage_check("ASR screening", SCREENING_RECOVERY, lambda: validate_screening(work, job, render, track))
    else:
        stage_check("ASR screening", SCREENING_RECOVERY, lambda: validate_screening_units(work, job, render, complete=False))
    if (work / "synchronization/report.json").exists():
        require(render is not None, "Timing has no completed render receipt; artifacts preserved; " + RENDER_RECOVERY)
        stage_check("Timing", TIMING_RECOVERY, lambda: validate_timing(work, job, render))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--remote-checkpoint", required=True)
    p.add_argument("--host", default="achillesjing@192.168.1.152")
    p.add_argument("--mlx-python", type=Path, default=Path.home() / ".local/share/uv/tools/mlx-audio/bin/python")
    args = p.parse_args()
    work = args.work.resolve()
    job = stage_check("Job", "restore the frozen inputs or prepare a new job", lambda: validated_job(work))
    validate_cached_stages(work, job)
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
    render = stage_check("Render", RENDER_RECOVERY, lambda: validate_render(work, job))
    if not (work / "audio/library.json").exists():
        assemble(work)
    track = stage_check("Natural audio", NATURAL_RECOVERY, lambda: validate_natural(work, job, render))
    stages = [("align_weekly_source.py", "source-alignment/report.json", "Source alignment", ALIGNMENT_RECOVERY, lambda: validate_alignment(work, job)),
        ("screen_weekly_audio.py", "audio/asr-screening.json", "ASR screening", SCREENING_RECOVERY, lambda: validate_screening(work, job, render, track)),
        ("check_weekly_timing.py", "synchronization/report.json", "Timing", TIMING_RECOVERY, lambda: validate_timing(work, job, render))]
    for script, report, name, recovery, check in stages:
        if not (work / report).exists():
            subprocess.run([str(args.mlx_python), str(HERE / script), "--work", str(work)], check=True)
        stage_check(name, recovery, check)
    evidence = validate_candidate(work)
    write_json(work / "workflow-receipt.json", {"status": "candidate_ready_for_extended_saturday_review", **evidence,
        "remoteWork": None if imported_render else remote, "renderImported": imported_render, "remoteCheckpoint": str(checkpoint), "humanAudioReview": "pending"})
    print(f"Candidate ready: {work / 'audio/zh-natural.mp3'}\nContinue the Saturday review in {work / 'audio-review.json'}")


if __name__ == "__main__":
    main()
