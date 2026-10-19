#!/usr/bin/env python3
"""Bind Layer 2/3 fragment POC receipts and apply ASR review priority.

This finalizer is deliberately fail-closed. It never grants production or
human approval; it only makes the machine-screening evidence reproducible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LOCALES = ("zh-Hans", "ko", "es", "vi")


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def index_unique(items: list[dict[str, Any]], key: str, expected: set[str], label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        identity = item.get(key)
        if identity not in expected or identity in result:
            raise ValueError(f"Unexpected or duplicate {label}: {identity}")
        result[str(identity)] = item
    if set(result) != expected:
        raise ValueError(f"{label} coverage differs: expected {sorted(expected)}, got {sorted(result)}")
    return result


def screening_state(result: dict[str, Any], threshold: float, model: str) -> dict[str, Any]:
    similarity = float(result["similarity"])
    status = "pass" if similarity >= threshold else "requires_review"
    return {
        "status": status,
        "model": model,
        "coverage": 1,
    }


def finalize(
    layer2: Path,
    layer3: Path,
    screening_path: Path,
    *,
    write: bool,
    speaker_id: str = "eric_geiger",
) -> dict[str, Any]:
    expected = set(LOCALES)
    layer2_receipt_path = layer2 / "layer2-receipt.json"
    layer2_receipt = load_json(layer2_receipt_path)
    candidate_receipts = index_unique(layer2_receipt.get("candidates", []), "targetLocale", expected, "Layer 2 candidate")

    candidates: dict[str, dict[str, Any]] = {}
    for locale in LOCALES:
        candidate_path = layer2 / locale / "target-language-candidate.json"
        candidate = load_json(candidate_path)
        if candidate.get("targetLocale") != locale:
            raise ValueError(f"Layer 2 target locale mismatch: {locale}")
        candidate_hash = canonical_sha(candidate)
        receipt_item = candidate_receipts[locale]
        if not write and receipt_item.get("jsonSha256") != candidate_hash:
            raise ValueError(f"Stale Layer 2 receipt hash: {locale}")
        receipt_item.update({
            "path": f"{locale}/target-language-candidate.json",
            "jsonSha256": candidate_hash,
            "status": candidate.get("status"),
        })
        candidates[locale] = candidate

    screening = load_json(screening_path)
    if float(screening.get("coverage", 0)) != 1 or int(screening.get("trackCount", 0)) != len(LOCALES):
        raise ValueError("ASR screening must cover every locale")
    threshold = float(screening["reviewPriorityThreshold"])
    model = str(screening["model"])
    results = index_unique(screening.get("results", []), "targetLocale", expected, "ASR result")

    renderer_tracks: dict[str, dict[str, Any]] = {}
    for manifest_name in ("manifest.json", "vietnamese-manifest.json"):
        manifest = load_json(layer3 / manifest_name)
        for item in manifest.get("tracks", []):
            locale = item.get("targetLocale")
            if locale in renderer_tracks:
                raise ValueError(f"Duplicate renderer track: {locale}")
            renderer_tracks[str(locale)] = item
    if set(renderer_tracks) != expected:
        raise ValueError("Renderer manifest coverage differs")

    layer3_receipt_path = layer3 / "layer3-receipt.json"
    layer3_receipt = load_json(layer3_receipt_path)
    receipt_tracks = index_unique(layer3_receipt.get("tracks", []), "targetLocale", expected, "Layer 3 track")
    review_priority: list[str] = []

    for locale in LOCALES:
        candidate = candidates[locale]
        candidate_hash = canonical_sha(candidate)
        result = results[locale]
        renderer_track = renderer_tracks[locale]
        if result.get("speakerId") != speaker_id:
            raise ValueError(f"Unexpected speaker in ASR result: {locale}")
        if result.get("audioSha256") != renderer_track.get("audioSha256"):
            raise ValueError(f"ASR audio does not match renderer track: {locale}")
        expected_text_hash = hashlib.sha256(candidate["groups"][0]["targetText"].encode()).hexdigest()
        if result.get("expectedTextSha256") != expected_text_hash:
            raise ValueError(f"ASR expected text does not match Layer 2: {locale}")

        package_path = layer3 / locale / "target-language-audio-package.json"
        package = load_json(package_path)
        if package.get("targetLanguageCandidateJsonSha256") != candidate_hash:
            raise ValueError(f"Layer 3 is not bound to current Layer 2 candidate: {locale}")
        audio_path = layer3 / locale / package["track"]["path"]
        if file_sha(audio_path) != package["track"]["sha256"]:
            raise ValueError(f"Layer 3 MP3 hash mismatch: {locale}")

        state = screening_state(result, threshold, model)
        original_screening = package.get("machineScreening")
        issues = [item for item in package.get("issues", []) if item not in {
            "machine_asr_screening_not_run",
            "machine_asr_screening_below_threshold_requires_human_review",
        }]
        if state["status"] == "requires_review":
            issues.insert(0, "machine_asr_screening_below_threshold_requires_human_review")
            review_priority.append(locale)
        package["machineScreening"] = state
        package["issues"] = issues

        package_hash = canonical_sha(package)
        receipt_track = receipt_tracks[locale]
        expected_receipt = {
            "durationSeconds": package["units"][0]["durationSeconds"],
            "audioSha256": package["track"]["sha256"],
            "packageJsonSha256": package_hash,
            "humanListeningStatus": "pending",
            "machineScreeningStatus": state["status"],
            "similarity": float(result["similarity"]),
        }
        if not write:
            if original_screening != state:
                raise ValueError(f"Stale Layer 3 machine screening: {locale}")
            for key, value in expected_receipt.items():
                if receipt_track.get(key) != value:
                    raise ValueError(f"Stale Layer 3 receipt {key}: {locale}")
        else:
            atomic_json(package_path, package)
            receipt_track.update(expected_receipt)

    layer2_receipt["allMachineChecksPass"] = all(
        item.get("status") == "machine_review_pass_human_review_pending" for item in candidates.values()
    )
    expected_status = "machine_screened_with_review_priority" if review_priority else "machine_screened"
    expected_screening = {
        "status": "complete",
        "model": model,
        "coverage": 1,
        "reviewPriorityThreshold": threshold,
        "reviewPriorityLocales": review_priority,
        "receiptPath": screening_path.name,
        "receiptSha256": canonical_sha(screening),
        "humanApproval": False,
    }

    if not write:
        if layer3_receipt.get("status") != expected_status or layer3_receipt.get("machineScreening") != expected_screening:
            raise ValueError("Layer 3 screening receipt is stale")
    else:
        layer3_receipt.update({
            "status": expected_status,
            "productionEligible": False,
            "humanApproval": False,
            "machineScreening": expected_screening,
        })
        atomic_json(layer2_receipt_path, layer2_receipt)
        atomic_json(layer3_receipt_path, layer3_receipt)

    return {
        "layer2": str(layer2),
        "layer3": str(layer3),
        "mode": "write" if write else "check",
        "reviewPriorityLocales": review_priority,
        "productionEligible": False,
        "humanApproval": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer2", type=Path, required=True)
    parser.add_argument("--layer3", type=Path, required=True)
    parser.add_argument("--screening", type=Path)
    parser.add_argument("--speaker-id", default="eric_geiger")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    screening_path = args.screening or args.layer3 / "asr-screening.json"
    print(json.dumps(finalize(
        args.layer2,
        args.layer3,
        screening_path,
        write=not args.check_only,
        speaker_id=args.speaker_id,
    ), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
