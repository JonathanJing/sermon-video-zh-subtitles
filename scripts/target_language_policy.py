#!/usr/bin/env python3
"""Freeze and validate a single-locale Layer 2 policy without granting approval."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
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
POLICY_V2 = "sermon-target-language-policy-v2"


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
    version = policy.get("schemaVersion")
    if version not in {"sermon-target-language-policy-v1", POLICY_V2}:
        raise ValueError("Unsupported Target-Language Policy version")
    schema_path = (ROOT / "schemas/sermon-target-language-policy-v2.schema.json"
                   if version == POLICY_V2 else SCHEMA_PATH)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return [error.message for error in Draft202012Validator(schema).iter_errors(policy)]


def validate_policy(policy: dict[str, Any], *, series_table: Path = SERIES_TABLE) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise ValueError("Target-Language Policy must be a JSON object")
    errors = _schema_errors(policy)
    if errors:
        raise ValueError(f"Invalid Target-Language Policy: {errors[0]}")
    components = COMPONENTS + (("sourceScope",) if policy["schemaVersion"] == POLICY_V2 else ())
    for component in components:
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
        if any(entry["reviewStatus"] != "pending"
               and (not isinstance(entry["target"], str) or not entry["target"].strip())
               for entry in terms):
            raise ValueError(f"Reviewed {kind} term lacks target text")
    if policy["translator"]["promptVersion"] == policy["reviewer"]["promptVersion"]:
        raise ValueError("Translator and reviewer need independent prompt versions")
    scripture = policy["scripture"]
    unresolved = []
    if not scripture["editionId"] or scripture["citationUseStatus"] == "pending" or scripture["quoteCheckPolicy"] == "pending":
        unresolved.append("scripture_policy_pending")
    if policy["languageReview"]["implementationStatus"] != "verified":
        unresolved.append("language_review_plugin_pending")
    if policy["schemaVersion"] != POLICY_V2:
        unresolved.append("plugin_implementation_hash_unbound_migrate_to_v2")
    if policy["schemaVersion"] == POLICY_V2:
        scope = policy["sourceScope"]
        series_sources = {term["source"] for term in series_names}
        proper_sources = {term["source"] for term in policy["terminology"]["properNames"]}
        if (not set(scope["usedSeriesNames"]) <= series_sources
                or not set(scope["usedProperNames"]) <= proper_sources):
            raise ValueError("Source-scoped terminology references undeclared terms")
        used = set(scope["usedSeriesNames"]) | set(scope["usedProperNames"])
        evidence = scope["termApprovalEvidence"]
        if len({entry["source"] for entry in evidence}) != len(evidence):
            raise ValueError("Duplicate source-scoped term approval evidence")
        for entry in evidence:
            term = next((row for kind in ("seriesNames", "properNames")
                         for row in policy["terminology"][kind] if row["source"] == entry["source"]), None)
            if entry["source"] not in used or term is None or term["target"] != entry["target"]:
                raise ValueError("Source-scoped term approval differs from reviewed terminology")
        if any(term["reviewStatus"] == "pending" for kind, names in (
                ("seriesNames", scope["usedSeriesNames"]),
                ("properNames", scope["usedProperNames"]))
               for term in policy["terminology"][kind] if term["source"] in names):
            unresolved.append("terminology_review_pending")
        if any(name not in {entry["source"] for entry in evidence}
               for name in scope["usedProperNames"]):
            unresolved.append("proper_name_approval_evidence_pending")
    elif any(term["reviewStatus"] == "pending" for kind in ("seriesNames", "properNames") for term in policy["terminology"][kind]):
        unresolved.append("terminology_review_pending")
    return {
        "translationPolicySha256": canonical_sha256(policy),
        "languageReviewPolicySha256": canonical_sha256(policy["languageReview"]),
        "componentSha256": policy["componentSha256"],
        "productionPolicyReady": not unresolved,
        "unresolved": unresolved,
    }


def verify_shadow_term_evidence(policy: dict[str, Any], candidate: dict[str, Any],
                                approval: dict[str, Any]) -> None:
    """Use an old human-approved shadow only for unchanged, source-bound terms."""
    scope = policy["sourceScope"]
    candidate_hash = canonical_sha256(candidate)
    approval_hash = canonical_sha256(approval)
    if (candidate.get("targetLocale") != policy["targetLocale"]
            or candidate.get("englishSourcePackageJsonSha256")
            != scope["englishSourcePackageJsonSha256"]
            or approval.get("targetLocale") != policy["targetLocale"]
            or approval.get("englishSourcePackageJsonSha256")
            != scope["englishSourcePackageJsonSha256"]
            or approval.get("candidateJsonSha256") != candidate_hash
            or approval.get("decision") != "approved"
            or approval.get("humanApproval") is not True
            or approval.get("formalLayer2Admitted") is not False):
        raise ValueError("Shadow term evidence is not a matching human-approved clip candidate")
    coverage = {row["sourceUnitId"]: row["targetText"]
                for group in candidate.get("groups", [])
                for row in group.get("coverage", [])}
    for item in scope["termApprovalEvidence"]:
        if (item["shadowCandidateJsonSha256"] != candidate_hash
                or item["shadowContentApprovalJsonSha256"] != approval_hash
                or item["sourceUnitId"] not in approval.get("reviewedSourceUnitIds", [])
                or item["target"] not in coverage.get(item["sourceUnitId"], "")):
            raise ValueError("Shadow approval does not cover the unchanged clip-scoped term")


def freeze_policy(draft: dict[str, Any], *, series_table: Path = SERIES_TABLE,
                  shadow_candidate: dict[str, Any] | None = None,
                  content_approval: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(draft, dict) or "componentSha256" in draft:
        raise ValueError("Freeze requires an unresolved policy draft without component hashes")
    policy = dict(draft)
    if policy.get("schemaVersion") == POLICY_V2 and policy["sourceScope"]["termApprovalEvidence"]:
        if shadow_candidate is None or content_approval is None:
            raise ValueError("Scoped term approvals require the exact shadow candidate and human receipt")
        verify_shadow_term_evidence(policy, shadow_candidate, content_approval)
    components = COMPONENTS + (("sourceScope",) if policy.get("schemaVersion") == POLICY_V2 else ())
    policy["componentSha256"] = {name: canonical_sha256(policy[name]) for name in components}
    validate_policy(policy, series_table=series_table)
    return policy


def validate_source_scope(policy: dict[str, Any], source: dict[str, Any],
                          anchor: dict[str, Any]) -> None:
    """Require a v2 policy's declared terminology use to match its frozen source."""
    if policy["schemaVersion"] != POLICY_V2:
        return
    scope = policy["sourceScope"]
    if (scope["englishSourcePackageJsonSha256"] != canonical_sha256(source)
            or scope["anchorManifestSha256"] != canonical_sha256(anchor)):
        raise ValueError("Source-scoped policy belongs to another English package or anchor")
    rows = anchor.get("sourceUnits", [])
    english = " ".join(row.get("english", "") for row in rows)
    observed_series = {term["source"] for term in policy["terminology"]["seriesNames"]
                       if term["source"].casefold() in english.casefold()}
    if observed_series != set(scope["usedSeriesNames"]):
        raise ValueError("Source-scoped series terminology is incomplete or overdeclared")
    # Multiword capitalized names are conservatively required in the scoped
    # proper-name list. Single biblical names are audited by locale plugins.
    candidates = {name for row in rows
                  for name in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b",
                                         row.get("english", ""))}
    discourse_starts = {"So", "Now", "And", "But", "Then", "His", "This", "Only", "First"}
    observed_names = {name for name in candidates
                      if name.split()[0] not in discourse_starts
                      and not any(name in title for title in observed_series)}
    if observed_names != set(scope["usedProperNames"]):
        raise ValueError("Source-scoped proper names are incomplete or overdeclared")
    by_id = {row["sourceUnitId"]: row["english"] for row in rows}
    for item in scope["termApprovalEvidence"]:
        if item["sourceUnitId"] not in by_id or item["source"] not in by_id[item["sourceUnitId"]]:
            raise ValueError("Source-scoped term evidence points outside its English unit")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "inspect"))
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--series-terminology", type=Path, default=SERIES_TABLE)
    parser.add_argument("--shadow-candidate", type=Path)
    parser.add_argument("--content-approval", type=Path)
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if args.command == "freeze":
        if not args.out or args.out.exists():
            parser.error("freeze requires a new --out path")
        resolved = freeze_policy(
            policy, series_table=args.series_terminology,
            shadow_candidate=json.loads(args.shadow_candidate.read_text(encoding="utf-8"))
            if args.shadow_candidate else None,
            content_approval=json.loads(args.content_approval.read_text(encoding="utf-8"))
            if args.content_approval else None,
        )
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(resolved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        policy = resolved
    print(json.dumps(validate_policy(policy, series_table=args.series_terminology), ensure_ascii=False))


if __name__ == "__main__":
    main()
