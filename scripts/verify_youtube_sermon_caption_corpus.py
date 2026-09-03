#!/usr/bin/env python3
"""Verify the extracted Mariners sermon-caption corpus and emit final reports.

This audit is deliberately stricter than the per-asset extraction gate. It checks
the inventory partition, exact asset set, every recorded SHA-256 receipt, JSONL
structure, normalized transcript reconstruction, content duplicates, extraction
batch receipts, and the absence of audio/video artifacts. It also emits the
inventory-only queue for sermons that require separately authorized ASR.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from extract_youtube_sermon_captions import (
    CAPTION_LANGUAGE,
    DEFAULT_INVENTORY,
    DEFAULT_OUTPUT_ROOT,
    SCHEMA_VERSION,
    atomic_write_json,
    atomic_write_text,
    eligible_candidates,
    load_jsonl,
    normalize_whitespace,
    sha256_file,
    verify_completed_asset,
)


DEFAULT_REPORT_DIR = Path("data/reports/mariners-caption-extraction-v1")
FINAL_REPORT_NAME = "final-verification.json"
PENDING_ASR_NAME = "pending-asr.jsonl"
README_NAME = "README.zh.md"
PENDING_ASR_SCHEMA = "mariners-pending-asr-v1"
MEDIA_SUFFIXES = {
    ".aac",
    ".aiff",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".oga",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}


def main() -> int:
    args = parse_args()
    rows = load_jsonl(args.inventory)
    report, pending_rows = verify_corpus(
        rows,
        inventory=args.inventory,
        corpus_root=args.corpus_root,
        report_dir=args.report_dir,
        expected_eligible=args.expected_eligible,
        expected_pending_asr=args.expected_pending_asr,
    )

    args.report_dir.mkdir(parents=True, exist_ok=True)
    pending_path = args.report_dir / PENDING_ASR_NAME
    final_path = args.report_dir / FINAL_REPORT_NAME
    readme_path = args.report_dir / README_NAME
    atomic_write_text(pending_path, render_pending_jsonl(pending_rows))
    report["artifacts"] = {
        "finalVerification": str(final_path),
        "pendingAsr": str(pending_path),
        "humanSummary": str(readme_path),
    }
    atomic_write_json(final_path, report)
    atomic_write_text(readme_path, render_readme(report))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--corpus-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--expected-eligible", type=int, default=180)
    parser.add_argument("--expected-pending-asr", type=int, default=10)
    args = parser.parse_args()
    if not args.inventory.is_file():
        parser.error(f"inventory does not exist: {args.inventory}")
    if not args.corpus_root.is_dir():
        parser.error(f"corpus root does not exist: {args.corpus_root}")
    if args.expected_eligible < 0 or args.expected_pending_asr < 0:
        parser.error("expected counts cannot be negative")
    return args


def verify_corpus(
    rows: list[dict[str, Any]],
    *,
    inventory: Path,
    corpus_root: Path,
    report_dir: Path,
    expected_eligible: int,
    expected_pending_asr: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    id_counts = Counter(str(row.get("id") or "") for row in rows)
    duplicate_inventory_ids = sorted(
        asset_id for asset_id, count in id_counts.items() if asset_id and count > 1
    )
    blank_inventory_ids = id_counts.get("", 0)
    if duplicate_inventory_ids:
        add_error(errors, "duplicate_inventory_ids", detail=duplicate_inventory_ids)
    if blank_inventory_ids:
        add_error(errors, "blank_inventory_ids", detail=blank_inventory_ids)

    unique_rows: dict[str, dict[str, Any]] = {}
    for row in rows:
        asset_id = str(row.get("id") or "")
        if asset_id and asset_id not in unique_rows:
            unique_rows[asset_id] = row

    eligible = eligible_candidates(list(unique_rows.values()))
    eligible_by_id = {str(row["id"]): row for row in eligible}
    pending_inventory = sorted(
        (
            row
            for asset_id, row in unique_rows.items()
            if asset_id not in eligible_by_id
            and row.get("englishCaptionStatus") == "none"
            and not (row.get("manualEnglishCaptionTracks") or [])
            and not (row.get("automaticEnglishCaptionTracks") or [])
        ),
        key=lambda row: (str(row.get("upload_date") or ""), str(row.get("id") or "")),
        reverse=True,
    )
    pending_ids = {str(row["id"]) for row in pending_inventory}
    unpartitioned_ids = sorted(set(unique_rows) - set(eligible_by_id) - pending_ids)

    if len(eligible) != expected_eligible:
        add_error(
            errors,
            "eligible_count_mismatch",
            expected=expected_eligible,
            observed=len(eligible),
        )
    if len(pending_inventory) != expected_pending_asr:
        add_error(
            errors,
            "pending_asr_count_mismatch",
            expected=expected_pending_asr,
            observed=len(pending_inventory),
        )
    if unpartitioned_ids:
        add_error(errors, "unpartitioned_inventory_ids", detail=unpartitioned_ids)

    actual_asset_ids = {
        path.name for path in corpus_root.iterdir() if path.is_dir() and not path.name.startswith(".")
    }
    missing_asset_ids = sorted(set(eligible_by_id) - actual_asset_ids)
    unexpected_asset_ids = sorted(actual_asset_ids - set(eligible_by_id))
    if missing_asset_ids:
        add_error(errors, "missing_asset_directories", detail=missing_asset_ids)
    if unexpected_asset_ids:
        add_error(errors, "unexpected_asset_directories", detail=unexpected_asset_ids)

    totals = {
        "sourceVttBytes": 0,
        "rawCueCount": 0,
        "normalizedCueCount": 0,
        "transcriptCharacters": 0,
        "transcriptBytes": 0,
        "durationSeconds": 0,
        "manifestFileReceipts": 0,
    }
    coverage_values: list[float] = []
    low_coverage: list[dict[str, Any]] = []
    transcript_hashes: defaultdict[str, list[str]] = defaultdict(list)
    source_vtt_hashes: defaultdict[str, list[str]] = defaultdict(list)
    verified_asset_ids: list[str] = []
    media_artifacts: list[str] = []
    unexpected_files: list[dict[str, Any]] = []

    for asset_id in sorted(set(eligible_by_id) & actual_asset_ids):
        result = verify_asset(
            asset_id,
            eligible_by_id[asset_id],
            corpus_root / asset_id,
            errors=errors,
        )
        if not result:
            continue
        verified_asset_ids.append(asset_id)
        totals["sourceVttBytes"] += result["sourceVttBytes"]
        totals["rawCueCount"] += result["rawCueCount"]
        totals["normalizedCueCount"] += result["normalizedCueCount"]
        totals["transcriptCharacters"] += result["transcriptCharacters"]
        totals["transcriptBytes"] += result["transcriptBytes"]
        totals["durationSeconds"] += result["durationSeconds"]
        totals["manifestFileReceipts"] += result["manifestFileReceipts"]
        coverage_values.append(result["timelineCoverage"])
        if result["timelineCoverage"] < 0.95:
            low_coverage.append(
                {
                    "assetId": asset_id,
                    "coverage": round(result["timelineCoverage"], 4),
                    "title": eligible_by_id[asset_id].get("title"),
                }
            )
        transcript_hashes[result["transcriptSha256"]].append(asset_id)
        source_vtt_hashes[result["sourceVttSha256"]].append(asset_id)
        media_artifacts.extend(result["mediaArtifacts"])
        if result["unexpectedFiles"]:
            unexpected_files.append(
                {"assetId": asset_id, "paths": result["unexpectedFiles"]}
            )

    if media_artifacts:
        add_error(errors, "media_artifacts_found", detail=sorted(media_artifacts))
    if unexpected_files:
        add_error(errors, "unexpected_asset_files", detail=unexpected_files)

    duplicate_transcripts = duplicate_hash_groups(transcript_hashes)
    duplicate_source_vtts = duplicate_hash_groups(source_vtt_hashes)
    if duplicate_transcripts:
        add_error(errors, "duplicate_normalized_transcripts", detail=duplicate_transcripts)
    if duplicate_source_vtts:
        warnings.append(
            {"code": "duplicate_source_vtts", "detail": duplicate_source_vtts}
        )
    if low_coverage:
        warnings.append({"code": "timeline_coverage_below_0_95", "detail": low_coverage})

    batch_audit = verify_batch_reports(
        report_dir,
        eligible_ids=set(eligible_by_id),
        errors=errors,
    )
    pending_rows = [pending_asr_entry(row, inventory=inventory) for row in pending_inventory]
    corpus_bytes = sum(
        path.stat().st_size for path in corpus_root.rglob("*") if path.is_file()
    )

    report = {
        "schemaVersion": "mariners-caption-corpus-verification-v1",
        "status": "pass" if not errors else "fail",
        "verifiedAt": utc_now(),
        "inventory": str(inventory),
        "corpusRoot": str(corpus_root),
        "scope": {
            "source": "Mariners Church public standalone main sermon VOD inventory",
            "captionLanguage": CAPTION_LANGUAGE,
            "captionKind": "youtube_automatic",
            "reviewState": "unreviewed_raw",
            "authenticatedSessionUsed": False,
            "audioOrVideoRequestedByExtractor": False,
            "sermonBoundaryApplied": False,
            "translationApplied": False,
        },
        "inventoryCounts": {
            "uniqueSermonVods": len(unique_rows),
            "eligibleAutomaticEnglish": len(eligible),
            "pendingAuthorizedAsr": len(pending_inventory),
            "unpartitioned": len(unpartitioned_ids),
            "duplicateIds": len(duplicate_inventory_ids),
        },
        "corpusCounts": {
            "assetDirectories": len(actual_asset_ids),
            "verifiedComplete": len(verified_asset_ids),
            "missingEligible": len(missing_asset_ids),
            "unexpectedAssets": len(unexpected_asset_ids),
            "mediaArtifacts": len(media_artifacts),
        },
        "totals": {
            **totals,
            "durationHours": round(totals["durationSeconds"] / 3600, 2),
            "corpusBytes": corpus_bytes,
        },
        "timelineCoverage": distribution(coverage_values),
        "lowCoverageBelow0_95": low_coverage,
        "deduplication": {
            "duplicateInventoryIds": duplicate_inventory_ids,
            "duplicateNormalizedTranscriptGroups": duplicate_transcripts,
            "duplicateSourceVttGroups": duplicate_source_vtts,
        },
        "batchAudit": batch_audit,
        "pendingAsrIds": [entry["asset"]["id"] for entry in pending_rows],
        "errors": errors,
        "warnings": warnings,
        "limitations": [
            "YouTube automatic captions are unreviewed source material, not Gold labels.",
            "The complete VOD timeline is preserved; announcements and other non-sermon segments may remain.",
            "The 10 pending items have metadata only; media download and ASR require separate authorization.",
        ],
    }
    return report, pending_rows


def verify_asset(
    asset_id: str,
    inventory_row: dict[str, Any],
    asset_dir: Path,
    *,
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    manifest_path = asset_dir / "manifest.json"
    expected_paths = {
        f"source/{asset_id}.{CAPTION_LANGUAGE}.vtt",
        "normalized/cues.youtube-auto-raw.jsonl",
        "normalized/cues.youtube-auto.jsonl",
        "normalized/transcript.youtube-auto.txt",
        "manifest.json",
    }
    actual_paths = {
        str(path.relative_to(asset_dir)) for path in asset_dir.rglob("*") if path.is_file()
    }
    unexpected = sorted(actual_paths - expected_paths)
    missing = sorted(expected_paths - actual_paths)
    media = sorted(path for path in actual_paths if Path(path).suffix.lower() in MEDIA_SUFFIXES)
    if missing:
        add_error(errors, "missing_asset_files", asset_id=asset_id, detail=missing)
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        add_error(errors, "invalid_manifest", asset_id=asset_id, detail=str(exc))
        return None

    start_error_count = len(errors)
    if not verify_completed_asset(asset_dir):
        add_error(errors, "manifest_receipt_verification_failed", asset_id=asset_id)
    if manifest.get("asset", {}).get("id") != asset_id:
        add_error(errors, "manifest_asset_id_mismatch", asset_id=asset_id)
    if manifest.get("asset", {}).get("url") != inventory_row.get("webpage_url"):
        add_error(errors, "manifest_source_url_mismatch", asset_id=asset_id)
    caption = manifest.get("caption") or {}
    provenance = manifest.get("provenance") or {}
    if caption.get("kind") != "youtube_automatic" or caption.get("language") != CAPTION_LANGUAGE:
        add_error(errors, "manifest_caption_identity_mismatch", asset_id=asset_id)
    if caption.get("reviewState") != "unreviewed_raw":
        add_error(errors, "manifest_review_state_mismatch", asset_id=asset_id)
    if any(check.get("state") != "pass" for check in manifest.get("qualityChecks") or []):
        add_error(errors, "manifest_quality_check_failed", asset_id=asset_id)
    if provenance.get("authenticatedSessionUsed") is not False:
        add_error(errors, "authenticated_session_claimed", asset_id=asset_id)
    if provenance.get("audioDownloaded") is not False or provenance.get("videoDownloaded") is not False:
        add_error(errors, "media_download_claimed", asset_id=asset_id)

    receipts = manifest.get("files") or []
    receipt_paths = {str(receipt.get("path") or "") for receipt in receipts}
    expected_receipts = expected_paths - {"manifest.json"}
    if receipt_paths != expected_receipts:
        add_error(
            errors,
            "manifest_receipt_set_mismatch",
            asset_id=asset_id,
            detail={"expected": sorted(expected_receipts), "observed": sorted(receipt_paths)},
        )
    for receipt in receipts:
        path = asset_dir / str(receipt.get("path") or "")
        if path.is_file() and receipt.get("bytes") != path.stat().st_size:
            add_error(errors, "manifest_byte_count_mismatch", asset_id=asset_id, detail=str(path))

    vtt_path = asset_dir / f"source/{asset_id}.{CAPTION_LANGUAGE}.vtt"
    raw_path = asset_dir / "normalized/cues.youtube-auto-raw.jsonl"
    normalized_path = asset_dir / "normalized/cues.youtube-auto.jsonl"
    transcript_path = asset_dir / "normalized/transcript.youtube-auto.txt"
    if missing:
        return None
    if not vtt_path.read_text(encoding="utf-8", errors="replace").lstrip("\ufeff").startswith("WEBVTT"):
        add_error(errors, "invalid_source_vtt_header", asset_id=asset_id)

    raw_rows = read_jsonl_strict(raw_path, asset_id=asset_id, errors=errors)
    normalized_rows = read_jsonl_strict(normalized_path, asset_id=asset_id, errors=errors)
    transcript = transcript_path.read_text(encoding="utf-8")
    validate_cues(raw_rows, asset_id=asset_id, expected_origin="youtube_automatic_raw", errors=errors)
    validate_cues(
        normalized_rows,
        asset_id=asset_id,
        expected_origin="youtube_automatic_increment",
        errors=errors,
    )

    if len(raw_rows) != caption.get("rawCueCount"):
        add_error(errors, "raw_cue_count_mismatch", asset_id=asset_id)
    if len(normalized_rows) != caption.get("normalizedCueCount"):
        add_error(errors, "normalized_cue_count_mismatch", asset_id=asset_id)
    if len(transcript.rstrip("\n")) != caption.get("transcriptCharacters"):
        add_error(errors, "transcript_character_count_mismatch", asset_id=asset_id)

    reconstructed = normalize_whitespace(" ".join(str(row.get("text") or "") for row in normalized_rows))
    if reconstructed != transcript.strip():
        add_error(errors, "transcript_reconstruction_mismatch", asset_id=asset_id)
    adjacent_duplicates = [
        index
        for index, (left, right) in enumerate(zip(normalized_rows, normalized_rows[1:]), 1)
        if left.get("text") == right.get("text")
    ]
    if adjacent_duplicates:
        add_error(
            errors,
            "adjacent_normalized_duplicates",
            asset_id=asset_id,
            detail=adjacent_duplicates[:20],
        )
    if re.search(r"WEBVTT|<c(?:\.|>)|</c>|align:start|position:\d", transcript):
        add_error(errors, "subtitle_markup_in_transcript", asset_id=asset_id)

    duration_seconds = int(inventory_row.get("duration") or 0)
    timeline_end_ms = int(caption.get("timelineEndMs") or 0)
    coverage = timeline_end_ms / (duration_seconds * 1000) if duration_seconds else 0.0
    if len(errors) != start_error_count:
        return None
    return {
        "sourceVttBytes": vtt_path.stat().st_size,
        "rawCueCount": len(raw_rows),
        "normalizedCueCount": len(normalized_rows),
        "transcriptCharacters": len(transcript.rstrip("\n")),
        "transcriptBytes": transcript_path.stat().st_size,
        "durationSeconds": duration_seconds,
        "manifestFileReceipts": len(receipts),
        "timelineCoverage": coverage,
        "transcriptSha256": sha256_file(transcript_path),
        "sourceVttSha256": sha256_file(vtt_path),
        "mediaArtifacts": [str(asset_dir / path) for path in media],
        "unexpectedFiles": unexpected,
    }


def read_jsonl_strict(
    path: Path,
    *,
    asset_id: str,
    errors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            add_error(
                errors,
                "invalid_cue_jsonl",
                asset_id=asset_id,
                detail={"path": str(path), "line": line_number, "error": str(exc)},
            )
            continue
        if not isinstance(row, dict):
            add_error(
                errors,
                "non_object_cue_jsonl",
                asset_id=asset_id,
                detail={"path": str(path), "line": line_number},
            )
            continue
        rows.append(row)
    return rows


def validate_cues(
    rows: list[dict[str, Any]],
    *,
    asset_id: str,
    expected_origin: str,
    errors: list[dict[str, Any]],
) -> None:
    cue_ids = [str(row.get("cueId") or "") for row in rows]
    if len(cue_ids) != len(set(cue_ids)):
        add_error(errors, "duplicate_cue_ids", asset_id=asset_id, detail=expected_origin)
    for index, row in enumerate(rows, 1):
        if row.get("schemaVersion") != SCHEMA_VERSION:
            add_error(errors, "cue_schema_mismatch", asset_id=asset_id, detail=index)
            break
        if row.get("origin") != expected_origin or row.get("reviewState") != "unreviewed_raw":
            add_error(errors, "cue_provenance_mismatch", asset_id=asset_id, detail=index)
            break
        start_ms = row.get("startMs")
        end_ms = row.get("endMs")
        if not isinstance(start_ms, int) or not isinstance(end_ms, int) or end_ms <= start_ms:
            add_error(errors, "invalid_cue_timing", asset_id=asset_id, detail=index)
            break
        if not normalize_whitespace(str(row.get("text") or "")):
            add_error(errors, "empty_cue_text", asset_id=asset_id, detail=index)
            break
    if any(
        int(left.get("startMs") or 0) > int(right.get("startMs") or 0)
        for left, right in zip(rows, rows[1:])
    ):
        add_error(errors, "non_monotonic_cue_timeline", asset_id=asset_id, detail=expected_origin)


def verify_batch_reports(
    report_dir: Path,
    *,
    eligible_ids: set[str],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = sorted(report_dir.glob("batch-*.json"))
    completed_ids: list[str] = []
    failure_count = 0
    no_op_count = 0
    invalid_reports: list[str] = []
    for path in paths:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            invalid_reports.append(str(path))
            continue
        completed_ids.extend(str(asset_id) for asset_id in report.get("completedIds") or [])
        failure_count += len(report.get("failed") or [])
        no_op_count += int(report.get("status") == "no_op")
        if report.get("mediaDownloaded") is not False:
            add_error(errors, "batch_report_media_claim", detail=str(path))
        if report.get("authenticatedSessionUsed") is not False:
            add_error(errors, "batch_report_auth_claim", detail=str(path))
    if invalid_reports:
        add_error(errors, "invalid_batch_reports", detail=invalid_reports)
    completed_counts = Counter(completed_ids)
    duplicate_completed = sorted(
        asset_id for asset_id, count in completed_counts.items() if count > 1
    )
    completed_set = set(completed_ids)
    if failure_count:
        add_error(errors, "batch_failures_present", observed=failure_count)
    if duplicate_completed:
        add_error(errors, "duplicate_batch_completion_ids", detail=duplicate_completed)
    if completed_set != eligible_ids:
        add_error(
            errors,
            "batch_completion_set_mismatch",
            detail={
                "missing": sorted(eligible_ids - completed_set),
                "unexpected": sorted(completed_set - eligible_ids),
            },
        )
    return {
        "reportCount": len(paths),
        "successfulCompletionEvents": len(completed_ids),
        "uniqueCompletedIds": len(completed_set),
        "duplicateCompletionIds": duplicate_completed,
        "failureCount": failure_count,
        "noOpCount": no_op_count,
    }


def pending_asr_entry(row: dict[str, Any], *, inventory: Path) -> dict[str, Any]:
    return {
        "schemaVersion": PENDING_ASR_SCHEMA,
        "status": "pending_authorization",
        "reason": "youtube_has_no_manual_or_automatic_english_caption",
        "requiredNextStage": "authorized_media_download_then_asr",
        "mediaDownloaded": False,
        "asset": {
            "id": row.get("id"),
            "title": row.get("title"),
            "url": row.get("webpage_url"),
            "uploadDate": row.get("upload_date"),
            "durationSeconds": row.get("duration"),
            "classification": row.get("classification"),
        },
        "captionObservation": {
            "observedAt": row.get("observedAt"),
            "englishCaptionStatus": row.get("englishCaptionStatus"),
            "manualEnglishTracks": row.get("manualEnglishCaptionTracks") or [],
            "automaticEnglishTracks": row.get("automaticEnglishCaptionTracks") or [],
            "inventory": str(inventory),
        },
    }


def render_pending_jsonl(rows: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + (
        "\n" if rows else ""
    )


def duplicate_hash_groups(groups: dict[str, list[str]]) -> list[dict[str, Any]]:
    return [
        {"sha256": digest, "assetIds": sorted(asset_ids)}
        for digest, asset_ids in sorted(groups.items())
        if len(asset_ids) > 1
    ]


def distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "minimum": None, "p05": None, "median": None, "p95": None, "maximum": None}
    ordered = sorted(values)
    return {
        "count": len(ordered),
        "minimum": round(ordered[0], 4),
        "p05": round(percentile(ordered, 0.05), 4),
        "median": round(statistics.median(ordered), 4),
        "p95": round(percentile(ordered, 0.95), 4),
        "maximum": round(ordered[-1], 4),
    }


def percentile(ordered: list[float], quantile: float) -> float:
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def add_error(
    errors: list[dict[str, Any]],
    code: str,
    *,
    asset_id: str | None = None,
    expected: Any = None,
    observed: Any = None,
    detail: Any = None,
) -> None:
    item: dict[str, Any] = {"code": code}
    if asset_id is not None:
        item["assetId"] = asset_id
    if expected is not None:
        item["expected"] = expected
    if observed is not None:
        item["observed"] = observed
    if detail is not None:
        item["detail"] = detail
    errors.append(item)


def render_readme(report: dict[str, Any]) -> str:
    counts = report["inventoryCounts"]
    corpus = report["corpusCounts"]
    totals = report["totals"]
    coverage = report["timelineCoverage"]
    batch = report["batchAudit"]
    status_cn = "通过" if report["status"] == "pass" else "未通过"
    return f"""# Mariners 主证道英文字幕提取结果

- 最终审计：**{status_cn}**
- 主证道 VOD 库存：{counts['uniqueSermonVods']} 条
- YouTube 自动英文字幕已验证：{corpus['verifiedComplete']}/{counts['eligibleAutomaticEnglish']} 条
- 无英文字幕、待单独授权 ASR：{counts['pendingAuthorizedAsr']} 条
- 下载阶段失败：{batch['failureCount']} 条
- 音视频文件：{corpus['mediaArtifacts']} 个
- 规范化时间轴：{totals['normalizedCueCount']:,} 条 cue
- 规范化文本：{totals['transcriptCharacters']:,} 字符
- 对应视频总时长：{totals['durationHours']:.2f} 小时
- 语料目录大小：{totals['corpusBytes'] / 1024 / 1024:.1f} MiB
- 时间轴覆盖率：最小 {coverage['minimum']:.4f}，中位数 {coverage['median']:.4f}

## 数据边界

这些文本来自 YouTube 自动英文字幕，状态统一为 `unreviewed_raw`，不能直接当作 Gold 训练标签。当前保留完整 VOD 时间轴，开场通知、主持和结束段落可能仍在；本阶段没有切证道边界，也没有翻译。

10 条待 ASR 项目仅保存公开视频元数据。本阶段没有下载其音频或视频；后续需用户另行授权媒体下载和 ASR。

## 主要产物

- `final-verification.json`：全量集合、哈希、结构、去重和批次收据审计
- `pending-asr.jsonl`：10 条无英文字幕视频的待授权队列
- `data/raw/mariners-sermon-captions-v1/<video-id>/source/*.vtt`：原始 `en-orig` VTT
- `data/raw/mariners-sermon-captions-v1/<video-id>/normalized/*.jsonl`：原始及去滚动重复时间轴
- `data/raw/mariners-sermon-captions-v1/<video-id>/normalized/*.txt`：规范化英文文本

生成时间：{report['verifiedAt']}
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
