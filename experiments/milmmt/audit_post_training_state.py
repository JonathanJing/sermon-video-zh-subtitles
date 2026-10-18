#!/usr/bin/env python3
"""Audit fixed MiLMMT corpus artifacts without opening untouched bilingual text.

This is an evidence report, not a model-quality or human-approval gate. It reads
existing train/dev examples, the v4 split/source hashes, and teacher reports.
No v4 translation, reference, cache, or review-packet content is loaded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "milmmt-post-training-state-audit-v1"
DATASET_ROOT = Path("data/derived/sermon-dataset-v2")
CANARY_PATH = Path("data/derived/sermon-dataset-v2-canary/canary.jsonl")
V3_ROOT = Path("data/derived/milmmt-llamafactory-sermon-v3-corrective")
PROMOTED_PATH = Path("data/derived/milmmt-corrective-v2-promoted/promoted-real.jsonl")
PRE_FILTER_PATH = Path("data/derived/milmmt-corrective-v2-split/train.canonical.jsonl")
SPLIT_PATH = Path("data/benchmarks/milmmt-sermon-v4/corpus-split.json")
V4_SOURCE_ROOT = Path("data/derived/sermon-caption-source-reconciled-v1")
V4_REFERENCE_ROOT = Path("data/derived/milmmt-v4-untouched-final-reference")
FINAL_REPORT_STATUS = "hybrid_teacher_pipeline_completed_sol_high_text_review_training_blocked"
AUDIO_SOL_STATUS = "selective_audio_audit_completed_sol_high"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized(text: str) -> str:
    """Match the exporter's whitespace normalization; keep punctuation and case."""
    return " ".join(str(text).split())


def file_evidence(path: Path) -> dict:
    hasher = hashlib.sha256()
    line_count = 0
    size = 0
    with path.open("rb") as handle:
        for line in handle:
            hasher.update(line)
            size += len(line)
            line_count += bool(line.strip())
    return {"sha256": hasher.hexdigest(), "bytes": size, "nonemptyLineCount": line_count}


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def distribution(values: list[float]) -> dict:
    if not values:
        return {"count": 0}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "p10": ordered[math.floor(.1 * (len(ordered) - 1))],
        "p50": statistics.median(ordered),
        "p90": ordered[math.floor(.9 * (len(ordered) - 1))],
        "p95": ordered[math.floor(.95 * (len(ordered) - 1))],
        "max": ordered[-1],
    }


def corpus_summary(rows: list[dict]) -> dict:
    durations = [(r["endMs"] - r["startMs"]) / 1000 for r in rows
                 if isinstance(r.get("startMs"), (int, float)) and isinstance(r.get("endMs"), (int, float))]
    words = [len(str(r.get("en", "")).split()) for r in rows]
    return {
        "rows": len(rows),
        "sermons": len({r["sermonId"] for r in rows if r.get("sermonId")}),
        "uniqueIds": len({r.get("id") for r in rows}),
        "englishWords": distribution(words),
        "durationSeconds": distribution(durations),
        "missingDurationRows": len(rows) - len(durations),
        "durationBins": {
            "le8": sum(x <= 8 for x in durations),
            "gt8Le20": sum(8 < x <= 20 for x in durations),
            "gt20Le40": sum(20 < x <= 40 for x in durations),
            "gt40": sum(x > 40 for x in durations),
        },
        "englishWordBins": {
            "le15": sum(x <= 15 for x in words),
            "gt15Le40": sum(15 < x <= 40 for x in words),
            "gt40Le100": sum(40 < x <= 100 for x in words),
            "gt100": sum(x > 100 for x in words),
        },
        "incompleteTerminalPunctuationRows": sum(
            not str(r.get("en", "")).rstrip().endswith((".", "?", "!", '"', "'")) for r in rows
        ),
        "reviewStatus": dict(Counter(str(r.get("reviewStatus")) for r in rows)),
        "audioAuditStatus": dict(Counter(str(r.get("audioAuditStatus")) for r in rows)),
        "qualityTier": dict(Counter(str(r.get("qualityTier")) for r in rows)),
        "teacherClaimsHumanApprovalRows": sum(
            r.get("teacherPipeline", {}).get("humanApprovalClaimed") is True for r in rows
        ),
        "humanApprovalVerified": False,
        "note": "Review metadata and terminal punctuation are diagnostics, not semantic or human-review proof.",
    }


def supervision_groups(rows: list[dict], source_key: str, target_key: str) -> dict:
    groups: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        source_hash = digest(normalized(row.get(source_key, "")))
        groups[source_hash][digest(normalized(row.get(target_key, "")))] += 1
    conflicts = [
        {"sourceSha256": source, "targets": [
            {"sha256": target, "exposures": count} for target, count in sorted(targets.items())
        ]}
        for source, targets in sorted(groups.items()) if len(targets) > 1
    ]
    return {
        "rowCount": len(rows),
        "uniqueSources": len(groups),
        "extraSourceExposures": sum(sum(x.values()) - 1 for x in groups.values()),
        "sourceGroupsWithMultipleTargets": len(conflicts),
        "conflictingSupervision": conflicts,
        "matchingPolicy": "case_and_punctuation_preserving_whitespace_normalized",
    }


def corrective_conflicts(base: list[dict], promoted: list[dict], pre_filter: list[dict] | None = None) -> dict:
    base_by_source: dict[str, list[dict]] = defaultdict(list)
    for row in base:
        base_by_source[normalized(row["en"])].append(row)
    matched = 0
    conflicts = []
    for row in promoted:
        if not str(row.get("trainingEligibility", "")).startswith("eligible"):
            continue
        matches = base_by_source.get(normalized(row["sourceEn"]), [])
        matched += bool(matches)
        differing = [r for r in matches if normalized(r["zh"]) != normalized(row["v2ReviewedTargetZh"])]
        if differing:
            conflicts.append({
                "correctionId": row.get("id"),
                "sourceSegmentId": row.get("sourceSegmentId"),
                "sourceSermonId": row.get("sourceSermonId"),
                "sourceSha256": digest(normalized(row["sourceEn"])),
                "baseIds": sorted(str(r.get("id")) for r in differing),
                "baseTargetSha256": sorted({digest(normalized(r["zh"])) for r in differing}),
                "correctedTargetSha256": digest(normalized(row["v2ReviewedTargetZh"])),
            })
    base_ids = {r["id"] for r in base}
    prior = {r["id"]: r for r in (pre_filter or [])}
    unadmitted = []
    for row in promoted:
        source_id = row.get("sourceSegmentId")
        if source_id not in base_ids:
            previous = prior.get(source_id, {})
            unadmitted.append({"sourceSegmentId": source_id, "sourceSermonId": row.get("sourceSermonId"),
                               "preFilterRowFound": bool(previous), "severity": previous.get("severity"),
                               "audioAuditStatus": previous.get("audioAuditStatus"),
                               "sourceQualityDisposition": previous.get("sourceQualityDisposition")})
    return {"promotedRows": len(promoted), "matchingBaseRows": matched,
            "conflictingCorrectionRows": len(conflicts), "conflicts": conflicts,
            "promotedRowsAbsentFromAdmittedBase": len(unadmitted), "unadmittedSources": unadmitted}


def safe_report(root: Path, path: Path, missing: list[str]) -> dict | None:
    if not path.is_file():
        missing.append(str(path.relative_to(root)))
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def audit_v4(root: Path, train_ids: set[str], dev_ids: set[str]) -> dict:
    split = json.loads((root / SPLIT_PATH).read_text(encoding="utf-8"))
    missing: list[str] = []
    items = []
    for sermon in split["sermons"]:
        video_id = str(sermon["videoId"])
        if not video_id or Path(video_id).name != video_id or video_id in {".", ".."}:
            raise ValueError("invalid video ID in frozen split")
        source_path = root / V4_SOURCE_ROOT / video_id / "segments.en.jsonl"
        item = {"videoId": video_id, "split": sermon["split"], "expectedSegments": sermon["segmentCount"],
                "sourcePathMatchesFixedPath": sermon.get("sourcePath") in {
                    str(V4_SOURCE_ROOT / video_id / "segments.en.jsonl"), str(source_path)},
                "overlapsExistingTrain": video_id in train_ids, "overlapsExistingDev": video_id in dev_ids}
        if source_path.is_file():
            source = file_evidence(source_path)
            item["source"] = source
            item["sourceHashMatchesFrozen"] = source["sha256"] == sermon["sourceSha256"]
            item["sourceRowCountMatchesFrozen"] = source["nonemptyLineCount"] == sermon["segmentCount"]
        else:
            missing.append(str(source_path.relative_to(root)))
            item["sourceHashMatchesFrozen"] = False
            item["sourceRowCountMatchesFrozen"] = False
        if sermon["split"] == "untouched_final_v4":
            report_dir = root / V4_REFERENCE_ROOT / video_id
            teacher = safe_report(root, report_dir / "run-report.json", missing)
            if teacher is not None:
                selected_ids = teacher.get("selectedSegmentIds", [])
                item["teacher"] = {
                    "status": teacher.get("status"),
                    "sourceHashMatchesFrozen": teacher.get("sourceSha256") == sermon["sourceSha256"],
                    "selectedSegments": len(selected_ids),
                    "selectedIdsUnique": len(set(selected_ids)) == len(selected_ids),
                    "textReviewCompleted": teacher.get("status") == FINAL_REPORT_STATUS
                        and teacher.get("segmentCount") == sermon["segmentCount"]
                        and len(set(selected_ids)) == sermon["segmentCount"]
                        and teacher.get("sourceSha256") == sermon["sourceSha256"],
                    "humanApprovalClaimed": teacher.get("humanApprovalClaimed"),
                }
            audio = safe_report(root, report_dir / "selective-audio-audit-report.json", missing)
            if audio is not None:
                reviewer = audio.get("audioEvidenceReviewer", {})
                item["audio"] = {
                    "status": audio.get("status"),
                    "selectedSegments": audio.get("selectedSegmentCount"),
                    "totalSegments": audio.get("totalSegmentCount"),
                    "videoIdMatchesFrozen": audio.get("videoId") == video_id,
                    "totalSegmentsMatchFrozen": audio.get("totalSegmentCount") == sermon["segmentCount"],
                    "decisionCounts": audio.get("decisionCounts", {}),
                    "reviewerModel": reviewer.get("model"),
                    "reviewerReasoningEffort": reviewer.get("reasoningEffort"),
                    "solHighCompleted": audio.get("status") == AUDIO_SOL_STATUS
                        and audio.get("videoId") == video_id
                        and audio.get("totalSegmentCount") == sermon["segmentCount"]
                        and reviewer.get("model") == "gpt-5.6-sol"
                        and reviewer.get("reasoningEffort") == "high",
                    "humanApprovalClaimed": audio.get("humanApprovalClaimed"),
                }
        items.append(item)
    finals = [x for x in items if x["split"] == "untouched_final_v4"]
    return {
        "splitManifest": str(SPLIT_PATH), "splitManifestSha256": file_evidence(root / SPLIT_PATH)["sha256"],
        "sermons": items,
        "candidateCount": len(items),
        "uniqueVideoIds": len({x["videoId"] for x in items}),
        "countMatchesManifest": len(items) == split.get("candidateCount"),
        "finalSermonCount": len(finals),
        "trainAdditionSermonCount": sum(x["split"] == "v4_train_addition" for x in items),
        "allSourceHashesMatch": bool(items) and all(x["sourceHashMatchesFrozen"] for x in items),
        "allSourceRowCountsMatch": bool(items) and all(x["sourceRowCountMatchesFrozen"] for x in items),
        "existingTrainDevOverlap": [x["videoId"] for x in items if x["overlapsExistingTrain"] or x["overlapsExistingDev"]],
        "textReviewCompletedSermons": sum(x.get("teacher", {}).get("textReviewCompleted", False) for x in finals),
        "solHighAudioCompletedSermons": sum(x.get("audio", {}).get("solHighCompleted", False) for x in finals),
        "missingReportsOrSources": missing,
        "untouchedBilingualArtifactsOpened": False,
        "scope": "Final reference and prediction content remain sealed; metadata alone cannot prove final reference quality.",
    }


def audit(root: Path) -> dict:
    root = root.resolve()
    train = read_rows(root / DATASET_ROOT / "train.jsonl")
    dev = read_rows(root / DATASET_ROOT / "dev.jsonl")
    canary = read_rows(root / CANARY_PATH)
    promoted = read_rows(root / PROMOTED_PATH)
    pre_filter = read_rows(root / PRE_FILTER_PATH)
    v3 = read_rows(root / V3_ROOT / "train.jsonl")
    train_sermons = {r["sermonId"] for r in train}
    dev_sermons = {r["sermonId"] for r in dev}
    canonical_paths = [DATASET_ROOT / "train.jsonl", DATASET_ROOT / "dev.jsonl", CANARY_PATH,
                       PROMOTED_PATH, PRE_FILTER_PATH, V3_ROOT / "train.jsonl"]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "evidence_collected_not_a_promotion_gate",
        "authorizationGates": {
            "sourceTrainingRights": "requires_separate_authorization_receipt",
            "providerOutputForExternalStudent": "blocked_pending_explicit_authorization",
            "externalStudentTrainingEligibility": "blocked",
        },
        "artifacts": {str(path): file_evidence(root / path) for path in canonical_paths},
        "datasetV2": {
            "train": corpus_summary(train), "dev": corpus_summary(dev),
            "trainDevSermonOverlap": sorted(train_sermons & dev_sermons),
            "trainDevIdOverlap": sorted({r["id"] for r in train} & {r["id"] for r in dev}),
            "trainDevExactEnglishOverlap": len({normalized(r["en"]) for r in train} & {normalized(r["en"]) for r in dev}),
            "trainSupervision": supervision_groups(train, "en", "zh"),
        },
        "canary": corpus_summary(canary),
        "v3": {"supervision": supervision_groups(v3, "input", "output"),
               "correctionOverlay": corrective_conflicts(train, promoted, pre_filter)},
        "v4": audit_v4(root, train_sermons, dev_sermons),
        "limits": [
            "Does not certify human Gold, theological correctness, source-target alignment, or training completion.",
            "Exact-source checks do not rule out paraphrase, shared scripture, cross-video, or series-level leakage.",
            "Different targets for identical input require adjudication; target difference alone is not proof either target is incorrect.",
            "Existing artifacts are inspected without modification; no paid calls, model inference, or training are performed.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.root)
    output = args.output.resolve()
    data_root = (args.root.resolve() / "data").resolve()
    # Reports may be written under data/reports; immutable corpora are read-only.
    if output.is_relative_to(data_root) and not output.is_relative_to(data_root / "reports"):
        raise SystemExit("Output must not overwrite source, derived, or benchmark corpus artifacts")
    if output.exists():
        raise SystemExit("Output already exists; use a new audit receipt path")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output),
                      "trainRows": report["datasetV2"]["train"]["rows"],
                      "v3ConflictingSources": report["v3"]["supervision"]["sourceGroupsWithMultipleTargets"],
                      "v4SourceHashesMatch": report["v4"]["allSourceHashesMatch"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
