#!/usr/bin/env python3
"""Build a compact human calibration queue from model-reviewed ASR runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NON_SPEECH_CUE_RE = re.compile(
    r"[\[(][^\])]*(?:music|applause|laughter|cheering|silence)[^\])]*[\])]",
    re.IGNORECASE,
)
STANDALONE_NON_SPEECH_CUE_RE = re.compile(
    r"^\s*(?:(?:music|applause|laughter|cheering|silence)[\s.,!?;:/&+_-]*)+$",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def words(text: str) -> list[str]:
    without_cues = NON_SPEECH_CUE_RE.sub(" ", text)
    if STANDALONE_NON_SPEECH_CUE_RE.fullmatch(without_cues):
        return []
    return re.findall(r"[a-z0-9']+", without_cues.casefold())


def contains_term(text: str, term: str) -> bool:
    source, target = words(text), words(term)
    return bool(target) and any(
        source[index : index + len(target)] == target
        for index in range(len(source) - len(target) + 1)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--leaderboard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--random-per-source", type=int, default=3)
    args = parser.parse_args()

    manifest_path = (REPO_ROOT / args.manifest).resolve()
    leaderboard_path = (REPO_ROOT / args.leaderboard).resolve()
    manifest = json.loads(manifest_path.read_text())
    leaderboard = json.loads(leaderboard_path.read_text())
    if leaderboard["manifestSha256"] != sha256_file(manifest_path):
        raise SystemExit("Leaderboard and manifest do not match")

    prediction_sets: dict[str, dict[str, dict]] = {}
    for result in leaderboard["results"]:
        prediction_path = REPO_ROOT / result["runDirectory"] / "predictions.jsonl"
        if sha256_file(prediction_path) != result["predictionsSha256"]:
            raise SystemExit(f"Prediction hash mismatch: {prediction_path}")
        prediction_sets[result["modelId"]] = {
            row["id"]: row
            for row in (json.loads(line) for line in prediction_path.read_text().splitlines())
        }

    reasons: dict[str, set[str]] = {}
    for item in manifest["items"]:
        item_id = item["id"]
        if not item["speechExpected"]:
            reasons.setdefault(item_id, set()).add("silence_or_non_speech_reference")
        for model_id, predictions in prediction_sets.items():
            prediction = predictions[item_id]
            if not prediction["outputValid"]:
                reasons.setdefault(item_id, set()).add(f"invalid_output:{model_id}")
            for term in item.get("criticalTerms", []):
                if not contains_term(prediction["transcript"], term):
                    reasons.setdefault(item_id, set()).add(
                        f"critical_term_miss:{model_id}:{term}"
                    )

    by_source: dict[str, list[dict]] = {}
    for item in manifest["items"]:
        if item["id"] not in reasons:
            by_source.setdefault(item["sermonId"], []).append(item)
    for source_items in by_source.values():
        ranked = sorted(
            source_items,
            key=lambda item: hashlib.sha256(item["id"].encode()).hexdigest(),
        )
        for item in ranked[: args.random_per_source]:
            reasons.setdefault(item["id"], set()).add("deterministic_stratified_random")

    items_by_id = {item["id"]: item for item in manifest["items"]}
    output_items = []
    for item_id in sorted(reasons):
        source = items_by_id[item_id]
        output_items.append(
            {
                "id": item_id,
                "sermonId": source["sermonId"],
                "audioPath": source["audioPath"],
                "audioSha256": source["audioSha256"],
                "durationSeconds": source["durationSeconds"],
                "modelReviewedReferenceText": source["referenceText"],
                "criticalTerms": source.get("criticalTerms", []),
                "selectionReasons": sorted(reasons[item_id]),
                "modelTranscripts": {
                    model_id: predictions[item_id]["transcript"]
                    for model_id, predictions in prediction_sets.items()
                },
                "humanReferenceText": None,
                "humanAudioClass": None,
                "reviewer": None,
                "reviewStatus": "needs_human_listening",
            }
        )

    payload = {
        "schemaVersion": "local-asr-human-calibration-queue-v1",
        "status": "needs_human_listening",
        "purpose": "calibrate_model_reviewed_reference_before_production_selection",
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "manifestSha256": sha256_file(manifest_path),
        "leaderboard": str(leaderboard_path.relative_to(REPO_ROOT)),
        "leaderboardSha256": sha256_file(leaderboard_path),
        "selectionPolicy": {
            "includeAllSilenceOrNonSpeechReferences": True,
            "includeAllInvalidOutputs": True,
            "includeAllCriticalTermMisses": True,
            "deterministicRandomPerSource": args.random_per_source,
        },
        "itemCount": len(output_items),
        "durationMinutes": round(sum(item["durationSeconds"] for item in output_items) / 60, 3),
        "items": output_items,
    }
    output_path = (REPO_ROOT / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"itemCount": payload["itemCount"], "durationMinutes": payload["durationMinutes"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
