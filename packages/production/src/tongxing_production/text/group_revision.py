"""Layer 2 revision by group ID: translate only the groups an operator listed.

Design: docs/canonical-layer2-controller.zh.md (按组号修订). The only required input
is a prior source and the groups to revise, each with an optional note, plus the
operator decision row that produced the list. The prior source is an admitted
candidate, or a runner round directory (for example a failed repair round whose
other groups passed review), whose caches are each checked against their saved
raw responses. Listed groups get a new
paid translator request, an independent reviewer request and the plugin check,
in parallel, inside the bounded repair loop. Every other group keeps its exact
target bytes and its prior translator/reviewer evidence, carried by hash from the
named prior source, with no model call and no re-review.

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
REQUIRED_KEYS = frozenset({"schemaVersion", "targetLocale", "groups", "decision"})
OPTIONAL_KEYS = frozenset({"priorCandidate", "priorRound", "priorPolicy", "priorRulePreflight"})


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

    The prior source is exactly one of ``priorCandidate`` (an admitted candidate) or
    ``priorRound`` (a runner round directory, such as a failed repair round whose other
    groups passed). ``groups`` lists 1-based group numbers (the ``group-NNNN`` of the run
    files) or exact ``translationGroupId`` strings, each optionally ``{"group": ..., "note": "..."}``.
    ``decision`` names the run's ``decisions.ndjson`` and the canonical SHA-256 of the
    ``record_decision.py`` row that produced the list."""
    path = Path(path).absolute()
    value = _load(path)
    _validate_schema(value, REQUEST_SCHEMA + ".schema.json", "invalid_group_revision_request")
    _require(isinstance(value, dict) and REQUIRED_KEYS <= set(value) <= REQUIRED_KEYS | OPTIONAL_KEYS
             and value["schemaVersion"] == REQUEST_SCHEMA
             and isinstance(value["targetLocale"], str) and value["targetLocale"]
             and isinstance(value["groups"], list) and value["groups"]
             and (("priorCandidate" in value) != ("priorRound" in value))
             and ("priorRulePreflight" not in value or "priorCandidate" in value)
             and all(isinstance(value.get(key, "x"), str) and value.get(key, "x")
                     for key in ("priorCandidate", "priorRound", "priorPolicy", "priorRulePreflight")),
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
            "priorCandidate": resolve("priorCandidate"), "priorRound": resolve("priorRound"),
            "priorPolicy": resolve("priorPolicy"), "priorRulePreflight": resolve("priorRulePreflight"),
            "decisionsFile": (path.parent / decision["decisionsFile"]).resolve(),
            "decisionRowSha256": decision["rowSha256"]}


def input_paths(loaded: dict) -> list[Path]:
    return [item for item in (loaded["path"], loaded["priorCandidate"], loaded["priorRound"], loaded["priorPolicy"],
                              loaded["priorRulePreflight"], loaded["decisionsFile"]) if item is not None]


ROUND_FILES = ("request.json", "rule-preflight.json", "group-failures.json", "evidence.json")


def round_manifest(round_dir: Path) -> dict:
    """SHA-256 of every file a prior round contributes: its request, rules, report and model caches."""
    round_dir = Path(round_dir)
    _require(round_dir.is_dir() and not round_dir.is_symlink() and (round_dir / "request.json").is_file(),
             "group_revision_prior_round_missing")
    names = [name for name in ROUND_FILES if (round_dir / name).is_file()] + sorted(
        path.name for path in round_dir.glob("group-*.json")
        if path.name.endswith(("-astra.json", "-sol.json", "-astra.raw.json", "-sol.raw.json", ".started.json")))
    return {name: _file_sha256(round_dir / name) for name in names}


def identity(loaded: dict) -> str:
    """The request and the bytes of every prior file it names: a new list or note is a new job.

    The decision binds by its row hash only: ``decisions.ndjson`` is append-only, and later
    rows recorded during the run must not change this job's identity."""
    files = {name: _file_sha256(loaded[name]) if loaded[name] is not None else None
             for name in ("priorCandidate", "priorPolicy", "priorRulePreflight")}
    if loaded["priorRound"] is not None:
        files["priorRound"] = policy_tools.canonical_sha256(round_manifest(loaded["priorRound"]))
    return policy_tools.canonical_sha256({"request": loaded["value"], "files": files})


def decision_row(decisions_file: Path, row_sha256: str, governed_sha256s: set[str]) -> dict:
    """The record_decision.py row, artifact-bound to the prior source's exact bytes."""
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
             and any(isinstance(item, dict) and item.get("sha256") in governed_sha256s
                     for item in row["governs"])
             and all(isinstance(row.get(key), str) and row[key].strip()
                     for key in ("at", "question", "choice", "decidedBy")),
             "group_revision_decision_does_not_govern_prior_source")
    return row


# ---------------------------------------------------------------- prior source


def _passed(semantic: dict) -> bool:
    return (semantic.get("status") == "pass" and all(value == "pass" for value in semantic["checks"].values())
            and not semantic.get("uncertainty") and not semantic.get("issues"))


def _evidence_row(group: dict, utterances: list, coverage: list, semantic: dict,
                  translator_id: str, reviewer_id: str) -> dict:
    return {"translationGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"],
            "targetUtterances": copy.deepcopy(utterances), "coverage": copy.deepcopy(coverage),
            "semanticReview": copy.deepcopy(semantic),
            "translatorRequestId": translator_id, "reviewerRequestId": reviewer_id}


def _prior_candidate(loaded: dict, source: dict, anchor: dict, request: dict, plan: list[dict]) -> dict:
    path = loaded["priorCandidate"]
    prior = _load(path)
    _require(isinstance(prior, dict) and prior.get("schemaVersion") == producer.handoff.CANDIDATE_SCHEMA
             and prior.get("targetLocale") == request["targetLocale"]
             and prior.get("englishSourcePackageJsonSha256") == request["englishSourcePackageJsonSha256"]
             and prior.get("anchorManifestSha256") == request["anchorManifestSha256"],
             "group_revision_prior_source_belongs_to_another_source")
    producer.handoff.validate_target_candidate(source, anchor, prior, require_human_approval=False)
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
    rows = {index: _evidence_row(plan[index - 1], row["targetUtterances"], row["coverage"], row["semanticReview"],
                                 translator_ids[index - 1], reviewer_ids[index - 1])
            for index, row in enumerate(groups, 1)}
    return {"kind": "candidate", "sha256": policy_tools.canonical_sha256(prior),
            "governedSha256s": {_file_sha256(path)}, "policySha256": prior["translationPolicySha256"],
            "models": {role: prior["generation"][role] for role in ("translator", "reviewer")},
            "candidate": prior, "rows": rows, "unusable": {}, "caches": {},
            "rulePreflight": _load(loaded["priorRulePreflight"]) if loaded["priorRulePreflight"] else None}


def _prior_round(loaded: dict, request: dict, plan: list[dict], policy: dict) -> dict:
    """Reviewed rows from a runner round's caches, each backed by its saved raw response.

    A group whose caches are missing, malformed or whose review did not pass has no row to
    carry (``unusable``); it must be listed. A started call with neither cache nor raw
    response is an unknown paid outcome and stops the revision before anything else."""
    round_dir = loaded["priorRound"]
    manifest = round_manifest(round_dir)
    prior_request = _load(round_dir / "request.json")
    _require(isinstance(prior_request, dict)
             and all(prior_request.get(key) == request[key] for key in (
                 "schemaVersion", "sourceLocale", "targetLocale", "englishSourcePackageJsonSha256",
                 "anchorManifestSha256", "sourceUnits")),
             "group_revision_prior_source_belongs_to_another_source")
    for name in manifest:
        if name.endswith(".started.json"):
            stem = name.removesuffix(".started.json")
            _require(stem + ".json" in manifest or stem + ".raw.json" in manifest,
                     "group_revision_prior_round_has_unknown_outcome")
    rows, unusable, caches = {}, {}, {}
    for index, group in enumerate(plan, 1):
        stem = f"group-{index:04d}"
        names = {role: f"{stem}-{suffix}.json" for role, suffix in (("translator", "astra"), ("reviewer", "sol"))}
        if not all(name in manifest for name in names.values()):
            unusable[index] = "no_prior_result"
            continue
        saved = {role: _load(round_dir / name) for role, name in names.items()}
        for role, name in names.items():
            raw_name = name.removesuffix(".json") + ".raw.json"
            raw = _load(round_dir / raw_name) if raw_name in manifest else None
            response = raw.get("response") if isinstance(raw, dict) else None
            _require(isinstance(saved[role], dict) and saved[role].get("model") == policy[role]["model"]
                     and isinstance(saved[role].get("requestId"), str) and saved[role]["requestId"]
                     and isinstance(response, dict) and response.get("id") == saved[role]["requestId"]
                     and raw.get("payloadSha256") == saved[role].get("payloadSha256"),
                     f"group_revision_prior_round_cache_not_backed_by_response: {name}")
        result = saved["reviewer"].get("result")
        try:
            _require(isinstance(result, dict) and result.get("translationGroupId") == group["translationGroupId"]
                     and result.get("sourceUnitIds") == group["sourceUnitIds"], "identity")
            utterances = runner._utterances(result.get("targetUtterances"), group["sourceUnitIds"])
            coverage = result.get("coverage")
            text = "".join(utterances)
            _require(isinstance(coverage, list)
                     and [row.get("sourceUnitId") for row in coverage] == group["sourceUnitIds"]
                     and all(isinstance(row.get("targetText"), str) and runner._coverage_substring(row["targetText"], text)
                             for row in coverage), "coverage")
            semantic = runner.normalize_semantic_review(result.get("semanticReview"))
            _require(isinstance(semantic, dict) and isinstance(semantic.get("checks"), dict)
                     and set(semantic["checks"]) == set(runner.SEMANTIC_CHECKS)
                     and isinstance(semantic.get("evidence"), str) and semantic["evidence"].strip()
                     and isinstance(semantic.get("uncertainty"), list) and isinstance(semantic.get("issues"), list),
                     "review")
        except ValueError:
            unusable[index] = "prior_result_malformed"
            continue
        rows[index] = _evidence_row(group, utterances, coverage, semantic,
                                    saved["translator"]["requestId"], saved["reviewer"]["requestId"])
        caches[index] = {role: manifest[name] for role, name in names.items()}
        if not _passed(semantic):
            unusable[index] = "independent_review_failed"
    governed = {manifest["request.json"]} | ({manifest["group-failures.json"]} if "group-failures.json" in manifest
                                            else set())
    return {"kind": "round", "sha256": policy_tools.canonical_sha256(manifest), "governedSha256s": governed,
            "policySha256": prior_request["translationPolicySha256"], "models": None, "candidate": None,
            "rows": rows, "unusable": unusable, "caches": caches,
            "rulePreflight": _load(round_dir / "rule-preflight.json")
            if (round_dir / "rule-preflight.json").is_file() else None}


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

    Raises GroupRevisionGateFailed (after writing its report) when a group the operator did not
    list cannot be carried: the prior source has no passing reviewed result for it, the current
    plugin rejects it, or its own quote rules changed."""
    request = producer.prepare_request(source, anchor, policy)
    _require(loaded["value"]["targetLocale"] == request["targetLocale"], "group_revision_locale_differs")
    plan = runner.group_plan(request, anchor)
    prior = (_prior_candidate(loaded, source, anchor, request, plan) if loaded["priorCandidate"] is not None
             else _prior_round(loaded, request, plan, policy))
    if prior["policySha256"] == request["translationPolicySha256"]:
        prior_policy = policy
    else:
        _require(loaded["priorPolicy"] is not None and prior["rulePreflight"] is not None,
                 "group_revision_policy_changed_requires_prior_policy_and_rule_preflight")
        prior_policy = _load(loaded["priorPolicy"])
    _require(policy_tools.canonical_sha256(prior_policy) == prior["policySha256"],
             "group_revision_prior_policy_differs")
    if prior["candidate"] is not None:
        producer.handoff.validate_policy_binding(prior["candidate"], prior_policy)
    policy_change = policy_preview.classify_policy_change(prior_policy, policy)
    _require(policy_change["classification"] in ALLOWED_POLICY_CHANGES,
             "group_revision_model_facing_policy_changed")
    for role, receipt_value in (prior["models"] or {}).items():
        _require(receipt_value["model"] == policy[role]["model"]
                 and receipt_value["promptVersion"] == policy[role]["promptVersion"],
                 "group_revision_model_or_prompt_changed")
    listed = _resolve_groups(loaded["groups"], plan)
    listed_indices = {row["group"] for row in listed}
    rule_change = _rule_change(prior["rulePreflight"], rule_receipt, request,
                               policy_change["priorPolicySha256"], plan)
    rows = prior["rows"]
    checked = sorted(rows)
    evaluated = producer.evaluate_plugin_groups(
        policy, request, plugin_path, policy["languageReview"]["pluginImplementationSha256"],
        [{key: rows[index][key] for key in ("translationGroupId", "sourceUnitIds", "targetUtterances")}
         for index in checked]) if checked else {"groupReviews": [], "pluginVersion": None,
                                                 "pluginImplementationSha256": None}
    reviews = dict(zip(checked, evaluated["groupReviews"]))
    failing = {index for index, review in reviews.items() if review["status"] != "pass"}

    def reasons(index: int) -> list[str]:
        return [reason for reason, hit in (
            (prior["unusable"].get(index), index in prior["unusable"]),
            ("language_plugin_failed", index in failing),
            ("group_model_rules_changed", index in rule_change["groupsWithChangedRules"])) if hit]

    required = [index for index in range(1, len(plan) + 1) if index not in listed_indices and reasons(index)]
    gate = {"schemaVersion": GATE_SCHEMA, "targetLocale": request["targetLocale"],
            "priorSource": {"kind": prior["kind"], "sha256": prior["sha256"]},
            "priorPolicySha256": policy_change["priorPolicySha256"],
            "translationPolicySha256": request["translationPolicySha256"],
            "pluginImplementationSha256": evaluated["pluginImplementationSha256"],
            "pluginVersion": evaluated["pluginVersion"],
            "groupsChecked": len(checked), "totalGroups": len(plan), "listedGroups": sorted(listed_indices),
            "priorUnusable": [{"group": index, "reason": reason} for index, reason in sorted(prior["unusable"].items())],
            "pluginFailures": [{"group": index, "translationGroupId": plan[index - 1]["translationGroupId"],
                                "listed": index in listed_indices,
                                "failedChecks": [check["checkId"] for check in reviews[index]["checks"]
                                                 if check["status"] != "pass"]}
                               for index in sorted(failing)],
            "groupsWithChangedRules": rule_change["groupsWithChangedRules"],
            "unlistedFailures": [{"group": index, "translationGroupId": plan[index - 1]["translationGroupId"],
                                  "reasons": reasons(index)} for index in required],
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
    for index, group in enumerate(plan, 1):
        row = rows.get(index)
        if index in listed_indices:
            text = "".join(row["targetUtterances"]) if row is not None else None
            revise.append({"translationGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"],
                           "priorTargetText": text, "priorTargetTextSha256": _text_sha256(text) if text else None,
                           "note": notes[index]})
            continue
        carry.append(row)
        carried_rows.append({"group": index, "translationGroupId": group["translationGroupId"],
                             "targetTextSha256": _text_sha256("".join(row["targetUtterances"])),
                             "priorGroupSha256": policy_tools.canonical_sha256(
                                 prior["candidate"]["groups"][index - 1]) if prior["candidate"] is not None
                             else policy_tools.canonical_sha256(row),
                             "evidenceRowSha256": policy_tools.canonical_sha256(row),
                             **({"priorCacheSha256": prior["caches"][index]} if index in prior["caches"] else {})})
    brief = {"schemaVersion": runner.OPERATOR_REVISION_SCHEMA,
             **{key: request[key] for key in ("targetLocale", "englishSourcePackageJsonSha256",
                                              "anchorManifestSha256", "translationPolicySha256")},
             "priorSourceSha256": prior["sha256"], "revise": revise, "carry": carry}
    decision = decision_row(loaded["decisionsFile"], loaded["decisionRowSha256"], prior["governedSha256s"])
    record = {"requestSha256": identity(loaded), "briefSha256": policy_tools.canonical_sha256(brief),
              "decisionRowSha256": loaded["decisionRowSha256"]}
    return {"request": request, "brief": brief, "prior": prior, "listed": listed, "carried": carried_rows,
            "priorSource": {"kind": prior["kind"], "sha256": prior["sha256"]},
            "policyChange": policy_change, "ruleChange": rule_change, "gate": gate, "decision": decision,
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
    """Every unlisted group's target bytes and model evidence are the prior source's."""
    rows = prepared["prior"]["rows"]
    _require(len(candidate["groups"]) == len(prepared["brief"]["revise"]) + len(prepared["carried"]),
             "group_revision_group_count_changed")
    carried = {row["group"] for row in prepared["carried"]}
    ids = {role: candidate["generation"][role]["requestIds"] for role in ("translator", "reviewer")}
    revised = []
    for index, after in enumerate(candidate["groups"], 1):
        before = rows.get(index)
        if index in carried:
            _require(all(before[key] == after[key] for key in (
                         "translationGroupId", "sourceUnitIds", "targetUtterances", "coverage", "semanticReview"))
                     and after["targetText"] == "".join(before["targetUtterances"]),
                     f"group_revision_unlisted_group_changed: {index}")
            _require(ids["translator"][index - 1] == before["translatorRequestId"]
                     and ids["reviewer"][index - 1] == before["reviewerRequestId"],
                     f"group_revision_unlisted_group_evidence_changed: {index}")
            continue
        prior_text = "".join(before["targetUtterances"]) if before is not None else None
        revised.append({"group": index, "translationGroupId": after["translationGroupId"],
                        "priorTargetTextSha256": _text_sha256(prior_text) if prior_text else None,
                        "targetTextSha256": _text_sha256(after["targetText"]),
                        "targetTextChanged": prior_text != after["targetText"],
                        "translatorRequestId": ids["translator"][index - 1],
                        "reviewerRequestId": ids["reviewer"][index - 1]})
    return revised


def receipt(prepared: dict, candidate: dict, repair_receipt: dict, revision_allowance: dict, *,
            job_id: str | None = None) -> dict:
    """The revision record: what was listed and why, what was carried and from where, and the result."""
    revised = verify_candidate(prepared, candidate)
    notes = {row["group"]: row["note"] for row in prepared["listed"]}
    record = {"schemaVersion": RECEIPT_SCHEMA, "status": "revised_machine_review_pass_human_review_pending",
              "targetLocale": candidate["targetLocale"],
              "englishSourcePackageJsonSha256": candidate["englishSourcePackageJsonSha256"],
              "anchorManifestSha256": candidate["anchorManifestSha256"],
              "priorSource": prepared["priorSource"],
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
              "carriedFrom": {"priorSourceSha256": prepared["priorSource"]["sha256"],
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
