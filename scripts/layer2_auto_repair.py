#!/usr/bin/env python3
"""Layer 2 automatic repair: re-translate failed groups until they pass the gates.

Design: docs/layer2-bounded-auto-repair.zh.md. Release depends on the gates,
not on how many repairs a group took. A round runs every group, collects Sol
and plugin failures, and classifies them deterministically. A systemic failure
stops the locale before any repair: dispatch stops early only when one failure
code hits the threshold in consecutive groups (a rule that never reached the
model fails every group in a row); scattered failures are judged after the
whole round, so a small test batch is not halted by a few isolated errors. Otherwise each repairable group gets a
machine-written partial repair brief and a fresh translator plus independent
reviewer request; every other group reuses its cache.

Repair stops for a group when its failure fingerprint repeats or when two
consecutive repair rounds leave it with no fewer failure codes than before. The
locale stops repairing when the remaining spend cap cannot reserve a complete
bounded translator/reviewer pair. Unknown outcomes and
execution errors are never retried here; they stop the loop for reconciliation.

Formal runs reach this loop through the canonical controller (execution config
v3): its worker injects ``run_round`` inside one durable job and budget binding.
There is no standalone command-line entry.

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
    from scripts import source_meaning_machine_adjudication as source_meaning
except ImportError:  # pragma: no cover - direct script execution
    import run_target_language_models as runner
    import source_meaning_machine_adjudication as source_meaning

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


# Umbrella codes lump unrelated defects (one group a negation, another a number,
# a third a name). They stop dispatch only when consecutive, never by scattered
# count at the end of a round.
UMBRELLA_CODES = frozenset({"negation_number_name_error", "review_issue_open", "review_uncertainty"})
# Repository waiver policy: at most four repairs per English source unit.
MAX_REPAIRS_PER_SOURCE_UNIT = 4


def systemic_threshold(total_groups: int) -> int:
    return max(SYSTEMIC_MINIMUM_GROUPS, math.ceil(total_groups * SYSTEMIC_FRACTION))


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= EVIDENCE_LIMIT else text[:EVIDENCE_LIMIT - 1] + "…"


class FailureCollector:
    """Runner hook: record failed groups and stop dispatch on a systemic failure."""

    def __init__(self, total_groups: int, counted_group_ids=None, known_fingerprints=None,
                 lineage_value: dict | None = None, group_workers: int = 1):
        """The systemic judgement counts only new evidence: ``counted_group_ids``
        limits it to groups dispatched this round (a repair round reuses the other
        failures unchanged), and a failure whose fingerprint is already in
        ``known_fingerprints`` repeats an earlier round instead of adding to a
        batch-wide rule failure."""
        _require(type(total_groups) is int and total_groups > 0, "Failure collection needs the group count")
        _require(type(group_workers) is int and 1 <= group_workers <= 16, "Group workers must be 1..16")
        self.group_workers = group_workers
        self.total_groups = total_groups
        self.threshold = systemic_threshold(total_groups)
        self.counted = None if counted_group_ids is None else frozenset(counted_group_ids)
        self.known = frozenset(known_fingerprints or ())
        self.lineage_value = lineage_value
        _require(not self.known or lineage_value is not None, "Known fingerprints need the lineage")
        self.identity = {"routingVersion": ROUTING_VERSION, "systemicThreshold": self.threshold,
                         "countedGroupIds": None if self.counted is None else sorted(self.counted),
                         "knownFingerprints": sorted(self.known), "groupWorkers": group_workers}
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

    def _is_counted(self, row: dict) -> bool:
        if self.counted is not None and row["translationGroupId"] not in self.counted:
            return False
        if self.known and fingerprint(self.lineage_value, row["sourceUnitIds"], row["failureCodes"]) in self.known:
            return False
        return True

    def _counted_failures(self) -> list[dict]:
        return [row for row in self.failures if self._is_counted(row)]

    def _counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for failure in self._counted_failures():
            for code in failure["failureCodes"]:
                counts[code] = counts.get(code, 0) + 1
        return counts

    def _consecutive(self, code: str) -> int:
        """Longest run of adjacent group indices that all failed with ``code``."""
        indices = sorted(row["index"] for row in self._counted_failures() if code in row["failureCodes"])
        best = run = 0
        for position, index in enumerate(indices):
            run = run + 1 if position and index == indices[position - 1] + 1 else 1
            best = max(best, run)
        return best

    def _record(self, row: dict) -> None:
        with self._lock:
            self.failures.append(row)
            if self.systemic is None and self._is_counted(row):
                for code in sorted(set(row["failureCodes"])):
                    run = self._consecutive(code)
                    if run >= self.threshold:
                        self.systemic = {"failureCode": code, "groups": self._counts()[code],
                                         "consecutiveGroups": run, "threshold": self.threshold,
                                         "reasonCode": "systemic_rule_or_policy_issue",
                                         "stoppedDispatch": True}
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
            if self.systemic is None:
                for code, count in sorted(self._counts().items()):
                    if count >= self.threshold and code not in UMBRELLA_CODES:
                        self.systemic = {"failureCode": code, "groups": count,
                                         "consecutiveGroups": self._consecutive(code),
                                         "threshold": self.threshold,
                                         "reasonCode": "systemic_rule_or_policy_issue",
                                         "stoppedDispatch": False}
                        break
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
    if type(usage.get("total_tokens")) is int and usage["total_tokens"] >= 0:
        return usage["total_tokens"]
    for first, second in (("prompt_tokens", "completion_tokens"), ("input_tokens", "output_tokens")):
        if all(type(usage.get(name)) is int and usage[name] >= 0 for name in (first, second)):
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


def _repair_token_bound() -> int | None:
    """Worst-case tokens per bounded API call, including reasoning output.

    Reserve whole translator/reviewer pairs before selecting the next round.
    The canonical transport enforces these same input/output bounds; measured
    usage from an earlier call is not an upper bound for a repaired prompt.
    """
    from scripts.canonical_layer2_budget import CURRENT_LIMITS
    from scripts.sermon_provider_limits import validate_request_limits
    selected = CURRENT_LIMITS.get()
    if selected is None:
        return None
    selected = validate_request_limits(selected)
    return selected["maxInputTokens"] + selected["maxCompletionTokens"]


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


def _sync_ancestry(path: Path) -> None:
    """Persist ``path`` and every ancestor directory, including newly created ones."""
    current = Path(path).resolve()
    while True:
        fd = os.open(current, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        if current.parent == current:
            return
        current = current.parent


def append_ledger(root: Path, value: dict, entries: list[dict], body: dict) -> dict:
    """Exclusively create the next round; a concurrent loop at the same position fails.

    The entry is synced before it is linked and the directory chain after, so a
    crash cannot lose a round whose next paid round has already started.
    """
    entry = {"schemaVersion": LEDGER_SCHEMA, "lineage": value, "sequence": len(entries) + 1,
             "previousEntryJsonSha256": json_sha256(entries[-1]) if entries else None, **body}
    folder = ledger_directory(root, value)
    folder.mkdir(parents=True, exist_ok=True)
    name = f"round-{entry['sequence']:06d}.json"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder.parent, prefix=f".{folder.name}.{name}.",
                                     suffix=".tmp", delete=False) as stream:
        stream.write(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary = Path(stream.name)
    try:
        os.link(temporary, folder / name)
    finally:
        temporary.unlink()
    _sync_ancestry(folder)
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


def decide(failure: dict, history: list[dict], value: dict, *, noted: bool = False) -> tuple[str, str]:
    """('repair', reason) or ('stop', reason) for one failed group, from durable history.

    ``noted`` says machine audio adjudication settled the wording of a unit in
    this group (its meaning note rides the repair brief). A failure that would
    otherwise go to source review then gets one more repair carrying the note;
    a recurrence after that repair goes to source review as before."""
    action = failure["action"]
    if action != "repair_translation":
        return "stop", action
    # A group already stopped keeps its reason while its unchanged cache is reused.
    if history and not history[-1]["repaired"]:
        held = [reason for reason in history[-1]["decisions"] if reason != "repairable_content_failure"]
        if held:
            return "stop", held[0]
    if sum(row["repaired"] for row in history) >= MAX_REPAIRS_PER_SOURCE_UNIT:
        return "stop", "repair_limit_per_source_unit"
    current = fingerprint(value, failure["sourceUnitIds"], failure["failureCodes"])
    seen = {item for row in history for item in row["fingerprints"]}
    if current in seen:
        repeated = {REPEATED_FAILURE_ACTIONS[code] for code in failure["failureCodes"]
                    if code in REPEATED_FAILURE_ACTIONS}
        for action in ("request_source_review", "request_human_review"):
            if action in repeated:
                if action == "request_source_review" and noted \
                        and not any("source_meaning_noted" in row["decisions"] for row in history):
                    return "repair", "source_meaning_noted"
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


def repair_row(failure: dict, meaning_notes: dict | None = None) -> dict:
    reason = _clip(f"{', '.join(failure['failureCodes'])}: {failure['evidence']} "
                   + " ".join(failure["issues"]))
    instruction = " ".join(INSTRUCTIONS[code] for code in failure["failureCodes"])
    noted = source_meaning.repair_instruction(meaning_notes or {}, failure["sourceUnitIds"])
    if noted:
        # The frozen English of these units is what was said: translate it literally, add no meaning.
        instruction += " " + noted
    instruction += (" Machine-written repair instruction from a failed independent review; "
                    "check every point against the English source. Reviewer finding: " + reason)
    return {"translationGroupId": failure["translationGroupId"], "sourceUnitIds": failure["sourceUnitIds"],
            "failedRole": "reviewer", "failedCacheSha256": failure["reviewerCacheSha256"],
            "failureReason": reason, "instruction": instruction[:2000]}


# ---------------------------------------------------------------- loop


RoundRunner = Callable[[Path, Path | None, dict | None, FailureCollector], dict]


def _cache_matches(path: Path, digest: str) -> bool:
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest


def _evidence_path(out: Path, failure: dict) -> str:
    """A plugin rejection's evidence is the report's plugin check, not the passing Sol cache."""
    if "language_plugin_failed" in failure["failureCodes"]:
        return str(out / "group-failures.json")
    return str(out / failure["reviewerCache"])


def _saved_report(out: Path, request: dict, total_groups: int) -> dict:
    """Load a durable round report and check that its identity and caches still exist."""
    report = json.loads((out / "group-failures.json").read_text(encoding="utf-8"))
    _require(report.get("schemaVersion") == REPORT_SCHEMA and report.get("totalGroups") == total_groups
             and report.get("humanApproval") is False
             and all(report.get(key) == request[key] for key in (
                 "targetLocale", "englishSourcePackageJsonSha256", "anchorManifestSha256",
                 "translationPolicySha256")),
             "Saved group failure report does not match this round")
    _require(all(_cache_matches(out / failure["reviewerCache"], failure["reviewerCacheSha256"])
                 for failure in report["failures"]),
             "Saved group failure report references a missing or changed cache")
    return report


def drive(request: dict, total_groups: int, run_round: RoundRunner, out_root: Path,
          ledger_root: Path, *, group_workers: int = 1, meaning_notes: dict | None = None) -> dict:
    """Run rounds until every group passes or repair stops; write and return a receipt.

    ``run_round(out, reuse_from, brief, collector)`` returns evidence when every
    group passed, raises GroupFailuresCollected otherwise, and lets any other
    error (execution failure, unknown outcome) propagate unchanged.

    ``meaning_notes`` are the Layer 1 machine audio adjudication notes, keyed by
    source unit, that ``source_meaning_machine_adjudication.load_meaning_notes``
    bound to this run's source and anchor: a group holding a noted unit carries
    the note in its repair brief, and a quotation failure that recurs on such a
    group is repaired once more with it before it is sent to source review.
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
        if brief is not None:
            # Recheck resumed work against today's enforced provider bounds.
            # A changed/missing bound never silently dispatches an old plan.
            token_bound = _repair_token_bound()
            _require(token_bound is not None and initial is not None
                     and not initial["callsWithoutUsage"]
                     and not any(e["spend"]["callsWithoutUsage"] for e in entries[1:])
                     and spent["tokens"] + len(brief["groups"]) * CALLS_PER_REPAIR * token_bound
                     <= math.ceil(initial["tokens"] * SPEND_FRACTION),
                     "repair_token_reservation_unavailable")
        collector = FailureCollector(
            total_groups, [row["translationGroupId"] for row in brief["groups"]] if brief else None,
            {item for entry in entries for row in entry["groups"] for item in [row["fingerprint"]] if item},
            value, group_workers)
        if (out / "group-failures.json").exists():
            # A saved report is the round's result. Replay after a crash never
            # re-dispatches its groups, even if the scheduler would now differ.
            evidence, report = None, _saved_report(out, request, total_groups)
        else:
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
                noted = bool(source_meaning.repair_instruction(meaning_notes or {}, failure["sourceUnitIds"]))
                verdict, reason = ("stop", "systemic_rule_or_policy_issue") if report["systemicStop"] \
                    else decide(failure, history, value, noted=noted)
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
                                    "evidencePath": _evidence_path(out, failure)})
            for skipped in report["notDispatched"]:
                stopped.append({**skipped, "failureCodes": [], "reasonCode": "not_dispatched_after_systemic_stop",
                                "evidencePath": None})
            cap_calls = max(MINIMUM_REPAIR_CALLS, math.ceil(initial["calls"] * SPEND_FRACTION))
            cap_tokens = math.ceil(initial["tokens"] * SPEND_FRACTION)
            token_bound = _repair_token_bound()
            known_usage = not initial["callsWithoutUsage"] and not spend["callsWithoutUsage"] \
                and not any(e["spend"]["callsWithoutUsage"] for e in entries[1:])
            # Repair as many groups as the cap still allows, in source order.
            affordable = min(max(0, (cap_calls - spent["calls"]) // CALLS_PER_REPAIR),
                             max(0, (cap_tokens - spent["tokens"]) // (CALLS_PER_REPAIR * token_bound))) \
                if known_usage and token_bound is not None else 0
            cap_reason = "repair_spend_cap" if known_usage and token_bound is not None \
                else "repair_token_usage_unavailable" if not known_usage else "repair_token_bound_unavailable"
            if len(repairs) > affordable:
                capped = repairs[affordable:]
                repairs = repairs[:affordable]
                capped_ids = {failure["translationGroupId"] for failure in capped}
                for failure in capped:
                    stopped.append({"translationGroupId": failure["translationGroupId"],
                                    "sourceUnitIds": failure["sourceUnitIds"],
                                    "failureCodes": failure["failureCodes"], "reasonCode": cap_reason,
                                    "evidencePath": _evidence_path(out, failure)})
                for row in rows:
                    if row["translationGroupId"] in capped_ids:
                        row["repaired"], row["decision"] = False, cap_reason
            if not repairs:
                outcome = "stopped"
        elif brief is not None and (spend["callsWithoutUsage"]
                                    or spent["tokens"] > math.ceil(initial["tokens"] * SPEND_FRACTION)):
            # Even a passing injected/misbehaving transport cannot hide unknown
            # or excessive usage behind successful semantic/plugin checks.
            outcome = "stopped"
            stopped = [{"translationGroupId": row["translationGroupId"],
                        "sourceUnitIds": row["sourceUnitIds"], "failureCodes": [],
                        "reasonCode": "repair_token_usage_unavailable" if spend["callsWithoutUsage"]
                        else "repair_spend_cap", "evidencePath": str(out / "evidence.json")}
                       for row in brief["groups"]]
        next_brief = None
        if repairs:
            next_brief = {"schemaVersion": runner.PARTIAL_REPAIR_SCHEMA, **{key: request[key] for key in (
                "targetLocale", "englishSourcePackageJsonSha256", "anchorManifestSha256",
                "translationPolicySha256")}, "groups": [repair_row(failure, meaning_notes) for failure in repairs]}
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
               "gatesPassed": ["independent_review", "language_plugin"] if outcome == "passed" else [],
               "releaseAuthority": "none",
               "ledgerRoot": str(Path(ledger_root).resolve()),
               "ledgerHeadSha256": json_sha256(last),
               "humanApproval": False, "reviewKind": "machine_review"}
    path = out_root / f"auto-repair-receipt-{len(entries):03d}.json"
    if not path.exists():
        runner.save_new(path, receipt)
    # Admission must consume the saved terminal evidence, including on resume.
    # A prior interrupted write or foreign receipt cannot be bypassed by
    # recomputing a successful result from the ledger in memory.
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValueError(f"Saved auto-repair receipt is corrupt: {path}") from exc
    _require(json_sha256(saved) == json_sha256(receipt),
             f"Saved auto-repair receipt does not match the terminal ledger: {path}")
    return saved
