#!/usr/bin/env python3
"""Verify lineage, coverage, safety boundaries, and resumable POC artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402


SECRET_MARKERS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"projects/[^/\s]+/secrets/[^/\s]+"),
    re.compile(r"Authorization:\s*Bearer", re.IGNORECASE),
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def scan_secret_markers(root: Path) -> list[str]:
    findings: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix not in {".json", ".jsonl", ".md"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(pattern.search(text) for pattern in SECRET_MARKERS):
            findings.append(corpus.display_path(path))
    return findings


def verify_sermon(sermon_dir: Path, corpus_root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    required = [
        "source-receipt.json",
        "boundary-candidate.json",
        "segments.en.jsonl",
        "segments.zh.first.jsonl",
        "segments.zh.edit1.jsonl",
        "segments.zh.final.jsonl",
        "glossary.candidate.json",
        "scripture-alignments.json",
        "human-review-queue.jsonl",
        "run-report.json",
    ]
    missing = [name for name in required if not (sermon_dir / name).exists()]
    add_check(checks, "required_artifacts", not missing, {"missing": missing})
    if missing:
        return {"videoId": sermon_dir.name, "status": "failed", "checks": checks}

    receipt = corpus.read_json(sermon_dir / "source-receipt.json")
    boundary = corpus.read_json(sermon_dir / "boundary-candidate.json")
    source = corpus.read_jsonl(sermon_dir / "segments.en.jsonl")
    first = corpus.read_jsonl(sermon_dir / "segments.zh.first.jsonl")
    edit1 = corpus.read_jsonl(sermon_dir / "segments.zh.edit1.jsonl")
    final = corpus.read_jsonl(sermon_dir / "segments.zh.final.jsonl")
    queue = corpus.read_jsonl(sermon_dir / "human-review-queue.jsonl")
    report = corpus.read_json(sermon_dir / "run-report.json")
    source_cues = corpus_root / sermon_dir.name / "normalized" / "cues.youtube-auto.jsonl"
    source_manifest = corpus_root / sermon_dir.name / "manifest.json"
    hashes_match = (
        source_cues.exists()
        and source_manifest.exists()
        and receipt["sourceCues"]["sha256"] == corpus.sha256_file(source_cues)
        and receipt["sourceManifest"]["sha256"] == corpus.sha256_file(source_manifest)
    )
    add_check(checks, "immutable_source_hashes", hashes_match, {"match": hashes_match})

    counts = [len(source), len(first), len(edit1), len(final), len(queue)]
    add_check(checks, "stage_coverage", len(set(counts)) == 1 and counts[0] > 0, counts)
    ids = [[str(item.get("id") or item.get("segmentId") or "") for item in rows] for rows in (source, first, edit1, final, queue)]
    add_check(checks, "exact_id_coverage", all(item == ids[0] for item in ids[1:]), [len(item) for item in ids])
    add_check(checks, "unique_segment_ids", len(set(ids[0])) == len(ids[0]), len(ids[0]))

    timeline_ok = all(
        int(item["endMs"]) > int(item["startMs"])
        and (index == 0 or int(item["startMs"]) >= int(source[index - 1]["startMs"]))
        for index, item in enumerate(source)
    )
    add_check(checks, "monotonic_timeline", timeline_ok, {"segments": len(source)})
    model_candidate = (
        boundary.get("status") == "model_candidate_requires_human_review"
        and boundary.get("requiresHumanReview") is True
        and boundary.get("approvedByHuman") is False
    )
    human_approved = (
        boundary.get("status") == "approved_human_boundary"
        and boundary.get("requiresHumanReview") is False
        and boundary.get("approvedByHuman") is True
        and (boundary.get("approval") or {}).get("audioReviewCompleted") is True
        and bool((boundary.get("approval") or {}).get("decisionSha256"))
    )
    boundary_ok = (
        boundary.get("contentScope") == "sermon_only"
        and (model_candidate or human_approved)
        and int(boundary["endMs"]) > int(boundary["startMs"])
    )
    add_check(checks, "boundary_status_honest", boundary_ok, boundary.get("status"))
    binding = boundary.get("sourceBindings") or {}
    approval_binding_ok = (
        not human_approved
        or (
            binding.get("sourceCuesSha256") == receipt["sourceCues"]["sha256"]
            and binding.get("sourceManifestSha256")
            == receipt["sourceManifest"]["sha256"]
            and bool(boundary.get("approvalArtifactSha256"))
        )
    )
    add_check(
        checks,
        "boundary_approval_binding",
        approval_binding_ok,
        "human_approved" if human_approved else "not_applicable",
    )

    chinese_ok = all(
        corpus.compact_text(item.get("zh")) and corpus.CHINESE_RE.search(str(item.get("zh") or ""))
        for item in final
    )
    add_check(checks, "nonempty_chinese", chinese_ok, {"segments": len(final)})
    markdown_ids = [item["id"] for item in final if corpus.MARKDOWN_RE.search(str(item.get("zh") or ""))]
    add_check(checks, "no_markdown_in_chinese", not markdown_ids, markdown_ids)

    blocked = all(
        item.get("trainingEligibility") == "blocked"
        and item.get("qualityTier") == "isolated_reference"
        and item.get("reviewStatus") == "model_reviewed_requires_human"
        and (item.get("teacher") or {}).get("provenance") == "gpt_isolated_nontrainable"
        for item in final
    )
    add_check(checks, "nontrainable_provenance", blocked, {"segments": len(final)})
    boundary_blocker_consistent = all(
        (
            "sermon_boundary_not_human_approved" not in (item.get("trainingBlockers") or [])
            if human_approved
            else "sermon_boundary_not_human_approved" in (item.get("trainingBlockers") or [])
        )
        for item in final
    )
    add_check(
        checks,
        "boundary_training_blocker_consistent",
        boundary_blocker_consistent,
        {"humanApproved": human_approved},
    )
    all_pending = all(item.get("reviewStatus") == "pending_human" for item in queue)
    add_check(checks, "human_review_queue_complete", all_pending, {"queued": len(queue)})
    report_consistent = (
        int(report.get("segmentCount") or -1) == len(final)
        and report.get("trainingEligibility") == "blocked"
        and report.get("apiKeyMaterialIncluded") is False
        and report.get("secretResourceNamesIncluded") is False
    )
    add_check(checks, "run_report_consistent", report_consistent, report.get("status"))
    failures = [check["name"] for check in checks if check["state"] == "fail"]
    return {
        "videoId": sermon_dir.name,
        "status": "pass" if not failures else "failed",
        "segmentCount": len(final),
        "highPriorityReviewCount": sum(1 for item in queue if item.get("priority") == "high"),
        "checks": checks,
        "failedChecks": failures,
    }


def verify(args: argparse.Namespace) -> dict[str, Any]:
    selection_path = args.out_root / "pilot-selection.json"
    selection = corpus.read_json(selection_path)
    video_ids = [str(item) for item in selection.get("videoIds") or []]
    checks: list[dict[str, Any]] = []
    add_check(checks, "three_unique_pilots", len(video_ids) == 3 and len(set(video_ids)) == 3, video_ids)
    add_check(
        checks,
        "poc_split_not_test",
        selection.get("split") == "poc" and selection.get("reservedFromFutureTest") is True,
        {"split": selection.get("split"), "reservedFromFutureTest": selection.get("reservedFromFutureTest")},
    )
    sermons = [verify_sermon(args.out_root / video_id, args.corpus_root) for video_id in video_ids]
    secret_findings = scan_secret_markers(args.out_root)
    add_check(checks, "no_secret_material", not secret_findings, secret_findings)
    unique_all_ids: list[str] = []
    for video_id in video_ids:
        final_path = args.out_root / video_id / "segments.zh.final.jsonl"
        if final_path.exists():
            unique_all_ids.extend(str(item["id"]) for item in corpus.read_jsonl(final_path))
    add_check(checks, "cross_sermon_unique_ids", len(unique_all_ids) == len(set(unique_all_ids)), len(unique_all_ids))
    failed = [check["name"] for check in checks if check["state"] == "fail"]
    failed_sermons = [item["videoId"] for item in sermons if item["status"] != "pass"]
    status = "pass_with_training_blockers" if not failed and not failed_sermons else "failed"
    return {
        "schemaVersion": 1,
        "status": status,
        "verifiedAt": utc_now(),
        "selection": selection,
        "checks": checks,
        "sermons": sermons,
        "failedChecks": failed,
        "failedSermons": failed_sermons,
        "totals": {
            "sermons": len(sermons),
            "segments": sum(int(item.get("segmentCount") or 0) for item in sermons),
            "highPriorityReview": sum(int(item.get("highPriorityReviewCount") or 0) for item in sermons),
        },
        "trainingEligibility": "blocked",
        "blockerMeaning": "Verification passed for POC integrity, not for Silver/Gold or student training.",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-corpus-poc-v1"),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("data/raw/mariners-sermon-captions-v1"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-poc/final-verification.json"),
    )
    args = parser.parse_args()
    args.out_root = corpus.resolve_path(args.out_root)
    args.corpus_root = corpus.resolve_path(args.corpus_root)
    args.out = corpus.resolve_path(args.out)
    return args


def main() -> int:
    args = parse_args()
    report = verify(args)
    corpus.write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass_with_training_blockers" else 2


if __name__ == "__main__":
    raise SystemExit(main())
