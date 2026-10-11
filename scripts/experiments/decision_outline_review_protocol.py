"""Offline experiment records; never creates a production approval receipt.

Configured human identities are operator assertions, not verified human identity.
Callers must independently recompute payload hashes before invoking these helpers.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import random
from pathlib import Path

LABELS = {"supported", "contradiction", "unsupported", "needs_more_evidence"}
FRAMING = {"faithful", "misleading", "needs_more_evidence"}
PRIVATE_KEYS = {"expected", "family", "provenance", "authorId", "severity", "gold", "mutation", "parentSha256", "sampleType", "authorExpected", "variantType"}


def _cases(cases):
    result = {}
    for case in cases:
        if not all(isinstance(case.get(k), str) and case[k] for k in ("caseId", "sourceId", "payloadSha256")):
            raise ValueError("case_identity_missing")
        if case["caseId"] in result:
            raise ValueError("duplicate_case_id")
        result[case["caseId"]] = case
    if not result:
        raise ValueError("cases_missing")
    return result


def _reviewers(ids, count=2):
    if len(ids) != count or any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != count:
        raise ValueError("explicit_distinct_reviewer_ids_required")


def allocate_timed_reviews(cases, reviewer_ids, seed=20261006):
    """Cross over by source, never by item; deterministic from sorted identities."""
    by_id = _cases(cases)
    _reviewers(reviewer_ids)
    sources = sorted({c["sourceId"] for c in cases})
    if len(sources) % 2:
        raise ValueError("balanced_allocation_requires_even_source_count")
    rng = random.Random(seed)
    rng.shuffle(sources)
    assignments = []
    for index, source in enumerate(sources):
        items = sorted((c for c in by_id.values() if c["sourceId"] == source), key=lambda c: c["caseId"])
        rng.shuffle(items)
        for reviewer_index, reviewer in enumerate(reviewer_ids):
            arm = "A" if (index + reviewer_index) % 2 == 0 else "B"
            for case in items:
                assignments.append({"reviewerId": reviewer, "caseId": case["caseId"], "sourceId": source,
                                    "payloadSha256": case["payloadSha256"], "arm": arm})
    return assignments


def _blind(value):
    if isinstance(value, dict):
        return {k: _blind(v) for k, v in value.items() if k not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [_blind(v) for v in value]
    return copy.deepcopy(value)


def make_gold_templates(cases, gold_reviewer_ids):
    _cases(cases)
    _reviewers(gold_reviewer_ids)
    return [{"caseId": c["caseId"], "sourceId": c["sourceId"], "payloadSha256": c["payloadSha256"],
             "reviewerId": reviewer, "sharedEvidence": _blind(c.get("sharedEvidence", {})),
             "status": "pending", "claims": [], "framingLabel": None, "severity": None}
            for reviewer in gold_reviewer_ids for c in sorted(cases, key=lambda c: c["caseId"])]


def _human(reviewer, identities):
    # Identity verification remains outside this program. No default humans.
    identity = identities.get(reviewer, {})
    return identity.get("kind") == "human" and identity.get("role") not in {"author", "agent", "model"}


def _units(case):
    evidence = case.get("sharedEvidence", {})
    units = case.get("sourceUnits", evidence.get("sourceUnits", evidence.get("sourceExcerpts", evidence.get("sources", []))))
    if isinstance(units, dict):
        return {k: (v.get("text", "") if isinstance(v, dict) else v) for k, v in units.items()}
    return {u.get("sourceUnitId", u.get("id")): u.get("text", u.get("textEn", "")) for u in units if isinstance(u, dict)}


def _judgment(record, case):
    if record.get("status") != "completed" or record.get("framingLabel") not in FRAMING or record.get("severity") not in {"none", "minor", "severe", "uncertain"}:
        raise ValueError("gold_judgment_incomplete")
    claims = record.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ValueError("gold_claims_missing")
    units = _units(case)
    if not units or any(not isinstance(text, str) or not text.strip() for text in units.values()):
        raise ValueError("source_units_required_for_gold")
    expected_claims = case.get("sharedEvidence", {}).get("claims")
    if expected_claims is not None:
        expected_spans = [c.get("span") for c in expected_claims]
        actual_spans = [c.get("span") for c in claims]
        if (not expected_spans or len(set(expected_spans)) != len(expected_spans)
                or len(set(actual_spans)) != len(actual_spans)
                or set(actual_spans) != set(expected_spans)):
            raise ValueError("gold_claim_coverage_mismatch")
    for claim in claims:
        if not isinstance(claim.get("span"), str) or not claim["span"].strip():
            raise ValueError("claim_span_missing")
        if any(claim.get(k) not in LABELS for k in ("windowLabel", "wholeSourceLabel")):
            raise ValueError("gold_label_invalid")
        evidence = claim.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError("source_evidence_missing")
        for span in evidence:
            unit_id, text = span.get("sourceUnitId"), span.get("textSpan")
            if not isinstance(unit_id, str) or not unit_id or not isinstance(text, str) or not text.strip():
                raise ValueError("source_span_missing")
            if units and (unit_id not in units or text not in units[unit_id]):
                raise ValueError("source_span_not_bound")
    return {"claims": claims, "framingLabel": record["framingLabel"], "severity": record["severity"]}


def validate_gold(cases, gold_records, reviewer_identities, timed_assignments=None, adjudications=None):
    """Fail closed for absent humans, mismatched evidence, and unresolved disagreement."""
    by_id = _cases(cases)
    errors, complete = [], []
    warnings = [{"caseId": c["caseId"], "warning": "source_units_not_supplied_span_binding_unavailable"}
                for c in cases if not _units(c)]
    by_case = {key: [] for key in by_id}
    timed_by_source = {}
    for row in timed_assignments or []:
        # Bind isolation to the frozen case, never to an assignment's claimed
        # source: an invented source would otherwise hide a reused reviewer.
        case = by_id.get(row.get("caseId")) if isinstance(row, dict) else None
        if (case is None or not isinstance(row.get("reviewerId"), str)
                or not row["reviewerId"].strip() or row.get("arm") not in {"A", "B"}):
            errors.append({"caseId": row.get("caseId") if isinstance(row, dict) else None,
                           "error": "timed_assignment_invalid"})
            continue
        if (row.get("sourceId") != case["sourceId"]
                or row.get("payloadSha256") != case["payloadSha256"]):
            errors.append({"caseId": case["caseId"], "error": "timed_assignment_identity_mismatch"})
            continue
        timed_by_source.setdefault(case["sourceId"], set()).add(row["reviewerId"])
    authors_by_source = {}
    for case in cases:
        authors_by_source.setdefault(case["sourceId"], set()).update([case["authorId"]] if case.get("authorId") else [])
    for source, authors in authors_by_source.items():
        if authors & timed_by_source.get(source, set()):
            errors.append({"sourceId": source, "error": "author_timed_same_source"})
    for row in gold_records:
        if row.get("caseId") not in by_case:
            errors.append({"caseId": row.get("caseId"), "error": "unknown_gold_case"})
        else:
            by_case[row["caseId"]].append(row)
    adjudication_map = {}
    for row in adjudications or []:
        if row.get("caseId") not in by_case:
            errors.append({"caseId": row.get("caseId"), "error": "unknown_adjudication_case"})
        if row.get("caseId") in adjudication_map:
            errors.append({"caseId": row.get("caseId"), "error": "duplicate_adjudication"})
        adjudication_map[row.get("caseId")] = row
    for case_id, case in by_id.items():
        try:
            rows = by_case[case_id]
            if len(rows) != 2 or len({r.get("reviewerId") for r in rows}) != 2:
                raise ValueError("two_independent_gold_reviewers_required")
            verdicts = []
            for row in rows:
                reviewer = row.get("reviewerId")
                if not _human(reviewer, reviewer_identities):
                    raise ValueError("configured_human_gold_required")
                if reviewer in authors_by_source.get(case["sourceId"], set()):
                    raise ValueError("author_gold_same_source")
                if reviewer in timed_by_source.get(case["sourceId"], set()):
                    raise ValueError("gold_timed_same_source")
                if row.get("payloadSha256") != case["payloadSha256"] or row.get("sourceId") != case["sourceId"]:
                    raise ValueError("gold_identity_mismatch")
                verdicts.append(_judgment(row, case))
            # Evidence spans may differ; compare labels and exact claim spans only.
            def classification(v):
                return (v["framingLabel"], v["severity"], sorted((c["span"], c["windowLabel"], c["wholeSourceLabel"]) for c in v["claims"]))
            if classification(verdicts[0]) != classification(verdicts[1]):
                adj = adjudication_map.get(case_id, {})
                reviewer = adj.get("reviewerId")
                if (not _human(reviewer, reviewer_identities) or reviewer in {r["reviewerId"] for r in rows}
                        or reviewer in authors_by_source.get(case["sourceId"], set())
                        or reviewer in timed_by_source.get(case["sourceId"], set())):
                    raise ValueError("independent_human_adjudication_required")
                if adj.get("payloadSha256") != case["payloadSha256"] or adj.get("sourceId") != case["sourceId"]:
                    raise ValueError("adjudication_identity_mismatch")
                _judgment(adj, case)
            complete.append(case_id)
        except (ValueError, TypeError, KeyError) as exc:
            errors.append({"caseId": case_id, "error": str(exc)})
    return {"status": "ready" if not errors else "incomplete", "configuredHumanIdentityVerified": False,
            "productionApproval": False, "timedReviewStatus": "assignments_supplied" if timed_assignments else "not_prepared", "totalCases": len(cases), "completeCases": len(complete), "errors": errors, "warnings": warnings}


def summarize_timing(cases, assignments, events, observation_limit_seconds=480):
    """Reject malformed intervals; retain unfinished/censored assignments in totals."""
    by_id = _cases(cases)
    if not math.isfinite(observation_limit_seconds) or observation_limit_seconds <= 0:
        raise ValueError("observation_limit_invalid")
    states = {}
    source_arms = {}
    for row in assignments:
        key = (row.get("reviewerId"), row.get("caseId"))
        case = by_id.get(row.get("caseId"))
        if key in states or not case or row.get("arm") not in {"A", "B"} or not row.get("reviewerId"):
            raise ValueError("assignment_invalid")
        if row.get("sourceId") != case["sourceId"] or row.get("payloadSha256") != case["payloadSha256"]:
            raise ValueError("assignment_identity_mismatch")
        source_key = (key[0], case["sourceId"])
        if source_key in source_arms and source_arms[source_key] != row["arm"]:
            raise ValueError("reviewer_source_cross_arm")
        source_arms[source_key] = row["arm"]
        states[key] = {"assignment": row, "active": 0.0, "closedIntervals": 0, "start": None, "last": None, "first": None, "terminal": None}
    for event in events:
        key = (event.get("reviewerId"), event.get("caseId"))
        if key not in states:
            raise ValueError("event_assignment_missing")
        s = states[key]
        if event.get("payloadSha256") != s["assignment"]["payloadSha256"]:
            raise ValueError("event_identity_mismatch")
        t = event.get("timestampSeconds")
        if not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t) or t < 0 or (s["last"] is not None and t < s["last"]):
            raise ValueError("event_timestamp_invalid")
        if s["terminal"]:
            raise ValueError("event_after_terminal")
        kind = event.get("type")
        if kind == "start":
            if s["start"] is not None:
                raise ValueError("active_start_without_stop")
            s["start"] = t
        elif kind == "stop":
            if s["start"] is None:
                raise ValueError("active_stop_without_start")
            s["active"] += t - s["start"]
            s["closedIntervals"] += 1
            s["start"] = None
        elif kind in {"completed", "incomplete"}:
            if s["start"] is not None:
                raise ValueError("terminal_requires_stopped_active_timer")
            if kind == "completed" and s["closedIntervals"] == 0:
                raise ValueError("completed_requires_closed_active_interval")
            s["terminal"] = kind
        else:
            raise ValueError("event_type_invalid")
        s["first"] = t if s["first"] is None else s["first"]
        s["last"] = t
    rows = []
    for s in states.values():
        active = s["active"]
        censored = active > observation_limit_seconds or s["terminal"] != "completed" or s["start"] is not None
        rows.append({**s["assignment"], "observedClosedActiveSeconds": active,
                     "restrictedActiveSeconds": min(active, observation_limit_seconds),
                     "completed": s["terminal"] == "completed" and active <= observation_limit_seconds,
                     "censored": censored, "openActiveInterval": s["start"] is not None,
                     "wallSeconds": None if s["first"] is None else s["last"] - s["first"]})
    arms = {arm: {"denominator": sum(r["arm"] == arm for r in rows),
                   "completed": sum(r["arm"] == arm and r["completed"] for r in rows),
                   "censored": sum(r["arm"] == arm and r["censored"] for r in rows)} for arm in ("A", "B")}
    return {"status": "observed" if events else "not_started", "productionApproval": False,
            "observationLimitSeconds": observation_limit_seconds, "assignments": rows, "arms": arms,
            "note": "Completion is a recorded endpoint, not independently established endpoint validity."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["allocate", "templates", "validate-gold", "timing"])
    parser.add_argument("input", type=Path, help="JSON object with cases and explicit reviewer records")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    data = json.loads(args.input.read_text())
    if args.command == "allocate":
        result = allocate_timed_reviews(data["cases"], data.get("reviewerIds", []), data.get("seed", 20261006))
    elif args.command == "templates":
        result = make_gold_templates(data["cases"], data.get("reviewerIds", []))
    elif args.command == "validate-gold":
        result = validate_gold(data["cases"], data.get("goldRecords", []), data.get("reviewerIdentities", {}), data.get("assignments", []), data.get("adjudications", []))
    else:
        result = summarize_timing(data["cases"], data.get("assignments", []), data.get("events", []))
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
