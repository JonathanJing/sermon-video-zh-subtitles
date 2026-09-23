#!/usr/bin/env python3
"""Freeze and validate a single-locale Layer 2 policy without granting approval."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

try:
    from scripts import series_terminology
except ImportError:  # Direct execution via ``python scripts/...``.
    import series_terminology


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/sermon-target-language-policy-v1.schema.json"
SERIES_TABLE = ROOT / "docs/series-terminology.zh.md"
COMPONENTS = ("translator", "reviewer", "terminology", "scripture", "languageReview", "formatting", "batching")


def canonical_sha256(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _schema_errors(policy: dict[str, Any]) -> list[str]:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return [error.message for error in Draft202012Validator(schema).iter_errors(policy)]


def validate_policy(policy: dict[str, Any], *, series_table: Path = SERIES_TABLE) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise ValueError("Target-Language Policy must be a JSON object")
    errors = _schema_errors(policy)
    if errors:
        raise ValueError(f"Invalid Target-Language Policy: {errors[0]}")
    for component in COMPONENTS:
        if policy["componentSha256"][component] != canonical_sha256(policy[component]):
            raise ValueError(f"Target-Language Policy component hash changed: {component}")
    if policy["terminology"]["seriesTableSha256"] != file_sha256(series_table):
        raise ValueError("Series terminology source changed; freeze a new policy")
    catalog = series_terminology.parse_table(series_table.read_text(encoding="utf-8"))
    expected_series = {row["english"]: row["chinese"] for row in catalog}
    series_names = policy["terminology"]["seriesNames"]
    if {entry["source"] for entry in series_names} != set(expected_series):
        raise ValueError("Target-Language Policy series terminology coverage changed")
    if policy["targetLocale"] == "zh-Hans" and any(
        entry["target"] != expected_series[entry["source"]] for entry in series_names
    ):
        raise ValueError("Chinese series terminology differs from established project names")
    for kind in ("seriesNames", "properNames"):
        terms = policy["terminology"][kind]
        names = [entry["source"] for entry in terms]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate {kind} source term")
        if any(entry["reviewStatus"] != "pending" and not entry["target"] for entry in terms):
            raise ValueError(f"Reviewed {kind} term lacks target text")
    if policy["translator"]["promptVersion"] == policy["reviewer"]["promptVersion"]:
        raise ValueError("Translator and reviewer need independent prompt versions")
    scripture = policy["scripture"]
    unresolved = []
    if not scripture["editionId"] or scripture["citationUseStatus"] == "pending" or scripture["quoteCheckPolicy"] == "pending":
        unresolved.append("scripture_policy_pending")
    if policy["languageReview"]["implementationStatus"] != "verified":
        unresolved.append("language_review_plugin_pending")
    if any(term["reviewStatus"] == "pending" for kind in ("seriesNames", "properNames") for term in policy["terminology"][kind]):
        unresolved.append("terminology_review_pending")
    return {
        "translationPolicySha256": canonical_sha256(policy),
        "languageReviewPolicySha256": canonical_sha256(policy["languageReview"]),
        "componentSha256": policy["componentSha256"],
        "productionPolicyReady": not unresolved,
        "unresolved": unresolved,
    }


def freeze_policy(draft: dict[str, Any], *, series_table: Path = SERIES_TABLE) -> dict[str, Any]:
    if not isinstance(draft, dict) or "componentSha256" in draft:
        raise ValueError("Freeze requires an unresolved policy draft without component hashes")
    policy = dict(draft)
    policy["componentSha256"] = {name: canonical_sha256(policy[name]) for name in COMPONENTS}
    validate_policy(policy, series_table=series_table)
    return policy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "inspect"))
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--series-terminology", type=Path, default=SERIES_TABLE)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if args.command == "freeze":
        if not args.out or args.out.exists():
            parser.error("freeze requires a new --out path")
        resolved = freeze_policy(policy, series_table=args.series_terminology)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(resolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        policy = resolved
    print(json.dumps(validate_policy(policy, series_table=args.series_terminology), ensure_ascii=False))


if __name__ == "__main__":
    main()
