"""Layer 2 revision by group ID: translate only the groups an operator listed.

Design: docs/canonical-layer2-controller.zh.md (按组号修订). The only required input
is an existing candidate and the groups to revise, each with an optional note,
plus the operator decision row that produced the list. Listed groups get a new
paid translator request, an independent reviewer request and the plugin check,
in parallel, inside the bounded repair loop. Every other group keeps its exact
target bytes and its prior translator/reviewer evidence, carried by hash from the
named prior candidate, with no model call and no re-review.

A changed plugin or frozen policy is allowed only when no model-facing field
changed (``policy_preview.classify_policy_change``). The current deterministic
plugin is then run locally over every prior group before any paid call: a group
it now fails must be in the list, or the command names it and stops. Old and new
policy hashes, rule bundles and plugin results are all recorded.

Nothing here grants human approval. The result is a normal candidate under the
current policy; whole-text QC still runs on it downstream.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from . import auto_repair
from . import backend as _text
from . import candidate as producer
from . import models as runner
from . import policy as policy_tools
from . import policy_preview

REQUEST_SCHEMA = "sermon-layer2-group-revision-request-v1"
GATE_SCHEMA = "sermon-layer2-group-revision-plugin-gate-v1"
RECEIPT_SCHEMA = "sermon-layer2-group-revision-receipt-v1"
DECISIONS_FILE = "decisions.ndjson"
# Repair pairs (translator + reviewer) each listed group may still spend after its first
# revision fails a gate. The loop's per-unit limit, fingerprint and patience rules still apply.
REPAIR_PAIRS_PER_LISTED_GROUP = 2
ALLOWED_POLICY_CHANGES = frozenset({"unchanged", "plugin_only_migration", "approval_rebinding"})
# Rule bundle keys a plugin-only migration may change. Anything else in the bundle comes from
# model-facing policy fields and would already classify as content_modified.
PLUGIN_RULE_KEYS = frozenset({"pluginNumberForms", "pluginNameForms", "exactQuotes"})
REQUIRED_KEYS = frozenset({"schemaVersion", "targetLocale", "priorCandidate", "groups", "decision"})
OPTIONAL_KEYS = frozenset({"priorPolicy", "priorRulePreflight"})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_schema(value: Any, name: str, reason: str) -> None:
    schema = json.loads(_text.current().schemas.path(name).read_text(encoding="utf-8"))
    _require(not any(True for _ in Draft202012Validator(schema).iter_errors(value)), reason)


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class GroupRevisionGateFailed(ValueError):
    """Groups outside the list fail a check of the current policy; nothing was dispatched."""

    def __init__(self, report: dict, path: Path | None = None):
        groups = ", ".join(str(row["group"]) for row in report["unlistedFailures"])
        super().__init__(f"group_revision_unlisted_groups_fail_current_checks: {groups}")
        self.report = report
        self.path = path


# ---------------------------------------------------------------- request


def load_request(path: Path) -> dict:
    """Read a revision request; file fields resolve beside it.

    ``groups`` lists 1-based group numbers (the ``group-NNNN`` of the run files) or exact
    ``translationGroupId`` strings, each optionally ``{"group": ..., "note": "..."}``.
    ``decision`` names the run's ``decisions.ndjson`` and the canonical SHA-256 of the
    ``record_decision.py`` row that produced the list."""
    path = Path(path).absolute()
    value = _load(path)
    _validate_schema(value, REQUEST_SCHEMA + ".schema.json", "invalid_group_revision_request")
    _require(isinstance(value, dict) and REQUIRED_KEYS <= set(value) <= REQUIRED_KEYS | OPTIONAL_KEYS
             and value["schemaVersion"] == REQUEST_SCHEMA
             and isinstance(value["targetLocale"], str) and value["targetLocale"]
             and isinstance(value["groups"], list) and value["groups"]
             and all(isinstance(value.get(key, "x"), str) and value.get(key, "x")
                     for key in ("priorCandidate", "priorPolicy", "priorRulePreflight")),
             "invalid_group_revision_request")
    decision = value["decision"]
    _require(isinstance(decision, dict) and set(decision) == {"decisionsFile", "rowSha256"}
             and isinstance(decision["decisionsFile"], str) and decision["decisionsFile"]
             and isinstance(decision["rowSha256"], str) and len(decision["rowSha256"]) == 64,
             "invalid_group_revision_request")
    entries = []
    for item in value["groups"]:
        group, note = (item.get("group"), item.get("note")) if isinstance(item, dict) else (item, None)
        _require((not isinstance(item, dict) or set(item) <= {"group", "note"})
                 and ((type(group) is int and group >= 1) or (isinstance(group, str) and group))
                 and (note is None or (isinstance(note, str) and note.strip() and len(note) <= 2000)),
                 "invalid_group_revision_request")
        entries.append({"group": group, "note": note.strip() if note else None})
    resolve = lambda name: (path.parent / value[name]).resolve() if name in value else None  # noqa: E731
    return {"path": path, "value": value, "groups": entries,
            "priorCandidate": resolve("priorCandidate"), "priorPolicy": resolve("priorPolicy"),
            "priorRulePreflight": resolve("priorRulePreflight"),
            "decisionsFile": (path.parent / decision["decisionsFile"]).resolve(),
            "decisionRowSha256": decision["rowSha256"]}


def input_paths(loaded: dict) -> list[Path]:
    return [item for item in (loaded["path"], loaded["priorCandidate"], loaded["priorPolicy"],
                              loaded["priorRulePreflight"], loaded["decisionsFile"]) if item is not None]


def identity(loaded: dict) -> str:
    """The request and the bytes of every file it names: a new list or note is a new job."""
    return policy_tools.canonical_sha256({
        "request": loaded["value"],
        "files": {name: _file_sha256(loaded[name]) if loaded[name] is not None else None
                  for name in ("priorCandidate", "priorPolicy", "priorRulePreflight", "decisionsFile")}})


def decision_row(decisions_file: Path, row_sha256: str, prior_candidate_file_sha256: str) -> dict:
    """The record_decision.py row, artifact-bound to exactly the prior candidate's bytes."""
    _require(decisions_file.is_file() and not decisions_file.is_symlink()
             and decisions_file.name == DECISIONS_FILE, "group_revision_decision_file_missing")
    matches = []
    for line in decisions_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if policy_tools.canonical_sha256(row) == row_sha256:
                matches.append(row)
    _require(len(matches) == 1, "group_revision_decision_row_missing")
    row = matches[0]
    _require(isinstance(row, dict) and row.get("authority") == "artifact_bound"
             and isinstance(row.get("governs"), list)
             and any(isinstance(item, dict) and item.get("sha256") == prior_candidate_file_sha256
                     for item in row["governs"])
             and all(isinstance(row.get(key), str) and row[key].strip()
                     for key in ("at", "question", "choice", "decidedBy")),
             "group_revision_decision_does_not_govern_prior_candidate")
    return row


# ---------------------------------------------------------------- plan


def _resolve_groups(entries: list[dict], plan: list[dict]) -> list[dict]:
    by_id = {row["translationGroupId"]: index for index, row in enumerate(plan, 1)}
    listed, seen = [], set()
    for entry in entries:
        group = entry["group"]
        index = group if type(group) is int else by_id.get(group)
        _require(index is not None and 1 <= index <= len(plan), f"group_revision_unknown_group: {group}")
        _require(index not in seen, f"group_revision_duplicate_group: {group}")
        seen.add(index)
        row = plan[index - 1]
        listed.append({"group": index, "translationGroupId": row["translationGroupId"],
                       "sourceUnitIds": list(row["sourceUnitIds"]), "note": entry["note"]})
    return sorted(listed, key=lambda row: row["group"])


def _rule_change(prior_rules: dict | None, rules: dict, request: dict, prior_policy_sha256: str,
                 plan: list[dict]) -> dict:
    """What the model-facing rule bundle changed, and the groups whose own quote rules changed."""
    current = {"ruleBundleSha256": rules["ruleBundleSha256"]}
    if prior_rules is None:
        return {**current, "priorRuleBundleSha256": rules["ruleBundleSha256"],
                "changedKeys": [], "groupsWithChangedRules": []}
    _require(isinstance(prior_rules, dict) and prior_rules.get("schemaVersion") == rules["schemaVersion"]
             and prior_rules.get("translationPolicySha256") == prior_policy_sha256
             and all(prior_rules.get(key) == request[key]
                     for key in ("englishSourcePackageJsonSha256", "anchorManifestSha256"))
             and isinstance(prior_rules.get("modelRules"), dict)
             and prior_rules.get("ruleBundleSha256") == policy_tools.canonical_sha256(prior_rules["modelRules"]),
             "group_revision_prior_rule_preflight_mismatch")
    old, new = prior_rules["modelRules"], rules["modelRules"]
    changed = sorted(key for key in set(old) | set(new) if old.get(key) != new.get(key))
    _require(set(changed) <= PLUGIN_RULE_KEYS, "group_revision_model_facing_rules_changed: " + ", ".join(
        key for key in changed if key not in PLUGIN_RULE_KEYS))
    quote_changed = []
    for index, group in enumerate(plan, 1):
        units = set(group["sourceUnitIds"])
        own = lambda bundle: [quote for quote in bundle.get("exactQuotes", [])  # noqa: E731
                              if units & set(quote["sourceUnitIds"])]
        if own(old) != own(new):
            quote_changed.append(index)
    return {**current, "priorRuleBundleSha256": prior_rules["ruleBundleSha256"],
            "changedKeys": changed, "groupsWithChangedRules": quote_changed}


def prepare(loaded: dict, source: dict, anchor: dict, policy: dict, plugin_path: Path,
            rule_receipt: dict, *, gate_report_path: Path | None = None) -> dict:
    """Check the request against the current inputs and build the runner brief; no model call.

    Raises GroupRevisionGateFailed (after writing its report) when the current plugin, or a
    changed per-group quote rule, rejects a group the operator did not list."""
    request = producer.prepare_request(source, anchor, policy)
    _require(loaded["value"]["targetLocale"] == request["targetLocale"], "group_revision_locale_differs")
    plan = runner.group_plan(request, anchor)
    prior_path = loaded["priorCandidate"]
    prior_file_sha256 = _file_sha256(prior_path)
    prior = _load(prior_path)
    _require(isinstance(prior, dict) and prior.get("schemaVersion") == producer.handoff.CANDIDATE_SCHEMA
             and prior.get("targetLocale") == request["targetLocale"]
             and prior.get("englishSourcePackageJsonSha256") == request["englishSourcePackageJsonSha256"]
             and prior.get("anchorManifestSha256") == request["anchorManifestSha256"],
             "group_revision_prior_candidate_belongs_to_another_source")
    producer.handoff.validate_target_candidate(source, anchor, prior, require_human_approval=False)
    if prior["translationPolicySha256"] == request["translationPolicySha256"]:
        prior_policy, prior_rules = policy, None
    else:
        _require(loaded["priorPolicy"] is not None and loaded["priorRulePreflight"] is not None,
                 "group_revision_policy_changed_requires_prior_policy_and_rule_preflight")
        prior_policy = _load(loaded["priorPolicy"])
        prior_rules = _load(loaded["priorRulePreflight"])
    producer.handoff.validate_policy_binding(prior, prior_policy)
    policy_change = policy_preview.classify_policy_change(prior_policy, policy)
    _require(policy_change["classification"] in ALLOWED_POLICY_CHANGES,
             "group_revision_model_facing_policy_changed")
    for role in ("translator", "reviewer"):
        _require(prior["generation"][role]["model"] == policy[role]["model"]
                 and prior["generation"][role]["promptVersion"] == policy[role]["promptVersion"],
                 "group_revision_model_or_prompt_changed")
    groups = prior["groups"]
    _require([(row["translationGroupId"], row["sourceUnitIds"]) for row in groups]
             == [(row["translationGroupId"], row["sourceUnitIds"]) for row in plan],
             "group_revision_prior_group_plan_differs")
    translator_ids = prior["generation"]["translator"]["requestIds"]
    reviewer_ids = prior["generation"]["reviewer"]["requestIds"]
    # The runner admits one translator and one reviewer request per group, in group order.
    _require(len(translator_ids) == len(groups) == len(reviewer_ids)
             and len(set(translator_ids)) == len(groups) == len(set(reviewer_ids)),
             "group_revision_prior_request_ids_not_per_group")
    listed = _resolve_groups(loaded["groups"], plan)
    listed_indices = {row["group"] for row in listed}
    rule_change = _rule_change(prior_rules, rule_receipt, request,
                               policy_change["priorPolicySha256"], plan)
    evaluated = producer.evaluate_plugin_groups(
        policy, request, plugin_path, policy["languageReview"]["pluginImplementationSha256"],
        [{key: row[key] for key in ("translationGroupId", "sourceUnitIds", "targetUtterances")}
         for row in groups])
    failing = {index for index, review in enumerate(evaluated["groupReviews"], 1) if review["status"] != "pass"}
    required = sorted((failing | set(rule_change["groupsWithChangedRules"])) - listed_indices)
    gate = {"schemaVersion": GATE_SCHEMA, "targetLocale": request["targetLocale"],
            "priorCandidateJsonSha256": policy_tools.canonical_sha256(prior),
            "priorPolicySha256": policy_change["priorPolicySha256"],
            "translationPolicySha256": request["translationPolicySha256"],
            "pluginImplementationSha256": evaluated["pluginImplementationSha256"],
            "pluginVersion": evaluated["pluginVersion"],
            "groupsChecked": len(groups), "listedGroups": sorted(listed_indices),
            "pluginFailures": [{"group": index, "translationGroupId": plan[index - 1]["translationGroupId"],
                                "listed": index in listed_indices,
                                "failedChecks": [check["checkId"] for check in
                                                 evaluated["groupReviews"][index - 1]["checks"]
                                                 if check["status"] != "pass"]}
                               for index in sorted(failing)],
            "groupsWithChangedRules": rule_change["groupsWithChangedRules"],
            "unlistedFailures": [{"group": index, "translationGroupId": plan[index - 1]["translationGroupId"],
                                  "reasons": [reason for reason, hit in (
                                      ("language_plugin_failed", index in failing),
                                      ("group_model_rules_changed", index in rule_change["groupsWithChangedRules"]))
                                              if hit]}
                                 for index in required],
            "status": "blocked" if required else "pass", "modelCalls": 0, "humanApproval": False}
    if gate_report_path is not None:
        gate_report_path.parent.mkdir(parents=True, exist_ok=True)
        if gate_report_path.exists():
            _require(_load(gate_report_path) == gate, "group_revision_gate_report_changed")
        else:
            runner.save_new(gate_report_path, gate)
    if required:
        raise GroupRevisionGateFailed(gate, gate_report_path)
    revise, carry, carried_rows = [], [], []
    notes = {row["group"]: row["note"] for row in listed}
    for index, row in enumerate(groups, 1):
        text = "".join(row["targetUtterances"])
        if index in listed_indices:
            revise.append({"translationGroupId": row["translationGroupId"], "sourceUnitIds": row["sourceUnitIds"],
                           "priorTargetText": text, "priorTargetTextSha256": _text_sha256(text),
                           "note": notes[index]})
            continue
        evidence_row = {"translationGroupId": row["translationGroupId"], "sourceUnitIds": row["sourceUnitIds"],
                        "targetUtterances": copy.deepcopy(row["targetUtterances"]),
                        "coverage": copy.deepcopy(row["coverage"]),
                        "semanticReview": copy.deepcopy(row["semanticReview"]),
                        "translatorRequestId": translator_ids[index - 1],
                        "reviewerRequestId": reviewer_ids[index - 1]}
        carry.append(evidence_row)
        carried_rows.append({"group": index, "translationGroupId": row["translationGroupId"],
                             "targetTextSha256": _text_sha256(text),
                             "priorGroupSha256": policy_tools.canonical_sha256(row),
                             "evidenceRowSha256": policy_tools.canonical_sha256(evidence_row)})
    brief = {"schemaVersion": runner.OPERATOR_REVISION_SCHEMA,
             **{key: request[key] for key in ("targetLocale", "englishSourcePackageJsonSha256",
                                              "anchorManifestSha256", "translationPolicySha256")},
             "priorCandidateJsonSha256": policy_tools.canonical_sha256(prior),
             "revise": revise, "carry": carry}
    decision = decision_row(loaded["decisionsFile"], loaded["decisionRowSha256"], prior_file_sha256)
    record = {"requestSha256": identity(loaded), "briefSha256": policy_tools.canonical_sha256(brief),
              "decisionRowSha256": loaded["decisionRowSha256"]}
    return {"request": request, "brief": brief, "prior": prior, "listed": listed,
            "carried": carried_rows, "priorCandidateJsonSha256": brief["priorCandidateJsonSha256"],
            "priorCandidateFileSha256": prior_file_sha256, "policyChange": policy_change,
            "ruleChange": rule_change, "gate": gate, "decision": decision,
            "decisionRowSha256": loaded["decisionRowSha256"],
            # The repair loop starts a chain of its own for this record (auto_repair.drive lineage_extra).
            "lineageExtra": {"groupRevisionSha256": policy_tools.canonical_sha256(record)}}


# ---------------------------------------------------------------- allowance


def allowance(listed_groups: int, policy: dict, remaining_cost_microusd: int | None) -> dict:
    """The repair allowance: sized from the listed groups, never from the initial round's calls.

    Each listed group may spend ``REPAIR_PAIRS_PER_LISTED_GROUP`` repair pairs, reserved at the
    worst case per call the loop enforces (``auto_repair._repair_token_bound``). The budget
    authorization's remaining USD cap bounds it again: the listed groups' first pairs are
    reserved first, the remainder buys repair pairs, each at the worst-case cost of the bound
    request limits. ``None`` for the USD cap means no budget transport is bound (offline tests
    only); production workers always pass the authorization's remaining amount."""
    from ..compute import provider_limits as limits
    from .budget import CURRENT_LIMITS
    _require(type(listed_groups) is int and listed_groups > 0, "group_revision_allowance_needs_groups")
    listed_pairs = listed_groups * REPAIR_PAIRS_PER_LISTED_GROUP
    token_bound = auto_repair._repair_token_bound()
    pair_cost = usd_pairs = None
    if remaining_cost_microusd is not None:
        selected = CURRENT_LIMITS.get()
        _require(type(remaining_cost_microusd) is int and remaining_cost_microusd >= 0 and selected is not None,
                 "group_revision_allowance_needs_bounded_cost")
        selected = limits.validate_request_limits(selected)
        pair_cost = sum(limits._cost(policy[role]["model"], selected["maxInputTokens"],
                                     selected["maxCompletionTokens"]) for role in ("translator", "reviewer"))
        usd_pairs = max(0, remaining_cost_microusd // pair_cost - listed_groups)
    pairs = listed_pairs if usd_pairs is None else min(listed_pairs, usd_pairs)
    calls = pairs * auto_repair.CALLS_PER_REPAIR
    return {"basis": "operator_listed_groups", "listedGroups": listed_groups,
            "repairPairsPerListedGroup": REPAIR_PAIRS_PER_LISTED_GROUP,
            "pairs": pairs, "calls": calls, "tokens": calls * token_bound if token_bound is not None else 0,
            "worstCaseTokensPerCall": token_bound, "worstCasePairCostMicrousd": pair_cost,
            "remainingCostMicrousdAtStart": remaining_cost_microusd,
            "usdCap": "budget_authorization" if remaining_cost_microusd is not None else "not_bound"}


# ---------------------------------------------------------------- result


def verify_candidate(prepared: dict, candidate: dict) -> list[dict]:
    """Every unlisted group's target bytes and model evidence are the prior candidate's."""
    prior = prepared["prior"]
    _require(len(candidate["groups"]) == len(prior["groups"]), "group_revision_group_count_changed")
    carried = {row["group"] for row in prepared["carried"]}
    kept = ("translationGroupId", "sourceUnitIds", "targetUtterances", "coverage", "semanticReview", "targetText")
    rows = []
    for index, (before, after) in enumerate(zip(prior["groups"], candidate["groups"]), 1):
        if index in carried:
            _require(all(before[key] == after[key] for key in kept),
                     f"group_revision_unlisted_group_changed: {index}")
            _require(candidate["generation"]["translator"]["requestIds"][index - 1]
                     == prior["generation"]["translator"]["requestIds"][index - 1]
                     and candidate["generation"]["reviewer"]["requestIds"][index - 1]
                     == prior["generation"]["reviewer"]["requestIds"][index - 1],
                     f"group_revision_unlisted_group_evidence_changed: {index}")
        else:
            rows.append({"group": index, "translationGroupId": after["translationGroupId"],
                         "priorTargetTextSha256": _text_sha256(before["targetText"]),
                         "targetTextSha256": _text_sha256(after["targetText"]),
                         "targetTextChanged": before["targetText"] != after["targetText"],
                         "translatorRequestId": candidate["generation"]["translator"]["requestIds"][index - 1],
                         "reviewerRequestId": candidate["generation"]["reviewer"]["requestIds"][index - 1]})
    return rows


def receipt(prepared: dict, candidate: dict, repair_receipt: dict, revision_allowance: dict, *,
            job_id: str | None = None) -> dict:
    """The revision record: what was listed and why, what was carried and from where, and the result."""
    revised = verify_candidate(prepared, candidate)
    notes = {row["group"]: row["note"] for row in prepared["listed"]}
    record = {"schemaVersion": RECEIPT_SCHEMA, "status": "revised_machine_review_pass_human_review_pending",
            "targetLocale": candidate["targetLocale"],
            "englishSourcePackageJsonSha256": candidate["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": candidate["anchorManifestSha256"],
            "priorCandidateJsonSha256": prepared["priorCandidateJsonSha256"],
            "priorCandidateFileSha256": prepared["priorCandidateFileSha256"],
            "priorPolicySha256": prepared["policyChange"]["priorPolicySha256"],
            "translationPolicySha256": candidate["translationPolicySha256"],
            "policyChange": prepared["policyChange"], "ruleChange": prepared["ruleChange"],
            "pluginGateSha256": policy_tools.canonical_sha256(prepared["gate"]),
            "operatorDecision": {"rowSha256": prepared["decisionRowSha256"],
                                 "decidedBy": prepared["decision"]["decidedBy"],
                                 "at": prepared["decision"]["at"],
                                 "channel": prepared["decision"].get("channel"),
                                 "question": prepared["decision"]["question"][:500],
                                 "choice": prepared["decision"]["choice"][:500]},
            "revisedGroups": [{**row, "noteSha256": _text_sha256(notes[row["group"]])
                               if notes[row["group"]] else None} for row in revised],
            "carriedGroups": prepared["carried"],
            "carriedFrom": {"priorCandidateJsonSha256": prepared["priorCandidateJsonSha256"],
                            "modelCalls": 0, "reReviewed": False,
                            "languagePlugin": "rerun_under_current_policy"},
            "repairAllowance": revision_allowance,
            "repairReceiptSha256": policy_tools.canonical_sha256(repair_receipt),
            "repairLedgerHeadSha256": repair_receipt["ledgerHeadSha256"],
            "lineage": repair_receipt["lineage"],
            "candidateJsonSha256": policy_tools.canonical_sha256(candidate),
            **({"jobId": job_id} if job_id is not None else {}),
            "downstreamTextQc": "required_on_final_candidate",
            "releaseEligible": False, "humanApproval": False, "reviewKind": "machine_review"}
    _validate_schema(record, RECEIPT_SCHEMA + ".schema.json", "invalid_group_revision_receipt")
    return record
