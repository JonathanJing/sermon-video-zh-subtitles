#!/usr/bin/env python3
"""Layer 2 automatic repair: re-translate failed groups until they pass the gates.

Design: docs/layer2-bounded-auto-repair.zh.md. Release depends on the gates,
not on how many repairs a group took. A round runs every group, collects Sol
and plugin failures, and classifies them deterministically. A systemic failure
stops the locale before any repair. Otherwise each repairable group gets a
machine-written partial repair brief and a fresh translator plus independent
reviewer request; every other group reuses its cache.

Repair stops for a group when its failure fingerprint repeats or when two
consecutive repair rounds leave it with no fewer failure codes than before. The
locale stops repairing when repair spend exceeds the cap. Unknown outcomes and
execution errors are never retried here; they stop the loop for reconciliation.

There is no command-line entry yet: formal repairs need a controller-native
revision and cache reuse path with durable budget reservations (the standalone
runner refuses unbound API requests and cross-run reuse under a transport
identity). Callers inject ``run_round``.

The result is machine evidence only. Nothing here sets human approval, edits a
translation, or rewrites a translation that Sol passed but a plugin rejected.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Callable

try:
    from scripts import run_target_language_models as runner
except ImportError:  # pragma: no cover - direct script execution
    import run_target_language_models as runner

ROUTING_VERSION = "layer2-auto-repair-routing-v1"
REPORT_SCHEMA = "sermon-layer2-group-failures-v1"
LEDGER_SCHEMA = "sermon-layer2-repair-ledger-entry-v1"
RECEIPT_SCHEMA = "sermon-layer2-auto-repair-receipt-v1"

# Sol semantic checks map to the failure codes of sermon_repair_planning, except
# negation/number/name, which stays one code: its repair action is the same and
# telling the three apart would mean parsing Sol's free text.
CHECK_CODES = {
    "completeMeaning": "meaning_omission",
    "noAddedMeaning": "meaning_addition",
    "negationsNumbersNames": "negation_number_name_error",
    "quotationAttribution": "quotation_attribution_error",
}
# Back-translation QC issue kinds (target_text_auto_qc) for when gate 4 feeds the loop.
QC_KIND_CODES = {
    "omission": "meaning_omission",
    "addition": "meaning_addition",
    "negation": "negation_number_name_error",
    "number": "negation_number_name_error",
    "name": "negation_number_name_error",
    "scripture_reference": "scripture_reference_error",
    "meaning_shift": "meaning_shift",
}
ACTIONS = {
    "meaning_omission": "repair_translation",
    "meaning_addition": "repair_translation",
    "negation_number_name_error": "repair_translation",
    "quotation_attribution_error": "repair_translation",
    "scripture_reference_error": "repair_translation",
    "meaning_shift": "repair_translation",
    # AGENTS.md: a Sol issue or uncertainty also starts a new repair revision.
    "review_uncertainty": "repair_translation",
    "review_issue_open": "repair_translation",
    "language_plugin_failed": "escalate_engineering",
}
# What a repeated failure becomes once a repair made no progress on it.
REPEATED_FAILURE_ACTIONS = {
    "quotation_attribution_error": "request_source_review",  # points at the source, not the wording
    "review_uncertainty": "request_human_review",
    "review_issue_open": "request_human_review",
}
INSTRUCTIONS = {
    "meaning_omission": "Restore every meaning the English source states; the prior translation omitted some.",
    "meaning_addition": "Remove meaning the English source does not state; the prior translation added some.",
    "negation_number_name_error": "Match every negation, number and name of the English source exactly.",
    "quotation_attribution_error": ("Attribute quotations exactly as the English source does: keep the speaker's "
                                    "paraphrase as paraphrase and a quotation as a quotation of its stated source."),
    "scripture_reference_error": "Give scripture references exactly as the English source speaks them.",
    "meaning_shift": "Restore the meaning of the English source; the prior translation shifted it.",
    "review_uncertainty": "Resolve the reviewer's stated uncertainty from the English source and its context.",
    "review_issue_open": "Resolve the reviewer's open issue from the English source.",
}
SYSTEMIC_MINIMUM_GROUPS = 3
SYSTEMIC_FRACTION = 0.01
SPEND_FRACTION = 0.10
MINIMUM_REPAIR_CALLS = 4
PATIENCE_ROUNDS = 2
EVIDENCE_LIMIT = 600
CALLS_PER_REPAIR = 2  # one translator and one independent reviewer request


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def json_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def classify_review(semantic: dict) -> tuple[list[str], str]:
    """Failure codes and action for a Sol review that did not pass.

    Every Sol failure, uncertainty or open issue starts a new repair revision
    (AGENTS.md). Uncertainty or an open issue that repeats after a repair goes
    to a person instead (REPEATED_FAILURE_ACTIONS).
    """
    checks = semantic.get("checks") or {}
    codes = {CHECK_CODES[name] for name, value in checks.items()
             if name in CHECK_CODES and value != "pass"}
    if semantic.get("uncertainty"):
        codes.add("review_uncertainty")
    if not codes:
        codes.add("review_issue_open")
    return sorted(codes), "repair_translation"


def systemic_threshold(total_groups: int) -> int:
    return max(SYSTEMIC_MINIMUM_GROUPS, math.ceil(total_groups * SYSTEMIC_FRACTION))


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= EVIDENCE_LIMIT else text[:EVIDENCE_LIMIT - 1] + "…"


class FailureCollector:
    """Runner hook: record failed groups and stop dispatch on a systemic failure."""

    def __init__(self, total_groups: int):
        _require(type(total_groups) is int and total_groups > 0, "Failure collection needs the group count")
        self.threshold = systemic_threshold(total_groups)
        self.identity = {"routingVersion": ROUTING_VERSION, "systemicThreshold": self.threshold}
        self.failures: list[dict] = []
        self.not_dispatched: list[dict] = []
        self.systemic: dict | None = None
        self._lock = threading.Lock()

    def stopped(self) -> bool:
        with self._lock:
            return self.systemic is not None

    def has_failures(self) -> bool:
        with self._lock:
            return bool(self.failures or self.not_dispatched)

    def _record(self, row: dict) -> None:
        with self._lock:
            self.failures.append(row)
            counts: dict[str, int] = {}
            for failure in self.failures:
                for code in failure["failureCodes"]:
                    counts[code] = counts.get(code, 0) + 1
            if self.systemic is None:
                for code, count in sorted(counts.items()):
                    if count >= self.threshold:
                        self.systemic = {"failureCode": code, "groups": count, "threshold": self.threshold,
                                         "reasonCode": "systemic_rule_or_policy_issue"}
                        break

    def _base(self, index: int, group: dict, sol_path: Path) -> dict:
        return {"index": index, "translationGroupId": group["translationGroupId"],
                "sourceUnitIds": list(group["sourceUnitIds"]),
                "reviewerCache": sol_path.name,
                "reviewerCacheSha256": hashlib.sha256(sol_path.read_bytes()).hexdigest()}

    def record_review_failure(self, index: int, group: dict, semantic: dict, sol_path: Path) -> None:
        codes, action = classify_review(semantic)
        self._record({**self._base(index, group, sol_path), "gate": "independent_review",
                      "failureCodes": codes, "action": action,
                      "evidence": _clip(semantic.get("evidence", "")),
                      "issues": [_clip(item) for item in semantic.get("issues", [])][:5],
                      "uncertainty": [_clip(item) for item in semantic.get("uncertainty", [])][:5]})

    def record_plugin_failure(self, index: int, group: dict, review: dict, sol_path: Path) -> None:
        failed = [check for check in review.get("checks", [])
                  if isinstance(check, dict) and check.get("status") == "fail"]
        self._record({**self._base(index, group, sol_path), "gate": "language_plugin",
                      "failureCodes": ["language_plugin_failed"], "action": ACTIONS["language_plugin_failed"],
                      "evidence": _clip("; ".join(f"{check.get('checkId')}: {check.get('evidence', '')}"
                                                  for check in failed)),
                      "issues": [], "uncertainty": []})

    def record_not_dispatched(self, index: int, group: dict) -> None:
        with self._lock:
            self.not_dispatched.append({"index": index, "translationGroupId": group["translationGroupId"],
                                        "sourceUnitIds": list(group["sourceUnitIds"])})

    def finish(self, out: Path, request: dict, plan: list[dict]) -> None:
        with self._lock:
            report = {"schemaVersion": REPORT_SCHEMA, "routingVersion": ROUTING_VERSION,
                      "targetLocale": request["targetLocale"],
                      "englishSourcePackageJsonSha256": request["englishSourcePackageJsonSha256"],
                      "anchorManifestSha256": request["anchorManifestSha256"],
                      "translationPolicySha256": request["translationPolicySha256"],
                      "totalGroups": len(plan), "systemicThreshold": self.threshold,
                      "systemicStop": self.systemic,
                      "failures": sorted(self.failures, key=lambda row: row["index"]),
                      "notDispatched": sorted(self.not_dispatched, key=lambda row: row["index"]),
                      "humanApproval": False}
        path = out / "group-failures.json"
        if path.exists():  # a resumed round reproduces its report from the same caches
            _require(json.loads(path.read_text(encoding="utf-8")) == report, "Group failure report changed")
        else:
            runner.save_new(path, report, private=True)
        raise GroupFailuresCollected(path, report)


class GroupFailuresCollected(ValueError):
    def __init__(self, path: Path, report: dict):
        super().__init__(f"layer2_group_failures_collected: {path}")
        self.path = path
        self.report = report


# ---------------------------------------------------------------- spend


def _response_tokens(response: dict) -> int | None:
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    if isinstance(usage.get("total_tokens"), int):
        return usage["total_tokens"]
    for first, second in (("prompt_tokens", "completion_tokens"), ("input_tokens", "output_tokens")):
        if isinstance(usage.get(first), int) and isinstance(usage.get(second), int):
            return usage[first] + usage[second]
    return None


def round_spend(out: Path, reuse_from: Path | None) -> dict:
    """Paid calls and tokens a round made: raw responses not copied from its reuse source."""
    calls, tokens, unknown = 0, 0, 0
    for raw in sorted(out.glob("group-*.raw.json")):
        copied = reuse_from is not None and (reuse_from / raw.name).is_file() \
            and (reuse_from / raw.name).read_bytes() == raw.read_bytes()
        if copied:
            continue
        calls += 1
        value = _response_tokens(json.loads(raw.read_text(encoding="utf-8")).get("response"))
        if value is None:
            unknown += 1
        else:
            tokens += value
    return {"calls": calls, "tokens": tokens, "callsWithoutUsage": unknown}


# ---------------------------------------------------------------- ledger


def lineage(request: dict) -> dict:
    return {key: request[key] for key in ("targetLocale", "englishSourcePackageJsonSha256",
                                          "anchorManifestSha256", "translationPolicySha256")}


def ledger_directory(root: Path, value: dict) -> Path:
    return Path(root) / "layer2-repair" / value["targetLocale"] / json_sha256(value)


def load_ledger(root: Path, value: dict) -> list[dict]:
    """All rounds of one locale's repair chain, checked as one unbroken hash chain."""
    folder = ledger_directory(root, value)
    names = sorted(path.name for path in folder.glob("*")) if folder.exists() else []
    _require(names == [f"round-{index:06d}.json" for index in range(1, len(names) + 1)],
             "Repair ledger has a gap or a foreign file")
    entries = [json.loads((folder / name).read_text(encoding="utf-8")) for name in names]
    previous = None
    for sequence, entry in enumerate(entries, 1):
        _require(entry.get("schemaVersion") == LEDGER_SCHEMA and entry.get("lineage") == value
                 and entry.get("sequence") == sequence and entry.get("previousEntryJsonSha256") == previous,
                 f"Repair ledger entry {sequence} does not follow the chain")
        previous = json_sha256(entry)
    return entries


def append_ledger(root: Path, value: dict, entries: list[dict], body: dict) -> dict:
    """Exclusively create the next round; a concurrent loop at the same position fails."""
    entry = {"schemaVersion": LEDGER_SCHEMA, "lineage": value, "sequence": len(entries) + 1,
             "previousEntryJsonSha256": json_sha256(entries[-1]) if entries else None, **body}
    folder = ledger_directory(root, value)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"round-{entry['sequence']:06d}.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder.parent, prefix=f".{folder.name}.{name}.",
                                     suffix=".tmp", delete=False) as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    temporary = Path(stream.name)
    try:
        os.link(temporary, folder / name)
    finally:
        temporary.unlink()
    return entry


def fingerprint(value: dict, source_unit_ids: list[str], codes: list[str]) -> str:
    return json_sha256({"lineage": value, "sourceUnitIds": source_unit_ids, "failureCodes": sorted(codes)})


def unit_history(entries: list[dict], source_unit_ids: list[str]) -> list[dict]:
    """Per round, what happened to any unit of this group (regrouping keeps the history)."""
    units = set(source_unit_ids)
    history = []
    for entry in entries:
        rows = [row for row in entry["groups"] if units & set(row["sourceUnitIds"])]
        if rows:
            history.append({"round": entry["sequence"],
                            "repaired": any(row["repaired"] for row in rows),
                            "decisions": sorted({row["decision"] for row in rows}),
                            "failureCodes": sorted({code for row in rows for code in row["failureCodes"]}),
                            "fingerprints": sorted({row["fingerprint"] for row in rows if row["fingerprint"]})})
    return history


# ---------------------------------------------------------------- decisions


def decide(failure: dict, history: list[dict], value: dict) -> tuple[str, str]:
    """('repair', reason) or ('stop', reason) for one failed group, from durable history."""
    action = failure["action"]
    if action != "repair_translation":
        return "stop", action
    # A group already stopped keeps its reason while its unchanged cache is reused.
    if history and not history[-1]["repaired"]:
        held = [reason for reason in history[-1]["decisions"] if reason != "repairable_content_failure"]
        if held:
            return "stop", held[0]
    current = fingerprint(value, failure["sourceUnitIds"], failure["failureCodes"])
    seen = {item for row in history for item in row["fingerprints"]}
    if current in seen:
        repeated = {REPEATED_FAILURE_ACTIONS[code] for code in failure["failureCodes"]
                    if code in REPEATED_FAILURE_ACTIONS}
        for action in ("request_source_review", "request_human_review"):
            if action in repeated:
                return "stop", action
        return "stop", "repeated_failure_without_progress"
    # Patience: count failure codes before and after each repair round.
    counts = [len(row["failureCodes"]) for row in history] + [len(failure["failureCodes"])]
    repaired = [row["repaired"] for row in history]
    streak = 0
    for position in range(1, len(counts)):
        if repaired[position - 1]:
            streak = streak + 1 if counts[position] >= counts[position - 1] else 0
    if streak >= PATIENCE_ROUNDS:
        return "stop", "no_fewer_failures_after_two_repairs"
    return "repair", "repairable_content_failure"


def repair_row(failure: dict) -> dict:
    reason = _clip(f"{', '.join(failure['failureCodes'])}: {failure['evidence']} "
                   + " ".join(failure["issues"]))
    instruction = " ".join(INSTRUCTIONS[code] for code in failure["failureCodes"])
    instruction += (" Machine-written repair instruction from a failed independent review; "
                    "check every point against the English source. Reviewer finding: " + reason)
    return {"translationGroupId": failure["translationGroupId"], "sourceUnitIds": failure["sourceUnitIds"],
            "failedRole": "reviewer", "failedCacheSha256": failure["reviewerCacheSha256"],
            "failureReason": reason, "instruction": instruction[:2000]}


# ---------------------------------------------------------------- loop


RoundRunner = Callable[[Path, Path | None, dict | None, FailureCollector], dict]


def drive(request: dict, total_groups: int, run_round: RoundRunner, out_root: Path,
          ledger_root: Path) -> dict:
    """Run rounds until every group passes or repair stops; write and return a receipt.

    ``run_round(out, reuse_from, brief, collector)`` returns evidence when every
    group passed, raises GroupFailuresCollected otherwise, and lets any other
    error (execution failure, unknown outcome) propagate unchanged.
    """
    value = lineage(request)
    out_root = Path(out_root)
    entries = load_ledger(ledger_root, value)
    # A loop resumes after its last recorded round; it never repeats one.
    sequence = len(entries)
    reuse_from = Path(entries[-1]["runDirectory"]) if entries else None
    brief = entries[-1]["nextBrief"] if entries else None
    initial = entries[0]["spend"] if entries else None
    spent = {"calls": sum(e["spend"]["calls"] for e in entries[1:]),
             "tokens": sum(e["spend"]["tokens"] for e in entries[1:])}
    if entries and entries[-1]["outcome"] != "repairing":
        return _receipt(out_root, ledger_root, value, entries, entries[-1]["outcome"], entries[-1]["stopped"])
    while True:
        sequence += 1
        out = out_root / f"round-{sequence:03d}"
        collector = FailureCollector(total_groups)
        try:
            evidence = run_round(out, reuse_from, brief, collector)
            report = None
        except GroupFailuresCollected as collected:
            evidence, report = None, collected.report
        spend = round_spend(out, reuse_from)
        if initial is None:
            initial = spend
        else:
            spent = {"calls": spent["calls"] + spend["calls"], "tokens": spent["tokens"] + spend["tokens"]}
        rows, stopped, repairs, outcome = [], [], [], "passed"
        if report is not None:
            outcome = "repairing"
            for failure in report["failures"]:
                history = unit_history(entries, failure["sourceUnitIds"])
                verdict, reason = ("stop", "systemic_rule_or_policy_issue") if report["systemicStop"] \
                    else decide(failure, history, value)
                rows.append({"translationGroupId": failure["translationGroupId"],
                             "sourceUnitIds": failure["sourceUnitIds"],
                             "failureCodes": failure["failureCodes"],
                             "fingerprint": fingerprint(value, failure["sourceUnitIds"], failure["failureCodes"]),
                             "repaired": verdict == "repair", "decision": reason})
                if verdict == "repair":
                    repairs.append(failure)
                else:
                    stopped.append({"translationGroupId": failure["translationGroupId"],
                                    "sourceUnitIds": failure["sourceUnitIds"],
                                    "failureCodes": failure["failureCodes"], "reasonCode": reason,
                                    "evidencePath": str(out / failure["reviewerCache"])})
            for skipped in report["notDispatched"]:
                stopped.append({**skipped, "failureCodes": [], "reasonCode": "not_dispatched_after_systemic_stop",
                                "evidencePath": None})
            cap_calls = max(MINIMUM_REPAIR_CALLS, math.ceil(initial["calls"] * SPEND_FRACTION))
            cap_tokens = math.ceil(initial["tokens"] * SPEND_FRACTION) if initial["tokens"] else None
            over_tokens = cap_tokens is not None and spent["tokens"] > cap_tokens
            if repairs and (over_tokens or spent["calls"] + CALLS_PER_REPAIR * len(repairs) > cap_calls):
                for failure in repairs:
                    stopped.append({"translationGroupId": failure["translationGroupId"],
                                    "sourceUnitIds": failure["sourceUnitIds"],
                                    "failureCodes": failure["failureCodes"], "reasonCode": "repair_spend_cap",
                                    "evidencePath": str(out / failure["reviewerCache"])})
                for row in rows:
                    row["repaired"] = False
                repairs = []
            if not repairs:
                outcome = "stopped"
        next_brief = None
        if repairs:
            next_brief = {"schemaVersion": runner.PARTIAL_REPAIR_SCHEMA, **{key: request[key] for key in (
                "targetLocale", "englishSourcePackageJsonSha256", "anchorManifestSha256",
                "translationPolicySha256")}, "groups": [repair_row(failure) for failure in repairs]}
        entry = append_ledger(ledger_root, value, entries, {
            "runDirectory": str(out.resolve()), "routingVersion": ROUTING_VERSION,
            "repairBriefSha256": json_sha256(brief) if brief else None,
            "evidenceSha256": json_sha256(evidence) if evidence is not None else None,
            "failureReportSha256": json_sha256(report) if report is not None else None,
            "spend": spend, "groups": rows, "outcome": outcome, "stopped": stopped, "nextBrief": next_brief})
        entries.append(entry)
        if outcome != "repairing":
            return _receipt(out_root, ledger_root, value, entries, outcome, stopped)
        reuse_from, brief = out, next_brief


def _receipt(out_root: Path, ledger_root: Path, value: dict, entries: list[dict], outcome: str,
             stopped: list[dict]) -> dict:
    last = entries[-1]
    receipt = {"schemaVersion": RECEIPT_SCHEMA, "routingVersion": ROUTING_VERSION, "lineage": value,
               "status": "all_groups_passed" if outcome == "passed" else "repair_stopped",
               "rounds": len(entries), "finalRunDirectory": last["runDirectory"],
               "evidenceSha256": last["evidenceSha256"],
               "initialSpend": entries[0]["spend"],
               "repairSpend": {"calls": sum(e["spend"]["calls"] for e in entries[1:]),
                               "tokens": sum(e["spend"]["tokens"] for e in entries[1:])},
               "stoppedGroups": stopped,
               "ledgerRoot": str(Path(ledger_root).resolve()),
               "ledgerHeadSha256": json_sha256(last),
               "humanApproval": False, "reviewKind": "machine_review"}
    path = out_root / f"auto-repair-receipt-{len(entries):03d}.json"
    if not path.exists():
        runner.save_new(path, receipt)
    return receipt
