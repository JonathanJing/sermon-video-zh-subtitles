#!/usr/bin/env python3
"""Execute/resume a prepared weekly job with MacBook-first model routing.

This command never approves audio, sends messages, or deploys automatically.
The final review candidate remains bound to the existing Saturday evidence.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from contextvars import copy_context
import threading
import difflib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from scripts.sermon_accounting import accounting_session, record_workload, stage as accounting_stage, subprocess_environment
from scripts.sermon_execution_harness import (Execution, ExecutionTerminated, RemoteOutcomeUnknown, WorkAlreadyRunning,
    atomic_json, bounded_process as process_run, utc_now, work_lock)
from scripts.sermon_model_resources import local_model_slot
from poc import sha256, write_json
from weekly_dubbing import read, validate_frozen, assemble
from render_weekly_audio import render_identity
from speech_backend import ASR, ALIGNER, accepted_model
from spark_transport import dispatch
from screen_audio import normalize

REMOTE_ROOT = "/home/achillesjing/dgx-spark-benchmark/results"
RUNTIME = REMOTE_ROOT + "/sermon-voice-poc-20260905"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def same_speech_identity(actual, expected):
    return (accepted_model(actual.get("model"), actual.get("revision"), "asr")
            and {k: v for k, v in actual.items() if k not in ("model", "revision")}
            == {k: v for k, v in expected.items() if k not in ("model", "revision")})


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
    folder = work / "render"
    saved_identity = read(folder / "identity.json")
    identity = render_identity(work / "job.json", job["voice"]["checkpointSha256"], device=saved_identity.get("executionDevice", "cuda:0"))
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
    require(report.get("schemaVersion") == "sermon-acoustic-anchors-v1" and accepted_model(*report.get("asr", [None, None]), "asr") and accepted_model(*report.get("aligner", [None, None]), "aligner"), "acoustic model/revision changed")
    for field, pattern, nested in [("asrModels", "window-*.asr.json", True), ("alignerModels", "window-*.alignment.json", False)]:
        if field in report:
            actual = []
            for receipt in sorted((work / "source-alignment").glob(pattern)):
                row = read(receipt)
                row = row["identity"] if nested else row
                pair = [row["model"], row["revision"]]
                if pair not in actual:
                    actual.append(pair)
            require(report[field] == actual and actual and report["asr" if nested else "aligner"] == actual[0], "Acoustic model inventory differs from actual receipts")
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
        require(same_speech_identity(receipt["identity"], identity) and isinstance(receipt["text"], str), f"acoustic {name} source/audio/model differs from its receipt")
        aligned = wav.with_suffix(".alignment.json")
        if aligned.exists():
            row = read(aligned)
            require(row["audioSha256"] == identity["audioSha256"] and accepted_model(row["model"], row["revision"], "aligner"), f"acoustic {name} alignment settings changed")
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
        require(same_speech_identity(check["identity"], identity) and check["unitId"] == i and check["blockId"] == unit["blockId"], f"ASR unit {i} is for changed audio/text/model")
        expected, actual = normalize(expected_text), normalize(check["recognized"])
        matcher = difflib.SequenceMatcher(None, expected, actual, autojunk=False)
        differences = [{"kind": op, "expected": expected[a:b], "recognized": actual[c:d]} for op, a, b, c, d in matcher.get_opcodes() if op != "equal"]
        require(check["differences"] == differences and same_seconds(check["similarity"], matcher.ratio(), 1e-9), f"ASR unit {i} difference evidence changed")
        if render is not None:
            issues.extend({"unitId": i, "blockId": unit["blockId"], "audioStart": render["cues"][i]["start"], **d} for d in differences)
    return issues


def validate_screening(work, job, render, track):
    report = read(work / "audio/asr-screening.json")
    require(report["jobSha256"] == sha256(work / "job.json") and report.get("status") == "machine_screening_only" and accepted_model(report.get("model"), report.get("revision"), "asr"), "ASR screening job/model changed")
    if "modelIdentities" in report:
        models = []
        for index in range(len(job["units"])):
            identity = read(work / f"audio/unit-screening/unit-{index:04d}.json")["identity"]
            pair = [identity["model"], identity["revision"]]
            if pair not in models:
                models.append(pair)
        require(report["modelIdentities"] == models and models and [report["model"], report["revision"]] == models[0], "Screening model inventory differs from actual receipts")
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


def receipt_snapshot(work, job):
    """Count only expected receipts after the existing render validator passes."""
    return {i: sha256(path) for i in range(len(job["units"]))
            if (path := work / f"render/unit-{i:04d}.json").is_file()}


def revision_workload(work, job):
    """Report parent reuse only when the revision plan and WAV receipts agree."""
    metrics = {"revisionReportPresent": False, "revisionEvidenceVerified": False, "revisionReportSha256": None,
               "parentReusedUnitCount": None, "revisionRegenerateUnitCount": None}
    path = work / "revision-report.json"
    if not path.is_file():
        return metrics
    metrics["revisionReportPresent"] = True
    try:
        metrics["revisionReportSha256"] = sha256(path)
        report = read(path)
        parent = Path(job["revisionOf"]["path"])
        parent_hash = sha256(parent / "job.json")
        require(report["jobSha256"] == sha256(work / "job.json")
                and report["parentJobSha256"] == job["revisionOf"]["jobSha256"] == parent_hash, "revision identity")
        pairs = ([(row["unitId"], row["parentUnitId"]) for row in report["reusedUnits"]]
                 if "reusedUnits" in report else [(i, i) for i in report["reusedUnitIds"]])
        reused, parents = [i for i, _ in pairs], [i for _, i in pairs]
        changed = report["regenerateUnitIds"]
        require(all(type(i) is int for i in reused + parents + changed)
                and len(set(reused)) == len(reused) and len(set(parents)) == len(parents)
                and len(set(changed)) == len(changed) and not set(reused) & set(changed)
                and set(reused) | set(changed) == set(range(len(job["units"]))), "revision coverage")
        old = read(parent / "job.json")
        for child_id, parent_id in pairs:
            require(0 <= parent_id < len(old["units"]), "parent unit")
            current = read(work / f"render/unit-{child_id:04d}.json")
            original_wav = parent / f"render/unit-{parent_id:04d}.wav"
            original_receipt = original_wav.with_suffix(".json")
            original = read(original_receipt)
            provenance = current["reusedFrom"]
            require(Path(provenance["path"]).resolve() == original_wav.resolve()
                    and provenance.get("unitId", parent_id) == parent_id
                    and provenance["receiptSha256"] == sha256(original_receipt)
                    and provenance["wavSha256"] == original["sha256"] == current["sha256"] == sha256(original_wav)
                    and provenance["generationIdentity"] == original["identity"]
                    and original["identity"]["jobSha256"] == parent_hash
                    and original["unit"] == old["units"][parent_id], "parent receipt")
            keys = ("blockId", "text", "gapAfterSeconds")
            previous, unit = original["unit"], job["units"][child_id]
            require(all(previous.get(k) == unit.get(k) for k in keys)
                    and previous.get("spokenText", previous["text"]) == unit.get("spokenText", unit["text"]), "reused speech")
        metrics.update(revisionEvidenceVerified=True, parentReusedUnitCount=len(reused),
                       revisionRegenerateUnitCount=len(changed))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
        # Optional accounting evidence never grants approval or changes existing gates.
        pass
    return metrics


def record_render_workload(work, job, render, before, imported_render):
    after = receipt_snapshot(work, job)
    timer = render.get("generationSeconds")
    if type(timer) not in (int, float) or not math.isfinite(timer) or timer < 0:
        timer = None
    record_workload("render_output", {
        "jobSha256": sha256(work / "job.json"), "renderReportSha256": sha256(work / "render/report.json"),
        "acceptedUnitCount": len(after), "localCachedUnitCountAtStart": len(before),
        "newlyAvailableOutputUnitCount": len(set(after) - set(before)),
        "preservedLocalReceiptCount": sum(after.get(i) == digest for i, digest in before.items()),
        "currentRunGeneratedUnitCount": 0 if imported_render else None, "modelInputUnitCount": 0 if imported_render else None,
        "completeRenderCacheHit": imported_render, "modelTimerSeconds": timer,
        "modelTimerIsHistorical": True if imported_render else None, "timingScope": "after_model_load",
        "evidenceScope": "existing_report", "countStatus": "verified_receipts",
        "modelTimerIsPureModelTime": False, "modelTimerIncludesLoadOrPriorRetries": False,
        **revision_workload(work, job)})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--remote-checkpoint", required=True)
    p.add_argument("--host", default="achillesjing@192.168.1.152")
    p.add_argument("--local-checkpoint", type=Path, default=os.environ.get("SERMON_LOCAL_TTS_CHECKPOINT", str(HERE.parents[1] / "artifacts/model-routing/macbook-tts/checkpoint")))
    p.add_argument("--local-python", default=os.environ.get("SERMON_LOCAL_TTS_PYTHON", str(HERE.parents[1] / "artifacts/model-routing/macbook-tts/runtime/bin/python")))
    p.add_argument("--speech-python", "--mlx-python", dest="speech_python", type=Path, default=Path.home() / ".local/share/uv/tools/mlx-audio/bin/python")
    p.add_argument("--command-timeout", type=float, default=3600, help="Maximum seconds for each local/model command")
    p.add_argument("--transfer-timeout", type=float, default=600, help="Maximum seconds for each SSH probe or transfer")
    p.add_argument("--serial-stages", action="store_true", help="Disable independent source-alignment/render overlap for diagnostics")
    p.add_argument("--execution-timeout", type=float, default=21600, help="Maximum seconds for this candidate attempt")
    args = p.parse_args()
    work = args.work.resolve()
    try:
        job_hash = sha256(work / "job.json")
    except OSError:
        job_hash = None  # The existing job validator supplies the actionable error below.
    with accounting_session(work / "accounting", "weekly_dubbing", metadata={"jobSha256": job_hash}):
        run(args, work)


def run(args, work, job=None):
    work = Path(work).resolve()
    with work_lock(work):
        with accounting_stage("job_validation", billing="local"):
            current = stage_check("Job", "restore the frozen inputs or prepare a new job", lambda: validated_job(work))
            if job is not None and job != current:
                raise ValueError("Job changed before acquiring its execution lock")
            job = current
            record_workload("weekly_job", {"jobSha256": sha256(work / "job.json"),
                "blockCount": len(job["blocks"]) if isinstance(job.get("blocks"), list) else None,
                "unitCount": len(job["units"]) if isinstance(job.get("units"), list) else None,
                "sourceDurationSeconds": job.get("sourceDurationSeconds")})
        with Execution(work, sha256(work / "job.json"), timeout=getattr(args, "execution_timeout", 21600)) as execution:
            _run(args, work, job, execution)


def pending_import_path(work):
    return Path(work) / "accounting" / "harness" / "pending-import.json"


def validate_import_source(work, job, folder):
    """Revalidate quarantined bytes without trusting paths from a pending pointer."""
    work, folder = Path(work).resolve(), Path(folder)
    root = work / "accounting" / "remote-recovery"
    require(root.resolve() == root and folder.is_absolute() and folder.parent == root
            and folder.resolve() == folder and folder.is_dir(), "Unsafe remote import quarantine path")
    copied_job = folder / "job.json"
    require(copied_job.is_file() and not copied_job.is_symlink()
            and sha256(copied_job) == sha256(work / "job.json"), "Remote import job copy changed")
    source = folder / "render"
    require(source.is_dir() and not source.is_symlink() and (source / "identity.json").is_file(),
            "Remote output has no verifiable render identity; preserve and inspect")
    require(all(not path.is_symlink() for path in source.rglob("*")), "Unsafe remote import symlink")
    validate_render(folder, job, complete=(source / "report.json").exists())
    names = ["identity.json"]
    for i in range(len(job["units"])):
        if (source / f"unit-{i:04d}.json").exists():
            names += [f"unit-{i:04d}.wav", f"unit-{i:04d}.json"]
    if (source / "report.json").exists():
        names += ["chinese.raw.wav", "report.json"]
    for receipt in source.glob("unit-*.json"):
        override = read(receipt).get("generationOverride", {})
        if "failedAudioPreserved" in override:
            relative = Path(override["failedAudioPreserved"])
            require(not relative.is_absolute() and ".." not in relative.parts
                    and bool(relative.parts) and relative.parts[0] == "diagnostics", "Unsafe repair diagnostic path")
            diagnostic = source / relative
            require(diagnostic.is_file() and sha256(diagnostic) == override.get("failedAudioSha256"),
                    "Missing or changed repair diagnostic")
    diagnostics = source / "diagnostics"
    if diagnostics.exists():
        for diagnostic in sorted(diagnostics.rglob("*")):
            if diagnostic.is_file():
                names.append(str(diagnostic.relative_to(source)))
    return source, {name: sha256(source / name) for name in names}


def validate_import_targets(work, files, *, resuming=False):
    """Check every collision before copying any missing file."""
    work = Path(work).resolve()
    for name, digest in files.items():
        target = work / "render" / name
        temporary = target.with_suffix(target.suffix + ".recovery-tmp")
        require(target.resolve() == target and temporary.resolve() == temporary,
                "Unsafe local import target path")
        require(not target.exists() or target.is_file() and sha256(target) == digest,
                "Local and remote output differ; both preserved for inspection")
        require(not temporary.exists() or resuming and temporary.is_file(),
                "Unowned remote import temporary file; preserve and inspect")


def resume_pending_import(work, job):
    """Finish only an explicitly recorded, hash-bound interrupted local import."""
    work = Path(work).resolve()
    pending = pending_import_path(work)
    if not pending.exists():
        return False
    require(not pending.is_symlink() and pending.resolve() == pending, "Unsafe pending import path")
    saved = read(pending)
    require(isinstance(saved, dict) and saved.get("schemaVersion") == "sermon-remote-import-v1"
            and saved.get("jobSha256") == sha256(work / "job.json"), "Pending import belongs to a changed job")
    folder_value = saved.get("quarantine")
    require(isinstance(folder_value, str), "Missing pending import quarantine")
    source, files = validate_import_source(work, job, Path(folder_value))
    require(saved.get("files") == files, "Pending remote import quarantine changed after verification")
    validate_import_targets(work, files, resuming=True)
    for name, digest in files.items():
        target = work / "render" / name
        temporary = target.with_suffix(target.suffix + ".recovery-tmp")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            # This scratch file is owned by the durable pending manifest. Its
            # verified quarantine source survives interruption and is retained.
            shutil.copyfile(source / name, temporary)
            require(sha256(temporary) == digest, "Remote import source changed during copy")
            temporary.replace(target)
        elif temporary.exists():
            require(sha256(temporary) == digest, "Unexpected partial temporary beside a completed import")
            temporary.unlink()
    # Only render files were imported. Other independent branches may be
    # between WAV and receipt writes; their own completion gates validate them.
    validate_render(work, job, complete=(work / "render/report.json").exists())
    pending.unlink()  # Derived pointer only; immutable quarantine remains intact.
    return True


def reconcile_remote(work, job, fetch):
    """Fetch to quarantine, validate, then durably record a missing-files import."""
    import uuid
    work = Path(work).resolve()
    pending = pending_import_path(work)
    require(not pending.exists(), "Resume the existing pending import before fetching remote output")
    root = work / "accounting" / "remote-recovery"
    require(root.resolve() == root, "Unsafe remote import quarantine root")
    folder = root / uuid.uuid4().hex
    folder.mkdir(parents=True, mode=0o700)
    shutil.copyfile(work / "job.json", folder / "job.json")
    fetch(folder)
    _, files = validate_import_source(work, job, folder)
    validate_import_targets(work, files)
    require(pending.resolve() == pending, "Unsafe pending import path")
    atomic_json(pending, {"schemaVersion": "sermon-remote-import-v1", "jobSha256": sha256(work / "job.json"),
                         "quarantine": str(folder), "files": files, "createdAt": utc_now()})
    resume_pending_import(work, job)


def validate_local_render_cache(work, job):
    """Inspect MPS attempt data before *any* environment-based fallback."""
    folder = work / "local-render-mps"
    if not folder.exists():
        return
    require(folder.resolve() == folder and folder.is_dir(), "Unsafe local MPS attempt directory")
    require(all(not path.is_symlink() for path in folder.rglob("*")), "Unsafe local MPS cache symlink")
    identity = render_identity(work / "job.json", job["voice"]["checkpointSha256"], device="mps")
    require(read(folder / "identity.json") == identity, "Local MPS cache identity changed")
    expected = {f"unit-{i:04d}" for i in range(len(job["units"]))}
    require(all(path.stem in expected and path.suffix in (".wav", ".json") for path in folder.glob("unit-*")), "Unknown local MPS audio unit")
    for i, unit in enumerate(job["units"]):
        raw = folder / f"unit-{i:04d}.wav"
        receipt = raw.with_suffix(".json")
        require(not raw.exists() or receipt.exists(), "Unreceipted local MPS audio; inspect before fallback")
        if receipt.exists():
            saved = read(receipt)
            require(saved["unit"] == unit and saved["identity"] == identity and saved["sha256"] == sha256(raw), "Stale local MPS audio; inspect before fallback")
    assembled = folder / "chinese.raw.wav"
    report_path = folder / "report.json"
    require(not assembled.exists() or report_path.exists(), "Unreceipted assembled MPS audio")
    if report_path.exists():
        report = read(report_path)
        require(all(report.get(k) == v for k, v in identity.items()) and report.get("status") == "complete_candidate_render"
                and report["sha256"] == sha256(assembled), "Changed local MPS completion report")
        require(all((folder / f"unit-{i:04d}.json").exists() for i in range(len(job["units"]))), "Incomplete local MPS completion report")


@contextmanager
def alignment_branch(action, cancel_event, *, parallel=True):
    """One independent worker; drain/cancel before releasing the parent job lock.

    Context propagation keeps accounting and inherited lock descriptors bound to
    the same attempt. A failed branch stops new model commands in its sibling;
    successful receipts survive so the ordinary validators can resume them.
    """
    if not parallel:
        finished = False
        def join():
            nonlocal finished
            if not finished:
                action()
                finished = True
        yield join
        return
    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="source-alignment")
    def worker():
        try:
            return action()
        except BaseException:
            cancel_event.set()
            raise
    future = pool.submit(copy_context().run, worker)
    try:
        yield future.result
        future.result()
    except BaseException as exc:
        cancel_event.set()
        future.cancel()
        if isinstance(exc, ExecutionTerminated) and future.done() and not future.cancelled():
            failure = future.exception()
            if failure is not None:
                raise failure from exc
        raise
    finally:
        # bounded_process observes cancellation and terminates only its owned
        # child process group. Never release the job lease over a live worker.
        pool.shutdown(wait=True, cancel_futures=True)


def _run(args, work, job, execution):
    cancel_event = threading.Event()
    @contextmanager
    def stage(name, *, billing="local", cache_hit=False):
        with accounting_stage(name, billing=billing, cache_hit=cache_hit), execution.stage(name, cache_hit=cache_hit):
            yield

    def command(argv, *, transfer=False, **kwargs):
        limit = getattr(args, "transfer_timeout", 600) if transfer else getattr(args, "command_timeout", 3600)
        model_command = len(argv) > 1 and Path(argv[1]).name in {
            "render_weekly_audio.py", "align_weekly_source.py", "screen_weekly_audio.py"}
        slot = local_model_slot(cancel_event=cancel_event, timeout=execution.remaining(limit)) if model_command else nullcontext()
        environment = kwargs.pop("env", None) or subprocess_environment()
        def invoke(cmd, **options):
            options.setdefault("env", environment)
            return process_run(cmd, timeout=execution.remaining(limit),
                               cancel_event=cancel_event, **options)
        with slot:
            return dispatch(argv, invoke, **kwargs)

    with stage("cache_validation", billing="local"):
        resume_pending_import(work, job)
        validate_cached_stages(work, job)
        validate_local_render_cache(work, job)
        before = receipt_snapshot(work, job)
        record_workload("render_cache", {"expectedUnitCount": len(job["units"]),
            "localCachedUnitCount": len(before), "missingLocalUnitCount": len(job["units"]) - len(before),
            "completeRenderCache": (work / "render/report.json").exists()})
    def align_source():
        cached = (work / "source-alignment/report.json").exists()
        with stage("source_alignment", cache_hit=cached):
            if not cached:
                python = getattr(args, "speech_python", Path(sys.executable))
                command([str(python if Path(python).exists() else sys.executable),
                         str(HERE / "align_weekly_source.py"), "--work", str(work)], check=True)
            stage_check("Source alignment", ALIGNMENT_RECOVERY, lambda: validate_alignment(work, job))

    with alignment_branch(align_source, cancel_event, parallel=not getattr(args, "serial_stages", False)) as join_alignment:
        _render_and_finish(args, work, job, execution, stage, command, before, join_alignment)


def _render_and_finish(args, work, job, execution, stage, command, before, join_alignment):
    local_rendered = False
    if not (work / "render/report.json").exists():
        with stage("local_render_attempt", billing="local"):
            local_checkpoint = getattr(args, "local_checkpoint", None)
            local_receipt = {"primary": "macbook_mps", "fallback": "dgx_spark_cuda"}
            if (work / "render").exists():
                local_receipt["fallbackReason"] = "preserve_existing_render_backend"
            elif not local_checkpoint or not Path(local_checkpoint).is_dir():
                local_receipt["fallbackReason"] = "local_checkpoint_unavailable"
            else:
                # Checkpoint mismatches and output validation failures never trigger fallback.
                require(sha256(Path(local_checkpoint) / "model.safetensors") == job["voice"]["checkpointSha256"], "Wrong local speaker checkpoint")
                try:
                    command([str(getattr(args, "local_python", sys.executable)), str(HERE / "render_weekly_audio.py"),
                        "--job", str(work / "job.json"), "--checkpoint", str(local_checkpoint), "--out", str(work / "local-render-mps"), "--device", "mps"], check=True)
                    (work / "local-render-mps").rename(work / "render")
                    validate_render(work, job)
                    local_receipt["status"] = "local_render_complete"
                    local_rendered = True
                except FileNotFoundError:
                    local_receipt["fallbackReason"] = "local_python_unavailable"
                except subprocess.CalledProcessError as exc:
                    if exc.returncode != 75:
                        raise
                    local_receipt["fallbackReason"] = "local_model_runtime_unavailable"
            atomic_json(work / "accounting" / "local-render-attempt.json", local_receipt)
    checkpoint = Path(args.remote_checkpoint)
    if not checkpoint.is_absolute() or not str(checkpoint).startswith(REMOTE_ROOT + "/sermon-") or ".." in checkpoint.parts:
        raise ValueError("Use a checkpoint in the isolated sermon results directory")
    remote = f'{REMOTE_ROOT}/sermon-weekly-{job["week"]}-{sha256(work / "job.json")[:12]}'
    container = "sermon-voice-weekly-" + sha256(work / "job.json")[:12]
    remote_state = work / "accounting" / "harness" / "remote-attempt.json"
    remote_marker = remote + "/.harness-attempt-" + execution.attempt
    imported_render = (work / "render/report.json").exists() and not local_rendered
    ssh_options = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=2", args.host]
    scp_options = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=2"]

    def ssh(text, *, transfer=False, capture=False):
        return command([*ssh_options, text], transfer=transfer, check=True, capture_output=capture, text=capture)

    def ensure_remote_idle():
        result = ssh("docker ps -a --filter " + shlex.quote("name=^/" + container + "$") + " --format '{{.State}}'", transfer=True, capture=True)
        if result.stdout.strip():
            raise RemoteOutcomeUnknown("The job container still exists on Spark; inspect it before starting another attempt")

    def remote_model(argv, logfile):
        atomic_json(remote_state, {"schemaVersion": 1, "jobSha256": sha256(work / "job.json"),
            "container": container, "remoteWork": remote, "attemptId": execution.attempt,
            "status": "outcome_unknown", "startedAt": utc_now()})
        try:
            ssh("touch " + shlex.quote(remote_marker) + " && " + shlex.join(argv) + " >> " + shlex.quote(remote + "/" + logfile) + " 2>&1")
        except subprocess.TimeoutExpired as exc:
            raise RemoteOutcomeUnknown("Remote command timed out; next run must reconcile Spark output before generation") from exc
        except subprocess.CalledProcessError as exc:
            if exc.returncode == 255:
                raise RemoteOutcomeUnknown("SSH disconnected; remote model outcome must be reconciled") from exc
            # A name conflict/transport failure must not launch a repair against a live job.
            ensure_remote_idle()
            raise
        else:
            atomic_json(remote_state, {"schemaVersion": 1, "jobSha256": sha256(work / "job.json"),
                "attemptId": execution.attempt, "status": "command_completed", "endedAt": utc_now()})

    if not (work / "render/report.json").exists():
        with stage("transfer_upload", billing="local"):
            ensure_remote_idle()
            if remote_state.exists():
                saved = read(remote_state)
                require(saved.get("jobSha256") == sha256(work / "job.json"), "Remote attempt belongs to another job; preserve and inspect")
                if saved.get("status") in {"outcome_unknown", "command_completed"}:
                    try:
                        reconcile_remote(work, job, lambda folder: command([*scp_options, "-r", args.host + ":" + remote + "/render", str(folder)], transfer=True, check=True))
                    except (ValueError, OSError, subprocess.SubprocessError) as exc:
                        raise RemoteOutcomeUnknown("Remote output could not be safely reconciled; preserved copies require inspection") from exc
                    atomic_json(remote_state, {**saved, "status": "output_reconciled", "reconciledAt": utc_now()})
            if not (work / "render/report.json").exists():
                ssh("mkdir -p " + shlex.quote(remote), transfer=True)
                command([*scp_options, str(work / "job.json"), str(HERE / "render_weekly_audio.py"), str(HERE / "retry_weekly_unit.py"), str(HERE / "run_qwen_training_smoke.py"), args.host + ":" + remote + "/"], transfer=True, check=True)
                if (work / "render/identity.json").exists():
                    exists = command([*ssh_options, "test -d " + shlex.quote(remote + "/render")], transfer=True)
                    if exists.returncode == 1:
                        command([*scp_options, "-r", str(work / "render"), args.host + ":" + remote + "/"], transfer=True, check=True)
                    elif exists.returncode != 0:
                        raise ValueError("Cannot inspect the remote resume directory")
            else:
                imported_render = True
    if not (work / "render/report.json").exists():
        render_command = ["docker", "run", "--rm", "--name", container, "--gpus", "all", "--memory", "24g", "--memory-swap", "28g", "--cpus", "6", "--shm-size", "1g", "--user", "1000:1000",
            "-v", remote + ":/work", "-v", RUNTIME + "/venv:/work/venv:ro", "-v", str(checkpoint) + ":/checkpoint:ro", "-v", RUNTIME + "/model-cache:/cache", "-w", "/work", "-e", "HF_HOME=/cache", "-e", "USE_TF=0", "-e", "PYTHONUNBUFFERED=1",
            "nvcr.io/nvidia/pytorch:26.06-py3", "/work/venv/bin/python", "/work/render_weekly_audio.py", "--job", "/work/job.json", "--checkpoint", "/checkpoint", "--out", "/work/render"]
        for attempt in range(6):
            try:
                with stage("render", billing="local"):
                    remote_model(render_command, "runner.log")
                break
            except subprocess.CalledProcessError:
                if attempt == 5:
                    raise
                with stage("render_recovery", billing="local"):
                    identity = json.loads(ssh("test " + shlex.quote(remote + "/render/failure.json")
                        + " -nt " + shlex.quote(remote_marker) + " && cat "
                        + shlex.quote(remote + "/render/identity.json"), transfer=True, capture=True).stdout)
                    require(identity == render_identity(work / "job.json", job["voice"]["checkpointSha256"]),
                        "Repair requires current renderer identity and a failure written by this attempt")
                    failure = json.loads(ssh("cat " + shlex.quote(remote + "/render/failure.json"), transfer=True, capture=True).stdout)
                    if failure.get("reason") != "duration_or_signal" or not isinstance(failure.get("unit"), int) or not 0 <= failure["unit"] < len(job["units"]):
                        raise ValueError("Failure needs inspection; automatic recovery is limited to an identified audio unit")
                    index = render_command.index("/work/render_weekly_audio.py")
                    repair = render_command[:index] + ["/work/retry_weekly_unit.py"] + render_command[index + 1:] + ["--unit", str(failure["unit"]), "--seed", str(142 + attempt)]
                    remote_model(repair, "recovery.log")
        with stage("transfer_download", billing="local"):
            reconcile_remote(work, job, lambda folder: command([*scp_options, "-r", args.host + ":" + remote + "/render", str(folder)], transfer=True, check=True))
    with stage("render" if imported_render else "render_validation", cache_hit=imported_render, billing="local"):
        render = stage_check("Render", RENDER_RECOVERY, lambda: validate_render(work, job))
        record_render_workload(work, job, render, before, imported_render)
    cached_assembly = (work / "audio/library.json").exists()
    with stage("assemble", cache_hit=cached_assembly, billing="local"):
        if not cached_assembly:
            assemble(work, process_runner=command)
        track = stage_check("Natural audio", NATURAL_RECOVERY, lambda: validate_natural(work, job, render))
    # Serial diagnostics retain the historic stage order; the default lets
    # screening use the freed TTS slot while source alignment is still running.
    if getattr(args, "serial_stages", False):
        join_alignment()
    stages = [("screen_weekly_audio.py", "audio/asr-screening.json", "ASR screening", "local_asr", SCREENING_RECOVERY, lambda: validate_screening(work, job, render, track)),
        ("check_weekly_timing.py", "synchronization/report.json", "Timing", "timing", TIMING_RECOVERY, lambda: validate_timing(work, job, render))]
    for script, report, name, accounting_name, recovery, check in stages:
        if script == "check_weekly_timing.py":
            join_alignment()
        cached = (work / report).exists()
        with stage(accounting_name, cache_hit=cached, billing="local"):
            if not cached:
                python = getattr(args, "speech_python", Path(sys.executable)) if script != "check_weekly_timing.py" else Path(sys.executable)
                command([str(python if Path(python).exists() else sys.executable), str(HERE / script), "--work", str(work)], check=True)
            stage_check(name, recovery, check)
    with stage("candidate_validation", billing="local"):
        evidence = validate_candidate(work)
        record_workload("candidate_evidence", {**evidence, "candidateReady": True, "humanApproval": False})
    write_json(work / "workflow-receipt.json", {"status": "candidate_ready_for_extended_saturday_review", **evidence,
        "remoteWork": None if imported_render or local_rendered else remote, "localRender": local_rendered, "renderImported": imported_render, "remoteCheckpoint": str(checkpoint), "humanAudioReview": "pending"})
    print(f"Candidate ready: {work / 'audio/zh-natural.mp3'}\nContinue the Saturday review in {work / 'audio-review.json'}")


if __name__ == "__main__":
    try:
        main()
    except WorkAlreadyRunning:
        print("Another process is executing this job; wait and inspect its current evidence.", file=sys.stderr)
        sys.exit(75)
