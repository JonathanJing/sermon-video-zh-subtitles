#!/usr/bin/env python3
"""Opt-in audio extension to Saturday's reviewed reading / companion outputs.

Prepare freezes existing evidence; assemble creates a review candidate. Only an
explicit, hash-bound human audio review plus the original completion gates can
make a week ready for Sunday. No upstream artifacts or reviews are overwritten.
"""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from poc import probe, sha256, speech_units, write_json


def read(path):
    return json.loads(Path(path).read_text())


def timecode(text):
    h, m, s = map(float, text.split(":"))
    if not (h >= 0 and 0 <= m < 60 and 0 <= s < 60):
        raise ValueError("Invalid source timecode")
    return h * 3600 + m * 60 + s


def source_id_from_run(run):
    """Directory is only a candidate identity; approval URL hash validates it."""
    import re
    name = Path(run).name
    for prefix in ("sermon_", "mariners_"):
        if name.startswith(prefix):
            source_id = name[len(prefix):]
            if re.fullmatch(r"[A-Za-z0-9_-]+", source_id):
                return source_id
    raise ValueError("Unsupported source run identity; expected sermon_ID or mariners_ID")


def resolve_approved_timeline(run, approval, *, week, source_url):
    """Select existing evidence by the approval's canonical digest, never path age.

    Supervisor approvals bind agent-job-report.json; historical jobs may bind
    report.json. Prefer the historical path when both contain identical JSON so
    adding the Supervisor report does not invalidate a frozen legacy job.
    """
    from poc import ROOT
    sys.path.insert(0, str(ROOT))
    from scripts.sermon_production_supervisor import json_digest, validate_window_approval
    digest = approval.get("timelineReportSha256") if isinstance(approval, dict) else None
    for relative in ("timeline/report.json", "timeline/agent-job-report.json"):
        path = Path(run) / relative
        if not path.is_file():
            continue
        try:
            report = read(path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(report, dict) or json_digest(report) != digest:
            continue
        valid, reason = validate_window_approval(approval, sunday=week, live_url=source_url, timeline_report=report)
        if not valid:
            raise ValueError(reason)
        return path
    raise ValueError("No local timeline report matches the existing operator window approval")


PDF_PACKAGE_KEYS = {"readingPdf", "companionPdf", "readingPdfQa", "companionPdfQa", "generationReport", "sameVideoPdfReceipt", "sameVideoHandoff"}


def deferred_package(job):
    deferred = job.get("schemaVersion") == "sermon-weekly-dubbing-job-v2"
    if deferred != (job.get("pdfPackagePolicy") == "deferred_until_release"):
        raise ValueError("Deferred PDF policy requires the explicit v2 job schema")
    return deferred


def validate_frozen(job):
    deferred = deferred_package(job)
    for name, item in job["inputs"].items():
        if sha256(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"Saturday / voice input changed: {name}; prepare a new job")
    if ("archiveCaptionContractVersion" in job or "archiveCaptionHandoff" in job["inputs"]) and job.get("sourceRoute") != "archive_caption":
        raise ValueError("Archive caption evidence cannot be relabeled as another route")
    if job.get("sourceRoute") == "archive_caption":
        from prepare_archive_sermon import BOUNDARY_BASIS, validate_handoff
        run = Path(job["inputs"]["sourceContract"]["path"]).parent
        contract, inputs = validate_handoff(run, media_probe=probe)
        expected = {"boundaryBasis": BOUNDARY_BASIS, "archiveCaptionContractVersion": contract["schemaVersion"],
            "sourceRun": str(run.resolve()), "week": contract["week"], "sourceId": contract["sourceId"],
            "sourceUrl": contract["canonicalURL"], "sourceStartSeconds": 0,
            "sourceEndSeconds": contract["durationSeconds"], "sourceDurationSeconds": contract["durationSeconds"]}
        if (any(job.get(key) != value for key, value in expected.items())
                or job["inheritedReview"].get("humanWindow") != "not_applicable"
                or any(key in job["inputs"] for key in ("windowApproval", "timeline", "sameVideoHandoff"))
                or "sameVideoContractVersion" in job
                or any(job["inputs"].get(key) != value for key, value in inputs.items())):
            raise ValueError("Archive caption job must retain its distinct source and caption evidence")
    elif (job.get("sourceRoute") == "same_video" or "sourceContract" in job["inputs"]
            or "sameVideoHandoff" in job["inputs"] or job.get("inheritedReview", {}).get("humanWindow") == "not_applicable"):
        from prepare_same_video import boundary_metadata, source_window, validate_handoff
        run = Path(job["inputs"]["sourceContract"]["path"]).parent
        if deferred:
            from prepare_same_video import reviewed_inputs
            contract, inputs = reviewed_inputs(run, media_probe=probe, include_pdfs=False)
        else:
            contract, inputs = validate_handoff(run, media_probe=probe)
        if (job.get("sourceRoute") != "same_video" or job.get("boundaryBasis") != boundary_metadata(contract)["boundaryBasis"]
                or job.get("sameVideoContractVersion") != contract["schemaVersion"] or job.get("sourceRun") != str(run.resolve())
                or job["inheritedReview"].get("humanWindow") != boundary_metadata(contract)["humanWindow"]
                or any(key in job["inputs"] for key in ("windowApproval", "timeline"))
                or any(job["inputs"].get(key) != value for key, value in inputs.items())
                or any(job.get(key) != value for key, value in {"week": contract["week"], "sourceId": contract["sourceId"],
                    "sourceUrl": contract["canonicalURL"], "sourceStartSeconds": source_window(contract)[0], "sourceEndSeconds": source_window(contract)[1],
                    "sourceDurationSeconds": source_window(contract)[1] - source_window(contract)[0]}.items())):
            raise ValueError("Same-video job must retain its distinct source contract and explicit boundary basis")
    if "spokenReview" in job or "spokenScriptReview" in job["inputs"]:
        from apply_spoken_review import validate_job_review
        validate_job_review(job)


def prepare(run, voice_run, out, week, title, speaker, scripture, authorization, *, same_video_contract=None, archive_contract=None, defer_pdfs=False, report_stream=None):
    date.fromisoformat(week)
    if defer_pdfs and archive_contract is not None:
        raise ValueError("Archive caption candidate preparation still requires its complete handoff")
    if same_video_contract is not None and archive_contract is not None:
        raise ValueError("Choose exactly one source contract")
    if out.exists():
        raise ValueError("Use a new job directory; previous audio and reviews are immutable")
    pipeline = run / "pipeline"
    paths = {"reading": pipeline / "reading-edition-v2/reading_blocks.final.json",
        "readingQuality": pipeline / "reading-edition-v2/reading_quality_report.json",
        "readingPdfQa": pipeline / "sermon_zh_en_reading.qa.json", "companionPdfQa": pipeline / "sermon_interpretation_zh.qa.json",
        "readingPdf": pipeline / "sermon_zh_en_reading.pdf", "companionPdf": pipeline / "sermon_interpretation_zh.pdf",
        "outline": pipeline / "sermon-interpretation/insights/openai-notes.json", "summary": pipeline / "summary.json",
        "sourceAudio": pipeline / "source_clip.m4a", "clipReceipt": pipeline / "source_clip.m4a.cache.json",
        "voiceTraining": voice_run / "training-report.json", "voiceInputs": voice_run / "research-inputs.json", "authorization": authorization}
    if archive_contract is not None:
        from prepare_archive_sermon import BOUNDARY_BASIS, CONTRACT, validate_handoff
        if Path(archive_contract).resolve() != (run / CONTRACT).resolve():
            raise ValueError("The archive contract must belong to this source run")
        contract, archive_inputs = validate_handoff(run, media_probe=probe)
        if contract["week"] != week:
            raise ValueError("Archive source belongs to another week")
        paths.pop("clipReceipt")
        paths.update({key: Path(value["path"]) for key, value in archive_inputs.items()})
        source_id, source_url = contract["sourceId"], contract["canonicalURL"]
        start, end = 0, contract["durationSeconds"]
        human_window = "not_applicable"
    elif same_video_contract is not None:
        from prepare_same_video import CONTRACT_NAME, boundary_metadata, source_window, validate_handoff
        if Path(same_video_contract).resolve() != (run / CONTRACT_NAME).resolve():
            raise ValueError("The same-video contract must belong to this source run")
        if defer_pdfs:
            from prepare_same_video import reviewed_inputs
            contract, same_inputs = reviewed_inputs(run, read(same_video_contract), media_probe=probe, include_pdfs=False)
        else:
            contract, same_inputs = validate_handoff(run, read(same_video_contract), media_probe=probe)
        if contract["week"] != week:
            raise ValueError("Same-video source belongs to another week")
        paths.update({key: Path(value["path"]) for key, value in same_inputs.items()})
        source_id, source_url = contract["sourceId"], contract["canonicalURL"]
        start, end = source_window(contract)
        human_window = boundary_metadata(contract)["humanWindow"]
    else:
        paths.update(windowApproval=run / "operator-window-approval.json")
        approval, summary = read(paths["windowApproval"]), read(paths["summary"])
        source_id = source_id_from_run(run)
        source_url = f"https://www.youtube.com/watch?v={source_id}"
        paths["timeline"] = resolve_approved_timeline(run, approval, week=week, source_url=source_url)
        from poc import ROOT
        start, end = timecode(approval["startTime"]), timecode(approval["endTime"])
        clip = read(paths["clipReceipt"])
        if not (start == summary["sermonStartSeconds"] == clip["startSeconds"] < end == summary["sermonEndSeconds"] == clip["endSeconds"]):
            raise ValueError("Clipped audio does not match the approved window")
        original = Path(summary["source"])
        if not original.is_absolute():
            original = ROOT / original
        if sha256(original) != clip["source"]["sha256"]:
            raise ValueError("Original video audio changed")
        paths["originalAudio"] = original
        if abs(probe(paths["sourceAudio"])["durationSeconds"] - (end - start)) > .2:
            raise ValueError("Source clip duration differs from the window")
        human_window = "approved"
    if defer_pdfs:
        paths = {key: path for key, path in paths.items() if key not in PDF_PACKAGE_KEYS}
    for key in (["readingQuality"] if defer_pdfs else ["readingQuality", "readingPdfQa", "companionPdfQa"]):
        if read(paths[key]).get("status") != "pass":
            raise ValueError(f"Existing Saturday gate has not passed: {key}")
    permission = read(authorization)
    from voice_source import authorized_source
    if not authorized_source(permission, source_id, sha256(paths["sourceAudio"]), "chinese_dubbing"):
        raise ValueError("An authorization receipt bound to this source clip is required")
    blocks, notes = read(paths["reading"]), read(paths["outline"])
    from scripts.series_terminology import require_consistent
    terminology = read(paths["readingQuality"]).get("seriesTerminology")
    if terminology:
        # New jobs check the exact registry used by editorial QA. Legacy jobs
        # remain resumable and never gain a terminology review retroactively.
        require_consistent(blocks, terminology)
        if notes.get("seriesTerminology", {}).get("sha256") != terminology["sha256"]:
            raise ValueError("Reading and outline series terminology differ; review a matching version before dubbing")
    if notes.get("status") != "ready" or notes.get("sermonDate") != week:
        raise ValueError("Companion outline is not for this week")
    if archive_contract is not None and notes.get("speaker") != speaker:
        raise ValueError("Archive outline speaker differs from the selected dubbing speaker")
    training, voice_inputs = read(paths["voiceTraining"]), read(paths["voiceInputs"])
    if training.get("status") != "training_smoke_completed" or training.get("inputManifestSha256") != sha256(paths["voiceInputs"]):
        raise ValueError("Incomplete or stale voice checkpoint receipt")
    if voice_inputs.get("speaker", "Eric Geiger") != speaker:
        raise ValueError("Selected checkpoint belongs to another speaker")
    if not blocks or len({b["id"] for b in blocks}) != len(blocks) or any(not b.get("en", "").strip() or not b.get("zh", "").strip() for b in blocks):
        raise ValueError("Missing / repeated bilingual reading blocks")
    units = []
    from spoken_text import spoken_text, VERSION
    for block in blocks:
        parts = speech_units([block["zh"]], "flow")
        for i, text in enumerate(parts):
            if len(text) > 180:
                raise ValueError(f"Reading block {block['id']} needs a reviewed sentence break before synthesis")
            unit = {"id": len(units), "blockId": block["id"], "text": text, "gapAfterSeconds": .45 if i == len(parts) - 1 else .18}
            if spoken_text(text) != text:
                unit["spokenText"] = spoken_text(text)
            units.append(unit)
    # Preserve historical failure receipts. A local candidate can be evaluated,
    # but the existing Saturday completion criterion cannot be bypassed.
    generation = run / "agent-generation-report.json"
    upstream_complete = generation.exists() and read(generation).get("status") == "completed"
    if generation.exists() and not defer_pdfs:
        paths["generationReport"] = generation
    job = {"schemaVersion": "sermon-weekly-dubbing-job-v1", "createdAt": datetime.now(timezone.utc).isoformat(),
        "week": week, "title": title, "speaker": speaker, "scripture": scripture, "sourceId": source_id, "sourceUrl": source_url,
        "sourceStartSeconds": start, "sourceEndSeconds": end, "sourceDurationSeconds": end - start,
        "voice": {"speaker": speaker, "speakerKey": training.get("speakerKey", "eric_pilot"), "checkpointSha256": training["checkpointSha256"], "model": training["baseModel"], "baseRevision": training["baseRevision"]},
        "inputs": {key: {"path": str(path.resolve()), "sha256": sha256(path)} for key, path in paths.items()},
        "inheritedReview": {"readingQuality": "pass", "readingPdfQa": "pass", "companionPdfQa": "pass", "humanWindow": human_window, "generationComplete": upstream_complete,
            "publicationRecheck": "required_before_sunday_release", "translationModel": read(paths["readingQuality"]).get("model"), "translationEffort": read(paths["readingQuality"]).get("reasoningEffort")},
        "blocks": [{"id": b["id"], "en": b["en"], "zh": b["zh"]} for b in blocks], "units": units,
        "timingPolicy": "natural speech; measured English anchors only; never use reading-layout timestamps",
        "pronunciationRuleVersion": VERSION, "status": "prepared_for_audio_generation", "humanAudioReview": "pending"}
    if defer_pdfs:
        job.update(schemaVersion="sermon-weekly-dubbing-job-v2", pdfPackagePolicy="deferred_until_release")
        job["inheritedReview"].update(readingPdfQa="pending", companionPdfQa="pending", generationComplete=False)
    if archive_contract is not None:
        job.update(sourceRoute="archive_caption", boundaryBasis=BOUNDARY_BASIS,
                   archiveCaptionContractVersion=contract["schemaVersion"], sourceRun=str(run.resolve()))
        validate_frozen(job)
    elif same_video_contract is not None:
        job.update(sourceRoute="same_video", boundaryBasis=boundary_metadata(contract)["boundaryBasis"],
                   sameVideoContractVersion=contract["schemaVersion"], sourceRun=str(run.resolve()))
        validate_frozen(job)
    write_json(out / "job.json", job)
    print(json.dumps({"job": str(out / "job.json"), "blocks": len(blocks), "units": len(units), "upstreamGenerationComplete": upstream_complete}, ensure_ascii=False), file=report_stream)
    return job


def normalize_mp3(raw, mp3, *, process_runner=None):
    if process_runner is None:
        from poc import ROOT
        sys.path.insert(0, str(ROOT))
        from functools import partial
        from scripts.sermon_execution_harness import bounded_process
        process_runner = partial(bounded_process, timeout=3600)
    if mp3.exists():
        raise ValueError("Preserve existing MP3; choose a new output")
    result = process_runner(["ffmpeg", "-hide_banner", "-i", str(raw), "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], capture_output=True, text=True, check=True)
    loud, _ = json.JSONDecoder().raw_decode(result.stderr[result.stderr.rfind("{"):])
    filt = "loudnorm=I=-18:TP=-1.5:LRA=11:linear=true:" + ":".join(f"{a}={loud[b]}" for a, b in [("measured_I", "input_i"), ("measured_TP", "input_tp"), ("measured_LRA", "input_lra"), ("measured_thresh", "input_thresh"), ("offset", "target_offset")])
    process_runner(["ffmpeg", "-v", "error", "-n", "-i", str(raw), "-af", filt, "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
    process_runner(["ffmpeg", "-v", "error", "-i", str(mp3), "-f", "null", "-"], check=True)
    return {"sha256": sha256(mp3), "fullDecode": "pass", **probe(mp3, process_runner=process_runner)}


def assemble(work, *, process_runner=None):
    job = read(work / "job.json")
    validate_frozen(job)
    render = read(work / "render/report.json")
    if render["jobSha256"] != sha256(work / "job.json") or render["checkpointSha256"] != job["voice"]["checkpointSha256"] or len(render["cues"]) != len(job["units"]):
        raise ValueError("Incomplete or wrong render")
    raw = work / "render/chinese.raw.wav"
    if sha256(raw) != render["sha256"] or [c["text"] for c in render["cues"]] != [u["text"] for u in job["units"]]:
        raise ValueError("Rendered audio/text changed")
    out = work / "audio"
    out.mkdir(exist_ok=True)
    mp3 = out / "zh-natural.mp3"
    info = normalize_mp3(raw, mp3, process_runner=process_runner)
    cues = [{"start": c["start"], "end": c["end"], "text": c["text"], "blockId": c["blockId"]} for c in render["cues"]]
    track = {"id": "full_candidate", "label": "整篇待审", "voiceLabel": f'{job["speaker"]} · 训练音色', "scope": "full_candidate",
        "file": mp3.name, "audioUrl": f"/media/{mp3.name}", "sha256": info["sha256"], "durationSeconds": render["durationSeconds"], "cues": cues}
    write_json(out / "library.json", {"schemaVersion": "sermon-audio-library-v1", "date": job["week"], "tracks": [track]})
    write_json(out / "experiment.json", {"paragraphs": [b["zh"] for b in job["blocks"]], "sourceId": job["sourceId"], "checkpointSha256": job["voice"]["checkpointSha256"]})
    write_json(work / "audio-review.json", {"schemaVersion": "sermon-weekly-audio-review-v1", "jobSha256": sha256(work / "job.json"), "mp3Sha256": info["sha256"],
        "checkpointSha256": job["voice"]["checkpointSha256"], "reviewedBy": None, "reviewedAt": None, "humanApproval": False,
        "checks": {"speakerIdentity": "pending", "voiceSimilarity": "pending", "chineseFluency": "pending", "pronunciation": "pending", "noOmissionOrRepetition": "pending", "sameVideoSynchronization": "pending"},
        "notes": "扩展周六已有审校，逐项试听后填写；音色样片认可不等于本周整篇配音审核通过。"})
    repairs = [{"unitId": i, **receipt["generationOverride"]} for i in range(len(job["units"])) if (receipt := read(work / f"render/unit-{i:04d}.json")).get("generationOverride")]
    write_json(work / "assembly-report.json", {"status": "audio_candidate_for_review", "jobSha256": sha256(work / "job.json"), "mp3": str(mp3), **info, "synthesisRepairs": repairs, "humanAudioReview": "pending", "sameVideoSynchronization": "not_validated"})
    return track


def completed_package_job(job):
    """Read current delivery evidence; never modify the frozen synthesis job."""
    import copy
    validate_frozen(job)
    run = Path(job["inputs"]["sourceContract" if job.get("sourceRoute") == "same_video" else "windowApproval"]["path"]).parent
    if job.get("sourceRoute") == "same_video":
        from prepare_same_video import validate_handoff
        _, inputs = validate_handoff(run, media_probe=probe)
    else:
        from continue_saturday_dubbing import validate_live_inputs
        inputs, blocked = validate_live_inputs(run, job["week"])
        if blocked:
            raise ValueError("Deferred PDF package is not complete: " + blocked[1])
    for key, item in inputs.items():
        if key not in PDF_PACKAGE_KEYS and job["inputs"].get(key) != item:
            raise ValueError("Completed PDF package differs from frozen synthesis input: " + key)
    generation = read(run / "agent-generation-report.json")
    if generation.get("status") != "completed":
        raise ValueError("Original Saturday generation is not completed")
    result = copy.deepcopy(job)
    result["inputs"].update(inputs)
    result["inheritedReview"].update(generationComplete=True)
    return result


def validate_review(work, *, write_receipt=True):
    synchronized = (work / "synchronization/assembly.json").exists()
    job, review = read(work / "job.json"), read(work / ("audio-review-synced.json" if synchronized else "audio-review.json"))
    validate_frozen(job)
    if job.get("sourceRoute") == "archive_caption":
        raise ValueError("Archive caption production supports review candidates only; archive publication acceptance is not implemented")
    audio = work / ("synchronization/zh-synced.mp3" if synchronized else "audio/zh-natural.mp3")
    if review.get("jobSha256") != sha256(work / "job.json") or review.get("mp3Sha256") != sha256(audio) or review.get("checkpointSha256") != job["voice"]["checkpointSha256"]:
        raise ValueError("Review is stale or bound to different audio")
    keys = {"speakerIdentity", "voiceSimilarity", "chineseFluency", "pronunciation", "noOmissionOrRepetition", "sameVideoSynchronization"}
    if review.get("humanApproval") is not True or not review.get("reviewedBy") or not review.get("reviewedAt") or set(review.get("checks", {})) != keys or any(v != "pass" for v in review["checks"].values()):
        raise ValueError("Human audio review is not complete")
    screening = read(work / "audio/asr-screening.json")
    result = screening["results"][0]
    if screening.get("jobSha256") != sha256(work / "job.json") or result.get("sha256") != sha256(work / "audio/zh-natural.mp3") or result.get("fullDecode") != "pass" or result.get("screenedUnits") != len(job["units"]):
        raise ValueError("Complete per-unit audio screening is required")
    if deferred_package(job):
        # Resolve the completed package without mutating the immutable synthesis
        # job or laundering pending PDF QA into inherited approval.
        job = completed_package_job(job)
    if not job["inheritedReview"]["generationComplete"]:
        raise ValueError("Original Saturday generation is not completed")
    if not synchronized:
        raise ValueError("The same-video synchronized MP3 is not ready")
    timing, assembled = read(work / "synchronization/report.json"), read(work / "synchronization/assembly.json")
    if timing["status"] != "natural_timing_fits" or assembled["jobSha256"] != sha256(work / "job.json") or assembled["sha256"] != sha256(audio) or assembled["sourceNaturalMp3Sha256"] != result["sha256"] or assembled["timingReportSha256"] != sha256(work / "synchronization/report.json") or assembled["fullDecode"] != "pass":
        raise ValueError("Synchronized MP3 / timing evidence changed")
    from check_weekly_timing import budgets, load_anchors, load_placements
    anchors, approval_hash = load_anchors(work, job, sha256(work / "job.json"))
    if timing.get("jobSha256") != sha256(work / "job.json") or timing.get("alignmentSha256") != sha256(work / "source-alignment/report.json") or timing.get("anchorReviewSha256") != approval_hash:
        raise ValueError("Synchronized anchor evidence changed; review the new timing")
    render = read(work / "render/report.json")
    if render.get("jobSha256") != sha256(work / "job.json") or render.get("sha256") != sha256(work / "render/chinese.raw.wav") or assembled.get("sourceNaturalWavSha256") != render["sha256"]:
        raise ValueError("Synchronized source audio changed")
    placements, placement_hash = load_placements(work, job, render, anchors)
    if timing.get("placementReviewSha256") != placement_hash:
        raise ValueError("Synchronized playback placement evidence changed; review the new timing")
    rows, failures = budgets(job["blocks"], anchors, render["cues"], job["sourceDurationSeconds"], placements)
    if failures or timing.get("blocks") != rows or timing.get("failures") != []:
        raise ValueError("Current acoustic anchors do not match the approved timing")
    # Delegate PDF / GCS completion to the existing supervisor; no new looser
    # interpretation of its publication receipts.
    from poc import ROOT
    sys.path.insert(0, str(ROOT))
    from scripts.run_codex_local_sermon_production import local_completion_artifacts
    run = Path(job["inputs"]["sourceContract" if job.get("sourceRoute") == "same_video" else "windowApproval"]["path"]).parent
    generation = read(run / "agent-generation-report.json")
    artifacts = generation.get("publication", {}).get("artifacts", [])
    locations = {"readingPdfLocal": job["inputs"]["readingPdf"]["path"], "interpretationPdfLocal": job["inputs"]["companionPdf"]["path"],
        "generationReportLocal": str(run / "agent-generation-report.json"), "readingQualityLocal": job["inputs"]["readingQuality"]["path"],
        "readingQaLocal": job["inputs"]["readingPdfQa"]["path"], "interpretationQaLocal": job["inputs"]["companionPdfQa"]["path"], "runStatusLocal": str(run / "run-status.json")}
    for label, name in [("readingPdfGcs", "sermon_zh_en_reading.pdf"), ("interpretationPdfGcs", "sermon_interpretation_zh.pdf")]:
        matches = [a for a in artifacts if str(a.get("gcsUri", "")).endswith("/" + name)]
        if len(matches) != 1:
            raise ValueError("Saturday PDF publication receipt is missing or ambiguous")
        locations[label] = matches[0]["gcsUri"]
    if not local_completion_artifacts({"locations": locations}):
        raise ValueError("Existing Saturday PDF / GCS completion check has not passed")
    if write_receipt:
        write_json(work / "saturday-completion.json", {"status": "completed", "sourceId": job["sourceId"], "jobSha256": sha256(work / "job.json"),
            "checkedAt": datetime.now(timezone.utc).isoformat(), "validator": "scripts.run_codex_local_sermon_production.local_completion_artifacts"})
    return review


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--defer-pdfs", action="store_true", help="Freeze reviewed text now; require full PDF package before release")
    for name in ["run", "voice-run", "out", "authorization"]:
        s.add_argument("--" + name, type=Path, required=True)
    for name in ["week", "title", "speaker", "scripture"]:
        s.add_argument("--" + name, required=True)
    source_options = s.add_mutually_exclusive_group()
    source_options.add_argument("--same-video-contract", type=Path)
    source_options.add_argument("--archive-contract", type=Path)
    for command in ["assemble", "validate-review"]:
        s = sub.add_parser(command)
        s.add_argument("--work", type=Path, required=True)
    args = p.parse_args()
    if args.command == "prepare":
        prepare(args.run.resolve(), args.voice_run.resolve(), args.out.resolve(), args.week, args.title, args.speaker, args.scripture, args.authorization.resolve(),
                same_video_contract=args.same_video_contract, archive_contract=args.archive_contract, defer_pdfs=args.defer_pdfs)
    elif args.command == "assemble":
        print(json.dumps(assemble(args.work.resolve()), ensure_ascii=False))
    else:
        validate_review(args.work.resolve())
        print("Audio review and Saturday completion pass")
