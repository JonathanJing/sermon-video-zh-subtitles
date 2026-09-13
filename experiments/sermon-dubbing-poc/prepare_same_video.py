#!/usr/bin/env python3
"""Archive an explicitly confirmed same-version video and bind reviewed inputs.

Inspection is read-only. Initialization copies media and writes a production
plan. Sealing renders local PDFs from verified reading/outline inputs into a new
bundle, then freezes their hashes. Neither action calls a model, writes a human
window approval, changes discovery state, or publishes anything.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

from poc import ROOT, probe, sha256, write_json

sys.path.insert(0, str(ROOT))
SOURCE_SCHEMA = "sermon-same-video-source-v1"
WINDOW_SOURCE_SCHEMA = "sermon-same-video-source-v2"
ARCHIVE_SCHEMA = "sermon-same-video-archive-v1"
HANDOFF_SCHEMA = "sermon-same-video-reviewed-handoff-v1"
BOUNDARY_BASIS = "explicit_sermon_only_source_contract"
CONTRACT_NAME = "same-video-source.json"
ARCHIVE_NAME = "same-video-archive.json"
HANDOFF_NAME = "same-video-reviewed-handoff.json"
PDF_RECEIPT = "same-video-pdfs/render-receipt.json"
REVIEWED_INPUTS = {
    "reading": "pipeline/reading-edition-v2/reading_blocks.final.json",
    "readingDraft": "pipeline/reading-edition-v2/reading_blocks.draft.json",
    "readingQuality": "pipeline/reading-edition-v2/reading_quality_report.json",
    "readingPdfQa": "same-video-pdfs/sermon_zh_en_reading.qa.json",
    "companionPdfQa": "same-video-pdfs/sermon_interpretation_zh.qa.json",
    "readingPdf": "same-video-pdfs/sermon_zh_en_reading.pdf", "companionPdf": "same-video-pdfs/sermon_interpretation_zh.pdf",
    "readingZhSrt": "pipeline/reading-edition-v2/sermon_zh_reading_revised.srt",
    "readingEnSrt": "pipeline/reading-edition-v2/sermon_en_reading_revised.srt",
    "outline": "pipeline/sermon-interpretation/insights/openai-notes.json",
    "summary": "pipeline/summary.json", "sourceAudio": "pipeline/source_clip.m4a",
    "clipReceipt": "pipeline/source_clip.m4a.cache.json",
    "rawEnglish": "pipeline/segments_timed_en_raw.json",
    "correctedEnglish": "pipeline/segments_timed_en_corrected.json", "translatedSegments": "pipeline/segments_timed_zh.json",
}
PDF_KEYS = {"readingPdf", "companionPdf", "readingPdfQa", "companionPdfQa"}
PDF_BINDINGS = {"reading", "readingZhSrt", "readingEnSrt", "outline", "sourceContract"}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def path_from(value, root=ROOT):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else root / path).resolve()


def seconds_equal(a, b, tolerance=.002):
    return all(type(v) in (int, float) and math.isfinite(v) for v in (a, b)) and abs(a - b) <= tolerance


def timecode(seconds):
    from scripts.build_sermon_reading_edition_with_openai import srt_time
    return srt_time(seconds).replace(",", ".")


def pcm_sha256(path):
    result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ar", "16000", "-ac", "1",
                             "-c:a", "pcm_s16le", "-f", "s16le", "-"], capture_output=True, check=True)
    return hashlib.sha256(result.stdout).hexdigest()


def source_window(source):
    """Absolute full-video bounds; downstream text/audio starts at clip zero."""
    if source.get("schemaVersion", SOURCE_SCHEMA) == WINDOW_SOURCE_SCHEMA:
        return source["sermonStartSeconds"], source["sermonEndSeconds"]
    return 0, source["durationSeconds"]


def boundary_metadata(source):
    return {"boundaryBasis": "explicit_same_version_sermon_window_contract",
            "humanWindow": "explicit_source_contract"} if source.get("schemaVersion") == WINDOW_SOURCE_SCHEMA else {
                "boundaryBasis": BOUNDARY_BASIS, "humanWindow": "not_applicable"}


def versioned_schema(v1, source):
    return v1.removesuffix("-v1") + "-v2" if source.get("schemaVersion") == WINDOW_SOURCE_SCHEMA else v1


def validate_source(source, week, *, root=ROOT, media_probe=probe, media_override=None):
    require(isinstance(source, dict), "Same-video source contract must be an object")
    require(date.fromisoformat(week).isoformat() == week and source.get("week") == week, "Same-video week changed")
    schema = source.get("schemaVersion", SOURCE_SCHEMA)
    require(schema in {SOURCE_SCHEMA, WINDOW_SOURCE_SCHEMA}, "Unsupported same-video source contract")
    require(source.get("sameVersionConfirmed") is True
            and isinstance(source.get("confirmationReference"), str) and bool(source["confirmationReference"].strip()),
            "Explicit same-version confirmation is required")
    require(source.get("sermonOnly") is (schema == SOURCE_SCHEMA), "Source kind does not match its contract schema")
    if schema == WINDOW_SOURCE_SCHEMA:
        start, end = source.get("sermonStartSeconds"), source.get("sermonEndSeconds")
        require(all(type(v) in (int, float) and math.isfinite(v) for v in (start, end))
                and 0 <= start < end, "A finite, positive sermon window is required")
        require(isinstance(source.get("windowConfirmationReference"), str) and bool(source["windowConfirmationReference"].strip()),
                "Explicit sermon-window confirmation is required")
    source_id, url = source.get("sourceId"), source.get("canonicalURL")
    require(isinstance(source_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", source_id), "Explicit sourceId is required")
    require(isinstance(url, str), "Explicit canonicalURL is required")
    parsed = urlsplit(url)
    require(parsed.scheme in {"https", "http"} and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.fragment, "Use a canonical media page URL without credentials or fragment")
    query = parse_qs(parsed.query)
    require(not any(re.search(r"token|secret|signature|password|cookie", key, re.I) for key in query), "Use the canonical page URL, not a signed download URL")
    if parsed.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        require(parsed.path == "/watch" and query.get("v") == [source_id], "Canonical YouTube URL differs from sourceId")
    duration = source.get("durationSeconds")
    require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0, "A positive full-video duration is required")
    if schema == WINDOW_SOURCE_SCHEMA:
        require(end <= duration, "Sermon window exceeds the complete video")
    require(isinstance(source.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", source["sha256"]), "A video SHA-256 is required")
    original = path_from(source["path"], root)
    media = Path(media_override) if media_override is not None else original
    require(media.is_file() and sha256(media) == source["sha256"], "Same-video media hash changed or media is missing")
    measured = media_probe(media)
    require(seconds_equal(measured["durationSeconds"], duration, .2), "Same-video duration differs from its contract")
    kinds = {stream.get("codec_type") for stream in measured.get("streams", [])}
    require({"video", "audio"} <= kinds, "The same-video contract requires actual video and audio streams")
    normalized = {"schemaVersion": schema, "week": week, "sourceId": source_id, "canonicalURL": url,
        "path": str(original), "sha256": source["sha256"], "durationSeconds": duration,
        "sameVersionConfirmed": True, "sermonOnly": schema == SOURCE_SCHEMA, "confirmationReference": source["confirmationReference"]}
    if schema == WINDOW_SOURCE_SCHEMA:
        normalized.update(sermonStartSeconds=start, sermonEndSeconds=end,
                          windowConfirmationReference=source["windowConfirmationReference"])
    return normalized


def validate_archive(run, source=None, *, root=ROOT, media_probe=probe):
    run = Path(run).resolve()
    saved = read(run / CONTRACT_NAME)
    receipt = read(run / ARCHIVE_NAME)
    relative = Path(receipt.get("archiveFile", ""))
    require(not relative.is_absolute() and ".." not in relative.parts and relative.parts[:1] == ("source",), "Unsafe same-video archive path")
    media = run / relative
    require(media.resolve().is_relative_to(run), "Archive media escapes its source run")
    normalized = validate_source(saved, saved["week"], root=root, media_probe=media_probe, media_override=media)
    require(saved == normalized and receipt.get("schemaVersion") == versioned_schema(ARCHIVE_SCHEMA, normalized)
            and receipt.get("sourceContractSha256") == sha256(run / CONTRACT_NAME)
            and receipt.get("sourceVideoSha256") == normalized["sha256"]
            and receipt.get("week") == normalized["week"] and receipt.get("sourceId") == normalized["sourceId"], "Same-video archive receipt changed")
    if normalized["schemaVersion"] == WINDOW_SOURCE_SCHEMA:
        require(all(receipt.get(key) == value for key, value in boundary_metadata(normalized).items()), "Archived window confirmation metadata changed")
    if source is not None:
        expected = validate_source(source, normalized["week"], root=root, media_probe=media_probe, media_override=media)
        require(expected == normalized, "Archived video belongs to another source contract")
    return normalized, media


def production_plan(run, source, *, python=sys.executable, title=None, speaker=None):
    """Commands are handed to this conversation; this adapter never runs them."""
    run = Path(run).resolve()
    pipeline = run / "pipeline"
    start, end = source_window(source)
    media = run / "source" / ("video" + (Path(source["path"]).suffix or ".media"))
    commands = [[python, str(ROOT / "scripts/sermon_pipeline.py"), "--input", str(media), "--outdir", str(pipeline),
        "--slug", "sermon_" + source["sourceId"], "--output-mode", "reading", "--start-time", timecode(start),
        "--end-time", timecode(end), "--reference-model", "gpt-transcribe", "--zh-model", "gpt-6-astra",
        "--en-correction-model", "gpt-6-astra", "--reasoning-effort", "medium"],
        [python, str(ROOT / "scripts/build_sermon_reading_edition_with_openai.py"), "--source-pipeline", str(pipeline),
         "--outdir", str(pipeline / "reading-edition-v2"), "--provider", "openai", "--model", "gpt-6-astra", "--reasoning-effort", "medium", "--passes", "2"]]
    if title and speaker:
        from scripts.run_post_live_subtitle_generation import build_reading_pdf_command, build_sermon_interpretation_command
        args = argparse.Namespace(sunday=source["week"], sermon_title=title, speaker=speaker, start_time=timecode(start), end_time=timecode(end),
                                  interpretation_model="gpt-6-astra", interpretation_reasoning_effort="medium")
        commands.append(build_reading_pdf_command(args, pipeline, source["canonicalURL"]))
        companion = build_sermon_interpretation_command(args, pipeline)
        companion[companion.index("--source-label") + 1] = (f"本材料基于用户确认的周日播放同版完整礼拜视频及明确证道范围整理；来源：{urlsplit(source['canonicalURL']).hostname}。" if source.get("schemaVersion") == WINDOW_SOURCE_SCHEMA else "本材料基于已确认于周日播放的同版纯证道视频整理；中文内容为生成并审校的材料。")
        commands.append(companion)
        for command in commands:
            command[0] = python
        commands.append([python, str(Path(__file__).resolve()), "--contract", str(run / CONTRACT_NAME),
                         "--run", str(run), "--seal-reviewed"])
    return {"schemaVersion": versioned_schema("sermon-same-video-production-plan-v1", source), "week": source["week"], "sourceId": source["sourceId"],
        "sourceContractIdentitySha256": digest(source), "sourceVideoSha256": source["sha256"], "run": str(run),
        **boundary_metadata(source), "commands": commands,
        "metadataRequiredForPdf": not bool(title and speaker), "executionLocation": "current_conversation",
        "nextAction": "generate_and_review_same_source_artifacts_then_seal", "published": False}


def initialize(source, run, *, root=ROOT, media_probe=probe, title=None, speaker=None, python=sys.executable):
    run = Path(run).resolve()
    from scripts.sermon_accounting import accounting_session, stage
    with accounting_session(run.parent / "accounting" / run.name, "same_video_intake", evidence_directory=run):
        with stage("same_video.validate_source"):
            cached = run.exists()
            normalized = validate_archive(run, source, root=root, media_probe=media_probe)[0] if cached else validate_source(source, source["week"], root=root, media_probe=media_probe)
        with stage("same_video.archive", cache_hit=cached):
            if not cached:
                with tempfile.TemporaryDirectory(prefix=".same-video-intake-", dir=run.parent) as temporary:
                    staging = Path(temporary)
                    relative = Path("source") / ("video" + (Path(normalized["path"]).suffix or ".media"))
                    (staging / "source").mkdir()
                    shutil.copyfile(normalized["path"], staging / relative)
                    require(sha256(staging / relative) == normalized["sha256"], "Video changed while archiving")
                    write_json(staging / CONTRACT_NAME, normalized)
                    write_json(staging / ARCHIVE_NAME, {"schemaVersion": versioned_schema(ARCHIVE_SCHEMA, normalized), "week": normalized["week"], "sourceId": normalized["sourceId"],
                        "archiveFile": str(relative), "sourceContractSha256": sha256(staging / CONTRACT_NAME), "sourceVideoSha256": normalized["sha256"],
                        **boundary_metadata(normalized)})
                    write_json(staging / "same-video-production-plan.json", production_plan(run, normalized, python=python, title=title, speaker=speaker))
                    staging.rename(run)
            return production_plan(run, normalized, python=python, title=title, speaker=speaker)


def text_evidence(run, paths, summary, duration):
    from scripts.sermon_pipeline import clean_text, reference_chunks_to_reading_segments, source_file_identity
    pipeline = run / "pipeline"
    single = pipeline / "asr_reference.json"
    model = summary.get("models", {}).get("referenceAsr")
    if single.is_file():
        request = pipeline / "asr_reference.request.json"
        identity = read(request)
        require(identity.get("audioSha256") == sha256(paths["sourceAudio"])
                and identity.get("model") == model and seconds_equal(identity.get("startSeconds"), 0)
                and seconds_equal(identity.get("endSeconds"), duration, .2), "ASR request does not bind the same source clip")
        result = read(single)
        end = round(duration, 3)
        chunks = [{"id": 0, "start": 0.0, "end": end, "duration": end, "text": clean_text(result.get("text", "")),
                   "usage": result.get("usage"), "detectedLanguages": result.get("languages", [])}]
        asr = single
        paths.update(referenceAsr=single, referenceAsrRequest=request)
    else:
        asr = pipeline / "asr_reference_chunks.json"
        chunks = read(asr)
        require(isinstance(chunks, list) and bool(chunks), "Missing same-video ASR chunks")
        cursor = 0.0
        for index, chunk in enumerate(chunks):
            base = pipeline / "chunks_reference" / f"chunk_{index:04d}"
            audio, request, result_path = base.with_suffix(".m4a"), base.with_suffix(".request.json"), base.with_suffix(".json")
            cache = audio.with_suffix(".m4a.cache.json")
            cut, identity, result = read(cache), read(request), read(result_path)
            require(chunk.get("id") == index and seconds_equal(chunk.get("start"), cursor)
                    and type(chunk.get("end")) in (int, float) and chunk["end"] > cursor
                    and seconds_equal(chunk.get("duration"), chunk["end"] - cursor), "ASR chunk coverage is incomplete or overlapping")
            require(cut.get("operation") == "cut_chunk" and cut.get("source") == source_file_identity(paths["sourceAudio"])
                    and seconds_equal(cut.get("startSeconds"), cursor) and seconds_equal(cut.get("durationSeconds"), chunk["duration"]),
                    "ASR chunk was cut from a different source clip")
            request_audio = audio
            if identity.get("audioSha256") != sha256(audio):
                request_audio = base.with_suffix(".wav")
                require(request_audio.is_file() and pcm_sha256(audio) == pcm_sha256(request_audio),
                        "ASR fallback PCM differs from its source chunk")
            require(identity.get("audioSha256") == sha256(request_audio) and identity.get("model") == model
                    and seconds_equal(identity.get("startSeconds"), cursor) and seconds_equal(identity.get("endSeconds"), chunk["end"]),
                    "ASR request differs from its same-video chunk")
            expected = {"id": index, "start": chunk["start"], "end": chunk["end"], "duration": chunk["duration"],
                        "text": clean_text(result.get("text", "")), "usage": result.get("usage"), "detectedLanguages": result.get("languages", [])}
            require(chunk == expected, "ASR chunk text differs from its response")
            paths.update({f"referenceChunk{index}": audio, f"referenceAudio{index}": request_audio,
                f"referenceRequest{index}": request, f"referenceResult{index}": result_path, f"referenceCut{index}": cache})
            cursor = chunk["end"]
        require(seconds_equal(cursor, duration, .2), "ASR chunks do not cover the complete same-video source")
        paths["referenceAsr"] = asr
    raw = reference_chunks_to_reading_segments(chunks, target_chars=max(120, int(summary["readingSegmentTargetCharacters"])))
    require(raw == read(paths["rawEnglish"]), "Raw English is not reconstructed from the same-video ASR")
    corrected = raw
    if summary.get("sourceTextReview"):
        from scripts.sermon_source_text_review import apply_review
        review = Path(summary["sourceTextReview"]["reviewPath"])
        corrected, provenance = apply_review(raw, review, paths["sourceAudio"], asr)
        require(summary["sourceTextReview"] == provenance, "Source correction evidence changed")
        paths["sourceTextReview"] = review
    require(corrected == read(paths["correctedEnglish"]), "Same-video corrected English changed without source review")
    from scripts.build_sermon_reading_edition_with_openai import build_semantic_blocks, reading_quality_report
    quality = read(paths["readingQuality"])
    require(path_from(quality["sourcePipeline"]) == pipeline.resolve(), "Reading review belongs to another source pipeline")
    layout = quality["layoutTargets"]
    draft = build_semantic_blocks(corrected, read(paths["translatedSegments"]),
        preferred_seconds=layout["preferredSeconds"], preferred_english_chars=layout["preferredEnglishCharacters"],
        hard_seconds=layout["hardSeconds"], hard_english_chars=layout["hardEnglishCharacters"])
    require(draft == read(paths["readingDraft"]), "Reading draft is not derived from same-source bilingual segments")
    final = read(paths["reading"])
    require(len(final) == len(draft) and all(all(row.get(k) == original[k] for k in ("id", "start", "end", "segmentIds", "en"))
            for row, original in zip(final, draft)), "Reading English no longer matches same-source segments")
    require(reading_quality_report(final)["status"] == "pass", "Current same-video reading quality fails")
    from scripts.build_sermon_reading_edition_with_openai import srt_time
    from scripts.generate_notes_with_openai import segments_from_srt, merge_aligned_segments, build_note_slices, summarize_slices
    srts = {}
    for field, key in [("en", "readingEnSrt"), ("zh", "readingZhSrt")]:
        expected = "\n".join(line for index, block in enumerate(final, 1) for line in
            [str(index), f"{srt_time(float(block['start']))} --> {srt_time(float(block['end']))}", str(block[field]).strip(), ""])
        srts[field] = paths[key].read_text(encoding="utf-8")
        require(srts[field] == expected, "Reading SRT differs from final same-video blocks")
    segments = merge_aligned_segments(segments_from_srt(srts["zh"], lang="zh"), segments_from_srt(srts["en"], lang="en"))
    if "outline" in paths:
        notes = read(paths["outline"])
        require(notes.get("slices") == summarize_slices(build_note_slices(segments))
                and notes.get("sourceSegmentCount") == len(segments), "Companion outline does not cite the same-source reading")


def reviewed_inputs(run, source=None, *, root=ROOT, media_probe=probe, include_pdfs=True, include_outline=True):
    run = Path(run).resolve()
    contract, media = validate_archive(run, source, root=root, media_probe=media_probe)
    require(include_outline or not include_pdfs, "PDF handoff always requires its same-source outline")
    paths = {key: run / relative for key, relative in REVIEWED_INPUTS.items()
             if (include_pdfs or key not in PDF_KEYS) and (include_outline or key != "outline")}
    require(all(path.is_file() for path in paths.values()), "Reviewed same-video artifacts are incomplete")
    require(read(paths["readingQuality"]).get("status") == "pass", "Same-video reading QA must pass")
    summary, clip = read(paths["summary"]), read(paths["clipReceipt"])
    start, end = source_window(contract)
    duration = end - start
    require(summary.get("outputMode") == "reading" and path_from(summary["source"], root) == media.resolve()
            and clip["source"]["sha256"] == contract["sha256"], "Summary or source clip belongs to another video")
    require(seconds_equal(summary.get("sermonStartSeconds"), start) and seconds_equal(clip.get("startSeconds"), start)
            and seconds_equal(summary.get("sermonEndSeconds"), end) and seconds_equal(clip.get("endSeconds"), end)
            and seconds_equal(summary.get("sourceDurationSeconds"), contract["durationSeconds"], .2), "Same-video boundaries differ from the confirmed source window")
    measured = media_probe(paths["sourceAudio"])["durationSeconds"]
    require(seconds_equal(measured, duration, .2), "Same-video source clip duration changed")
    if include_outline:
        notes = read(paths["outline"])
        require(notes.get("status") == "ready" and notes.get("sermonDate") == contract["week"], "Same-video companion belongs to another week")
    text_evidence(run, paths, summary, measured)
    paths.update(sourceContract=run / CONTRACT_NAME, sourceArchive=run / ARCHIVE_NAME, sourceVideo=media, originalAudio=media)
    if include_pdfs:
        validate_pdf_receipt(run, paths)
        paths["sameVideoPdfReceipt"] = run / PDF_RECEIPT
    return contract, {key: {"path": str(path.resolve()), "sha256": sha256(path)} for key, path in paths.items()}


def validate_pdf_receipt(run, paths):
    receipt = read(run / PDF_RECEIPT)
    require(receipt.get("schemaVersion") == "sermon-same-video-pdf-render-v1"
            and receipt.get("status") == "pass"
            and receipt.get("inputHashes") == {key: sha256(paths[key]) for key in PDF_BINDINGS}
            and receipt.get("outputHashes") == {key: sha256(paths[key]) for key in PDF_KEYS},
            "Same-video PDF render receipt is missing, stale or belongs to different reviewed text")
    require(all(read(paths[key]).get("status") == "pass" for key in ("readingPdfQa", "companionPdfQa"))
            and all(paths[key].stat().st_size > 0 for key in ("readingPdf", "companionPdf")), "Same-video PDF QA must pass")


def render_reviewed_pdfs(run, contract, inputs, *, runner=subprocess.run, python=sys.executable):
    """Create a fresh local-only PDF bundle from verified final text and notes."""
    paths = {key: Path(value["path"]) for key, value in inputs.items()}
    paths.update({key: run / REVIEWED_INPUTS[key] for key in PDF_KEYS})
    destination = run / "same-video-pdfs"
    if destination.exists():
        validate_pdf_receipt(run, paths)
        return
    from scripts.run_post_live_subtitle_generation import build_reading_pdf_command
    notes = read(paths["outline"])
    require(all(isinstance(notes.get(key), str) and notes[key].strip() for key in ("sermonTitle", "speaker")),
            "Same-video PDFs require verified title and speaker in companion metadata")
    start, end = source_window(contract)
    args = argparse.Namespace(sunday=contract["week"], sermon_title=notes["sermonTitle"], speaker=notes["speaker"],
        start_time=timecode(start), end_time=timecode(end))
    with tempfile.TemporaryDirectory(prefix=".same-video-pdfs-", dir=run) as temporary:
        staging = Path(temporary)
        reading = build_reading_pdf_command(args, run / "pipeline", contract["canonicalURL"])
        reading[0] = python
        if isinstance(notes.get("seriesZh"), str) and notes["seriesZh"].strip():
            reading[reading.index("--subtitle") + 1] = f"{notes['seriesZh'].strip()} · 中英对照阅读版"
        reading[reading.index("--out") + 1] = str(staging / "sermon_zh_en_reading.pdf")
        companion = [python, str(ROOT / "scripts/render_sermon_interpretation_pdf.py"), "--input", str(paths["outline"]),
            "--out", str(staging / "sermon_interpretation_zh.pdf"), "--qa-out", str(staging / "sermon_interpretation_zh.qa.json")]
        frozen = {key: sha256(path) for key, path in paths.items() if key in PDF_BINDINGS}
        for command in [reading, companion]:
            runner(command, check=True, stdout=sys.stderr)
        outputs = {key: staging / Path(REVIEWED_INPUTS[key]).name for key in PDF_KEYS}
        require(all(path.is_file() and path.stat().st_size for path in outputs.values())
                and all(read(outputs[key]).get("status") == "pass" for key in ("readingPdfQa", "companionPdfQa")), "New same-video PDF rendering did not pass")
        require(frozen == {key: sha256(paths[key]) for key in PDF_BINDINGS}, "Reviewed text changed during PDF rendering")
        write_json(staging / "render-receipt.json", {"schemaVersion": "sermon-same-video-pdf-render-v1", "status": "pass",
            "inputHashes": frozen, "outputHashes": {key: sha256(path) for key, path in outputs.items()}, "humanApproval": False})
        staging.rename(destination)


def seal_reviewed(run, source=None, *, root=ROOT, media_probe=probe, runner=subprocess.run, python=sys.executable):
    run = Path(run).resolve()
    path = run / HANDOFF_NAME
    from scripts.sermon_accounting import accounting_session, stage
    with accounting_session(run / "accounting", "same_video_handoff", evidence_directory=run):
        with stage("same_video.validate_reviewed", cache_hit=path.exists()):
            if path.exists():
                validate_handoff(run, source, root=root, media_probe=media_probe)
                return read(path)
            contract, inputs = reviewed_inputs(run, source, root=root, media_probe=media_probe, include_pdfs=False)
        with stage("same_video.render_reviewed_pdfs", cache_hit=(run / PDF_RECEIPT).exists()):
            render_reviewed_pdfs(run, contract, inputs, runner=runner, python=python)
        with stage("same_video.seal"):
            contract, inputs = reviewed_inputs(run, source, root=root, media_probe=media_probe)
            receipt = {"schemaVersion": versioned_schema(HANDOFF_SCHEMA, contract), "week": contract["week"], "sourceId": contract["sourceId"],
                "canonicalURL": contract["canonicalURL"], "sourceVideoSha256": contract["sha256"], **boundary_metadata(contract), "humanApproval": False, "status": "reviewed_artifacts_bound", "inputs": inputs}
            if path.exists():
                require(read(path) == receipt, "Existing same-video handoff changed; preserve it and use a new run")
            else:
                write_json(path, receipt)
            return receipt


def validate_handoff(run, source=None, *, root=ROOT, media_probe=probe):
    contract, inputs = reviewed_inputs(run, source, root=root, media_probe=media_probe)
    path = Path(run) / HANDOFF_NAME
    receipt = read(path)
    require(receipt.get("schemaVersion") == versioned_schema(HANDOFF_SCHEMA, contract) and receipt.get("status") == "reviewed_artifacts_bound"
            and receipt.get("humanApproval") is False and receipt.get("humanWindow") == boundary_metadata(contract)["humanWindow"]
            and receipt.get("boundaryBasis") == boundary_metadata(contract)["boundaryBasis"] and receipt.get("week") == contract["week"]
            and receipt.get("sourceId") == contract["sourceId"] and receipt.get("canonicalURL") == contract["canonicalURL"]
            and receipt.get("sourceVideoSha256") == contract["sha256"] and receipt.get("inputs") == inputs,
            "Same-video reviewed handoff is stale or bound to another source")
    inputs["sameVideoHandoff"] = {"path": str(path.resolve()), "sha256": sha256(path)}
    return contract, inputs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    origin = p.add_mutually_exclusive_group(required=True)
    origin.add_argument("--contract", type=Path)
    origin.add_argument("--config", type=Path, help="Read weeks[week].sameVideo.source from an existing bridge config")
    p.add_argument("--week")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--title")
    p.add_argument("--speaker")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--initialize", action="store_true")
    mode.add_argument("--seal-reviewed", action="store_true")
    args = p.parse_args()
    if args.config:
        require(bool(args.week), "--config requires --week")
        settings = read(args.config)["weeks"][args.week]
        source = settings["sameVideo"]["source"]
        require(source["week"] == args.week, "Bridge source week changed")
        args.title = args.title or settings.get("title")
        args.speaker = args.speaker or settings.get("speaker")
    else:
        source = read(args.contract)
    if args.initialize:
        result = initialize(source, args.run, title=args.title, speaker=args.speaker)
    elif args.seal_reviewed:
        result = seal_reviewed(args.run, source)
    else:
        normalized = validate_archive(args.run, source)[0] if args.run.exists() else validate_source(source, source["week"])
        result = production_plan(args.run, normalized, title=args.title, speaker=args.speaker)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
