#!/usr/bin/env python3
"""Prepare an immutable clause-stable anchor candidate for future production.

This deterministic stage consumes the frozen MFA-aligned English produced by
the weekly reading pipeline.  It never calls a model, renders audio, changes a
delivery artifact, or grants human approval.  A clean receipt may advance to
the separate translation/model stage; anchor issues stop that candidate chain.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sermon_sentence_interpretation as contract


RECEIPT_SCHEMA = "sermon-sentence-interpretation-shadow-v1"
DEFAULT_MAX_UNIT_SECONDS = 8.0
DEFAULT_MIN_UNIT_SECONDS = 1.5
DEFAULT_PAUSE_SECONDS = 0.35
DEFAULT_WORD_OUTLIER_SECONDS = 2.5


def _write_immutable(path: Path, payload: object) -> None:
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise ValueError(f"Existing sentence interpretation shadow artifact changed: {path}")
        return
    contract.write_json(path, payload)


def prepare_shadow(
    source_path: Path,
    out_root: Path,
    *,
    max_unit_seconds: float = DEFAULT_MAX_UNIT_SECONDS,
    min_unit_seconds: float = DEFAULT_MIN_UNIT_SECONDS,
    internal_pause_seconds: float = DEFAULT_PAUSE_SECONDS,
    word_duration_outlier_seconds: float = DEFAULT_WORD_OUTLIER_SECONDS,
) -> dict[str, Any]:
    source_path = source_path.resolve()
    out_root = out_root.resolve()
    if not source_path.is_file():
        raise ValueError("Frozen MFA-aligned English segments are missing")
    segments = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(segments, list) or not segments:
        raise ValueError("Frozen MFA-aligned English segments must be a nonempty JSON list")

    identity = {
        "schemaVersion": RECEIPT_SCHEMA,
        "source": {"path": str(source_path), "sha256": contract.sha256(source_path)},
        "implementation": {
            "anchorGeneratorSha256": contract.sha256(Path(contract.__file__).resolve()),
            "shadowRunnerSha256": contract.sha256(Path(__file__).resolve()),
        },
        "policy": {
            "unitPolicy": contract.UNIT_POLICY_V2,
            "maxUnitSeconds": max_unit_seconds,
            "minUnitSeconds": min_unit_seconds,
            "internalPauseSeconds": internal_pause_seconds,
            "wordDurationOutlierSeconds": word_duration_outlier_seconds,
        },
    }
    run_dir = out_root / contract.json_sha256(identity)
    manifest = contract.build_anchor_manifest(
        segments,
        source_path=source_path,
        unit_policy=contract.UNIT_POLICY_V2,
        max_unit_seconds=max_unit_seconds,
        min_unit_seconds=min_unit_seconds,
        internal_pause_seconds=internal_pause_seconds,
        word_duration_outlier_seconds=word_duration_outlier_seconds,
    )
    if not manifest.get("sourceUnits"):
        raise ValueError("Clause-stable shadow produced no source units; inspect MFA word timing input")
    request = contract.translation_packet(manifest)
    manifest_path = run_dir / "anchor-manifest.json"
    request_path = run_dir / "translation-request.json"
    _write_immutable(manifest_path, manifest)
    _write_immutable(request_path, request)
    status = "ready_for_model_translation" if manifest.get("sourceUnits") and not manifest["issues"] else "waiting_anchor_review"
    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "status": status,
        "releaseEligible": False,
        "productionOutputChanged": False,
        "identity": identity,
        "artifacts": {
            "anchorManifest": {
                "path": str(manifest_path), "sha256": contract.sha256(manifest_path),
                "jsonSha256": contract.json_sha256(manifest),
            },
            "translationRequest": {
                "path": str(request_path), "sha256": contract.sha256(request_path),
                "jsonSha256": contract.json_sha256(request),
            },
        },
        "counts": manifest.get("counts", {}),
        "anchorIssueCount": len(manifest["issues"]),
        "anchorIssueTypes": sorted({str(issue.get("type")) for issue in manifest["issues"]}),
        "nextStage": "run_sentence_interpretation_models" if status == "ready_for_model_translation" else "operator_anchor_review",
        "humanReview": "pending",
    }
    receipt_path = run_dir / "receipt.json"
    receipt["artifacts"]["receipt"] = {"path": str(receipt_path)}
    _write_immutable(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mfa-segments", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-unit-seconds", type=float, default=DEFAULT_MAX_UNIT_SECONDS)
    parser.add_argument("--min-unit-seconds", type=float, default=DEFAULT_MIN_UNIT_SECONDS)
    parser.add_argument("--internal-pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--word-duration-outlier-seconds", type=float, default=DEFAULT_WORD_OUTLIER_SECONDS)
    args = parser.parse_args()
    receipt = prepare_shadow(
        args.mfa_segments,
        args.out,
        max_unit_seconds=args.max_unit_seconds,
        min_unit_seconds=args.min_unit_seconds,
        internal_pause_seconds=args.internal_pause_seconds,
        word_duration_outlier_seconds=args.word_duration_outlier_seconds,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "ready_for_model_translation" else 2


if __name__ == "__main__":
    raise SystemExit(main())
