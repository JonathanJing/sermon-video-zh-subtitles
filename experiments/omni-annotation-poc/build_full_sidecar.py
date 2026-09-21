#!/usr/bin/env python3
"""Normalize overlapping Gemini windows into sentence labels and merged events."""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
from pathlib import Path

from schema import EVENT_TYPES, sha256


WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)*")
SENTENCE_RE = re.compile(r".+?(?:[.!?]+(?=\s|$)|$)", re.S)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tokens(text: str) -> list[str]:
    return [item.lower().replace("’", "'") for item in WORD_RE.findall(text)]


def sentences(text: str) -> list[str]:
    return [re.sub(r"\s+", " ", item.group(0)).strip()
            for item in SENTENCE_RE.finditer(text.strip()) if item.group(0).strip()]


def word_id(index: int) -> str:
    return f"word-{index:05d}"


def build_sentence_timeline(reading_blocks: list[dict], report: dict,
                            aligned_words: list[dict]) -> tuple[list[dict], list[dict]]:
    report_by_id = {int(item["blockId"]): item for item in report["blocks"]}
    output: list[dict] = []
    issues: list[dict] = []
    for block in reading_blocks:
        block_id = int(block["id"])
        anchor = report_by_id[block_id]
        candidates = [(index, word) for index, word in enumerate(aligned_words)
                      if float(word["end"]) > float(anchor["start"]) - 0.001
                      and float(word["start"]) < float(anchor["end"]) + 0.001]
        block_sentences = sentences(str(block["en"]))
        source_tokens: list[str] = []
        spans: list[tuple[int, int]] = []
        for sentence in block_sentences:
            start = len(source_tokens)
            source_tokens.extend(tokens(sentence))
            spans.append((start, len(source_tokens)))
        target_tokens = [tokens(str(word["text"]))[0] if tokens(str(word["text"])) else ""
                         for _, word in candidates]
        matcher = difflib.SequenceMatcher(None, source_tokens, target_tokens, autojunk=False)
        source_to_target: dict[int, int] = {}
        for match in matcher.get_matching_blocks():
            for offset in range(match.size):
                source_to_target[match.a + offset] = match.b + offset
        for sentence_index, (text, span) in enumerate(zip(block_sentences, spans), start=1):
            matched = [source_to_target[index] for index in range(*span) if index in source_to_target]
            coverage = len(matched) / max(1, span[1] - span[0])
            if not matched:
                issues.append({"type": "sentence_without_word_anchor", "blockId": block_id,
                               "sentenceIndex": sentence_index, "text": text})
                continue
            first_global, first_word = candidates[min(matched)]
            last_global, last_word = candidates[max(matched)]
            item = {
                "sentenceId": f"b{block_id:02d}-s{sentence_index:03d}",
                "blockId": block_id,
                "text": text,
                "startSeconds": float(first_word["start"]),
                "endSeconds": float(last_word["end"]),
                "firstWordId": word_id(first_global),
                "lastWordId": word_id(last_global),
                "wordMatchCoverage": round(coverage, 4),
                "timingStatus": "candidate_supported" if coverage >= 0.8 else "uncertain",
            }
            output.append(item)
            if coverage < 0.8:
                issues.append({"type": "weak_sentence_word_match", "sentenceId": item["sentenceId"],
                               "coverage": round(coverage, 4)})
    output.sort(key=lambda item: (item["startSeconds"], item["endSeconds"]))
    return output, issues


def parse_silences(audio: Path) -> list[dict]:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio), "-af",
         "silencedetect=noise=-35dB:d=0.25", "-f", "null", "-"],
        capture_output=True, text=True, check=False)
    starts = [float(value) for value in re.findall(r"silence_start: ([0-9.]+)", result.stderr)]
    ends = [(float(end), float(duration)) for end, duration in
            re.findall(r"silence_end: ([0-9.]+) \| silence_duration: ([0-9.]+)", result.stderr)]
    return [{"silenceId": f"silence-{index:04d}", "startSeconds": start,
             "endSeconds": end, "durationSeconds": duration}
            for index, (start, (end, duration)) in enumerate(zip(starts, ends))]


def owner_window(windows: list[dict], midpoint: float) -> dict | None:
    covering = [item for item in windows
                if float(item["relativeStartSeconds"]) <= midpoint
                <= float(item["relativeEndSeconds"])]
    if not covering:
        return None
    return min(covering, key=lambda item: abs(
        midpoint - (float(item["relativeStartSeconds"]) + float(item["relativeEndSeconds"])) / 2))


def full_result_errors(result: dict) -> list[str]:
    errors = list(result.get("validationErrors") or [])
    analysis = result.get("analysis")
    if not isinstance(analysis, dict):
        return errors + ["missing_analysis"]
    if analysis.get("audio_status") != "matched":
        errors.append("full_run_audio_not_matched")
    if analysis.get("video_status") != "matched":
        errors.append("full_run_video_not_matched")
    if analysis.get("transcript_status") not in {"matched", "partial"}:
        errors.append("full_run_supplied_transcript_not_acknowledged")
    return sorted(set(errors))


def label_sentences(sentence_timeline: list[dict], windows: list[dict], results_dir: Path) -> tuple[list[dict], list[dict]]:
    by_window: dict[str, dict] = {}
    result_issues: list[dict] = []
    for window in windows:
        result_path = results_dir / f'{window["windowId"]}.result.json'
        retries = sorted(results_dir.glob(f'{window["windowId"]}-retry*.result.json'), reverse=True)
        for candidate in retries:
            if candidate.is_file():
                retry = json.loads(candidate.read_text(encoding="utf-8"))
                if not full_result_errors(retry):
                    result_path = candidate
                    break
        reparsed_path = results_dir / f'{window["windowId"]}.reparsed.result.json'
        if result_path.name == f'{window["windowId"]}.result.json' and reparsed_path.is_file():
            reparsed = json.loads(reparsed_path.read_text(encoding="utf-8"))
            if not full_result_errors(reparsed):
                result_path = reparsed_path
        if not result_path.is_file():
            result_issues.append({"type": "missing_result", "windowId": window["windowId"]})
            continue
        result = json.loads(result_path.read_text(encoding="utf-8"))
        selected_errors = full_result_errors(result)
        if selected_errors:
            result_issues.append({"type": "result_validation_error", "windowId": window["windowId"],
                                  "errors": selected_errors})
            continue
        by_window[window["windowId"]] = result
    labeled: list[dict] = []
    for sentence in sentence_timeline:
        midpoint = (sentence["startSeconds"] + sentence["endSeconds"]) / 2
        window = owner_window(windows, midpoint)
        label = dict(sentence)
        label.update({"geminiType": None, "geminiConfidence": None,
                      "geminiWindowId": window["windowId"] if window else None,
                      "geminiEventIndex": None, "geminiStatus": "missing"})
        result = by_window.get(window["windowId"]) if window else None
        analysis = result.get("analysis") if isinstance(result, dict) else None
        if isinstance(analysis, dict):
            local_start = sentence["startSeconds"] - float(window["relativeStartSeconds"])
            local_end = sentence["endSeconds"] - float(window["relativeStartSeconds"])
            overlaps: list[tuple[float, int, dict]] = []
            for index, event in enumerate(analysis.get("events") or []):
                overlap = max(0.0, min(local_end, float(event.get("end_seconds", 0)))
                              - max(local_start, float(event.get("start_seconds", 0))))
                if overlap:
                    overlaps.append((overlap, index, event))
            if overlaps:
                _, event_index, event = max(overlaps, key=lambda item: (item[0], item[2].get("confidence", 0)))
                label.update({"geminiType": event.get("type"),
                              "geminiConfidence": event.get("confidence"),
                              "geminiWindowId": window["windowId"],
                              "geminiAttemptId": result.get("caseId"),
                              "geminiEventIndex": event_index,
                              "geminiStatus": "machine_candidate",
                              "geminiScriptureRef": event.get("scripture_ref"),
                              "geminiOnScreenText": event.get("on_screen_text"),
                              "geminiEvidence": event.get("evidence"),
                              "geminiNote": event.get("note")})
            else:
                label["geminiStatus"] = "uncovered_by_event"
        labeled.append(label)
    return labeled, result_issues


def merge_events(labeled: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for sentence in labeled:
        event_type = sentence.get("geminiType")
        if event_type not in EVENT_TYPES:
            continue
        if (merged and merged[-1]["type"] == event_type
                and sentence["startSeconds"] - merged[-1]["endSeconds"] <= 2.0):
            merged[-1]["endSeconds"] = sentence["endSeconds"]
            merged[-1]["sentenceIds"].append(sentence["sentenceId"])
            merged[-1]["sourceWindowIds"] = sorted(set(
                merged[-1]["sourceWindowIds"] + [sentence["geminiWindowId"]]))
        else:
            merged.append({
                "eventId": f"event-{len(merged):04d}", "type": event_type,
                "startSeconds": sentence["startSeconds"], "endSeconds": sentence["endSeconds"],
                "sentenceIds": [sentence["sentenceId"]],
                "sourceWindowIds": [sentence["geminiWindowId"]],
                "reviewState": "machine_candidate_requires_judge_and_listening_review",
            })
    return merged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--reading-blocks", type=Path, required=True)
    parser.add_argument("--source-audio", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    words_path = Path(manifest["wordTiming"]["path"])
    report_path = Path(manifest["wordTiming"]["reportPath"])
    aligned_words = json.loads(words_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    reading_blocks = json.loads(args.reading_blocks.read_text(encoding="utf-8"))
    sentence_timeline, sentence_issues = build_sentence_timeline(reading_blocks, report, aligned_words)
    labeled, result_issues = label_sentences(sentence_timeline, manifest["windows"], args.results)
    silences = parse_silences(args.source_audio)
    output = {
        "schemaVersion": "sermon-omni-full-sidecar-v1",
        "source": manifest["source"],
        "reviewState": "machine_candidate_requires_gpt6_judge_and_operator_listening_review",
        "humanGold": False, "releaseEligible": False,
        "evidence": {
            "manifest": {"path": str(args.manifest.resolve()), "sha256": sha256(args.manifest)},
            "geminiResultsDirectory": str(args.results.resolve()),
            "readingBlocks": {"path": str(args.reading_blocks.resolve()), "sha256": sha256(args.reading_blocks)},
            "wordTiming": manifest["wordTiming"],
            "acoustics": {"path": str(args.source_audio.resolve()), "sha256": sha256(args.source_audio),
                          "method": "ffmpeg silencedetect noise=-35dB d=0.25",
                          "transcriptMatchStatus": "unverified", "silenceIntervals": silences},
        },
        "counts": {"windows": len(manifest["windows"]), "sentences": len(labeled),
                   "mergedEvents": 0, "silenceIntervals": len(silences)},
        "sentences": labeled,
        "mergedEvents": merge_events(labeled),
        "issues": sentence_issues + result_issues,
        "limitations": manifest["limitations"] + [
            "Sentence boundaries are derived from reading-edition punctuation and mapped to candidate word timing.",
            "A single owner window supplies each sentence label to prevent overlapping-window self-voting.",
            "Energy silence supports only acoustic gaps, not rhetorical intent.",
        ],
    }
    output["counts"]["mergedEvents"] = len(output["mergedEvents"])
    write_json(args.out, output)
    print(json.dumps({"out": str(args.out), **output["counts"],
                      "issues": len(output["issues"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
