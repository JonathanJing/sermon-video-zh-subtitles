#!/usr/bin/env python3
"""Archive real YouTube audio and existing English captions under a separate contract.

Initialization never invokes ASR/models or claims human review. --translate is an
explicit paid stage; the remaining existing production commands are emitted as a
plan. This intake is not the video-stream/same-video release contract.
"""
import argparse
from datetime import date
import html
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

from poc import ROOT, probe, sha256, write_json
from prepare_same_video import read, require, timecode
sys.path.insert(0, str(ROOT))

SCHEMA = "sermon-archive-caption-source-v1"
SCHEMA_V2 = "sermon-archive-caption-source-v2"
SUPPORTED_SCHEMAS = {SCHEMA, SCHEMA_V2}
SEGMENTATION_V2 = {"strategy": "complete_caption_sentences_v2", "preferredCharacters": 120, "targetMaximumCharacters": 420,
    "hardMaximumCharacters": 840, "targetMaximumSeconds": 24, "hardMaximumSeconds": 55,
    "timing": "synthetic_caption_sentence_layout_only", "interpolation": "source_cue_character_fraction"}
CONTRACT = "archive-caption-source.json"


def validate(source, media_probe=probe):
    require(source.get("schemaVersion") in SUPPORTED_SCHEMAS, "Unsupported archive caption contract")
    require(date.fromisoformat(source["week"]).isoformat() == source["week"], "Invalid week")
    sid = source["sourceId"]
    require(bool(re.fullmatch(r"[A-Za-z0-9_-]{11}", sid)), "Invalid YouTube sourceId")
    require(source["canonicalURL"] == f"https://www.youtube.com/watch?v={sid}", "Canonical URL/sourceId mismatch")
    require(source.get("sermonOnly") is True and bool(source.get("sourceEvidenceReference")), "Sermon-only source evidence is required")
    for key in ("audio", "captions"):
        item = source[key]
        require(item.get("sourceId") == sid, "Audio/caption source identity mismatch")
        require(Path(item["path"]).is_file() and sha256(Path(item["path"])) == item["sha256"], "Source file hash changed")
    require(source["captions"].get("language") == "en" and source["captions"].get("kind") in {"manual", "automatic"}, "Explicit English caption provenance required")
    duration = source["durationSeconds"]
    require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0, "Invalid duration")
    measured = media_probe(Path(source["audio"]["path"]))
    require(any(s.get("codec_type") == "audio" for s in measured["streams"]), "Actual audio stream required")
    require(abs(measured["durationSeconds"] - duration) <= .2, "Audio duration changed")
    if source["schemaVersion"] == SCHEMA_V2:
        require(source.get("segmentation") == SEGMENTATION_V2, "Archive v2 segmentation contract changed")
    return caption_segments(Path(source["captions"]["path"]), duration, schema=source["schemaVersion"])


def caption_segments(path, duration, *, schema=SCHEMA):
    text = path.read_text(encoding="utf-8-sig")
    def timestamp(value):
        match = re.fullmatch(r"(?:(\d+):)?(\d{2}):(\d{2})[.,](\d{3})", value)
        require(bool(match), "Invalid caption timestamp")
        h, m, s, ms = [int(v or 0) for v in match.groups()]
        require(m < 60 and s < 60, "Invalid caption timestamp")
        return ((h * 60 + m) * 60 + s) * 1000 + ms
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start, end = lines[timing].split("-->", 1)
        cues.append({"startMs": timestamp(start.strip()), "endMs": timestamp(end.strip().split()[0]),
            "text": " ".join(lines[timing + 1:]).strip()})
    require(bool(cues), "No caption cues")
    rows = []
    previous = 0
    for i, cue in enumerate(cues):
        start, end = cue["startMs"] / 1000, cue["endMs"] / 1000
        require(0 <= start < end <= duration + .2 and start >= previous - .002, "Overlapping, rolling or out-of-range captions require explicit preprocessing")
        value = html.unescape(re.sub(r"<[^>]+>", "", cue["text"])).strip()
        require(bool(value), "Empty caption cue")
        rows.append({"id": i, "start": start, "end": end, "text": value, "sourceCaptionIds": [i]})
        previous = end
    require(schema in SUPPORTED_SCHEMAS, "Unsupported caption segmentation schema")
    if schema == SCHEMA_V2:
        return sentence_segments(rows)
    # Legacy aggregation is frozen to preserve paid v1 cache identities.
    # Aggregate without altering caption words or pretending timing is acoustic ASR.
    blocks = []
    for row in rows:
        if blocks and len(blocks[-1]["text"]) < 420 and row["end"] - blocks[-1]["start"] <= 55:
            block = blocks[-1]
            block["text"] += " " + row["text"]
            block["end"] = row["end"]
            block["sourceCaptionIds"].extend(row["sourceCaptionIds"])
        else:
            blocks.append({**row, "id": len(blocks)})
    return blocks


def sentence_segments(rows):
    from scripts.build_sermon_reading_edition_with_openai import build_sentence_units, join_english, sentence_complete
    from prepare_same_video import digest
    units = build_sentence_units(rows)
    cue_hashes = {row["id"]: digest(row) for row in rows}
    blocks, pending = [], []
    def grouped(parts):
        ids = list(dict.fromkeys(i for part in parts for i in part["segmentIds"]))
        return {"start": parts[0]["start"], "end": parts[-1]["end"], "text": join_english([part["en"] for part in parts]),
            "sourceCaptionIds": ids, "sourceCaptionHashes": {str(i): cue_hashes[i] for i in ids},
            "timingQuality": "synthetic_caption_sentence_layout_only"}
    def flush():
        block = grouped(pending)
        require(len(block["text"]) <= 840 and block["end"] - block["start"] <= 55,
            f"Caption sentence requires explicit review at cue {block['sourceCaptionIds'][0]}: exceeds 840 characters or 55 seconds")
        block.update(id=len(blocks), boundaryReason="sentence_end" if sentence_complete(block["text"]) else "incomplete_source_tail_requires_review")
        blocks.append(block)
        pending.clear()
    for unit in units:
        if pending and (len(grouped(pending)["text"]) >= 120 or len(grouped([*pending, unit])["text"]) > 420
            or unit["end"] - pending[0]["start"] > 24):
            flush()
        pending.append(unit)
    if pending:
        flush()
    require(join_english([row["text"] for row in rows]) == join_english([block["text"] for block in blocks]),
        "Sentence layout altered the source caption words")
    return blocks


def plan(run, source, title, speaker, python=sys.executable):
    from scripts.run_post_live_subtitle_generation import build_reading_pdf_command, build_sermon_interpretation_command
    pipeline = run / "pipeline"
    args = argparse.Namespace(sunday=source["week"], sermon_title=title, speaker=speaker, start_time="00:00:00",
        end_time=timecode(source["durationSeconds"]), interpretation_model="gpt-6-astra", interpretation_reasoning_effort="medium")
    commands = [[python, str(Path(__file__).resolve()), "--run", str(run), "--translate"],
        [python, str(ROOT / "scripts/build_sermon_reading_edition_with_openai.py"), "--source-pipeline", str(pipeline),
         "--outdir", str(pipeline / "reading-edition-v2"), "--provider", "openai", "--model", "gpt-6-astra", "--reasoning-effort", "medium", "--passes", "2"],
        build_reading_pdf_command(args, pipeline, source["canonicalURL"]), build_sermon_interpretation_command(args, pipeline)]
    commands[-1][commands[-1].index("--source-label") + 1] = "基于 YouTube 最终发布版本的已有英文字幕整理；中文为 AI 生成及两轮文字审校，未声称人工审核。"
    commands.append([python, str(Path(__file__).resolve()), "--run", str(run), "--seal-reviewed"])
    for command in commands:
        command[0] = python
    return {"schemaVersion": "sermon-archive-caption-plan-v1", "sourceRoute": "archive_caption", "humanApproval": False,
        "asrPerformed": False, "commands": commands, "nextGate": "validate_reviewed_caption_handoff_before_dubbing", "published": False}


def initialize(source, run, title, speaker, media_probe=probe):
    run = Path(run).resolve()
    segments = validate(source, media_probe)
    require(not run.exists(), "Use a new archive run; preserve existing production artifacts")
    run.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".caption-intake-", dir=run.parent) as tmp:
        staging = Path(tmp)
        (staging / "source").mkdir()
        archived = {**source}
        for key in ("audio", "captions"):
            name = key + Path(source[key]["path"]).suffix
            shutil.copyfile(source[key]["path"], staging / "source" / name)
            require(sha256(staging / "source" / name) == source[key]["sha256"], "Source changed during archive")
            archived[key] = {**source[key], "path": str(run / "source" / name)}
        write_json(staging / CONTRACT, archived)
        pipeline = staging / "pipeline"
        for name in ("segments_timed_en_raw.json", "segments_timed_en_corrected.json"):
            write_json(pipeline / name, segments)
        write_json(pipeline / "caption-source-receipt.json", {"schemaVersion": "sermon-caption-text-evidence-v1", "sourceContractSha256": sha256(staging / CONTRACT),
            "captionSha256": source["captions"]["sha256"], "audioSha256": source["audio"]["sha256"], "asrPerformed": False,
            "englishCorrection": "none", "humanApproval": False, "segmentsSha256": sha256(pipeline / "segments_timed_en_raw.json")})
        write_json(pipeline / "summary.json", {"source": archived["audio"]["path"], "sourceDurationSeconds": source["durationSeconds"],
            "sermonStartSeconds": 0, "sermonEndSeconds": source["durationSeconds"], "outputMode": "reading", "sourceRoute": "archive_caption",
            "models": {"referenceAsr": None, "chineseTranslation": "gpt-6-astra", "reasoningEffort": "medium"}, "timingPrecision": "synthetic_caption_sentence_layout_only" if source["schemaVersion"] == SCHEMA_V2 else "existing_caption_groups_not_acoustic_alignment"})
        result = plan(run, archived, title, speaker)
        write_json(staging / "archive-caption-production-plan.json", result)
        staging.rename(run)
    return result


def validate_caption_receipt(run, source):
    pipeline = run / "pipeline"
    expected = {"schemaVersion": "sermon-caption-text-evidence-v1", "sourceContractSha256": sha256(run / CONTRACT),
        "captionSha256": source["captions"]["sha256"], "audioSha256": source["audio"]["sha256"], "asrPerformed": False,
        "englishCorrection": "none", "humanApproval": False, "segmentsSha256": sha256(pipeline / "segments_timed_en_raw.json")}
    require(read(pipeline / "caption-source-receipt.json") == expected, "Caption source receipt changed")


def translate(run):
    from scripts.sermon_accounting import accounting_session
    run = Path(run).resolve()
    with accounting_session(run / "pipeline/accounting", "archive_caption_translate", evidence_directory=run / "pipeline"):
        return _translate(run)


def _translate(run):
    from scripts.sermon_pipeline import translate_chinese, load_glossary, load_env
    run = Path(run).resolve()
    source = read(run / CONTRACT)
    segments = validate(source)
    pipeline = run / "pipeline"
    validate_caption_receipt(run, source)
    require(all(read(pipeline / name) == segments for name in ("segments_timed_en_raw.json", "segments_timed_en_corrected.json")), "Caption-derived English changed")
    load_env(ROOT / ".env")
    key = os.environ.get("OPENAI_API_KEY", "")
    require(bool(key), "OPENAI_API_KEY is not set")
    return translate_chinese(key, segments, pipeline, "gpt-6-astra", load_glossary(None), reasoning_effort="medium", workers=4)


BOUNDARY_BASIS = "published_sermon_only_audio_and_caption_contract"
HANDOFF_NAME = "archive-caption-reviewed-handoff.json"


def reviewed_inputs(run, media_probe=probe):
    from scripts.build_sermon_reading_edition_with_openai import build_semantic_blocks, reading_quality_report, srt_time
    from scripts.generate_notes_with_openai import segments_from_srt, merge_aligned_segments, build_note_slices, summarize_slices
    run = Path(run).resolve()
    source = read(run / CONTRACT)
    segments = validate(source, media_probe)
    pipeline = run / "pipeline"
    relative = {"reading": "reading-edition-v2/reading_blocks.final.json", "readingDraft": "reading-edition-v2/reading_blocks.draft.json",
        "readingQuality": "reading-edition-v2/reading_quality_report.json", "outline": "sermon-interpretation/insights/openai-notes.json",
        "readingEnSrt": "reading-edition-v2/sermon_en_reading_revised.srt", "readingZhSrt": "reading-edition-v2/sermon_zh_reading_revised.srt",
        "rawEnglish": "segments_timed_en_raw.json", "correctedEnglish": "segments_timed_en_corrected.json", "translatedSegments": "segments_timed_zh.json",
        "captionReceipt": "caption-source-receipt.json", "summary": "summary.json"}
    paths = {key: pipeline / value for key, value in relative.items()}
    paths.update(sourceContract=run / CONTRACT, sourceAudio=Path(source["audio"]["path"]), sourceCaptions=Path(source["captions"]["path"]))
    require(all(path.is_file() for path in paths.values()), "Archive reviewed inputs incomplete")
    validate_caption_receipt(run, source)
    require(read(paths["rawEnglish"]) == read(paths["correctedEnglish"]) == segments, "Caption-derived English changed")
    quality = read(paths["readingQuality"])
    require(quality.get("status") == "pass" and quality.get("passes") == 2 and quality.get("model") == "gpt-6-astra"
        and quality.get("reasoningEffort") == "medium" and Path(quality["sourcePipeline"]).resolve() == pipeline,
        "Two-pass Astra Medium reading review required")
    layout = quality["layoutTargets"]
    draft = build_semantic_blocks(segments, read(paths["translatedSegments"]), preferred_seconds=layout["preferredSeconds"],
        preferred_english_chars=layout["preferredEnglishCharacters"], hard_seconds=layout["hardSeconds"], hard_english_chars=layout["hardEnglishCharacters"])
    require(draft == read(paths["readingDraft"]), "Reading draft differs from caption bilingual inputs")
    final = read(paths["reading"])
    require(len(final) == len(draft) and all(all(row.get(k) == original[k] for k in ("id", "start", "end", "segmentIds", "en"))
        for row, original in zip(final, draft)) and reading_quality_report(final)["status"] == "pass", "Reviewed reading changed its English source or fails QA")
    for field, key in [("en", "readingEnSrt"), ("zh", "readingZhSrt")]:
        expected = "\n".join(line for index, block in enumerate(final, 1) for line in
            [str(index), f"{srt_time(float(block['start']))} --> {srt_time(float(block['end']))}", str(block[field]).strip(), ""])
        require(paths[key].read_text() == expected, "Reading SRT differs from final text")
    notes = read(paths["outline"])
    aligned = merge_aligned_segments(segments_from_srt(paths["readingZhSrt"].read_text(), lang="zh"), segments_from_srt(paths["readingEnSrt"].read_text(), lang="en"))
    require(notes.get("status") == "ready" and notes.get("sermonDate") == source["week"]
        and notes.get("slices") == summarize_slices(build_note_slices(aligned)) and notes.get("sourceSegmentCount") == len(aligned), "Outline differs from reviewed reading")
    return source, paths


def seal_reviewed(run, media_probe=probe, *, runner=None):
    from scripts.sermon_accounting import accounting_session
    run = Path(run).resolve()
    with accounting_session(run / "accounting", "archive_caption_handoff", evidence_directory=run):
        return _seal_reviewed(run, media_probe=media_probe, runner=runner)


def _seal_reviewed(run, media_probe=probe, *, runner=None):
    import subprocess
    runner = runner or subprocess.run
    run = Path(run).resolve()
    if (run / HANDOFF_NAME).exists():
        return validate_handoff(run, media_probe=media_probe)
    source, paths = reviewed_inputs(run, media_probe)
    destination = run / "archive-caption-pdfs"
    files = {"readingPdf": "sermon_zh_en_reading.pdf", "readingPdfQa": "sermon_zh_en_reading.qa.json",
        "companionPdf": "sermon_interpretation_zh.pdf", "companionPdfQa": "sermon_interpretation_zh.qa.json"}
    if not destination.exists():
        notes = read(paths["outline"])
        with tempfile.TemporaryDirectory(prefix=".archive-pdfs-", dir=run) as tmp:
            stage = Path(tmp)
            command = plan(run, source, notes["sermonTitle"], notes["speaker"])["commands"][2]
            command[command.index("--out") + 1] = str(stage / "sermon_zh_en_reading.pdf")
            frozen = {key: sha256(path) for key, path in paths.items()}
            runner(command, check=True)
            runner([sys.executable, str(ROOT / "scripts/render_sermon_interpretation_pdf.py"), "--input", str(paths["outline"]),
                "--out", str(stage / "sermon_interpretation_zh.pdf"), "--qa-out", str(stage / "sermon_interpretation_zh.qa.json")], check=True)
            require(frozen == {key: sha256(path) for key, path in reviewed_inputs(run, media_probe)[1].items()}, "Text changed during PDF rendering")
            require(all((stage / name).is_file() and (stage / name).stat().st_size for name in files.values())
                and all(read(stage / files[key]).get("status") == "pass" for key in ("readingPdfQa", "companionPdfQa")), "Archive PDF QA failed")
            write_json(stage / "render-receipt.json", {"schemaVersion": "sermon-archive-caption-pdf-render-v1", "status": "pass", "humanApproval": False,
                "inputHashes": frozen, "outputHashes": {key: sha256(stage / name) for key, name in files.items()}})
            stage.rename(destination)
    # The independent receipt survives a stop after PDF publication but before
    # handoff sealing; reuse only when all text and rendered bytes still match.
    validate_pdf_bundle(run, paths)
    paths.update({key: destination / name for key, name in files.items()})
    paths["archiveCaptionPdfReceipt"] = destination / "render-receipt.json"
    inputs = {key: {"path": str(path), "sha256": sha256(path)} for key, path in paths.items()}
    receipt = {"schemaVersion": "sermon-archive-caption-reviewed-handoff-v1", "status": "reviewed_artifacts_bound", "sourceRoute": "archive_caption",
        "week": source["week"], "sourceId": source["sourceId"], "boundaryBasis": BOUNDARY_BASIS, "humanWindow": "not_applicable",
        "humanApproval": False, "asrPerformed": False, "inputs": inputs}
    write_json(run / HANDOFF_NAME, receipt)
    return validate_handoff(run, media_probe=media_probe)


def validate_pdf_bundle(run, paths):
    destination = run / "archive-caption-pdfs"
    receipt_path = destination / "render-receipt.json"
    require(receipt_path.is_file(), "Archive PDF render receipt missing")
    receipt = read(receipt_path)
    files = {"readingPdf": "sermon_zh_en_reading.pdf", "readingPdfQa": "sermon_zh_en_reading.qa.json",
        "companionPdf": "sermon_interpretation_zh.pdf", "companionPdfQa": "sermon_interpretation_zh.qa.json"}
    require(all((destination / name).is_file() and (destination / name).stat().st_size for name in files.values()), "Archive PDF bundle incomplete")
    require(receipt == {"schemaVersion": "sermon-archive-caption-pdf-render-v1", "status": "pass", "humanApproval": False,
        "inputHashes": {key: sha256(path) for key, path in paths.items()},
        "outputHashes": {key: sha256(destination / name) for key, name in files.items()}}, "Archive PDF render receipt stale")
    require(all(read(destination / files[key]).get("status") == "pass" for key in ("readingPdfQa", "companionPdfQa")), "Archive PDF QA failed")


def validate_handoff(run, media_probe=probe):
    run = Path(run).resolve()
    source, paths = reviewed_inputs(run, media_probe)
    validate_pdf_bundle(run, paths)
    paths.update({key: run / "archive-caption-pdfs" / name for key, name in {
        "readingPdf": "sermon_zh_en_reading.pdf", "readingPdfQa": "sermon_zh_en_reading.qa.json",
        "companionPdf": "sermon_interpretation_zh.pdf", "companionPdfQa": "sermon_interpretation_zh.qa.json",
        "archiveCaptionPdfReceipt": "render-receipt.json"}.items()})
    receipt = read(run / HANDOFF_NAME)
    require(receipt.get("schemaVersion") == "sermon-archive-caption-reviewed-handoff-v1" and receipt.get("status") == "reviewed_artifacts_bound"
        and receipt.get("sourceRoute") == "archive_caption" and receipt.get("boundaryBasis") == BOUNDARY_BASIS
        and receipt.get("humanApproval") is False and receipt.get("asrPerformed") is False and receipt.get("humanWindow") == "not_applicable"
        and receipt.get("week") == source["week"] and receipt.get("sourceId") == source["sourceId"], "Invalid archive handoff")
    inputs = receipt["inputs"]
    for key, path in paths.items():
        require(inputs.get(key) == {"path": str(path), "sha256": sha256(path)}, "Archive handoff input changed")
    for key, item in inputs.items():
        path = Path(item["path"])
        require(path.resolve().is_relative_to(run) and path.is_file() and sha256(path) == item["sha256"], "Archive handoff file changed or escaped run")
    for key in ("readingPdf", "readingPdfQa", "companionPdf", "companionPdfQa"):
        require(key in inputs, "Archive handoff missing PDF")
    inputs = {**inputs, "archiveCaptionHandoff": {"path": str(run / HANDOFF_NAME), "sha256": sha256(run / HANDOFF_NAME)}}
    return source, inputs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", type=Path)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--title")
    p.add_argument("--speaker")
    modes = p.add_mutually_exclusive_group()
    modes.add_argument("--translate", action="store_true")
    modes.add_argument("--seal-reviewed", action="store_true")
    args = p.parse_args()
    if args.seal_reviewed:
        seal_reviewed(args.run)
    elif args.translate:
        translate(args.run)
    else:
        require(args.contract and args.title and args.speaker, "Intake requires --contract --title --speaker")
        import json
        print(json.dumps(initialize(read(args.contract), args.run, args.title, args.speaker), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
