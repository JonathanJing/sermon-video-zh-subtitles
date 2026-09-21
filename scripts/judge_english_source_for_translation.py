#!/usr/bin/env python3
"""Judge Layer 1 sentence anchors for Layer 2 shadow development.

This machine gate does not grant human approval or production translation
eligibility. It combines deterministic lossless coverage/timeline checks with
an independent GPT semantic-boundary review and emits an immutable receipt.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_english_source_package as layer1  # noqa: E402
from scripts import sermon_sentence_interpretation as anchors  # noqa: E402
from scripts.run_sentence_interpretation_models import cached_call  # noqa: E402
from scripts.sermon_pipeline import chat_json  # noqa: E402


SCHEMA_VERSION = "sermon-english-source-machine-judge-v1"
PROMPT_VERSION = "sermon-english-source-machine-judge-v1"
BATCH_SCHEMA = "sermon-english-source-machine-judge-batch-v1"
CHECKS = (
    "meaningPreserved",
    "negationsNumbersNames",
    "quotationAndClauseIntegrity",
    "timelineCoherent",
    "translationContextSufficient",
)
REVIEWABLE_MANIFEST_ISSUES = {
    "alignment_word_duration_outlier",
    "clause_unit_exceeds_target_without_safe_boundary",
}
THRESHOLDS = {
    "requiredDeterministicCheckPassRate": 1.0,
    "requiredSentencePassRate": 1.0,
    "maximumHighRiskSentences": 0,
    "maximumUnresolvedIssues": 0,
}
SYSTEM_PROMPT = """You are the independent machine judge for a frozen English sermon source.
Decide whether each source sentence remains semantically recoverable after it is split into timed
source units for downstream translation. Do not rewrite, translate, or improve the sermon.

A sentence passes only when all claims remain available in unit order; negations, numbers, names,
quotation attribution, and clause relationships are not changed; every unit is translatable with
the supplied neighboring context; and the listed unit/word timing is coherent enough to bind the
translation back to the same English words. Compare the units with their complete source sentence:
do not fail an ambiguity, pronoun, or speaker attribution that was already present in the unsplit
source and was not made worse by the slicing. An unsplit sentence is not required to be standalone
sermon context. The maximum unit duration is a downstream latency target, not a semantic or timeline
accuracy gate: exceeding it is not by itself a reason to fail when the word timestamps are exact,
monotonic, and keeping the unit intact better preserves meaning. Natural phrasing need not be perfect,
but a high-risk boundary, lost dependency, newly ambiguous attribution, inaccurate or incoherent
timing, or other unresolved slicing concern is a fail.

Return exactly the requested JSON schema and preserve every supplied sentence and unit ID."""


def _load(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {label}: {path}: {exc}") from exc


def _write_immutable(path: Path, payload: object) -> None:
    if path.exists():
        if _load(path, "existing machine judge receipt") != payload:
            raise ValueError(f"Existing machine judge receipt changed: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _batches(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    return [items[index:index + size] for index in range(0, len(items), size)]


def _sentence_inputs(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
    for unit in manifest.get("sourceUnits", []):
        grouped.setdefault(str(unit.get("sourceSentenceId", "")), []).append(unit)
    sentences: list[dict[str, Any]] = []
    all_ids = list(grouped)
    issues = manifest.get("issues") if isinstance(manifest.get("issues"), list) else []
    for index, (sentence_id, units) in enumerate(grouped.items()):
        sentences.append({
            "sourceSentenceId": sentence_id,
            "fullEnglish": " ".join(str(unit["english"]).strip() for unit in units),
            "contextBefore": (
                " ".join(str(unit["english"]).strip() for unit in grouped[all_ids[index - 1]])
                if index else ""
            ),
            "contextAfter": (
                " ".join(str(unit["english"]).strip() for unit in grouped[all_ids[index + 1]])
                if index + 1 < len(all_ids) else ""
            ),
            "units": [{
                "sourceUnitId": unit["sourceUnitId"],
                "partIndex": unit["partIndex"],
                "english": unit["english"],
                "sourceWordIds": unit["sourceWordIds"],
                "start": unit["start"],
                "end": unit["end"],
                "durationSeconds": unit["durationSeconds"],
                "boundary": unit["boundary"],
            } for unit in units],
            "manifestIssues": [
                issue for issue in issues
                if isinstance(issue, dict) and issue.get("sourceSentenceId") == sentence_id
            ],
        })
    return sentences


def deterministic_review(aligned_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    issues: list[str] = []

    def record(check_id: str, passed: bool, evidence: str) -> None:
        checks.append({"checkId": check_id, "status": "pass" if passed else "fail", "evidence": evidence})
        if not passed:
            issues.append(f"{check_id}: {evidence}")

    aligned = _load(aligned_path, "aligned English")
    valid_input = isinstance(aligned, list) and bool(aligned)
    record("alignedInput", valid_input, "aligned English is a non-empty JSON array" if valid_input else "aligned English is missing or invalid")
    bound_hash = manifest.get("input", {}).get("mfaSegmentsSha256")
    hash_matches = bound_hash == layer1.file_sha256(aligned_path)
    record("alignedInputHash", hash_matches, "manifest binds the supplied aligned English" if hash_matches else "aligned English SHA-256 differs from the manifest")

    rebuild_matches = False
    if valid_input and hash_matches and manifest.get("schemaVersion") == anchors.ANCHOR_SCHEMA_V2:
        policy = manifest.get("policy", {})
        rebuilt = anchors.build_anchor_manifest(
            aligned,
            source_path=aligned_path,
            unit_policy=anchors.UNIT_POLICY_V2,
            max_unit_seconds=policy.get("maxUnitSeconds"),
            min_unit_seconds=policy.get("minUnitSeconds", 1.5),
            internal_pause_seconds=policy.get("internalPauseSeconds", 0.35),
            reaction_lag_seconds=policy.get("reactionLagSeconds", 0.25),
            inter_utterance_gap_seconds=policy.get("interUtteranceGapSeconds", 0.12),
            max_end_lag_seconds=policy.get("maxEndLagSeconds", 8.0),
            word_duration_outlier_seconds=policy.get("wordDurationOutlierSeconds", 2.5),
        )
        rebuilt["input"]["mfaSegments"] = manifest.get("input", {}).get("mfaSegments")
        rebuild_matches = rebuilt == manifest
    record("manifestDeterministicRebuild", rebuild_matches, "anchor manifest exactly rebuilds from the bound English and policy" if rebuild_matches else "anchor manifest differs from a deterministic rebuild")

    units = manifest.get("sourceUnits") if isinstance(manifest.get("sourceUnits"), list) else []
    unit_ids = [unit.get("sourceUnitId") for unit in units if isinstance(unit, dict)]
    unit_identity_ok = bool(units) and len(unit_ids) == len(set(unit_ids)) and all(isinstance(item, str) and item for item in unit_ids)
    record("sourceUnitIdentity", unit_identity_ok, "source unit IDs are non-empty and unique" if unit_identity_ok else "source unit IDs are missing or duplicated")

    word_ids: list[str] = []
    timeline_ok = True
    previous_word_end: float | None = None
    for unit in units:
        words = unit.get("words") if isinstance(unit, dict) else None
        source_word_ids = unit.get("sourceWordIds") if isinstance(unit, dict) else None
        if not isinstance(words, list) or not words or source_word_ids != [word.get("wordId") for word in words]:
            timeline_ok = False
            continue
        if unit.get("start") != words[0].get("start") or unit.get("end") != words[-1].get("end"):
            timeline_ok = False
        for word in words:
            start, end = word.get("start"), word.get("end")
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start < 0 or end <= start:
                timeline_ok = False
                continue
            if previous_word_end is not None and start < previous_word_end - 0.001:
                timeline_ok = False
            previous_word_end = end
            word_ids.append(str(word.get("wordId", "")))
    word_identity_ok = bool(word_ids) and len(word_ids) == len(set(word_ids)) and all(word_ids)
    record("sourceWordCoverage", word_identity_ok, "every anchored word ID appears exactly once" if word_identity_ok else "anchored word IDs are missing or duplicated")
    record("timelineMonotonic", timeline_ok, "word and unit times are positive, bound, and monotonic" if timeline_ok else "word or unit timing is invalid, unbound, or overlapping")

    requests = manifest.get("translationRequests") if isinstance(manifest.get("translationRequests"), list) else []
    request_units = [request.get("sourceUnitIds") for request in requests if isinstance(request, dict)]
    request_ok = len(requests) == len(units) and request_units == [[unit_id] for unit_id in unit_ids]
    record("translationRequestCoverage", request_ok, "translation requests cover source units exactly once and in order" if request_ok else "translation request coverage differs from source units")

    manifest_issues = manifest.get("issues") if isinstance(manifest.get("issues"), list) else []
    issue_types = {str(issue.get("type", "")) for issue in manifest_issues if isinstance(issue, dict)}
    reviewable = all(issue_type in REVIEWABLE_MANIFEST_ISSUES for issue_type in issue_types)
    record("reviewableManifestIssues", reviewable, "all manifest issues are semantic/timing candidates supported by this judge" if reviewable else f"unsupported manifest issue types: {sorted(issue_types - REVIEWABLE_MANIFEST_ISSUES)}")

    return {
        "status": "pass" if not issues else "fail",
        "checks": checks,
        "issues": issues,
    }


def _response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schemaVersion", "sentences"],
        "properties": {
            "schemaVersion": {"type": "string", "const": BATCH_SCHEMA},
            "sentences": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["sourceSentenceId", "sourceUnitIds", "verdict", "risk", "checks", "evidence", "unresolvedIssues"],
                    "properties": {
                        "sourceSentenceId": {"type": "string"},
                        "sourceUnitIds": {"type": "array", "items": {"type": "string"}},
                        "verdict": {"type": "string", "enum": ["pass", "fail"]},
                        "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                        "checks": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(CHECKS),
                            "properties": {
                                name: {"type": "string", "enum": ["pass", "fail"]}
                                for name in CHECKS
                            },
                        },
                        "evidence": {"type": "string"},
                        "unresolvedIssues": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


def _payload(batch: list[dict[str, Any]], *, manifest_hash: str,
             anchor_policy: dict[str, Any], model: str, effort: str) -> dict[str, Any]:
    user = {
        "anchorManifestJsonSha256": manifest_hash,
        "evaluationScope": "text_and_timing_metadata_only",
        "anchorPolicy": anchor_policy,
        "sentences": batch,
        "gateRule": {
            "requiredSentencePassRate": 1.0,
            "maximumHighRiskSentences": 0,
            "maximumUnresolvedIssues": 0,
        },
    }
    return {
        "model": model,
        "reasoning_effort": effort,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "english_source_machine_judge",
                "strict": True,
                "schema": _response_schema(),
            },
        },
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }


def _checked_batch(result: dict[str, Any], expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if result.get("schemaVersion") != BATCH_SCHEMA:
        raise ValueError("Machine judge returned the wrong batch schema")
    rows = result.get("sentences")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("Machine judge sentence count differs")
    for row, source in zip(rows, expected):
        expected_units = [unit["sourceUnitId"] for unit in source["units"]]
        if row.get("sourceSentenceId") != source["sourceSentenceId"] or row.get("sourceUnitIds") != expected_units:
            raise ValueError("Machine judge changed sentence or source-unit identity")
        checks = row.get("checks")
        if not isinstance(checks, dict) or set(checks) != set(CHECKS) or any(value not in {"pass", "fail"} for value in checks.values()):
            raise ValueError("Machine judge returned an invalid check ledger")
        if row.get("verdict") not in {"pass", "fail"} or row.get("risk") not in {"low", "medium", "high"}:
            raise ValueError("Machine judge returned an invalid verdict or risk")
        if not isinstance(row.get("evidence"), str) or not row["evidence"].strip() or not isinstance(row.get("unresolvedIssues"), list):
            raise ValueError("Machine judge evidence or issues are invalid")
    return rows


def run(*, aligned_path: Path, manifest_path: Path, out: Path, model: str = "gpt-6-astra",
        effort: str = "medium", batch_size: int = 15, api_key: str,
        caller: Callable[..., dict[str, Any]] = chat_json) -> dict[str, Any]:
    aligned_path = aligned_path.resolve()
    manifest_path = manifest_path.resolve()
    manifest = _load(manifest_path, "anchor manifest")
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != anchors.ANCHOR_SCHEMA_V2:
        raise ValueError("Machine judge requires a clause-stable v2 anchor manifest")
    if out.exists():
        existing = _load(out, "existing machine judge receipt")
        if (existing.get("alignedSegmentsSha256") != layer1.file_sha256(aligned_path)
                or existing.get("anchorManifestJsonSha256") != layer1.json_sha256(manifest)):
            raise ValueError("Existing machine judge receipt belongs to changed inputs")
        if (existing.get("implementationSha256") != layer1.file_sha256(Path(__file__).resolve())
                or existing.get("model") != model
                or existing.get("reasoningEffort") != effort
                or existing.get("promptVersion") != PROMPT_VERSION):
            raise ValueError("Existing machine judge receipt belongs to changed judge configuration")
        return existing

    deterministic = deterministic_review(aligned_path, manifest)
    sentences = _sentence_inputs(manifest)
    reviewed: list[dict[str, Any]] = []
    request_receipts: list[dict[str, Any]] = []
    response_models: list[str] = []
    request_ids: list[str] = []
    created_times: list[int] = []
    if deterministic["status"] == "pass":
        for index, batch in enumerate(_batches(sentences, batch_size)):
            result, receipt = cached_call(
                out=out.parent,
                stage=f"english-source-judge-{index:03d}",
                payload=_payload(
                    batch,
                    manifest_hash=layer1.json_sha256(manifest),
                    anchor_policy=manifest.get("policy", {}),
                    model=model,
                    effort=effort,
                ),
                api_key=api_key,
                requested_model=model,
                caller=caller,
            )
            reviewed.extend(_checked_batch(result, batch))
            request_receipts.append(receipt)
            if isinstance(receipt.get("responseId"), str) and receipt["responseId"]:
                request_ids.append(receipt["responseId"])
            if isinstance(receipt.get("model"), str) and receipt["model"]:
                response_models.append(receipt["model"])
            cache_payload = _load(Path(receipt["path"]), "machine judge cache receipt")
            created = cache_payload.get("response", {}).get("created")
            if isinstance(created, int) and created >= 0:
                created_times.append(created)

    expected_sentence_ids = [item["sourceSentenceId"] for item in sentences]
    reviewed_sentence_ids = [item["sourceSentenceId"] for item in reviewed]
    sentence_pass = sum(
        row.get("verdict") == "pass"
        and row.get("risk") != "high"
        and all(row.get("checks", {}).get(name) == "pass" for name in CHECKS)
        and not row.get("unresolvedIssues")
        for row in reviewed
    )
    high_risk = sum(row.get("risk") == "high" for row in reviewed)
    sentence_fail = len(reviewed) - sentence_pass
    unresolved = list(deterministic["issues"])
    if reviewed_sentence_ids != expected_sentence_ids:
        unresolved.append("machine judge did not review every source sentence in order")
    for row in reviewed:
        unresolved.extend(f"{row['sourceSentenceId']}: {item}" for item in row.get("unresolvedIssues", []))
        if row.get("verdict") != "pass" or any(row.get("checks", {}).get(name) != "pass" for name in CHECKS):
            unresolved.append(f"{row['sourceSentenceId']}: semantic or timeline judge failed")
        if row.get("risk") == "high":
            unresolved.append(f"{row['sourceSentenceId']}: high-risk boundary")
    eligible = (
        deterministic["status"] == "pass"
        and reviewed_sentence_ids == expected_sentence_ids
        and sentence_pass == len(sentences)
        and sentence_fail == 0
        and high_risk == 0
        and not unresolved
    )
    reviewed_at = datetime.fromtimestamp(
        max(created_times) if created_times else 0, tz=timezone.utc,
    ).isoformat().replace("+00:00", "Z")
    manifest_issue_hashes = [
        layer1.json_sha256(issue) for issue in manifest.get("issues", []) if isinstance(issue, dict)
    ]
    invalidation_identity = {
        "alignedSegmentsSha256": layer1.file_sha256(aligned_path),
        "anchorManifestJsonSha256": layer1.json_sha256(manifest),
        "implementationSha256": layer1.file_sha256(Path(__file__).resolve()),
        "model": model,
        "reasoningEffort": effort,
        "promptVersion": PROMPT_VERSION,
        "requestIds": request_ids,
    }
    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "reviewType": "model",
        "humanApproval": False,
        "status": "approved_for_layer2_shadow" if eligible else "rejected_for_layer2_shadow",
        "layer2DevelopmentEligible": eligible,
        "productionTranslationEligible": False,
        "alignedSegmentsSha256": invalidation_identity["alignedSegmentsSha256"],
        "anchorManifestJsonSha256": invalidation_identity["anchorManifestJsonSha256"],
        "downstreamInvalidationKey": layer1.json_sha256(invalidation_identity),
        "implementationSha256": invalidation_identity["implementationSha256"],
        "model": model,
        "reasoningEffort": effort,
        "promptVersion": PROMPT_VERSION,
        "requestIds": request_ids,
        "responseModels": sorted(set(response_models)),
        "reviewedAt": reviewed_at,
        "thresholds": THRESHOLDS,
        "deterministicReview": deterministic,
        "reviewedSourceSentenceIds": reviewed_sentence_ids,
        "reviewedManifestIssueJsonSha256s": manifest_issue_hashes,
        "sentences": reviewed,
        "counts": {
            "sourceSentences": len(sentences),
            "sourceUnits": len(manifest.get("sourceUnits", [])),
            "manifestIssues": len(manifest.get("issues", [])),
            "sentencePass": sentence_pass,
            "sentenceFail": sentence_fail,
            "highRiskSentences": high_risk,
        },
        "unresolvedIssues": unresolved,
        "requestReceipts": request_receipts,
    }
    _write_immutable(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aligned-segments", type=Path, required=True)
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--api-key-secret")
    args = parser.parse_args()
    if args.api_key_secret:
        from backend.cloud import access_secret
        api_key = access_secret(args.api_key_secret)
    else:
        import os
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set and --api-key-secret was not provided")
    result = run(
        aligned_path=args.aligned_segments,
        manifest_path=args.anchor_manifest,
        out=args.out.resolve(),
        model=args.model,
        effort=args.reasoning_effort,
        batch_size=args.batch_size,
        api_key=api_key,
    )
    print(json.dumps({
        "status": result["status"],
        "layer2DevelopmentEligible": result["layer2DevelopmentEligible"],
        "productionTranslationEligible": result["productionTranslationEligible"],
        "counts": result["counts"],
        "out": str(args.out.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if result["layer2DevelopmentEligible"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
