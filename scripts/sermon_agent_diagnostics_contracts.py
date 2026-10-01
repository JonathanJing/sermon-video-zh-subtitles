"""Private diagnostic v1 validation. Evidence metadata is data, never authority.

Only fixed checked-in schemas are read; no runtime artifacts, URLs, credentials
or production state are read by this module.
Canonical hashes use sorted compact UTF-8 JSON, without Unicode normalization.
Evidence hashes exclude only sha256 and describe the redacted record, not media.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, validators

MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 32 * 1024
MAX_NODES = 8000
MAX_DEPTH = 12
INPUT_VERSION = "sermon-agent-diagnostic-input-v1"
OUTPUT_VERSION = "sermon-agent-diagnosis-v1"
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"


class DiagnosticContractError(ValueError):
    """Fixed safe codes; never echo provider bodies or private input."""


def require(condition, code):
    if not condition:
        raise DiagnosticContractError(code)


def bounded_json(value, max_bytes=MAX_INPUT_BYTES, *, max_nodes=MAX_NODES):
    """Bound depth, nodes and string size before serializing caller objects."""
    remaining = max_nodes
    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        require(remaining >= 0 and depth <= MAX_DEPTH, "json_complexity_limit")
        if type(item) is dict:
            require(len(item) <= 128, "json_complexity_limit")
            for key, child in item.items():
                require(type(key) is str and len(key) <= 128, "invalid_json_key")
                visit(child, depth + 1)
        elif type(item) is list:
            require(len(item) <= 256, "json_complexity_limit")
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            require(len(item) <= max_bytes, "json_size_limit")
        else:
            require(item is None or type(item) in (bool, int)
                    or type(item) is float and math.isfinite(item), "invalid_json_value")
    visit(value, 0)
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise DiagnosticContractError("invalid_json_value") from None
    require(len(data) <= max_bytes, "json_size_limit")
    return data


def decode_json(data, max_bytes=MAX_INPUT_BYTES):
    require(type(data) is bytes and len(data) <= max_bytes, "json_size_limit")
    def pairs(items):
        result = {}
        for key, item in items:
            require(key not in result, "duplicate_json_key")
            result[key] = item
        return result
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda _: require(False, "invalid_json_value"))
    except (ValueError, UnicodeError, RecursionError):
        raise DiagnosticContractError("invalid_json_bytes") from None
    bounded_json(value, max_bytes)
    return value


def fingerprint(value):
    return hashlib.sha256(bounded_json(value, 256 * 1024)).hexdigest()


def evidence_sha256(row):
    return fingerprint({key: value for key, value in row.items() if key != "sha256"})


@lru_cache(maxsize=2)
def _validator(version):
    require(version in {INPUT_VERSION, OUTPUT_VERSION}, "unsupported_schema_version")
    schema = json.loads((SCHEMA_ROOT / (version + ".schema.json")).read_text())
    Draft202012Validator.check_schema(schema)
    checker = FormatChecker()
    @checker.checks("date-time", raises=(ValueError, TypeError))
    def utc(value):
        return type(value) is str and value.endswith("Z") and datetime.fromisoformat(value).tzinfo is not None
    cls = validators.extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", lambda _, value: type(value) is int))
    return cls(schema, format_checker=checker)


def contract_schema(version):
    """Return an independent JSON Schema for a function's argument definition."""
    return json.loads(json.dumps(_validator(version).schema))


def _schema(value, version, max_bytes):
    bounded_json(value, max_bytes)
    require(type(value) is dict and next(_validator(version).iter_errors(value), None) is None,
            "invalid_diagnostic_schema")


def validate_manifest(manifest):
    _schema(manifest, INPUT_VERSION, MAX_INPUT_BYTES)
    identity = manifest["identity"]
    cutoff = datetime.fromisoformat(identity["evidenceCutoff"])
    units = {unit["unitId"]: unit["unitVersion"] for unit in manifest["failedUnits"]}
    require(len(units) == len(manifest["failedUnits"]), "duplicate_unit_id")
    evidence_ids = set()
    for collection, allowed in (("events", {"event", "reproduction"}), ("receipts", {"receipt"}),
                                ("versionDiffs", {"version_diff"})):
        require(all(row["evidenceType"] in allowed for row in manifest[collection]), "evidence_type_mismatch")
    for row in manifest["events"] + manifest["receipts"] + manifest["versionDiffs"]:
        require(row["evidenceId"] not in evidence_ids, "duplicate_evidence_id")
        evidence_ids.add(row["evidenceId"])
        require(row["identity"] == identity, "evidence_identity_mismatch")
        require(datetime.fromisoformat(row["observedAt"]) <= cutoff, "evidence_after_cutoff")
        require(all(units.get(unit["unitId"]) == unit["unitVersion"] for unit in row["units"]),
                "evidence_unit_identity_mismatch")
        require(len({unit["unitId"] for unit in row["units"]}) == len(row["units"]),
                "duplicate_evidence_unit")
        require(row["sha256"] == evidence_sha256(row), "evidence_hash_mismatch")
    return json.loads(bounded_json(manifest))


def validate_diagnosis(diagnosis, bundle):
    _schema(diagnosis, OUTPUT_VERSION, MAX_OUTPUT_BYTES)
    require(diagnosis["identity"] == bundle["manifest"]["identity"], "diagnosis_identity_mismatch")
    require(diagnosis["contextSha256"] == bundle["contextSha256"], "diagnosis_context_mismatch")
    require(diagnosis["snapshotId"] == bundle["snapshotId"], "diagnosis_snapshot_mismatch")
    units = {unit["unitId"] for unit in bundle["manifest"]["failedUnits"]}
    rows = bundle["manifest"]["events"] + bundle["manifest"]["receipts"] + bundle["manifest"]["versionDiffs"]
    evidence = {row["evidenceId"]: {unit["unitId"] for unit in row["units"]} for row in rows}
    reproduction_ids = {row["evidenceId"] for row in rows if row["evidenceType"] == "reproduction"}
    def refs(ids, affected):
        require(set(ids) <= evidence.keys(), "unknown_evidence_reference")
        require(all(evidence[key] & set(affected) for key in ids), "evidence_outside_hypothesis_scope")
    hypothesis_ids = set()
    for hypothesis in diagnosis["hypotheses"]:
        require(hypothesis["hypothesisId"] not in hypothesis_ids, "duplicate_hypothesis_id")
        hypothesis_ids.add(hypothesis["hypothesisId"])
        affected = hypothesis["affectedUnitIds"]
        require(hypothesis["impact"]["stage"] == bundle["manifest"]["identity"]["stage"], "impact_stage_mismatch")
        require(hypothesis["impact"]["blockingScope"] != "all_locales_downstream"
                or hypothesis["impact"]["stage"] == "layer1", "impact_scope_not_supported")
        require(set(affected) <= units, "diagnosis_unit_outside_scope")
        refs(hypothesis["evidenceIds"], affected)
        if not hypothesis["evidenceIds"]:
            require(hypothesis["confidence"] in {"low", "unknown"} and hypothesis["unknowns"], "unsupported_confidence")
        reproduction = hypothesis["reproducibility"]
        refs(reproduction["evidenceIds"], affected)
        require(reproduction["status"] != "replayable" or reproduction["evidenceIds"],
                "reproducibility_evidence_missing")
        require(reproduction["status"] != "replayable" or set(reproduction["evidenceIds"]) <= reproduction_ids,
                "reproducibility_not_supported")
        repair = hypothesis["suggestedRepair"]
        require(set(repair["unitIds"]) <= set(affected), "repair_unit_outside_hypothesis")
        refs(repair["evidenceIds"], repair["unitIds"])
        require(repair["action"] == "none" or repair["unitIds"], "repair_units_missing")
    for request in diagnosis["missingDataRequests"]:
        require(set(request["unitIds"]) <= units, "request_unit_outside_scope")
    # Absence/uncertainty cannot become an implicit pass or a confident root cause.
    missing = bundle["manifest"]["missingEvidenceTypes"]
    require(diagnosis["hypotheses"] or diagnosis["missingDataRequests"], "empty_diagnosis")
    needs_more = missing or any(not h["evidenceIds"] or h["unknowns"] for h in diagnosis["hypotheses"])
    if needs_more:
        require(diagnosis["status"] == "needs_more_evidence" and diagnosis["missingDataRequests"],
                "uncertainty_request_missing")
    require(set(missing) <= {request["kind"] for request in diagnosis["missingDataRequests"]},
            "declared_missing_evidence_not_requested")
    return json.loads(bounded_json(diagnosis, MAX_OUTPUT_BYTES))
