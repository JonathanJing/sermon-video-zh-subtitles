#!/usr/bin/env python3
"""Budget natural Chinese against measured English intervals before video use.

If anchors or durations need review, write a repair worksheet and no synchronized
audio. Speech is never cut, overlapped or automatically squeezed to pass a gate.
"""
import argparse
from pathlib import Path

from poc import sha256, write_json
from weekly_dubbing import read, validate_frozen, normalize_mp3


def reviewed_anchors(blocks, anchors, approval=None):
    ids = [block["id"] for block in blocks]
    by_id = {anchor["blockId"]: anchor for anchor in anchors}
    if len(set(ids)) != len(ids) or len(by_id) != len(anchors) or not set(by_id) <= set(ids):
        raise ValueError("Unknown or duplicate source anchor")
    if approval is not None:
        changes = {anchor["blockId"]: anchor for anchor in approval["blocks"]}
        required = (set(ids) - set(by_id)) | {key for key, anchor in by_id.items() if anchor.get("issues")}
        if len(changes) != len(approval["blocks"]) or not set(changes) <= set(ids) or not required <= set(changes):
            raise ValueError("Every missing or uncertain anchor needs one explicit review")
        for key, change in changes.items():
            by_id[key] = {**by_id.get(key, {}), "blockId": key, "start": change["start"], "end": change["end"], "issues": []}
    return [by_id[key] for key in ids if key in by_id]


def load_anchors(work, job, job_hash):
    alignment_path = work / "source-alignment/report.json"
    alignment = read(alignment_path)
    if alignment.get("jobSha256") != job_hash or alignment.get("sourceAudioSha256") != job["inputs"]["sourceAudio"]["sha256"] or alignment.get("timeOrigin") != "approved_sermon_clip_start" or alignment.get("fullVideoOffsetSeconds") != job["sourceStartSeconds"]:
        raise ValueError("Acoustic alignment belongs to changed source inputs")
    if "wordEvidence" in alignment or "englishBlocksSha256" in alignment:
        import hashlib
        import json
        from align_weekly_source import match_blocks
        evidence = alignment.get("wordEvidence")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("path"), str) or not evidence.get("sha256"):
            raise ValueError("Reused source-word evidence is incomplete")
        word_path = Path(evidence["path"])
        if not word_path.is_file() or sha256(word_path) != evidence["sha256"]:
            raise ValueError("Reused source-word evidence changed")
        english = json.dumps([{"id": block["id"], "en": block["en"]} for block in job["blocks"]], ensure_ascii=False, sort_keys=True)
        if alignment.get("englishBlocksSha256") != hashlib.sha256(english.encode()).hexdigest():
            raise ValueError("Reused source anchors belong to changed English blocks")
        anchors, issues = match_blocks(job["blocks"], read(word_path))
        if alignment.get("blocks") != anchors or alignment.get("issues") != issues:
            raise ValueError("Reused source anchors differ from their word evidence")
    approval_path = work / "source-alignment/anchor-review.json"
    model_path = work / "source-alignment/anchor-model-review.json"
    approval, approval_hash = None, None
    if approval_path.exists() and model_path.exists():
        raise ValueError("Choose one explicit anchor review; preserve the other in its parent job")
    if approval_path.exists():
        approval = read(approval_path)
        if not (approval.get("humanApproval") is True and approval.get("reviewType") in {None, "human"}
                and approval.get("reviewedBy") and approval.get("reviewedAt") and approval.get("alignmentSha256") == sha256(alignment_path)):
            raise ValueError("Anchor review is incomplete or stale")
        approval_hash = sha256(approval_path)
    elif model_path.exists():
        approval = read(model_path)
        if not (approval.get("schemaVersion") == "sermon-anchor-model-review-v1"
                and approval.get("reviewType") == "model" and approval.get("model") == "gpt-6-astra"
                and approval.get("humanApproval") is False and approval.get("status") == "approved_for_candidate_alignment"
                and approval.get("reviewedBy") and approval.get("reviewedAt")
                and approval.get("jobSha256") == job_hash
                and approval.get("sourceAudioSha256") == job["inputs"]["sourceAudio"]["sha256"]
                and approval.get("alignmentSha256") == sha256(alignment_path)
                and approval.get("unresolvedBoundaryIssues") == []):
            raise ValueError("Model anchor review is incomplete or stale")
        evidence = approval.get("evidence", [])
        if not evidence or len({e.get("path") for e in evidence}) != len(evidence):
            raise ValueError("Model anchor review requires distinct acoustic evidence")
        for item in evidence:
            if sha256(Path(item["path"])) != item["sha256"]:
                raise ValueError("Model anchor evidence changed")
        if any(not item.get("reason") or item.get("status") != "model_supported" for item in approval.get("blocks", [])):
            raise ValueError("Each model-reviewed anchor needs its own supported decision")
        approval_hash = sha256(model_path)
    anchors = reviewed_anchors(job["blocks"], alignment["blocks"], approval)
    previous = 0
    for anchor in anchors:
        if not previous <= anchor["start"] < anchor["end"] <= job["sourceDurationSeconds"] + .01:
            raise ValueError("Invalid / overlapping source anchors")
        previous = anchor["end"]
    return anchors, approval_hash


def anchor_review_type(work):
    if (work / "source-alignment/anchor-model-review.json").exists():
        return "model"
    return "human" if (work / "source-alignment/anchor-review.json").exists() else "unreviewed_machine_anchors"


def load_placements(work, job, render, anchors):
    """Optional model-reviewed playback offset; never changes English anchors."""
    path = work / "synchronization/placement-model-review.json"
    if not path.exists():
        return {}, None
    review = read(path)
    if not (review.get("schemaVersion") == "sermon-playback-placement-review-v1"
            and review.get("reviewType") == "model" and review.get("model") == "gpt-6-astra"
            and review.get("humanApproval") is False and review.get("status") == "approved_for_candidate_playback"
            and review.get("reviewedBy") and review.get("reviewedAt")
            and review.get("jobSha256") == sha256(work / "job.json")
            and review.get("renderSha256") == sha256(work / "render/report.json")
            and review.get("alignmentSha256") == sha256(work / "source-alignment/report.json")
            and review.get("sourceAudioSha256") == job["inputs"]["sourceAudio"]["sha256"]
            and review.get("unresolvedPlacementIssues") == []):
        raise ValueError("Playback placement review is incomplete or stale")
    evidence = review.get("evidence", [])
    if not evidence or len({e.get("path") for e in evidence}) != len(evidence):
        raise ValueError("Playback placement needs distinct source evidence")
    for item in evidence:
        if sha256(Path(item["path"])) != item["sha256"]:
            raise ValueError("Playback placement evidence changed")
    changes = review.get("blocks", [])
    placements = {b["blockId"]: b for b in changes}
    by_id = {a["blockId"]: a for a in anchors}
    ids = [b["id"] for b in job["blocks"]]
    if not changes or len(placements) != len(changes) or not set(placements) <= set(by_id):
        raise ValueError("Unknown or duplicate playback placement")
    for key, item in placements.items():
        anchor = by_id[key]
        index = ids.index(key)
        previous = by_id.get(ids[index - 1]) if index else None
        start = item.get("playbackStart")
        if not (item.get("status") == "model_supported" and item.get("reason")
                and item.get("sourceAnchorStart") == anchor["start"]
                and type(start) in (int, float) and 0 <= start <= anchor["start"]
                and anchor["start"] - start <= 1.000001
                and (index == 0 or previous is not None and start >= previous["end"])):
            raise ValueError("Placement must stay within one second of its anchor and after prior source speech")
    return {key: item["playbackStart"] for key, item in placements.items()}, sha256(path)


def budgets(blocks, anchors, cues, duration, placements=None):
    placements = placements or {}
    by_id = {a["blockId"]: a for a in anchors}
    rows, failures = [], []
    for i, block in enumerate(blocks):
        anchor = by_id.get(block["id"])
        following = by_id.get(blocks[i + 1]["id"]) if i + 1 < len(blocks) else None
        selected = [c for c in cues if c["blockId"] == block["id"]]
        if not anchor or not selected or (i + 1 < len(blocks) and not following):
            failures.append({"blockId": block["id"], "reason": "missing_anchor_or_audio"})
            continue
        target_end = placements.get(following["blockId"], following["start"]) if following else duration
        playback_start = placements.get(block["id"], anchor["start"])
        natural = selected[-1]["end"] - selected[0]["start"]
        available = target_end - playback_start
        overflow = max(0, natural - available)
        row = {"blockId": block["id"], "videoStart": playback_start, "videoEnd": target_end,
            "chineseStart": selected[0]["start"], "chineseEnd": selected[-1]["end"], "naturalSeconds": round(natural, 3), "availableSeconds": round(available, 3),
            "overflowSeconds": round(overflow, 3), "requiredSpeed": round(natural / available, 3) if available > 0 else None,
            "english": block["en"], "chinese": block["zh"], "anchorIssues": anchor.get("issues", [])}
        rows.append(row)
        if block["id"] in placements:
            row.update(sourceAnchorStart=anchor["start"], playbackLeadSeconds=round(anchor["start"] - playback_start, 3), placementReviewType="model")
        if anchor.get("issues"):
            failures.append({"blockId": block["id"], "reason": "anchor_needs_review"})
        if available <= 0 or overflow > .00001:
            failures.append({"blockId": block["id"], "reason": "natural_chinese_exceeds_video_slot", "overflowSeconds": row["overflowSeconds"]})
    return rows, failures


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--assemble", action="store_true")
    args = p.parse_args()
    work = args.work.resolve()
    job, render = read(work / "job.json"), read(work / "render/report.json")
    validate_frozen(job)
    job_hash = sha256(work / "job.json")
    if render["jobSha256"] != job_hash or render["sha256"] != sha256(work / "render/chinese.raw.wav"):
        raise ValueError("Timing evidence belongs to changed inputs")
    anchors, approval_hash = load_anchors(work, job, job_hash)
    placements, placement_hash = load_placements(work, job, render, anchors)
    rows, failures = budgets(job["blocks"], anchors, render["cues"], job["sourceDurationSeconds"], placements)
    out = work / "synchronization"
    out.mkdir(exist_ok=True)
    report = {"schemaVersion": "sermon-video-sync-budget-v1", "jobSha256": job_hash, "alignmentSha256": sha256(work / "source-alignment/report.json"), "anchorReviewSha256": approval_hash,
        "status": "needs_timing_review" if failures else "natural_timing_fits", "sourceVideoOffsetSeconds": job["sourceStartSeconds"], "durationSeconds": job["sourceDurationSeconds"],
        "blocks": rows, "failures": failures, "policy": "Preserve natural speech; review and re-render overflowing blocks. No speech trimming or automatic speed change.", "humanSameVideoPlayback": "pending"}
    report["anchorReviewType"] = anchor_review_type(work)
    if placement_hash:
        report["placementReviewSha256"] = placement_hash
    write_json(out / "report.json", report)
    if args.assemble:
        if failures:
            raise ValueError("Timing repair required; no synchronized MP3 was created")
        import numpy as np
        import soundfile as sf
        wave, rate = sf.read(work / "render/chinese.raw.wav", dtype="float32")
        synced = np.zeros(round(job["sourceDurationSeconds"] * rate), dtype=np.float32)
        cues = []
        for row in rows:
            segment = wave[round(row["chineseStart"] * rate):round(row["chineseEnd"] * rate)]
            start = round(row["videoStart"] * rate)
            if start + len(segment) > len(synced):
                raise ValueError("Speech would exceed the source video")
            synced[start:start + len(segment)] = segment
            for cue in render["cues"]:
                if cue["blockId"] == row["blockId"]:
                    cues.append({**cue, "start": cue["start"] - row["chineseStart"] + row["videoStart"], "end": cue["end"] - row["chineseStart"] + row["videoStart"]})
        raw = out / "zh-synced.raw.wav"
        if raw.exists():
            raise ValueError("Preserve the existing synchronized audio")
        sf.write(raw, synced, rate, subtype="PCM_24")
        info = normalize_mp3(raw, out / "zh-synced.mp3")
        write_json(out / "assembly.json", {"status": "synchronized_candidate", "jobSha256": job_hash, "timingReportSha256": sha256(out / "report.json"), "sourceNaturalMp3Sha256": sha256(work / "audio/zh-natural.mp3"), "sourceNaturalWavSha256": render["sha256"], "cues": cues, **info, "humanReview": "pending"})
        template = read(work / "audio-review.json")
        write_json(work / "audio-review-synced.json", {**template, "mp3Sha256": info["sha256"], "reviewedBy": None, "reviewedAt": None, "humanApproval": False, "checks": dict.fromkeys(template["checks"], "pending"),
            "notes": "同视频同步版本：确认中文音色、内容与完整视频同步；试听自然版的旧记录不会自动批准此版本。"})
    print(f"Timing checked: {len(rows)} blocks, {len(failures)} review items")


if __name__ == "__main__":
    main()
