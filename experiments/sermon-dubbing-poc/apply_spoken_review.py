#!/usr/bin/env python3
"""Apply a hash-bound conversational model review to a new weekly audio job.

Reading PDFs and their English source remain immutable. Revised speech has its
own model-review contract; this never creates human approval or training Gold.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from poc import sha256, speech_units, write_json
from render_weekly_audio import render_identity
from spoken_text import spoken_text, VERSION


SCHEMA = "sermon-spoken-script-review-v1"
CHECKS = {"completeMeaning", "negationsNumbersNames", "quotationAttribution", "spokenChinese"}


def read(path):
    return json.loads(Path(path).read_text())


def text_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def reviewed_blocks(parent, review_path):
    old = read(parent / "job.json")
    review = read(review_path)
    ids = [b["id"] for b in old["blocks"]]
    if review.get("schemaVersion") != SCHEMA or review.get("parentJobSha256") != sha256(parent / "job.json"):
        raise ValueError("Spoken review belongs to a different parent job")
    if not (review.get("reviewType") == "model" and review.get("model") == "gpt-6-astra"
            and review.get("humanApproval") is False and review.get("status") == "approved_for_synthesis"
            and review.get("reviewedAt") and review.get("reviewedBy")
            and review.get("authority") == "user_directed_conversation_review"):
        raise ValueError("A complete conversational Astra text review is required")
    if len(ids) != len(set(ids)) or review.get("reviewedBlockIds") != ids:
        raise ValueError("The text review must cover every source block in order")
    checks = review.get("checks", {})
    if set(checks) != CHECKS or any(value != "pass" for value in checks.values()):
        raise ValueError("Spoken text checks have not passed")
    if review.get("unresolvedTextIssues") != []:
        raise ValueError("Unresolved source/text issues prevent synthesis")
    evidence = review.get("evidence", [])
    if not evidence or len({e.get("path") for e in evidence}) != len(evidence):
        raise ValueError("Distinct review evidence is required")
    for item in evidence:
        if sha256(Path(item["path"])) != item["sha256"]:
            raise ValueError("Spoken review evidence changed")
    evidence_hashes = {e["sha256"] for e in evidence}
    changes = review.get("blocks", [])
    by_id = {b["blockId"]: b for b in changes}
    if len(by_id) != len(changes) or not set(by_id) <= set(ids):
        raise ValueError("Unknown or repeated spoken revision block")
    result = []
    for block in old["blocks"]:
        change = by_id.get(block["id"])
        if not change:
            result.append(dict(block))
            continue
        if change.get("originalEnglishSha256") != text_hash(block["en"]) or change.get("originalChineseSha256") != text_hash(block["zh"]):
            raise ValueError("Spoken revision source text changed")
        text = change.get("approvedChinese")
        if not isinstance(text, str) or not text.strip() or not change.get("reason"):
            raise ValueError("A nonempty reviewed spoken translation is required")
        updated = {**block, "zh": text}
        correction = change.get("sourceCorrection")
        if correction:
            if not (isinstance(correction.get("english"), str) and correction["english"].strip()
                    and correction.get("evidenceSha256") in evidence_hashes
                    and correction.get("reviewType") == "model" and correction.get("reason")):
                raise ValueError("English corrections require separate source evidence")
            updated["en"] = correction["english"]
        result.append(updated)
    return result


def make_units(blocks):
    units = []
    for block in blocks:
        parts = speech_units([block["zh"]], "flow")
        for index, text in enumerate(parts):
            if len(text) > 180:
                raise ValueError(f"Block {block['id']} needs a reviewed sentence break")
            unit = {"id": len(units), "blockId": block["id"], "text": text,
                    "gapAfterSeconds": .45 if index == len(parts) - 1 else .18}
            spoken = spoken_text(text)
            if spoken != text:
                unit["spokenText"] = spoken
            units.append(unit)
    return units


def validate_job_review(job):
    """Optional v1 job extension: validate revised speech against its own review."""
    if "spokenReview" not in job and "spokenScriptReview" not in job.get("inputs", {}):
        return
    if "spokenReview" not in job or "spokenScriptReview" not in job.get("inputs", {}) or "revisionOf" not in job:
        raise ValueError("Incomplete spoken review extension")
    parent = Path(job["revisionOf"]["path"])
    if sha256(parent / "job.json") != job["revisionOf"]["jobSha256"]:
        raise ValueError("Spoken revision parent changed")
    original = read(parent / "job.json")
    from weekly_dubbing import validate_frozen
    validate_frozen(original)
    item = job["inputs"].get("spokenScriptReview", {})
    path = Path(item.get("path", ""))
    if not path.is_file() or sha256(path) != item.get("sha256"):
        raise ValueError("Spoken script review changed")
    if job["inputs"] != {**original["inputs"], "spokenScriptReview": item}:
        raise ValueError("Spoken revision must preserve the parent frozen inputs")
    editable = {"createdAt", "blocks", "units", "inputs", "revisionOf", "spokenReview", "pronunciationRuleVersion", "humanAudioReview"}
    if any(job.get(key) != value for key, value in original.items() if key not in editable) or set(job) - (set(original) | editable):
        raise ValueError("Spoken revision must preserve the parent source/voice identity")
    if job.get("pronunciationRuleVersion") != VERSION or job.get("humanAudioReview") != "pending":
        raise ValueError("Revised speech must use current pronunciation rules and pending audio review")
    blocks = reviewed_blocks(parent, path)
    if job["blocks"] != blocks or job["units"] != make_units(blocks):
        raise ValueError("Job text does not match the approved spoken revision")
    if job["spokenReview"] != {"schemaVersion": SCHEMA, "reviewType": "model", "model": "gpt-6-astra",
                               "status": "approved_for_synthesis", "humanApproval": False}:
        raise ValueError("Spoken review must remain model-labelled")


def unit_key(unit):
    return (unit["blockId"], unit["text"], unit.get("spokenText", unit["text"]), unit["gapAfterSeconds"])


def reuse_source_alignment(parent, out, job):
    """Re-match revised English to existing, unchanged acoustic word evidence."""
    path = parent / "source-alignment/report.json"
    if not path.exists():
        return False
    original_path = path
    original = read(path)
    if (original.get("jobSha256") != sha256(parent / "job.json")
            or original.get("sourceAudioSha256") != job["inputs"]["sourceAudio"]["sha256"]
            or original.get("fullVideoOffsetSeconds") != job["sourceStartSeconds"]):
        raise ValueError("Source alignment cannot be reused for changed media")
    seen = set()
    while not (path.parent / "words.json").exists():
        if path in seen:
            raise ValueError("Cyclic source alignment provenance")
        seen.add(path)
        source = read(path).get("reusedFrom", {})
        if not source.get("path"):
            return False
        path = Path(source["path"])
        if sha256(path) != source.get("sha256"):
            raise ValueError("Source alignment reuse evidence changed")
    word_path = path.parent / "words.json"
    from align_weekly_source import match_blocks
    anchors, issues = match_blocks(job["blocks"], read(word_path))
    write_json(out / "source-alignment/report.json", {
        **original, "jobSha256": sha256(out / "job.json"), "blocks": anchors, "issues": issues,
        "status": "machine_anchors_ready" if not issues else "anchor_review_required",
        "wordEvidence": {"path": str(word_path.resolve()), "sha256": sha256(word_path)},
        "englishBlocksSha256": text_hash(json.dumps([{ "id": b["id"], "en": b["en"] } for b in job["blocks"]], ensure_ascii=False, sort_keys=True)),
        "reusedFrom": {"path": str(original_path.resolve()), "sha256": sha256(original_path),
                       "reason": "Same source audio; revised English re-matched to existing acoustic words without new ASR"}})
    return True


def derive(parent, out, review_path):
    from weekly_dubbing import validate_frozen
    old = read(parent / "job.json")
    validate_frozen(old)
    blocks = reviewed_blocks(parent, review_path)
    render = read(parent / "render/report.json")
    parent_hash = sha256(parent / "job.json")
    if render["jobSha256"] != parent_hash or render["sha256"] != sha256(parent / "render/chinese.raw.wav"):
        raise ValueError("Parent render is stale")
    if [c["text"] for c in render["cues"]] != [u["text"] for u in old["units"]]:
        raise ValueError("Parent render text coverage changed")
    if out.exists():
        raise ValueError("Use a new output directory; preserve previous revisions")
    units = make_units(blocks)
    job = {**old, "createdAt": datetime.now(timezone.utc).isoformat(), "blocks": blocks, "units": units,
           "inputs": {**old["inputs"], "spokenScriptReview": {"path": str(review_path.resolve()), "sha256": sha256(review_path)}},
           "revisionOf": {"path": str(parent.resolve()), "jobSha256": parent_hash,
                          "reason": "In-conversation Astra spoken-text and source-risk review; original Saturday files retained"},
           "spokenReview": {"schemaVersion": SCHEMA, "reviewType": "model", "model": "gpt-6-astra",
                            "status": "approved_for_synthesis", "humanApproval": False},
           "pronunciationRuleVersion": VERSION, "humanAudioReview": "pending"}
    validate_job_review(job)
    available = {}
    for i, unit in enumerate(old["units"]):
        available.setdefault(unit_key(unit), []).append(i)
    reusable = []
    changed = []
    # Validate all reused receipts before creating a derivative directory.
    for unit in units:
        candidates = available.get(unit_key(unit), [])
        if not candidates:
            changed.append(unit["id"])
            continue
        index = candidates.pop(0)
        wav = parent / f"render/unit-{index:04d}.wav"
        receipt_path = wav.with_suffix(".json")
        receipt = read(receipt_path)
        if (receipt.get("unit") != old["units"][index] or receipt.get("sha256") != sha256(wav)
                or receipt.get("identity", {}).get("jobSha256") != parent_hash
                or receipt["identity"].get("checkpointSha256") != job["voice"]["checkpointSha256"]):
            raise ValueError("Reused unit provenance changed")
        reusable.append((unit, index, wav, receipt_path, receipt))
    write_json(out / "job.json", job)
    identity = render_identity(out / "job.json", job["voice"]["checkpointSha256"])
    write_json(out / "render/identity.json", identity)
    for unit, index, wav, receipt_path, receipt in reusable:
        target = out / f"render/unit-{unit['id']:04d}.wav"
        shutil.copyfile(wav, target)
        write_json(target.with_suffix(".json"), {**receipt, "unit": unit, "identity": identity,
                   "reusedFrom": {"path": str(wav.resolve()), "unitId": index, "wavSha256": receipt["sha256"],
                                  "receiptSha256": sha256(receipt_path), "generationIdentity": receipt["identity"]}})
        screened = parent / f"audio/unit-screening/unit-{index:04d}.json"
        if screened.exists():
            target_screen = out / f"audio/unit-screening/unit-{unit['id']:04d}.json"
            check = read(screened)
            if check.get("identity", {}).get("audioSha256") != receipt["sha256"] or check["identity"].get("expected") != unit.get("spokenText", unit["text"]):
                raise ValueError("Reused ASR evidence belongs to changed speech")
            write_json(target_screen, {**check, "unitId": unit["id"], "blockId": unit["blockId"],
                       "reusedFrom": {"path": str(screened.resolve()), "sha256": sha256(screened), "unitId": index}})
    reused_alignment = reuse_source_alignment(parent, out, job)
    result = {"status": "model_reviewed_text_ready_for_synthesis", "parentJobSha256": parent_hash,
              "jobSha256": sha256(out / "job.json"), "scriptReviewSha256": sha256(review_path),
              "changedBlockIds": [a["id"] for a, b in zip(blocks, old["blocks"]) if a != b],
              "reusedUnits": [{"unitId": u["id"], "parentUnitId": i} for u, i, *_ in reusable],
              "regenerateUnitIds": changed, "sourceAlignment": "recomputed_from_existing_words" if reused_alignment else "new_acoustic_evidence_required",
              "saturdayReadingFilesChanged": False, "humanApproval": False}
    write_json(out / "revision-report.json", result)
    print(f"Reviewed {len(blocks)} blocks; reuse {len(reusable)} WAVs; generate {len(changed)} units")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ["parent", "out", "review"]:
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    derive(args.parent.resolve(), args.out.resolve(), args.review.resolve())
