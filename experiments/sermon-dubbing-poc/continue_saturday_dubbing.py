#!/usr/bin/env python3
"""Read-only by default bridge from Saturday artifacts to a dubbing candidate.

Config schema: sermon-saturday-dubbing-bridge-v1. Paths are absolute or relative
to the repository root. ``weeks[week]`` explicitly supplies speaker/title/scripture
and may pin ``liveArchive.run`` / ``liveArchive.existingWork``. Otherwise the run
comes from the matching Supervisor report, never from the newest directory.

``sameVideo.source`` is a separate, optional sermon-only media contract: week,
path, sha256, durationSeconds, sameVersionConfirmed=true, sermonOnly=true and a
confirmationReference. Until that evidence arrives this route waits; it never
fabricates a human window or prevents the live_archive fallback from advancing.
prepare_same_video.py archives that input and seals reviewed same-source PDFs;
this bridge then prepares/resumes the candidate without a human window record.

--execute may bind the existing authorization to a clip, prepare an immutable
job and run the existing candidate runner. It never calls a model for review,
approves a boundary, changes the Supervisor/global source or publishes audio.
"""
from __future__ import annotations

import argparse
from contextvars import copy_context
from contextlib import contextmanager, redirect_stdout
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from poc import ROOT, probe, sha256, write_json
sys.path.insert(0, str(ROOT))
from scripts.sermon_execution_harness import WorkAlreadyRunning, bounded_process, work_lock
from weekly_dubbing import PDF_PACKAGE_KEYS, prepare, read, resolve_approved_timeline, timecode, validate_frozen, source_id_from_run, deferred_package
from sentence_synthesis_policy import SENTENCE_SYNTHESIS_POLICY

HERE = Path(__file__).resolve().parent
SCHEMA = "sermon-saturday-dubbing-bridge-v1"
REPORT_SCHEMA = "sermon-saturday-dubbing-bridge-report-v1"
REMOTE_ROOT = "/home/achillesjing/dgx-spark-benchmark/results/sermon-"
SENTENCE_POLICY_START_WEEK = "2026-09-27"
CANDIDATE_FILES = (
    "render/report.json", "render/chinese.raw.wav", "audio/library.json",
    "audio/zh-natural.mp3", "assembly-report.json", "audio/asr-screening.json",
    "source-alignment/report.json", "synchronization/report.json",
)
INPUTS = {
    "reading": "pipeline/reading-edition-v2/reading_blocks.final.json",
    "readingQuality": "pipeline/reading-edition-v2/reading_quality_report.json",
    "readingPdfQa": "pipeline/sermon_zh_en_reading.qa.json",
    "companionPdfQa": "pipeline/sermon_interpretation_zh.qa.json",
    "readingPdf": "pipeline/sermon_zh_en_reading.pdf",
    "companionPdf": "pipeline/sermon_interpretation_zh.pdf",
    "outline": "pipeline/sermon-interpretation/insights/openai-notes.json",
    "summary": "pipeline/summary.json", "windowApproval": "operator-window-approval.json",
    "timeline": "timeline/report.json", "sourceAudio": "pipeline/source_clip.m4a",
    "clipReceipt": "pipeline/source_clip.m4a.cache.json",
}


def path_from(value, root=ROOT):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def executable_path_from(value, root=ROOT):
    # Resolving a venv's Python symlink selects the base interpreter instead.
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).absolute()


def identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def waiting(route, status, reason, action, **extra):
    return {"route": route, "status": status, "reason": reason,
        "nextActions": [{"action": action, "route": route, "commands": []}], **extra}


def inspect_same_video(week, settings, *, root=ROOT, media_probe=probe):
    source = settings.get("source")
    if not source:
        return waiting("same_video", "waiting_source", "The sermon-only video for this exact Sunday version has not been supplied.", "await_same_video_source")
    if not isinstance(source, dict) or source.get("week") != week or source.get("sameVersionConfirmed") is not True or source.get("sermonOnly") is not True or not nonempty(source.get("confirmationReference")):
        return waiting("same_video", "waiting_source_confirmation", "Same-version and sermon-only evidence must be explicit; a livestream window does not confirm this route.", "confirm_same_video_in_this_thread")
    try:
        from prepare_same_video import validate_archive, validate_source, BOUNDARY_BASIS
        run = path_from(settings["run"], root) if settings.get("run") else None
        if run and run.exists():
            normalized, _ = validate_archive(run, source, root=root, media_probe=media_probe)
        elif not path_from(source["path"], root).is_file():
            return waiting("same_video", "waiting_source", "The declared same-video media is not local yet.", "obtain_declared_same_video")
        else:
            normalized = validate_source(source, week, root=root, media_probe=media_probe)
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        return waiting("same_video", "waiting_source_evidence", str(exc), "inspect_same_video_evidence")
    return waiting("same_video", "ready_for_source_intake", "The complete confirmed video supplies this route's source range.",
        "initialize_same_video_source", sourceId=normalized["sourceId"], mediaSha256=normalized["sha256"],
        sourceContract=normalized, humanWindow="not_applicable",
        proposedWindow={"startSeconds": 0, "endSeconds": normalized["durationSeconds"], "basis": BOUNDARY_BASIS})


def inspect_same_route(config, config_path, week, settings, supervisor_report, *, root=ROOT, media_probe=probe, validator=None):
    from prepare_same_video import BOUNDARY_BASIS, CONTRACT_NAME, HANDOFF_NAME, production_plan, reviewed_inputs, validate_archive, validate_handoff
    source = settings.get("source")
    output_root = path_from(config.get("outputRoot", "artifacts/sermon-dubbing/weekly-bridge"), root)
    # No discovery report or liveArchive window/cache is ever used on this route.
    configured = dict(settings)
    if isinstance(source, dict) and source.get("sourceId") and source.get("sha256") and not settings.get("run"):
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(source["sourceId"])) and re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"])):
            configured["run"] = str(output_root / week / "same_video" / source["sourceId"] / ("source-" + source["sha256"][:20]))
    result = inspect_same_video(week, configured, root=root, media_probe=media_probe)
    if result["status"] != "ready_for_source_intake":
        return result, None
    run = path_from(configured["run"], root)
    metadata = {**config.get("weeks", {}).get(week, {}), **settings.get("metadata", {})}
    python = str(executable_path_from(config.get("pythonExecutable") or sys.executable, root))
    adapter = [python, str(HERE / "prepare_same_video.py"), "--config", str(config_path), "--week", week, "--run", str(run)]
    for field in ("title", "speaker"):
        if nonempty(metadata.get(field)):
            adapter += ["--" + field, metadata[field]]
    result.update(run=str(run), boundaryBasis=BOUNDARY_BASIS, sundayPublication="not_attempted")
    if not run.exists():
        result.update(status="waiting_same_video_intake", nextActions=[{"action": "initialize_same_video_source", "route": "same_video", "commands": [adapter + ["--initialize"]]}])
        return result, None
    contract, _ = validate_archive(run, source, root=root, media_probe=media_probe)
    from scripts.sermon_production_supervisor import lease_active
    if any((run / "leases" / (stage + ".json")).exists() and lease_active(read(run / "leases" / (stage + ".json"))) for stage in ("timeline", "generation")):
        return waiting("same_video", "waiting_saturday_run", "This same-video source still holds a production lease.", "wait_for_same_video_production", run=str(run)), None
    if not (run / HANDOFF_NAME).is_file():
        production = production_plan(run, contract, python=python, title=metadata.get("title"), speaker=metadata.get("speaker"))
        if (run / "pipeline/reading-edition-v2/reading_blocks.final.json").exists():
            # Validate the cached reading before dropping paid stages from the
            # handoff. A failed local PDF/seal never repeats notes generation.
            reviewed_inputs(run, source, root=root, media_probe=media_probe, include_pdfs=False, include_outline=False)
            if (run / "pipeline/sermon-interpretation/insights/openai-notes.json").exists():
                reviewed_inputs(run, source, root=root, media_probe=media_probe, include_pdfs=False)
                production["commands"] = [adapter + ["--seal-reviewed"]]
                production["nextAction"] = "seal_existing_same_source_reviewed_artifacts"
            elif not production["metadataRequiredForPdf"]:
                production["commands"] = production["commands"][-2:]
                production["nextAction"] = "generate_companion_from_verified_reading_then_seal"
        result.update(status="waiting_same_video_production", productionPlan=production,
            nextActions=[{"action": "produce_and_review_same_video_in_this_thread", "route": "same_video", "model": "gpt-6-astra", "commands": production["commands"]}])
        return result, None
    _, inputs = validate_handoff(run, source, root=root, media_probe=media_probe)
    return plan_candidate(config, config_path, week, settings, supervisor_report, run, contract["sourceId"], inputs,
        {"kind": "same_video_source_contract", "path": str(run / CONTRACT_NAME), "sha256": sha256(run / CONTRACT_NAME)},
        route="same_video", root=root, validator=validator, metadata=metadata)


def resolve_run(week, settings, supervisor_report, *, root=ROOT):
    explicit = settings.get("run")
    if explicit:
        run = path_from(explicit, root)
        provenance = {"kind": "explicit_weekly_config"}
    else:
        report_path = path_from(supervisor_report, root)
        if not report_path.is_file():
            return None, {"status": "waiting_source", "reason": "No matching Saturday Supervisor report exists yet."}
        report = read(report_path)
        snapshot = report.get("finalSnapshot", report.get("snapshot", report))
        if report.get("sunday", snapshot.get("sunday")) != week or snapshot.get("sunday") != week:
            raise ValueError("Supervisor report belongs to another week")
        locations = snapshot.get("locations") or {}
        if not locations.get("runRoot"):
            return None, {"status": "waiting_source", "reason": "The matching Supervisor report has not selected a source."}
        run = path_from(locations["runRoot"], root)
        if snapshot.get("slug") and snapshot["slug"] != run.name:
            raise ValueError("Supervisor source slug differs from its run directory")
        provenance = {"kind": "supervisor_report", "path": str(report_path), "sha256": sha256(report_path)}
    if run.parent.name != week or not re.fullmatch(r"sermon_[A-Za-z0-9_-]+", run.name):
        raise ValueError("Run directory is not an explicit sermon source for this week")
    return run, provenance


def validate_live_inputs(run, week, *, root=ROOT, media_probe=probe, defer_pdfs=False, reviewed_handoff=None):
    """Preflight the same inputs that prepare() validates again before mutation."""
    sys.path.insert(0, str(ROOT))
    from scripts.sermon_production_supervisor import lease_active
    if reviewed_handoff is not None:
        if not defer_pdfs or reviewed_handoff.get("schemaVersion") != "sermon-producer-reading-handoff-v1" or reviewed_handoff.get("week") != week or reviewed_handoff.get("run") != str(run.resolve()):
            raise ValueError("Invalid producer reading handoff")
        expected = {key: {"path": str((run / rel).resolve()), "sha256": sha256(run / rel)}
            for key, rel in INPUTS.items() if key not in PDF_PACKAGE_KEYS and key != "timeline"}
        if reviewed_handoff.get("inputs") != expected:
            raise ValueError("Reviewed producer inputs changed before candidate handoff")
    for stage in (["timeline"] if reviewed_handoff is not None else ["timeline", "generation"]):
        lease = run / "leases" / (stage + ".json")
        if lease.exists() and lease_active(read(lease)):
            return None, ("waiting_saturday_run", "An existing Saturday stage still holds its source lease.")
    paths = {key: run / relative for key, relative in INPUTS.items() if not (defer_pdfs and key in PDF_PACKAGE_KEYS)}
    if not paths["windowApproval"].is_file():
        return None, ("waiting_boundary", "A matching existing human sermon-window approval is required for the live archive.")
    source_id = source_id_from_run(run)
    try:
        paths["timeline"] = resolve_approved_timeline(run, read(paths["windowApproval"]), week=week,
            source_url=f"https://www.youtube.com/watch?v={source_id}")
    except ValueError as exc:
        return None, ("waiting_boundary", str(exc))
    missing = [key for key, path in paths.items() if not path.is_file()]
    if missing:
        return None, ("waiting_saturday_artifacts", "Missing reviewed Saturday artifacts: " + ", ".join(missing))
    if any(read(paths[key]).get("status") != "pass" for key in (["readingQuality"] if defer_pdfs else ["readingQuality", "readingPdfQa", "companionPdfQa"])):
        return None, ("waiting_saturday_review", "Saturday reading and both PDF QA gates must pass before dubbing preparation.")
    notes = read(paths["outline"])
    if notes.get("status") != "ready" or notes.get("sermonDate") != week:
        raise ValueError("Companion source is not reviewed for this week")
    for key in ([] if defer_pdfs else ["readingPdf", "companionPdf"]):
        if paths[key].stat().st_size == 0:
            raise ValueError("An existing Saturday PDF is empty")
    approval, clip, summary = read(paths["windowApproval"]), read(paths["clipReceipt"]), read(paths["summary"])
    start, end = timecode(approval["startTime"]), timecode(approval["endTime"])
    if not (start == summary["sermonStartSeconds"] == clip["startSeconds"] < end == summary["sermonEndSeconds"] == clip["endSeconds"]):
        raise ValueError("Source clip and approved sermon window disagree")
    original = path_from(summary["source"], root)
    if sha256(original) != clip["source"]["sha256"] or abs(media_probe(paths["sourceAudio"])["durationSeconds"] - (end - start)) > .2:
        raise ValueError("Source audio differs from the Saturday window evidence")
    paths["originalAudio"] = original
    return {key: {"path": str(path), "sha256": sha256(path)} for key, path in paths.items()}, None


def candidate_validator(work):
    # Shared runner validation is the authority for complete audio-stage caches.
    from run_weekly_dubbing import validate_candidate
    return validate_candidate(work)


def resume_validator(work):
    from run_weekly_dubbing import validate_cached_stages
    validate_cached_stages(work, read(work / "job.json"))


def candidate_state(work, *, validator=candidate_validator):
    missing = [name for name in CANDIDATE_FILES if not (work / name).is_file()]
    if missing:
        try:
            resume_validator(work)
        except (OSError, ValueError, KeyError) as exc:
            return {"status": "waiting_evidence_repair", "reason": str(exc), "missingArtifacts": missing}
        return {"status": "ready_to_resume", "missingArtifacts": missing}
    try:
        verified = validator(work)
    except (OSError, ValueError, KeyError) as exc:
        return {"status": "waiting_evidence_repair", "reason": str(exc)}
    return {"status": "waiting_conversation_review", "candidateEvidence": verified,
        "reviewModel": "gpt-6-astra", "reviewLocation": "current_conversation", "humanApproval": "not_written_by_bridge"}


def inspect_live_archive(config, config_path, week, settings, supervisor_report, *, root=ROOT, media_probe=probe, validator=candidate_validator):
    route = "live_archive"
    run, provenance = resolve_run(week, settings, supervisor_report, root=root)
    if run is None:
        return waiting(route, provenance["status"], provenance["reason"], "continue_existing_saturday_workflow"), None
    source_id = source_id_from_run(run)
    if not run.is_dir():
        return waiting(route, "waiting_source", "The selected Saturday archive has not been materialized locally.", "continue_existing_saturday_workflow", sourceId=source_id), None
    inputs, blocked = validate_live_inputs(run, week, root=root, media_probe=media_probe)
    if blocked:
        return waiting(route, *blocked, "continue_existing_saturday_workflow", sourceId=source_id, run=str(run)), None
    return plan_candidate(config, config_path, week, settings, supervisor_report, run, source_id, inputs, provenance,
        route=route, root=root, validator=validator)


def plan_candidate(config, config_path, week, settings, supervisor_report, run, source_id, inputs, provenance, *, route,
                   root=ROOT, validator=candidate_validator, metadata=None):
    metadata = config.get("weeks", {}).get(week, {}) if metadata is None else metadata
    missing = [key for key in ["speaker", "title", "scripture"] if not nonempty(metadata.get(key))]
    if missing:
        return waiting(route, "waiting_metadata", "Explicit weekly metadata is missing; no speaker is inferred from a filename or title.", "record_verified_weekly_metadata", missingFields=missing, sourceId=source_id), None
    source_pin = metadata.get("sourceId") if route == "live_archive" else settings.get("metadata", {}).get("sourceId")
    if source_pin and source_pin != source_id:
        raise ValueError("Weekly metadata belongs to a different source")
    if route == "same_video":
        notes = read(Path(inputs["outline"]["path"]))
        if notes.get("speaker") != metadata["speaker"] or notes.get("sermonTitle") != metadata["title"]:
            raise ValueError("Same-video title/speaker differs from its reviewed companion metadata")
    voice = config.get("voiceRuns", {}).get(metadata["speaker"])
    if not isinstance(voice, dict) or not voice.get("voiceRun") or not voice.get("remoteCheckpoint"):
        return waiting(route, "waiting_voice", "No configured trained voice exists for the explicitly identified speaker.", "prepare_or_select_speaker_voice", speaker=metadata["speaker"], sourceId=source_id), None
    voice_run = path_from(voice["voiceRun"], root)
    if any(not (voice_run / name).is_file() for name in ["training-report.json", "research-inputs.json"]):
        return waiting(route, "waiting_voice", "The selected voice training receipts are unavailable.", "restore_or_prepare_speaker_voice", speaker=metadata["speaker"], sourceId=source_id), None
    training, voice_inputs = read(voice_run / "training-report.json"), read(voice_run / "research-inputs.json")
    if training.get("status") != "training_smoke_completed" or training.get("inputManifestSha256") != sha256(voice_run / "research-inputs.json"):
        raise ValueError("Voice training evidence is incomplete or stale")
    if voice_inputs.get("speaker", "Eric Geiger") != metadata["speaker"] or training.get("speaker", "Eric Geiger") != metadata["speaker"]:
        raise ValueError("Voice registry maps to another speaker's training")
    checkpoint = Path(voice["remoteCheckpoint"])
    if not checkpoint.is_absolute() or not str(checkpoint).startswith(REMOTE_ROOT) or ".." in checkpoint.parts:
        raise ValueError("Voice registry checkpoint must remain in the isolated sermon results directory")
    if not nonempty(config.get("authorizationStatement")) or not nonempty(config.get("scopeReference")):
        return waiting(route, "waiting_authorization_scope", "The existing authorization statement and its scope reference must be configured before binding a new clip.", "record_existing_authorization_scope", sourceId=source_id), None
    authorization = {"schemaVersion": "sermon-voice-authorization-v1", "status": "confirmed_by_user",
        "statement": config["authorizationStatement"], "purposes": ["chinese_dubbing"],
        "scopeReference": config["scopeReference"], "basis": "existing_user_authorization_reused_not_a_new_approval",
        "sources": [{"sourceId": source_id, "sha256": inputs["sourceAudio"]["sha256"]}]}
    fingerprint_inputs = {"week": week, "sourceId": source_id, "inputs": inputs,
        "metadata": {key: metadata[key] for key in ["speaker", "title", "scripture"]},
        "voiceInputSha256": training["inputManifestSha256"], "checkpointSha256": training["checkpointSha256"], "authorization": authorization}
    if week >= SENTENCE_POLICY_START_WEEK:
        fingerprint_inputs["synthesisPolicy"] = SENTENCE_SYNTHESIS_POLICY
    fingerprint = identity(fingerprint_inputs)
    output_root = path_from(config.get("outputRoot", "artifacts/sermon-dubbing/weekly-bridge"), root)
    source_root = output_root / week / route / source_id
    existing = settings.get("existingWork")
    work = path_from(existing, root) if existing else source_root / ("job-" + fingerprint[:20])
    # Reuse an earlier producer candidate after PDFs finish; publication-only
    # inputs must not trigger a second paid TTS job.
    deferred_inputs = {key: value for key, value in inputs.items() if key not in PDF_PACKAGE_KEYS}
    candidate_work = source_root / ("job-" + identity({**fingerprint_inputs, "inputs": deferred_inputs})[:20])
    if not existing and (candidate_work / "job.json").is_file() and deferred_package(read(candidate_work / "job.json")):
        work = candidate_work
    if (work / "job.json").exists():
        job = read(work / "job.json")
        validate_frozen(job)
        if week >= SENTENCE_POLICY_START_WEEK and job.get("synthesisPolicy") != SENTENCE_SYNTHESIS_POLICY:
            return waiting(route, "waiting_synthesis_policy",
                "An existing weekly job uses the older segmentation; preserve it and select a new sentence-policy job.",
                "prepare_new_sentence_job", work=str(work), sourceId=source_id), None
        if (job.get("sourceRoute") == "same_video") != (route == "same_video"):
            raise ValueError("Existing job belongs to another source route")
        if any(job.get(key) != expected for key, expected in {"week": week, "sourceId": source_id, "speaker": metadata["speaker"], "title": metadata["title"], "scripture": metadata["scripture"]}.items()):
            raise ValueError("Existing job differs from the selected weekly source/metadata")
        if job["voice"]["checkpointSha256"] != training["checkpointSha256"] or any(job["inputs"].get(key) != value for key, value in inputs.items() if not (deferred_package(job) and key in PDF_PACKAGE_KEYS)):
            raise ValueError("Existing job is not bound to these Saturday inputs / speaker checkpoint")
        state = candidate_state(work, validator=validator)
    elif existing or work.exists():
        return waiting(route, "waiting_evidence_repair", "The selected job directory has no immutable job; it will not be overwritten.", "inspect_incomplete_job_directory", work=str(work), sourceId=source_id), None
    else:
        state = {"status": "ready_to_prepare"}
    auth_path = source_root / "authorizations" / (identity(authorization) + ".json")
    python = str(executable_path_from(config.get("pythonExecutable") or sys.executable, root))
    command = [python, str(HERE / "run_weekly_dubbing.py"), "--work", str(work), "--remote-checkpoint", str(checkpoint)]
    if config.get("localTtsCheckpoint"):
        command += ["--local-checkpoint", str(path_from(config["localTtsCheckpoint"], root))]
    if config.get("localTtsPython"):
        command += ["--local-python", str(executable_path_from(config["localTtsPython"], root))]
    if config.get("mlxPython"):
        command += ["--speech-python", str(executable_path_from(config["mlxPython"], root))]
    if config.get("sparkHost"):
        command += ["--host", config["sparkHost"]]
    bridge_command = [python, str(HERE / "continue_saturday_dubbing.py"), "--week", week, "--config", str(config_path), "--supervisor-report", str(supervisor_report), "--execute"]
    actions = [{"action": "continue_dubbing_candidate", "route": route, "commands": [bridge_command]}]
    if state["status"] == "waiting_conversation_review":
        actions = [{"action": "review_candidate_in_this_thread", "route": route, "model": "gpt-6-astra", "work": str(work), "commands": []}]
    elif state["status"] == "waiting_evidence_repair":
        actions = [{"action": "inspect_candidate_evidence", "route": route, "work": str(work), "commands": []}]
    report = {"route": route, **state, "sourceId": source_id, "run": str(run), "work": str(work), "sourceProvenance": provenance,
        "boundaryBasis": "explicit_sermon_only_source_contract" if route == "same_video" else "existing_human_window_approval", "nextActions": actions,
        "plannedRunnerCommand": command, "sundayPublication": "not_attempted"}
    plan = {"route": route, "run": run, "voiceRun": voice_run, "work": work, "week": week, "metadata": metadata, "sourceId": source_id,
        "authorization": authorization, "authorizationPath": auth_path, "command": command, "outputRoot": output_root}
    return report, plan


def inspect_bridge(config_path, week, supervisor_report=None, *, root=ROOT, media_probe=probe, validator=candidate_validator):
    date.fromisoformat(week)
    config_path = path_from(config_path, root)
    config = read(config_path)
    if not isinstance(config, dict) or config.get("schemaVersion") != SCHEMA or not isinstance(config.get("weeks", {}), dict) or not isinstance(config.get("voiceRuns", {}), dict):
        raise ValueError("Invalid Saturday dubbing bridge configuration")
    settings = config.get("weeks", {}).get(week, {})
    if not isinstance(settings, dict) or any(not isinstance(settings.get(key, {}), dict) for key in ["sameVideo", "liveArchive"]):
        raise ValueError("Weekly route settings must be explicit objects")
    supervisor_report = path_from(supervisor_report or f"artifacts/sermon-production-supervisor/{week}/latest.json", root)
    try:
        same, same_plan = inspect_same_route(config, config_path, week, settings.get("sameVideo", {}), supervisor_report,
            root=root, media_probe=media_probe, validator=validator)
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        same, same_plan = waiting("same_video", "waiting_evidence_repair", str(exc), "inspect_same_video_evidence"), None
    try:
        fallback, plan = inspect_live_archive(config, config_path, week, settings.get("liveArchive", {}), supervisor_report,
            root=root, media_probe=media_probe, validator=validator)
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        fallback, plan = waiting("live_archive", "waiting_evidence_repair", str(exc), "inspect_live_archive_evidence"), None
    usable = {"ready_to_prepare", "ready_to_resume", "waiting_conversation_review"}
    if same_plan and same["status"] in usable:
        plan = same_plan
    elif not (plan and fallback["status"] in usable):
        plan = same_plan or plan
    selected = same if plan and plan["route"] == "same_video" else fallback if plan else same if same.get("sourceId") else fallback
    return {"schemaVersion": REPORT_SCHEMA, "checkedAt": datetime.now(timezone.utc).isoformat(), "mode": "inspect", "week": week,
        "config": {"path": str(config_path), "sha256": sha256(config_path)},
        "status": selected["status"], "selectedRoute": plan["route"] if plan else None,
        "routes": {"same_video": same, "live_archive": fallback}, "nextActions": same["nextActions"] + fallback["nextActions"],
        "humanApprovalWritten": False, "globalSourceChanged": False, "published": False}, plan


@contextmanager
def source_lock(output_root, week, source_id):
    """OS-released, source-scoped lock; never unlink a potentially locked inode."""
    folder = output_root / ".locks"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"{week}-{source_id}.lock").open("a+") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def continue_saturday(config_path, week, supervisor_report=None, *, execute=False, root=ROOT, media_probe=probe,
    validator=candidate_validator, preparer=prepare, runner=bounded_process):
    options = {"root": root, "media_probe": media_probe, "validator": validator}
    report, plan = inspect_bridge(config_path, week, supervisor_report, **options)
    if not execute or plan is None or report["status"] not in {"ready_to_prepare", "ready_to_resume"}:
        report["mode"] = "execute" if execute else "inspect"
        return report
    route = plan["route"]
    with source_lock(plan["outputRoot"], week, plan["sourceId"]) as acquired:
        if not acquired:
            report.update(mode="execute", status="waiting_active_dubbing_run")
            report["routes"][route]["status"] = "waiting_active_dubbing_run"
            report["nextActions"] = [{"action": "wait_for_current_dubbing_run", "route": route, "commands": []}]
            return report
        # Re-read all input evidence inside the lock before making changes.
        report, fresh = inspect_bridge(config_path, week, supervisor_report, **options)
        if fresh is None or fresh["route"] != route or fresh["sourceId"] != plan["sourceId"] or fresh["outputRoot"] != plan["outputRoot"] or report["status"] not in {"ready_to_prepare", "ready_to_resume"}:
            report["mode"] = "execute"
            return report
        plan = fresh
        try:
            if report["status"] == "ready_to_prepare":
                auth_path = plan["authorizationPath"]
                if auth_path.exists():
                    if read(auth_path) != plan["authorization"]:
                        raise ValueError("Existing source authorization receipt differs; preserve it")
                else:
                    write_json(auth_path, plan["authorization"])
                with redirect_stdout(sys.stderr):
                    extra = {"same_video_contract": plan["run"] / "same-video-source.json"} if route == "same_video" else {}
                    with work_lock(plan["work"]):
                        preparer(plan["run"], plan["voiceRun"], plan["work"], week, plan["metadata"]["title"],
                            plan["metadata"]["speaker"], plan["metadata"]["scripture"], auth_path, **extra)
            with (plan["work"] / "bridge-runner.log").open("a") as log:
                result = runner(plan["command"], stdout=log, stderr=subprocess.STDOUT, check=False, timeout=21660)
            if result.returncode == 75:
                raise WorkAlreadyRunning("The direct candidate runner holds this work directory")
            if result.returncode:
                raise ValueError(f"Candidate runner stopped with exit {result.returncode}; retained artifacts and bridge-runner.log require inspection")
            # A zero exit or an old receipt cannot stand in for current evidence.
            evidence = validator(plan["work"])
            report["routes"][route].update(status="waiting_conversation_review", candidateEvidence=evidence,
                reviewModel="gpt-6-astra", reviewLocation="current_conversation",
                nextActions=[{"action": "review_candidate_in_this_thread", "route": route, "model": "gpt-6-astra", "work": str(plan["work"]), "commands": []}])
            report.update(status="waiting_conversation_review", mode="execute")
        except WorkAlreadyRunning:
            report.update(status="waiting_active_dubbing_run", mode="execute")
            report["routes"][route].update(status="waiting_active_dubbing_run",
                nextActions=[{"action": "wait_for_current_dubbing_run", "route": route, "commands": []}])
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
            report.update(status="waiting_evidence_repair", mode="execute")
            report["routes"][route].update(status="waiting_evidence_repair", reason=str(exc),
                nextActions=[{"action": "inspect_candidate_evidence", "route": route, "work": str(plan["work"]), "commands": []}])
        report["nextActions"] = report["routes"]["same_video"]["nextActions"] + report["routes"]["live_archive"]["nextActions"]
        write_json(plan["outputRoot"] / week / route / plan["sourceId"] / "bridge-latest.json", report)
        return report


class CandidateNotReady(Exception):
    """Ordinary audio readiness wait; does not invalidate the independent PDFs."""
    def __init__(self, status, reason):
        self.status = status
        self.reason = reason
        super().__init__(reason)


def start_producer_candidate(config_path, week, run, executor, *, root=ROOT, media_probe=probe,
                             runner=bounded_process, validator=candidate_validator):
    """Producer-only milestone hook; call after reviewed reading AND outline.

    The calling producer owns the generation lease and awaits the returned
    future before completion. The worker rechecks the planned input hashes when
    freezing its immutable job; only delivery artifacts are deferred. No CLI
    bypass is exposed.
    """
    config_path, run = Path(config_path).resolve(), Path(run).resolve()
    if not config_path.is_file():
        raise CandidateNotReady("waiting_configuration", "The dubbing bridge configuration is not available")
    config = read(config_path)
    if not isinstance(config, dict) or config.get("schemaVersion") != SCHEMA:
        raise ValueError("Unsupported dubbing bridge configuration")
    weeks = config.get("weeks", {})
    if not isinstance(weeks, dict):
        raise ValueError("Dubbing weeks configuration must be an object")
    if week not in weeks:
        raise CandidateNotReady("waiting_metadata", "No dubbing metadata is configured for this week")
    if not isinstance(weeks[week], dict):
        raise ValueError("Weekly dubbing metadata must be an object")
    handoff = {"schemaVersion": "sermon-producer-reading-handoff-v1", "week": week, "run": str(run),
        "inputs": {key: {"path": str((run / rel).resolve()), "sha256": sha256(run / rel)}
            for key, rel in INPUTS.items() if key not in PDF_PACKAGE_KEYS and key != "timeline"}}
    inputs, blocked = validate_live_inputs(run, week, root=root, media_probe=media_probe,
                                           defer_pdfs=True, reviewed_handoff=handoff)
    if blocked:
        raise ValueError("Producer dubbing handoff is not ready: " + blocked[1])
    source_id = source_id_from_run(run)
    settings = config.get("weeks", {}).get(week, {}).get("liveArchive", {})
    report, plan = plan_candidate(config, config_path, week, settings, None, run, source_id, inputs,
        {"kind": "producer_reviewed_text_milestone", "pdfPackage": "pending"},
        route="live_archive", root=root, validator=validator)
    if plan is None:
        if report.get("status") in {"waiting_metadata", "waiting_voice", "waiting_authorization_scope"}:
            raise CandidateNotReady(report["status"], report["reason"])
        raise ValueError("Producer dubbing handoff is not ready: " + report["reason"])

    def execute():
        with source_lock(plan["outputRoot"], week, source_id) as acquired:
            if not acquired:
                raise WorkAlreadyRunning("Another dubbing runner owns this source")
            with work_lock(plan["work"]):
                if not (plan["work"] / "job.json").exists():
                    auth_path = plan["authorizationPath"]
                    if auth_path.exists() and read(auth_path) != plan["authorization"]:
                        raise ValueError("Authorization changed before candidate freeze")
                    write_json(auth_path, plan["authorization"])
                    job = prepare(run, plan["voiceRun"], plan["work"], week, plan["metadata"]["title"],
                        plan["metadata"]["speaker"], plan["metadata"]["scripture"], auth_path,
                        defer_pdfs=True, report_stream=sys.stderr)
                    if any(job["inputs"].get(key) != value for key, value in inputs.items()):
                        raise ValueError("Reviewed source changed before candidate freeze")
                else:
                    validate_frozen(read(plan["work"] / "job.json"))
            write_json(plan["work"] / "producer-reading-handoff.json", handoff)
            from scripts.sermon_accounting import subprocess_environment
            with (plan["work"] / "bridge-runner.log").open("a") as log:
                result = runner(plan["command"], stdout=log, stderr=subprocess.STDOUT, check=False, timeout=21660,
                                env=subprocess_environment())
            if result.returncode:
                raise ValueError("Concurrent dubbing candidate failed; inspect bridge-runner.log")
            evidence = validator(plan["work"])
            return {"status": "waiting_conversation_review", "work": str(plan["work"]), "candidateEvidence": evidence,
                    "pdfPackagePolicy": "deferred_until_release", "published": False}
    return executor.submit(copy_context().run, execute)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--supervisor-report", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        result = continue_saturday(args.config, args.week, args.supervisor_report, execute=args.execute)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"schemaVersion": REPORT_SCHEMA, "status": "invalid_configuration", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
