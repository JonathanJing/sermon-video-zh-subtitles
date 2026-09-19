#!/usr/bin/env python3
"""Acoustic anchors for reviewed English blocks; layout timing is never read.

Local ASR is timing evidence only. It cannot replace the frozen English/Chinese
reading text. Unmatched boundaries are review items, never interpolated silently.
"""
import argparse
import difflib
import json
from pathlib import Path
import re
import subprocess

from poc import sha256, write_json
from speech_backend import same_identity, SpeechModel, ASR, ALIGNER
from weekly_dubbing import read, validate_frozen


def tokens(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("’", "'"))


def match_blocks(blocks, words):
    expected, ranges = [], []
    for block in blocks:
        start = len(expected)
        expected.extend(tokens(block["en"]))
        ranges.append((start, len(expected)))
    recognized, timed = [], []
    for word in words:
        for token in tokens(word["text"]):
            recognized.append(token)
            timed.append(word)
    matches = difflib.SequenceMatcher(None, expected, recognized, autojunk=False).get_matching_blocks()
    mapping = {m.a + i: m.b + i for m in matches for i in range(m.size)}
    anchors, issues = [], []
    previous = 0
    for block, (start, end) in zip(blocks, ranges):
        found = [i for i in range(start, end) if i in mapping]
        coverage = len(found) / max(1, end - start)
        problems = []
        if not found:
            issues.append({"blockId": block["id"], "reason": "no_acoustic_text_match"})
            continue
        first, last = timed[mapping[found[0]]], timed[mapping[found[-1]]]
        if coverage < .8:
            problems.append("low_english_match_coverage")
        if found[0] - start > 3 or end - 1 - found[-1] > 3:
            problems.append("unmatched_boundary_words")
        # Require several consecutive words at both ends of every block.
        for edge in [found[:5], found[-5:]]:
            if len(edge) < 3 or any(mapping[b] != mapping[a] + 1 for a, b in zip(edge, edge[1:])):
                problems.append("weak_boundary_anchor")
                break
        if not previous <= first["start"] < last["end"]:
            problems.append("nonmonotonic_or_empty_source_interval")
        previous = last["end"]
        anchors.append({"blockId": block["id"], "start": first["start"], "end": last["end"], "englishMatchCoverage": round(coverage, 4),
            "firstWords": " ".join(expected[found[0]:found[0] + 5]), "lastWords": " ".join(expected[max(start, found[-1] - 4):found[-1] + 1]), "issues": problems})
        issues.extend({"blockId": block["id"], "reason": problem} for problem in problems)
    return anchors, issues


def attach_timing_issues(anchors, issues, timing_issues):
    for issue in timing_issues:
        if anchors:
            anchor = min(anchors, key=lambda a: max(a["start"] - issue["time"], issue["time"] - a["end"], 0))
            issue["blockId"] = anchor["blockId"]
            if issue["reason"] not in anchor["issues"]:
                anchor["issues"].append(issue["reason"])
        issues.append(issue)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    work = args.work.resolve()
    job = read(work / "job.json")
    validate_frozen(job)
    folder = work / "source-alignment"
    folder.mkdir(exist_ok=True)
    if (folder / "report.json").exists():
        raise ValueError("Preserve completed alignment")
    model = SpeechModel(ASR)
    windows = []
    asr_models = []
    duration = job["sourceDurationSeconds"]
    for offset in range(0, int(duration), 50):
        wav = folder / f"window-{offset:04d}.wav"
        if not wav.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-n", "-ss", str(offset), "-i", job["inputs"]["sourceAudio"]["path"], "-t", str(min(60, duration - offset)), "-ar", "16000", "-ac", "1", str(wav)], check=True)
        receipt = wav.with_suffix(".asr.json")
        identity = {"audioSha256": sha256(wav), "sourceSha256": job["inputs"]["sourceAudio"]["sha256"], "model": model.model[0], "revision": model.model[1]}
        if receipt.exists():
            row = read(receipt)
            if not same_identity(row["identity"], identity):
                raise ValueError("Stale acoustic timing cache")
        else:
            row = {"identity": identity, "text": model.generate(str(wav), language="English", max_tokens=2048).text}
            identity.update(model=model.model[0], revision=model.model[1])
            row["inferenceReceipt"] = model.last_receipt
            write_json(receipt, row)
        actual_model = [row["identity"]["model"], row["identity"]["revision"]]
        if actual_model not in asr_models:
            asr_models.append(actual_model)
        windows.append((offset, wav, row["text"]))
        print(f"Timing evidence {offset}s / {duration}s", flush=True)
    windows_models = asr_models[0]
    del model
    aligner = SpeechModel(ALIGNER)
    words = []
    timing_issues = []
    aligner_models = []
    for offset, wav, text in windows:
        result = aligner.generate(str(wav), text=text, language="English")
        if list(aligner.model) not in aligner_models:
            aligner_models.append(list(aligner.model))
        write_json(wav.with_suffix(".alignment.json"), {"audioSha256": sha256(wav), "model": aligner.model[0], "revision": aligner.model[1], "words": result.segments, "inferenceReceipt": aligner.last_receipt})
        timing_issues.extend({"reason": "zero_duration_alignment_word", "windowStart": offset, "word": w["text"], "time": offset + w["start"]}
                             for w in result.segments if w["start"] == w["end"])
        left = 0 if offset == 0 else 5
        right = min(55, duration - offset) if offset + 60 < duration else duration - offset
        for word in result.segments:
            if left <= word["start"] < right and word["start"] < word["end"] <= min(60, duration - offset) + .1:
                words.append({**word, "start": offset + word["start"], "end": offset + word["end"]})
    anchors, issues = match_blocks(job["blocks"], words)
    attach_timing_issues(anchors, issues, timing_issues)
    write_json(folder / "words.json", words)
    write_json(folder / "report.json", {"schemaVersion": "sermon-acoustic-anchors-v1", "jobSha256": sha256(work / "job.json"),
        "status": "machine_anchors_ready" if not issues else "anchor_review_required", "sourceAudioSha256": job["inputs"]["sourceAudio"]["sha256"],
        "timeOrigin": "approved_sermon_clip_start", "fullVideoOffsetSeconds": job["sourceStartSeconds"], "blocks": anchors, "issues": issues,
        "asr": windows_models, "aligner": aligner_models[0], "asrModels": asr_models, "alignerModels": aligner_models, "modelIdentityScope": "representative_first_result_with_complete_model_lists", "humanReview": "pending", "readingTextReplaced": False})
    print(json.dumps({"blocks": len(anchors), "issues": len(issues)}), flush=True)


if __name__ == "__main__":
    main()
