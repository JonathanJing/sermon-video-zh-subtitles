#!/usr/bin/env python3
"""Independently verify whole-sermon split coverage, hashes, and leakage controls."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402
from scripts import build_sermon_split_manifest as split_builder  # noqa: E402
from scripts import verify_sermon_parallel_corpus_poc as poc_verify  # noqa: E402


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, observed: Any) -> None:
    checks.append({"name": name, "state": "pass" if passed else "fail", "observed": observed})


def hash_leakage(assignments: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for item in assignments:
        groups[str(item[field])].append(
            {"videoId": str(item["videoId"]), "split": str(item["split"])}
        )
    return [
        {"sha256": sha256, "items": items}
        for sha256, items in groups.items()
        if len({item["split"] for item in items}) > 1
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json"),
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("data/raw/mariners-sermon-captions-v1"),
    )
    parser.add_argument(
        "--poc-selection",
        type=Path,
        default=Path("data/derived/sermon-parallel-corpus-poc-v1/pilot-selection.json"),
    )
    parser.add_argument(
        "--pending-asr",
        type=Path,
        default=Path("data/reports/mariners-caption-extraction-v1/pending-asr.jsonl"),
    )
    parser.add_argument(
        "--metadata-overrides",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-splits-v1/metadata-overrides.json"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-splits-v1/final-verification.json"),
    )
    args = parser.parse_args()
    args.manifest = corpus.resolve_path(args.manifest)
    args.corpus_root = corpus.resolve_path(args.corpus_root)
    args.poc_selection = corpus.resolve_path(args.poc_selection)
    args.pending_asr = corpus.resolve_path(args.pending_asr)
    args.metadata_overrides = corpus.resolve_path(args.metadata_overrides)
    args.out = corpus.resolve_path(args.out)
    return args


def main() -> int:
    args = parse_args()
    manifest = corpus.read_json(args.manifest)
    assignments = manifest.get("assignments") or []
    checks: list[dict[str, Any]] = []
    ids = [str(item.get("videoId") or "") for item in assignments]
    raw_ids = {path.parent.name for path in args.corpus_root.glob("*/manifest.json")}
    add_check(
        checks,
        "exact_raw_asset_coverage",
        len(ids) == 180 and len(set(ids)) == 180 and set(ids) == raw_ids,
        {"assignments": len(ids), "unique": len(set(ids)), "rawAssets": len(raw_ids)},
    )
    split_counts = Counter(str(item.get("split") or "") for item in assignments)
    add_check(
        checks,
        "expected_split_counts",
        split_counts == {"train": 141, "dev": 18, "test": 18, "poc": 3},
        dict(sorted(split_counts.items())),
    )
    poc_selection = corpus.read_json(args.poc_selection)
    expected_poc = {str(item) for item in poc_selection.get("videoIds") or []}
    actual_poc = {str(item["videoId"]) for item in assignments if item["split"] == "poc"}
    add_check(checks, "frozen_poc_exact", actual_poc == expected_poc, sorted(actual_poc))

    pending_rows = corpus.read_jsonl(args.pending_asr)
    pending_ids = {
        str(item.get("videoId") or item.get("id") or "") for item in pending_rows
    }
    pending_overlap = sorted(set(ids) & pending_ids)
    add_check(checks, "pending_asr_excluded", not pending_overlap, pending_overlap)

    overrides = split_builder.load_metadata_overrides(args.metadata_overrides)
    assignment_by_id = {str(item["videoId"]): item for item in assignments}
    override_mismatches = [
        video_id
        for video_id, override in overrides.items()
        if video_id not in assignment_by_id
        or assignment_by_id[video_id].get("speaker") != override.get("speaker")
        or assignment_by_id[video_id].get("speakerProvenance", {}).get("type")
        != "verified_override"
        or not override.get("evidence")
    ]
    override_hash_ok = (
        manifest.get("strategy", {}).get("metadataOverridesSha256")
        == corpus.sha256_file(args.metadata_overrides)
    )
    add_check(
        checks,
        "verified_speaker_metadata_overrides",
        not override_mismatches and override_hash_ok,
        {"count": len(overrides), "mismatches": override_mismatches},
    )
    unknown_speakers = sorted(
        str(item["videoId"]) for item in assignments if item.get("speaker") == "unknown"
    )
    add_check(checks, "no_unknown_speakers", not unknown_speakers, unknown_speakers)

    hash_mismatches: list[dict[str, str]] = []
    for item in assignments:
        video_id = str(item["videoId"])
        root = args.corpus_root / video_id
        paths = {
            "sourceManifestSha256": root / "manifest.json",
            "sourceCuesSha256": root / "normalized" / "cues.youtube-auto.jsonl",
            "normalizedTranscriptSha256": root
            / "normalized"
            / "transcript.youtube-auto.txt",
        }
        for field, path in paths.items():
            if not path.exists() or item.get(field) != corpus.sha256_file(path):
                hash_mismatches.append({"videoId": video_id, "field": field})
    add_check(checks, "immutable_source_hashes", not hash_mismatches, hash_mismatches)

    transcript_leaks = hash_leakage(assignments, "normalizedTranscriptSha256")
    cue_leaks = hash_leakage(assignments, "sourceCuesSha256")
    add_check(checks, "no_transcript_hash_cross_split", not transcript_leaks, transcript_leaks)
    add_check(checks, "no_cue_hash_cross_split", not cue_leaks, cue_leaks)

    unseen_rows = [
        item
        for item in assignments
        if item["speaker"] == split_builder.UNSEEN_TEST_SPEAKER
    ]
    unseen_ok = bool(unseen_rows) and {item["split"] for item in unseen_rows} == {"test"}
    add_check(
        checks,
        "unseen_speaker_is_test_only",
        unseen_ok,
        {"speaker": split_builder.UNSEEN_TEST_SPEAKER, "count": len(unseen_rows)},
    )
    derivative_rule = (
        manifest.get("strategy", {}).get("unit") == "whole_sermon"
        and manifest.get("strategy", {}).get("derivativesMustInheritParentSplit") is True
        and manifest.get("strategy", {}).get("pocReservedFromUntouchedTest") is True
    )
    add_check(checks, "whole_sermon_derivative_rule", derivative_rule, manifest.get("strategy"))

    blocked = all(
        item.get("trainingEligibility") == "blocked"
        and item.get("rightsStatus") == "unconfirmed"
        for item in assignments
    )
    add_check(checks, "split_does_not_grant_training_rights", blocked, {"items": len(assignments)})
    secret_findings = poc_verify.scan_secret_markers(args.manifest.parent)
    add_check(checks, "no_secret_material", not secret_findings, secret_findings)

    failed = [item["name"] for item in checks if item["state"] == "fail"]
    report = {
        "schemaVersion": split_builder.SCHEMA_VERSION,
        "status": "pass_training_blocked" if not failed else "failed",
        "checks": checks,
        "failedChecks": failed,
        "countsBySplit": dict(sorted(split_counts.items())),
        "trainingEligibility": "blocked",
        "blockerMeaning": "Split integrity passed; rights, boundary, English, and Chinese gates remain unresolved.",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "verifiedAt": corpus.utc_now(),
    }
    corpus.write_json(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass_training_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
