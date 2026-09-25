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
from scripts import build_english_source_package as layer1


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
    summary_path: Path | None = None,
    approval_evidence_path: Path | None = None,
    review_path: Path | None = None,
    machine_judge_path: Path | None = None,
    source_id: str | None = None,
    source_url_hash: str | None = None,
    service_date: str | None = None,
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
            "englishSourceBuilderSha256": contract.sha256(Path(layer1.__file__).resolve()),
            "shadowRunnerSha256": contract.sha256(Path(__file__).resolve()),
        },
        "policy": {
            "unitPolicy": contract.UNIT_POLICY_V2,
            "maxUnitSeconds": max_unit_seconds,
            "minUnitSeconds": min_unit_seconds,
            "internalPauseSeconds": internal_pause_seconds,
            "wordDurationOutlierSeconds": word_duration_outlier_seconds,
        },
        "sourceContext": {
            "sourceId": source_id,
            "sourceUrlHash": source_url_hash,
            "serviceDate": service_date,
            "summarySha256": contract.sha256(summary_path.resolve()) if summary_path and summary_path.is_file() else None,
            "approvalEvidenceSha256": contract.sha256(approval_evidence_path.resolve()) if approval_evidence_path and approval_evidence_path.is_file() else None,
            "reviewSha256": contract.sha256(review_path.resolve()) if review_path and review_path.is_file() else None,
            "machineJudgeSha256": contract.sha256(machine_judge_path.resolve()) if machine_judge_path and machine_judge_path.is_file() else None,
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
    manifest_path = run_dir / "anchor-manifest.json"
    _write_immutable(manifest_path, manifest)
    source_package = layer1.build_package(
        source_path,
        manifest_path,
        summary_path=summary_path,
        approval_evidence_path=approval_evidence_path,
        review_path=review_path,
        machine_judge_path=machine_judge_path,
        source_id=source_id,
        source_url_hash=source_url_hash,
        service_date=service_date,
    )
    source_package_path = run_dir / "english-source-package.json"
    _write_immutable(source_package_path, source_package)
    if source_package["candidateTranslationEligible"]:
        status = "ready_for_model_translation"
        next_stage = "run_sentence_interpretation_models"
    elif manifest["issues"]:
        status = "waiting_anchor_review"
        next_stage = "operator_anchor_review"
    else:
        status = "waiting_machine_judge"
        next_stage = "run_english_source_machine_judge"
    receipt = {
        "schemaVersion": RECEIPT_SCHEMA,
        "layer": "shared_english_source_and_anchors",
        "interface": layer1.SCHEMA_VERSION,
        "status": status,
        "releaseEligible": False,
        "productionTranslationEligible": source_package["translationEligible"],
        "productionOutputChanged": False,
        "identity": identity,
        "artifacts": {
            "anchorManifest": {
                "path": str(manifest_path), "sha256": contract.sha256(manifest_path),
                "jsonSha256": contract.json_sha256(manifest),
            },
            "englishSourcePackage": {
                "path": str(source_package_path), "sha256": contract.sha256(source_package_path),
                "jsonSha256": contract.json_sha256(source_package),
            },
        },
        "counts": manifest.get("counts", {}),
        "anchorIssueCount": len(manifest["issues"]),
        "anchorIssueTypes": sorted({str(issue.get("type")) for issue in manifest["issues"]}),
        "nextStage": next_stage,
        "humanReview": "approved" if source_package["review"]["humanApproval"] else "pending",
    }
    receipt_path = run_dir / "receipt.json"
    receipt["artifacts"]["receipt"] = {"path": str(receipt_path)}
    _write_immutable(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mfa-segments", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--approval-evidence", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--machine-judge", type=Path)
    parser.add_argument("--source-id")
    parser.add_argument("--source-url-hash")
    parser.add_argument("--service-date")
    parser.add_argument("--max-unit-seconds", type=float, default=DEFAULT_MAX_UNIT_SECONDS)
    parser.add_argument("--min-unit-seconds", type=float, default=DEFAULT_MIN_UNIT_SECONDS)
    parser.add_argument("--internal-pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--word-duration-outlier-seconds", type=float, default=DEFAULT_WORD_OUTLIER_SECONDS)
    args = parser.parse_args()
    receipt = prepare_shadow(
        args.mfa_segments,
        args.out,
        summary_path=args.summary,
        approval_evidence_path=args.approval_evidence,
        review_path=args.review,
        machine_judge_path=args.machine_judge,
        source_id=args.source_id,
        source_url_hash=args.source_url_hash,
        service_date=args.service_date,
        max_unit_seconds=args.max_unit_seconds,
        min_unit_seconds=args.min_unit_seconds,
        internal_pause_seconds=args.internal_pause_seconds,
        word_duration_outlier_seconds=args.word_duration_outlier_seconds,
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "ready_for_model_translation" else 2


if __name__ == "__main__":
    raise SystemExit(main())
