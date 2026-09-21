#!/usr/bin/env python3
"""Validate sentence-level English/Chinese mapping and measured timing fit.

This POC intentionally validates structure, traceability, and measured window
fit without claiming semantic correctness.  Translation coverage remains a
candidate ledger until a human or independent semantic review approves it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


SCHEMA = "sermon-sentence-translation-map-poc-v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _finite_number(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def normalize_sentences(segments: list[dict], sample_id: str) -> tuple[list[dict], list[dict]]:
    sentences: list[dict] = []
    issues: list[dict] = []
    previous_end = 0.0
    next_word_id = 1
    for sentence_index, segment in enumerate(segments):
        text = str(segment.get("text", "")).strip()
        words = segment.get("wordTimes")
        if not text or not isinstance(words, list) or not words:
            issues.append({"type": "invalid_source_sentence", "sentenceIndex": sentence_index})
            continue
        normalized_words = []
        sentence_start = None
        sentence_end = None
        for word_index, word in enumerate(words):
            start, end = word.get("start"), word.get("end")
            if (not _finite_number(start) or not _finite_number(end) or start < 0 or end <= start
                    or start < previous_end - 1e-3):
                issues.append({
                    "type": "invalid_source_word_time",
                    "sentenceIndex": sentence_index,
                    "wordIndex": word_index,
                    "start": start,
                    "end": end,
                })
                continue
            previous_end = float(end)
            sentence_start = float(start) if sentence_start is None else sentence_start
            sentence_end = float(end)
            normalized_words.append({
                "wordId": next_word_id,
                "text": str(word.get("text", "")),
                "start": round(float(start), 6),
                "end": round(float(end), 6),
            })
            next_word_id += 1
        if not normalized_words:
            continue
        sentences.append({
            "sourceSentenceId": f"{sample_id}-s{sentence_index + 1:03d}",
            "sentenceIndex": sentence_index,
            "english": text,
            "sourceWordIds": [word["wordId"] for word in normalized_words],
            "localStart": round(sentence_start, 6),
            "localEnd": round(sentence_end, 6),
            "words": normalized_words,
            "timingQuality": segment.get("timingQuality"),
            "requiresOperatorReview": segment.get("requires_operator_review") is True,
        })
    return sentences, issues


def build_report(segments: list[dict], spec: dict, *, segments_path: Path, spec_path: Path) -> dict:
    sample_id = str(spec["sampleId"])
    sentences, issues = normalize_sentences(segments, sample_id)
    by_index = {sentence["sentenceIndex"]: sentence for sentence in sentences}
    all_indexes = set(by_index)

    excluded_indexes: set[int] = set()
    exclusions = []
    for exclusion in spec.get("excludedSentences", []):
        index = exclusion.get("sentenceIndex")
        if index not in all_indexes or index in excluded_indexes or not str(exclusion.get("reason", "")).strip():
            issues.append({"type": "invalid_sentence_exclusion", "value": exclusion})
            continue
        excluded_indexes.add(index)
        exclusions.append({
            "sourceSentenceId": by_index[index]["sourceSentenceId"],
            "reason": exclusion["reason"],
        })

    target_indexes = all_indexes - excluded_indexes
    assigned_indexes: list[int] = []
    groups = []
    sermon_start = float(spec["sermonSourceStartSeconds"])
    clip_start = float(spec["clipSourceStartSeconds"])
    tolerance = float(spec.get("fitToleranceSeconds", 0.05))
    for group_index, group in enumerate(spec.get("translationGroups", []), start=1):
        group_id = str(group.get("translationGroupId") or f"{sample_id}-g{group_index:03d}")
        source_indexes = group.get("sourceSentenceIndexes")
        chinese = str(group.get("chinese", "")).strip()
        if not isinstance(source_indexes, list) or not source_indexes or not chinese:
            issues.append({"type": "invalid_translation_group", "translationGroupId": group_id})
            continue
        if any(index not in target_indexes for index in source_indexes):
            issues.append({"type": "group_references_non_target_sentence", "translationGroupId": group_id})
            continue
        assigned_indexes.extend(source_indexes)
        source_sentences = [by_index[index] for index in source_indexes]

        coverage = group.get("coverage")
        covered_indexes: list[int] = []
        normalized_coverage = []
        if not isinstance(coverage, list):
            coverage = []
        for item in coverage:
            index = item.get("sourceSentenceIndex")
            target_text = str(item.get("targetText", ""))
            if index not in source_indexes or not target_text or target_text not in chinese:
                issues.append({
                    "type": "invalid_candidate_coverage_item",
                    "translationGroupId": group_id,
                    "value": item,
                })
                continue
            covered_indexes.append(index)
            normalized_coverage.append({
                "sourceSentenceId": by_index[index]["sourceSentenceId"],
                "targetText": target_text,
                "status": "candidate_requires_semantic_review",
            })
        if sorted(covered_indexes) != sorted(source_indexes) or len(set(covered_indexes)) != len(covered_indexes):
            issues.append({"type": "candidate_coverage_not_one_per_source_sentence", "translationGroupId": group_id})

        measured = group.get("measuredChineseAudio", {})
        cue_start, cue_end = measured.get("currentCueStart"), measured.get("currentCueEnd")
        cue_text = str(measured.get("text", ""))
        if (not _finite_number(cue_start) or not _finite_number(cue_end) or cue_end <= cue_start
                or cue_text != chinese):
            issues.append({"type": "invalid_measured_chinese_audio", "translationGroupId": group_id})
            measured_duration = None
        else:
            measured_duration = float(cue_end) - float(cue_start)

        local_start = min(sentence["localStart"] for sentence in source_sentences)
        local_end = max(sentence["localEnd"] for sentence in source_sentences)
        source_start = clip_start + local_start - sermon_start
        source_end = clip_start + local_end - sermon_start
        available = source_end - source_start
        planned_end = source_start + measured_duration if measured_duration is not None else None
        fits = planned_end is not None and planned_end <= source_end + tolerance
        if measured_duration is not None and not fits:
            issues.append({"type": "measured_chinese_audio_exceeds_source_window", "translationGroupId": group_id})

        groups.append({
            "translationGroupId": group_id,
            "mappingKind": f"{len(source_indexes)}:1",
            "sourceSentenceIds": [sentence["sourceSentenceId"] for sentence in source_sentences],
            "english": " ".join(sentence["english"] for sentence in source_sentences),
            "chinese": chinese,
            "candidateCoverage": normalized_coverage,
            "semanticReview": "pending",
            "sourceWindow": {
                "start": round(source_start, 6),
                "end": round(source_end, 6),
                "availableSeconds": round(available, 6),
            },
            "measuredChineseAudio": {
                "cueId": measured.get("cueId"),
                "currentStart": cue_start,
                "currentEnd": cue_end,
                "durationSeconds": round(measured_duration, 6) if measured_duration is not None else None,
            },
            "sentenceAnchoredPlan": {
                "start": round(source_start, 6),
                "end": round(planned_end, 6) if planned_end is not None else None,
                "fitMarginSeconds": round(source_end - planned_end, 6) if planned_end is not None else None,
                "fitsAtMeasuredNaturalRate": fits,
            },
            "observedCurrentPlacement": {
                "startsEarlyBySeconds": round(source_start - float(cue_start), 6) if _finite_number(cue_start) else None,
                "endsEarlyBySeconds": round(source_end - float(cue_end), 6) if _finite_number(cue_end) else None,
            },
        })

    if set(assigned_indexes) != target_indexes or len(set(assigned_indexes)) != len(assigned_indexes):
        issues.append({
            "type": "target_sentence_assignment_not_exact",
            "targetSentenceIndexes": sorted(target_indexes),
            "assignedSentenceIndexes": assigned_indexes,
        })

    structural_pass = not issues
    return {
        "schemaVersion": SCHEMA,
        "status": "structural_pass_semantic_review_pending" if structural_pass else "invalid_sentence_translation_map",
        "releaseEligible": False,
        "structuralPass": structural_pass,
        "semanticCoverageProven": False,
        "humanWordBoundaryGold": "not_supplied",
        "humanTranslationReview": "pending",
        "input": {
            "sampleId": sample_id,
            "sourceId": spec.get("sourceId"),
            "sourceSha256": spec.get("sourceSha256"),
            "sermonSourceStartSeconds": sermon_start,
            "clipSourceStartSeconds": clip_start,
            "publishedCatalogUrl": spec.get("publishedCatalogUrl"),
            "publishedCatalogSha256": spec.get("publishedCatalogSha256"),
            "mfaSegments": str(segments_path.resolve()),
            "mfaSegmentsSha256": sha256(segments_path),
            "mappingSpec": str(spec_path.resolve()),
            "mappingSpecSha256": sha256(spec_path),
        },
        "counts": {
            "sourceSentences": len(sentences),
            "targetSourceSentences": len(target_indexes),
            "excludedContextSentences": len(excluded_indexes),
            "translationGroups": len(groups),
            "sourceWords": sum(len(sentence["words"]) for sentence in sentences),
        },
        "sourceSentences": sentences,
        "excludedContext": exclusions,
        "translationGroups": groups,
        "issues": issues,
        "limitations": [
            "MFA word and sentence timings remain machine estimates pending listening review.",
            "Coverage rows prove explicit bookkeeping and exact target substrings, not semantic equivalence.",
            "The measured Chinese duration comes from the published cue; the sentence-anchored plan has not been rendered into a replacement track.",
            "This bounded clip does not prove full-sermon transcript or translation completeness.",
        ],
    }


def write_summary(path: Path, report: dict) -> None:
    def seconds(value: object) -> str:
        return f"{value:.2f}s" if _finite_number(value) else "n/a"

    lines = [
        f"# {report['input']['sampleId']} 句级英中对齐 POC",
        "",
        f"状态：`{report['status']}`；不能用于发布。",
        "",
        "| 中文组 | 英文句数 | 英文时间窗 | 已测中文时长 | 当前提前结束 | 重锚后余量 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group in report["translationGroups"]:
        window = group["sourceWindow"]
        audio = group["measuredChineseAudio"]
        observed = group["observedCurrentPlacement"]
        plan = group["sentenceAnchoredPlan"]
        lines.append(
            f"| {group['translationGroupId']} | {len(group['sourceSentenceIds'])} | "
            f"{seconds(window['availableSeconds'])} | {seconds(audio['durationSeconds'])} | "
            f"{seconds(observed['endsEarlyBySeconds'])} | {seconds(plan['fitMarginSeconds'])} |"
        )
    lines.extend([
        "",
        "这里的 coverage 只证明每个目标英文句都有显式中文落点；语义完整性仍待独立复核。",
        "MFA 仍是机器时间估计，且本 POC 尚未生成新的完整中文混音轨。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mfa-segments", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    segments = json.loads(args.mfa_segments.read_text(encoding="utf-8"))
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    if not isinstance(segments, list) or not isinstance(spec, dict):
        raise ValueError("Expected MFA segments list and mapping spec object")
    report = build_report(segments, spec, segments_path=args.mfa_segments, spec_path=args.spec)
    args.out.mkdir(parents=True, exist_ok=True)
    write_json(args.out / "report.json", report)
    write_summary(args.out / "review.md", report)
    print(args.out / "report.json")
    return 0 if report["structuralPass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
