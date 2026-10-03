"""Validate source-bound user authority to skip Layer 2 content review.

This never marks text human approved or makes a candidate release eligible.
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from scripts import target_language_policy as policy_tools
except ImportError:
    import target_language_policy as policy_tools

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/sermon-podcast-layer2-user-review-waiver-v1.schema.json"
ALLOWED_UNRESOLVED = {
    "terminology_review_pending",
    "proper_name_approval_evidence_pending",
}


def validate(waiver: dict[str, Any], source: dict[str, Any], anchor: dict[str, Any],
             policy: dict[str, Any], readiness: dict[str, Any]) -> str:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(waiver))
    if errors:
        raise ValueError(f"Invalid podcast review waiver: {errors[0].message}")
    expected = {
        "targetLocale": policy["targetLocale"],
        "englishSourcePackageJsonSha256": policy_tools.canonical_sha256(source),
        "anchorManifestSha256": policy_tools.canonical_sha256(anchor),
        "translationPolicySha256": readiness["translationPolicySha256"],
    }
    for key, value in expected.items():
        if waiver.get(key) != value:
            raise ValueError(f"Podcast review waiver binding differs: {key}")
    unresolved = set(readiness.get("unresolved", []))
    if not unresolved or not unresolved <= ALLOWED_UNRESOLVED:
        raise ValueError("Waiver cannot bypass unresolved scripture or language-plugin gates")
    return policy_tools.canonical_sha256(waiver)


def validate_candidate_binding(waiver: dict[str, Any], candidate: dict[str, Any],
                               policy: dict[str, Any], readiness: dict[str, Any]) -> str:
    """Bind the same waiver to a machine-reviewed candidate without approving it."""
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(waiver))
    if errors:
        raise ValueError(f"Invalid podcast review waiver: {errors[0].message}")
    expected = {
        "targetLocale": candidate.get("targetLocale"),
        "englishSourcePackageJsonSha256": candidate.get("englishSourcePackageJsonSha256"),
        "anchorManifestSha256": candidate.get("anchorManifestSha256"),
        "translationPolicySha256": readiness["translationPolicySha256"],
    }
    for key, value in expected.items():
        if waiver.get(key) != value or (key == "targetLocale"
                                        and policy.get("targetLocale") != value):
            raise ValueError(f"Podcast review waiver candidate binding differs: {key}")
    if candidate.get("releaseEligible") is not False \
            or candidate.get("humanReview", {}).get("translation") != "pending":
        raise ValueError("Content waiver requires a pending, release-ineligible candidate")
    unresolved = set(readiness.get("unresolved", []))
    if not unresolved or not unresolved <= ALLOWED_UNRESOLVED:
        raise ValueError("Waiver cannot bypass unresolved scripture or language-plugin gates")
    return policy_tools.canonical_sha256(waiver)
