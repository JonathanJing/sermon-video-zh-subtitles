#!/usr/bin/env python3
"""Freeze whole-sermon POC/train/dev/test assignments for the 180-caption corpus."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402


SCHEMA_VERSION = "sermon-whole-split-v1"
SPLIT_SEED = "mariners-sermon-whole-split-v1-20260830"
TEST_TARGET = 18
DEV_TARGET = 18
UNSEEN_TEST_SPEAKER = "Ed Stetzer"


def parse_speaker(title: str) -> str:
    base = str(title).rsplit("| Mariners Church", 1)[0].strip()
    if " - " in base:
        candidate = base.rsplit(" - ", 1)[1].strip()
        if candidate:
            return candidate
    if " : " in base:
        candidate = base.rsplit(" : ", 1)[1].strip()
        if candidate:
            return candidate
    return "unknown"


def rank_key(seed: str, video_id: str) -> str:
    return hashlib.sha256(f"{seed}|{video_id}".encode("utf-8")).hexdigest()


def select_stratified(
    items: list[dict[str, Any]], target: int, seed: str
) -> set[str]:
    if target < 0 or target > len(items):
        raise ValueError("Stratified target is outside the available item count")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item["speaker"])].append(item)
    for speaker in groups:
        groups[speaker].sort(key=lambda item: rank_key(seed, str(item["videoId"])))
    selected: list[dict[str, Any]] = []
    group_order = sorted(groups, key=lambda value: rank_key(seed, f"speaker:{value}"))
    for speaker in group_order:
        if len(selected) >= target:
            break
        selected.append(groups[speaker].pop(0))
    remaining = sorted(
        [item for values in groups.values() for item in values],
        key=lambda item: rank_key(seed, str(item["videoId"])),
    )
    selected.extend(remaining[: target - len(selected)])
    return {str(item["videoId"]) for item in selected}


def load_metadata_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = corpus.read_json(path)
    if data.get("status") != "verified_metadata_overrides":
        raise RuntimeError("Metadata overrides are not verified")
    items = data.get("items") or []
    by_id = {str(item.get("videoId") or ""): item for item in items}
    if not by_id or "" in by_id or len(by_id) != len(items):
        raise RuntimeError("Metadata overrides contain missing or duplicate video IDs")
    return by_id


def load_items(
    corpus_root: Path, metadata_overrides: dict[str, dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    metadata_overrides = metadata_overrides or {}
    items: list[dict[str, Any]] = []
    for manifest_path in sorted(corpus_root.glob("*/manifest.json")):
        manifest = corpus.read_json(manifest_path)
        asset = manifest["asset"]
        video_id = str(asset["id"])
        cues_path = manifest_path.parent / "normalized" / "cues.youtube-auto.jsonl"
        transcript_path = manifest_path.parent / "normalized" / "transcript.youtube-auto.txt"
        if not cues_path.exists() or not transcript_path.exists():
            raise RuntimeError(f"Incomplete raw caption asset: {video_id}")
        manifest_sha = corpus.sha256_file(manifest_path)
        cues_sha = corpus.sha256_file(cues_path)
        parsed_speaker = parse_speaker(str(asset["title"]))
        override = metadata_overrides.get(video_id)
        if override is not None:
            if override.get("sourceManifestSha256") != manifest_sha:
                raise RuntimeError(f"Metadata override manifest hash mismatch: {video_id}")
            if override.get("sourceCuesSha256") != cues_sha:
                raise RuntimeError(f"Metadata override cue hash mismatch: {video_id}")
            speaker = str(override.get("speaker") or "").strip()
            if not speaker or speaker == "unknown":
                raise RuntimeError(f"Metadata override has no speaker: {video_id}")
            speaker_provenance = {
                "type": "verified_override",
                "evidence": override.get("evidence"),
            }
        else:
            speaker = parsed_speaker
            speaker_provenance = {"type": "title_suffix"}
        items.append(
            {
                "videoId": video_id,
                "title": str(asset["title"]),
                "speaker": speaker,
                "speakerProvenance": speaker_provenance,
                "uploadDate": str(asset["uploadDate"]),
                "durationSeconds": int(asset["durationSeconds"]),
                "sourceManifestSha256": manifest_sha,
                "sourceCuesSha256": cues_sha,
                "normalizedTranscriptSha256": corpus.sha256_file(transcript_path),
                "sourceReviewStatus": manifest["caption"]["reviewState"],
                "captionKind": manifest["caption"]["kind"],
            }
        )
    return items


def assign_splits(
    items: list[dict[str, Any]], poc_ids: set[str]
) -> list[dict[str, Any]]:
    by_id = {str(item["videoId"]): item for item in items}
    if len(by_id) != len(items):
        raise RuntimeError("Duplicate video IDs in raw corpus")
    if not poc_ids <= set(by_id):
        raise RuntimeError("POC selection is not a subset of the raw corpus")
    unseen_ids = {
        str(item["videoId"])
        for item in items
        if item["speaker"] == UNSEEN_TEST_SPEAKER and item["videoId"] not in poc_ids
    }
    if not unseen_ids or len(unseen_ids) >= TEST_TARGET:
        raise RuntimeError("Unseen-speaker test group is empty or consumes the full test target")
    remaining_for_seen_test = [
        item
        for item in items
        if item["videoId"] not in poc_ids and item["videoId"] not in unseen_ids
    ]
    seen_test_ids = select_stratified(
        remaining_for_seen_test,
        TEST_TARGET - len(unseen_ids),
        f"{SPLIT_SEED}|test_seen",
    )
    test_ids = unseen_ids | seen_test_ids
    remaining_for_dev = [
        item
        for item in items
        if item["videoId"] not in poc_ids and item["videoId"] not in test_ids
    ]
    dev_ids = select_stratified(
        remaining_for_dev, DEV_TARGET, f"{SPLIT_SEED}|dev"
    )

    assigned: list[dict[str, Any]] = []
    for item in items:
        video_id = str(item["videoId"])
        if video_id in poc_ids:
            split = "poc"
            slices = ["poc_calibration", "reserved_from_untouched_test"]
            reason = "frozen representative POC; never eligible for untouched test"
        elif video_id in unseen_ids:
            split = "test"
            slices = ["test_unseen_speaker", "untouched_test"]
            reason = f"all {UNSEEN_TEST_SPEAKER} sermons held out from train/dev"
        elif video_id in seen_test_ids:
            split = "test"
            slices = ["test_seen_speaker_new_sermon", "untouched_test"]
            reason = "deterministic speaker-stratified whole-sermon holdout"
        elif video_id in dev_ids:
            split = "dev"
            slices = ["development"]
            reason = "deterministic speaker-stratified whole-sermon development set"
        else:
            split = "train"
            slices = ["training_candidate"]
            reason = "remaining whole sermon after frozen POC/dev/test assignment"
        assigned.append(
            {
                **item,
                "split": split,
                "evaluationSlices": slices,
                "splitReason": reason,
                "splitRankSha256": rank_key(SPLIT_SEED, video_id),
                "rightsStatus": "unconfirmed",
                "trainingEligibility": "blocked",
            }
        )
    return sorted(assigned, key=lambda item: (item["split"], item["uploadDate"], item["videoId"]))


def summarize(assignments: list[dict[str, Any]]) -> dict[str, Any]:
    split_counts = Counter(str(item["split"]) for item in assignments)
    split_durations = Counter()
    speaker_splits: dict[str, Counter[str]] = defaultdict(Counter)
    year_splits: dict[str, Counter[str]] = defaultdict(Counter)
    for item in assignments:
        split = str(item["split"])
        split_durations[split] += int(item["durationSeconds"])
        speaker_splits[str(item["speaker"])][split] += 1
        year_splits[str(item["uploadDate"])[:4]][split] += 1
    return {
        "countsBySplit": dict(sorted(split_counts.items())),
        "durationHoursBySplit": {
            key: round(value / 3600, 3) for key, value in sorted(split_durations.items())
        },
        "countsBySpeakerAndSplit": {
            speaker: dict(sorted(counts.items()))
            for speaker, counts in sorted(speaker_splits.items())
        },
        "countsByYearAndSplit": {
            year: dict(sorted(counts.items())) for year, counts in sorted(year_splits.items())
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--out-dir",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-splits-v1"),
    )
    parser.add_argument(
        "--metadata-overrides",
        type=Path,
        default=Path("data/reports/sermon-parallel-corpus-splits-v1/metadata-overrides.json"),
    )
    args = parser.parse_args()
    args.corpus_root = corpus.resolve_path(args.corpus_root)
    args.poc_selection = corpus.resolve_path(args.poc_selection)
    args.out_dir = corpus.resolve_path(args.out_dir)
    args.metadata_overrides = corpus.resolve_path(args.metadata_overrides)
    return args


def main() -> int:
    args = parse_args()
    selection = corpus.read_json(args.poc_selection)
    poc_ids = {str(item) for item in selection.get("videoIds") or []}
    if len(poc_ids) != 3:
        raise SystemExit("Expected exactly three frozen POC video IDs")
    metadata_overrides = load_metadata_overrides(args.metadata_overrides)
    assignments = assign_splits(load_items(args.corpus_root, metadata_overrides), poc_ids)
    unknown_speakers = [item["videoId"] for item in assignments if item["speaker"] == "unknown"]
    if unknown_speakers:
        raise RuntimeError(f"Unresolved speaker metadata: {unknown_speakers}")
    summary = summarize(assignments)
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "provisional_split_frozen_training_blocked",
        "strategy": {
            "unit": "whole_sermon",
            "seed": SPLIT_SEED,
            "testTarget": TEST_TARGET,
            "devTarget": DEV_TARGET,
            "unseenTestSpeaker": UNSEEN_TEST_SPEAKER,
            "pocReservedFromUntouchedTest": True,
            "derivativesMustInheritParentSplit": True,
            "metadataOverridesSha256": corpus.sha256_file(args.metadata_overrides),
        },
        "sourceCorpus": {
            "path": corpus.display_path(args.corpus_root),
            "expectedAssets": 180,
        },
        "summary": summary,
        "assignments": assignments,
        "trainingEligibility": "blocked",
        "blockingReasons": [
            "source_training_rights_unconfirmed",
            "sermon_boundaries_not_approved_for_full_corpus",
            "source_english_not_human_reviewed",
            "chinese_gold_not_available",
        ],
        "generatedAt": corpus.utc_now(),
    }
    if len(assignments) != 180:
        raise RuntimeError(f"Expected 180 raw caption assets, found {len(assignments)}")
    corpus.write_json(args.out_dir / "split-manifest.json", manifest)
    corpus.write_json(
        args.out_dir / "split-summary.json",
        {
            "schemaVersion": SCHEMA_VERSION,
            "status": manifest["status"],
            "strategy": manifest["strategy"],
            "summary": summary,
            "trainingEligibility": "blocked",
            "apiKeyMaterialIncluded": False,
            "secretResourceNamesIncluded": False,
            "generatedAt": manifest["generatedAt"],
        },
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
