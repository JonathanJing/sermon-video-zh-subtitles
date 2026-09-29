#!/usr/bin/env python3
"""Source-bound, non-production Layer 2 translator comparison.

Run with ``python -m scripts.experiments.layer2_ab --help``. The three arms
share one approved English source, group plan, policy body, prompts, reasoning
effort, and independent Sol reviewer. Only the translator model differs.
Outputs contain model text and belong in ignored artifacts, never in Git.
This tool creates no formal candidate, human approval, audio, or release.
Arm A is a contemporaneous controlled baseline with the same neutral reviewer
prompt as B/C; it is not byte-equivalent to the production runner's prompt.
Repeat the same command to resume after an intentional call/group limit. Never
run two processes against the same output directory at once.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import subprocess
import time
from typing import Any, Callable

from scripts import produce_target_language_candidate as producer
from scripts import run_target_language_models as production
from scripts import sermon_pipeline
from scripts import target_language_policy as policy_tools


MODELS = {"A": "gpt-6-astra", "B": "gpt-6-sol", "C": "gpt-6-luna"}
REVIEWER = "gpt-6-sol"
MAX_GROUPS_PER_INVOCATION = 10
MAX_API_CALLS_PER_INVOCATION = 60
LEGACY_HARNESS_SHA256 = "3f6970633a5b86bb4ec8e6e6544fe6f76a461b7118dde0c81ccb4a00821c6671"


class ExperimentPaused(Exception):
    """A deliberate batch limit, with completed responses left reusable."""


def _write_snapshot(path: Path, value: object) -> None:
    """Replace only mutable summaries; paid response artifacts stay immutable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp.json")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _check_run_identity(out: Path, identity: dict[str, Any]) -> dict[str, Any] | None:
    path = out / "run-identity.json"
    if not path.exists():
        production.require(not out.exists() or not any(out.iterdir()),
                           "Output directory is not empty and has no identity")
        production.save_new(path, identity)
        return None
    existing = producer._load(path)
    if existing == identity:
        return None
    old = {key: value for key, value in existing.items()
           if key not in {"schemaVersion", "harnessSha256"}}
    new = {key: value for key, value in identity.items()
           if key not in {"schemaVersion", "harnessSha256"}}
    production.require(existing.get("schemaVersion") == "layer2-ab-run-v1"
                       and existing.get("harnessSha256") == LEGACY_HARNESS_SHA256
                       and old == new,
                       "Run identity changed beyond the reviewed failure-handling migration")
    migration = {"schemaVersion": "layer2-ab-identity-migration-v1",
                 "fromHarnessSha256": LEGACY_HARNESS_SHA256,
                 "toHarnessSha256": identity["harnessSha256"],
                 "unchangedPayloadIdentitySha256": policy_tools.canonical_sha256(new),
                 "reason": "Preserve existing responses while adding per-arm validation failures and partial summaries"}
    _save_or_check(out / "run-identity-migration.json", migration)
    _save_or_check(out / "run-identity-v2.json", identity)
    return migration
TRANSLATOR_INSTRUCTION = (
    "Translate the English sermon group into the target locale. Preserve every "
    "meaning, negation, number, name, quotation and theological distinction. "
    "Use context only for interpretation. Return JSON with exactly "
    "translationGroupId, sourceUnitIds, targetUtterances and coverage. "
    "Coverage has one sourceUnitId and exact targetText substring per source unit. "
    "Do not claim human approval. Prompt version: "
)
REVIEWER_INSTRUCTION = (
    "Independently compare the English source and the draft, one group at a time. "
    "Correct any error in final targetUtterances and coverage. Check every English "
    "unit for omitted or added meaning, negations, numbers, names, and quotation "
    "attribution. If uncertain or unresolved, mark fail. Return JSON with exactly "
    "translationGroupId, sourceUnitIds, targetUtterances, coverage, semanticReview. "
    "semanticReview has status, checks (completeMeaning, negationsNumbersNames, "
    "quotationAttribution, noAddedMeaning), evidence, uncertainty, issues. "
    "Each check value must be the string pass or fail. uncertainty and issues "
    "must be arrays of unresolved concerns only; if you correct a draft "
    "issue in the final text, describe that correction in evidence and leave "
    "issues empty. Mark status fail for any unresolved concern. "
    "Do not claim human approval. Prompt version: "
)


def _save_or_check(path: Path, value: object) -> None:
    if path.exists():
        production.require(producer._load(path) == value, f"Existing artifact changed: {path}")
    else:
        production.save_new(path, value)


def _arm_policy(base: dict[str, Any], model: str) -> dict[str, Any]:
    policy = copy.deepcopy(base)
    policy["translator"]["model"] = model
    policy["reviewer"]["model"] = REVIEWER
    # The experiment interleaves requests serially; record that execution mode
    # in every derived policy instead of inheriting a production worker count.
    policy["batching"]["workers"] = 1
    for role in ("translator", "reviewer"):
        policy["componentSha256"][role] = policy_tools.canonical_sha256(policy[role])
    policy["componentSha256"]["batching"] = policy_tools.canonical_sha256(policy["batching"])
    return policy


def _same_except_model(policies: dict[str, dict[str, Any]]) -> None:
    shared = []
    for policy in policies.values():
        body = copy.deepcopy(policy)
        body["translator"].pop("model")
        body["componentSha256"].pop("translator")
        shared.append(body)
    production.require(all(body == shared[0] for body in shared),
                       "Experimental arms differ beyond translator model")


def _validate_group(result: dict[str, Any], group: dict[str, Any], *, reviewer: bool) -> bool:
    production.require(result.get("translationGroupId") == group["translationGroupId"]
                       and result.get("sourceUnitIds") == group["sourceUnitIds"],
                       "Model changed group identity")
    target = "".join(production._utterances(result.get("targetUtterances")))
    coverage = result.get("coverage")
    production.require(isinstance(coverage, list)
                       and [row.get("sourceUnitId") for row in coverage] == group["sourceUnitIds"]
                       and all(isinstance(row.get("targetText"), str)
                               and production._coverage_substring(row["targetText"], target)
                               for row in coverage), "Model coverage is incomplete")
    if not reviewer:
        return True
    semantic = production.normalize_semantic_review(result.get("semanticReview"))
    production.require(isinstance(semantic, dict)
                       and semantic.get("status") in {"pass", "fail"}
                       and isinstance(semantic.get("checks"), dict)
                       and set(semantic["checks"]) == set(production.SEMANTIC_CHECKS)
                       and all(value in {"pass", "fail"} for value in semantic["checks"].values())
                       and isinstance(semantic.get("evidence"), str)
                       and semantic["evidence"].strip()
                       and isinstance(semantic.get("uncertainty"), list)
                       and isinstance(semantic.get("issues"), list),
                       "Reviewer semantic review is incomplete")
    return (semantic["status"] == "pass"
            and all(value == "pass" for value in semantic["checks"].values())
            and not semantic["uncertainty"] and not semantic["issues"])


def _call_with_receipt(role: str, prompt: dict[str, Any], policy: dict[str, Any],
                       path: Path, key: str, caller: Callable,
                       clock: Callable[[], float], budget: dict[str, int]) -> dict[str, Any]:
    """Use the production raw/cache/started discipline and add API timing."""
    receipt_path = path.with_suffix(".timing.json")
    had_cache = path.exists() or path.with_suffix(".raw.json").exists()
    if had_cache:
        budget["cache_hits"] += 1
    if not had_cache and not path.with_suffix(".started.json").exists() \
            and budget["calls"] >= budget["limit"]:
        raise ExperimentPaused("max_api_calls")
    observed: dict[str, Any] = {}

    def measured(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        budget["calls"] += 1
        started_at = datetime.now(timezone.utc).isoformat()
        start = clock()
        try:
            response = caller(api_key, payload)
            observed.update({"startedAt": started_at,
                             "apiAttempted": True,
                             "elapsedSeconds": round(clock() - start, 6),
                             "responseId": response.get("id") if isinstance(response, dict) else None,
                             "usage": response.get("usage") if isinstance(response, dict) else None})
            return response
        except BaseException:
            observed.update({"startedAt": started_at,
                             "apiAttempted": True,
                             "elapsedSeconds": round(clock() - start, 6),
                             "responseUnconfirmed": True})
            raise

    try:
        saved = production._model_call(role, prompt, policy, path, key, measured)
    finally:
        if observed and not receipt_path.exists():
            production.save_new(receipt_path, observed)
    if not receipt_path.exists():
        raw = producer._load(path.with_suffix(".raw.json"))
        production.save_new(receipt_path, {
            "apiAttempted": False, "cacheRecovered": True,
            "responseId": saved["requestId"],
            "usage": raw["response"].get("usage"), "elapsedSeconds": None})
    else:
        receipt = producer._load(receipt_path)
        if had_cache and receipt.get("responseUnconfirmed"):
            raise ValueError(f"Uncertain call timing; inspect {receipt_path}")
    return saved


def _common(group: dict[str, Any], index: int, plan: list[dict[str, Any]],
            request: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    units = {row["sourceUnitId"]: row["english"] for row in request["sourceUnits"]}
    previous = plan[index - 2]["sourceUnitIds"][-1] if index > 1 else None
    following = plan[index]["sourceUnitIds"][0] if index < len(plan) else None
    return {"translationGroupId": group["translationGroupId"],
            "sourceUnitIds": group["sourceUnitIds"],
            "englishUnits": [{"sourceUnitId": unit_id, "english": units[unit_id]}
                             for unit_id in group["sourceUnitIds"]],
            "context": {"before": units[previous] if previous else "",
                        "after": units[following] if following else ""},
            "targetLocale": request["targetLocale"],
            "terminology": policy["terminology"], "scripture": policy["scripture"],
            "formatting": policy["formatting"]}


def _blind_materials(out: Path, request: dict[str, Any],
                     plan: list[dict[str, Any]], results: dict[str, list[dict[str, Any]]]) -> None:
    key_path = out / "blinding-key.json"
    sheet_path = out / "blind-review.json"
    if key_path.exists() or sheet_path.exists():
        production.require(key_path.exists() and sheet_path.exists(),
                           "Incomplete blinded review bundle")
        return
    lookup: list[dict[str, str]] = []
    sheets: list[dict[str, Any]] = []
    by_arm = {arm: {row["translationGroupId"]: row for row in rows}
              for arm, rows in results.items()}
    excluded = []
    for group in plan:
        missing = [arm for arm in MODELS if group["translationGroupId"] not in by_arm[arm]]
        if missing:
            excluded.append({"translationGroupId": group["translationGroupId"],
                             "missingArms": missing,
                             "availableArms": [arm for arm in MODELS if arm not in missing]})
            continue
        arm_order = list(MODELS)
        secrets.SystemRandom().shuffle(arm_order)
        options = []
        for ordinal, arm in enumerate(arm_order, 1):
            code = f"{group['translationGroupId']}:option-{ordinal}"
            lookup.append({"code": code, "arm": arm})
            row = by_arm[arm][group["translationGroupId"]]
            options.append({"code": code,
                            "draftUtterances": row["draftUtterances"],
                            "reviewedUtterances": row["targetUtterances"],
                            "humanEvaluation": {"draftSemanticErrors": None,
                                                "reviewedSemanticErrors": None,
                                                "editMinutes": None,
                                                "naturalness": None, "notes": None}})
        sheets.append({"translationGroupId": group["translationGroupId"],
                       "englishUnits": _common(group, plan.index(group) + 1, plan, request,
                                               {"terminology": {}, "scripture": {},
                                                "formatting": {}})["englishUnits"],
                       "options": options})
    production.save_new(key_path, {"schemaVersion": "layer2-ab-blinding-key-v1", "codes": lookup})
    production.save_new(sheet_path, {"schemaVersion": "layer2-ab-blind-review-v1",
                                     "targetLocale": request["targetLocale"],
                                     "pairedGroups": len(sheets),
                                     "excludedGroups": excluded, "groups": sheets})


def _wall_timing(out: Path, *, elapsed: float | None = None) -> dict[str, Any]:
    """Sum observed active runs; also expose calendar span including pauses."""
    path = out / "run-wall.json"
    if path.exists():
        data = producer._load(path)
    else:
        data = {"firstStartedAtEpoch": time.time(), "activeWallSeconds": 0.0,
                "completedInvocations": 0}
    if elapsed is not None:
        data["activeWallSeconds"] = round(data["activeWallSeconds"] + max(elapsed, 0), 6)
        data["completedInvocations"] += 1
        temporary = path.with_suffix(".tmp.json")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    elif not path.exists():
        production.save_new(path, data)
    return data


def _receipt_metrics(out: Path, arm: str, groups: int) -> dict[str, Any]:
    receipts = [producer._load(out / f"arm-{arm}" /
                               f"group-{index:04d}-{role}.timing.json")
                for index in range(1, groups + 1)
                for role in ("translator", "reviewer")
                if (out / f"arm-{arm}" /
                    f"group-{index:04d}-{role}.timing.json").is_file()]
    elapsed = sorted(row["elapsedSeconds"] for row in receipts
                     if row.get("apiAttempted") is True
                     and isinstance(row.get("elapsedSeconds"), (int, float)))
    observed_usage = [row["usage"] for row in receipts
                      if isinstance(row.get("usage"), dict)]
    token_names = ("prompt_tokens", "completion_tokens", "total_tokens")
    partial = {name: sum(usage.get(name, 0) for usage in observed_usage)
               for name in token_names}
    return {
        "logicalResponses": sum(
            (out / f"arm-{arm}" / f"group-{index:04d}-{role}.json").is_file()
            or (out / f"arm-{arm}" / f"group-{index:04d}-{role}.raw.json").is_file()
            for index in range(1, groups + 1)
            for role in ("translator", "reviewer")),
        "recordedHttpAttempts": sum(row.get("apiAttempted") is True for row in receipts),
        "cacheRecoveredResponses": sum(row.get("cacheRecovered") is True
                                       for row in receipts),
        "usageObservedResponses": len(observed_usage),
        "usageTotals": partial if len(observed_usage) == len(receipts) else None,
        "usagePartialTotals": partial,
        "usageComplete": len(observed_usage) == len(receipts),
        "apiElapsedSecondsSum": round(sum(elapsed), 6),
        "apiElapsedSecondsP50": round(statistics.median(elapsed), 6) if elapsed else None,
        "apiElapsedSecondsP95": round(elapsed[math.ceil(.95 * len(elapsed)) - 1], 6)
        if elapsed else None,
        "timedHttpAttempts": len(elapsed),
    }


def _failure(out: Path, arm: str, index: int, group: dict[str, Any],
             stage: str, error: Exception, saved: dict[str, Any] | None = None) -> dict[str, Any]:
    path = out / f"arm-{arm}" / f"group-{index:04d}-failure.json"
    if path.exists():
        return producer._load(path)
    response_path = out / f"arm-{arm}" / f"group-{index:04d}-{stage}.json"
    response_id = saved.get("requestId") if saved else None
    if response_id is None and response_path.is_file():
        response_id = producer._load(response_path).get("requestId")
    raw_path = response_path.with_suffix(".raw.json")
    if response_id is None and raw_path.is_file():
        response_id = producer._load(raw_path).get("response", {}).get("id")
    record = {"schemaVersion": "layer2-ab-arm-failure-v1",
              "arm": arm, "translationGroupId": group["translationGroupId"],
              "sourceUnitIds": group["sourceUnitIds"],
              "stage": stage, "errorType": type(error).__name__,
              "reason": str(error)[:240], "responseId": response_id,
              "responseArtifact": str(response_path.relative_to(out))
              if response_path.is_file() else str(raw_path.relative_to(out))}
    production.save_new(path, record)
    return record


def _can_record_model_failure(error: Exception, raw_path: Path) -> bool:
    """Reject cache-identity/config errors; retain malformed paid responses."""
    if not raw_path.is_file():
        return False
    return isinstance(error, json.JSONDecodeError) or (
        isinstance(error, ValueError) and str(error).startswith((
            "translator response", "reviewer response")))


def run(source: dict[str, Any], anchor: dict[str, Any], base_policy: dict[str, Any],
        out: Path, api_key: str, caller: Callable,
        *, custom_plan: list[dict[str, Any]] | None = None,
        plugin_path: Path | None = None,
        max_api_calls: int, max_groups: int,
        clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    production.require(type(max_api_calls) is int and 0 <= max_api_calls <= MAX_API_CALLS_PER_INVOCATION,
                       f"max_api_calls must be 0..{MAX_API_CALLS_PER_INVOCATION}")
    production.require(type(max_groups) is int and 1 <= max_groups <= MAX_GROUPS_PER_INVOCATION,
                       f"max_groups must be 1..{MAX_GROUPS_PER_INVOCATION}")
    # group_plan defines these independent model requests. The frozen policy's
    # batchSize describes its original producer configuration and is held equal
    # across arms; it does not merge source groups in this shadow harness.
    production.require(base_policy["translator"]["reasoningEffort"]
                       == base_policy["reviewer"]["reasoningEffort"],
                       "Freeze a common reasoning effort for the comparison")
    policies = {arm: _arm_policy(base_policy, model) for arm, model in MODELS.items()}
    _same_except_model(policies)
    requests = {arm: producer.prepare_request(source, anchor, policy)
                for arm, policy in policies.items()}
    if plugin_path is not None:
        production.require(producer.plugin_implementation_sha256(plugin_path)
                           == base_policy["languageReview"]["pluginImplementationSha256"],
                           "Language plugin differs from frozen policy")
    plan = production.group_plan(requests["A"], anchor, custom_plan)
    identity = {"schemaVersion": "layer2-ab-run-v2", "sourceHash":
                requests["A"]["englishSourcePackageJsonSha256"],
                "anchorHash": requests["A"]["anchorManifestSha256"],
                "basePolicyHash": policy_tools.canonical_sha256(base_policy),
                "harnessSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "plan": plan, "models": MODELS, "reviewer": REVIEWER,
                "translatorInstruction": TRANSLATOR_INSTRUCTION,
                "reviewerInstruction": REVIEWER_INSTRUCTION}
    migration = _check_run_identity(out, identity)
    comparison_path = out / "comparison.json"
    if comparison_path.exists() and producer._load(comparison_path).get("status") == "shadow_only":
        return producer._load(comparison_path)
    _wall_timing(out)
    invocation_start = clock()
    budget = {"limit": max_api_calls, "calls": 0, "cache_hits": 0}
    touched_groups = 0
    results: dict[str, list[dict[str, Any]]] = {arm: [] for arm in MODELS}
    failures: dict[str, list[dict[str, Any]]] = {arm: [] for arm in MODELS}
    for arm, policy in policies.items():
        arm_dir = out / f"arm-{arm}"
        _save_or_check(arm_dir / "request.json", requests[arm])
        _save_or_check(arm_dir / "experimental-policy.json", policy)

    def finish(status: str, pause_reason: str | None = None) -> dict[str, Any]:
        response_ids = [row[field] for rows in results.values() for row in rows
                        for field in ("translatorResponseId", "reviewerResponseId")]
        production.require(len(response_ids) == len(set(response_ids)),
                           "Response IDs overlap across arms or roles")
        plugin_status: dict[str, dict[str, Any]] = {}
        for arm, rows in results.items():
            if plugin_path is None or not rows:
                plugin_status[arm] = {"status": "not_run" if plugin_path is None
                                      else "no_valid_groups", "passGroups": None,
                                      "issueGroups": None}
                continue
            evidence = copy.deepcopy(requests[arm])
            evidence["generation"] = {
                role: {"model": policies[arm][role]["model"],
                       "promptVersion": policies[arm][role]["promptVersion"],
                       "responseIds": [row[f"{role}ResponseId"] for row in rows]}
                for role in ("translator", "reviewer")}
            evidence["groups"] = rows
            receipt = producer.run_language_plugin(
                source, anchor, policies[arm], requests[arm], evidence, plugin_path,
                policies[arm]["languageReview"]["pluginImplementationSha256"])
            _write_snapshot(out / f"arm-{arm}" / "language-plugin.json", receipt)
            plugin_status[arm] = {"status": "checked",
                                  "checkedGroups": len(receipt["groupReviews"]),
                                  "passGroups": sum(row["status"] == "pass"
                                                    for row in receipt["groupReviews"]),
                                  "issueGroups": [row["translationGroupId"]
                                                  for row in receipt["groupReviews"]
                                                  if row["status"] != "pass"]}
        wall = _wall_timing(out, elapsed=clock() - invocation_start)
        arm_summaries = {}
        for arm, rows in results.items():
            completed_ids = {row["translationGroupId"] for row in rows}
            failed_ids = {row["translationGroupId"] for row in failures[arm]}
            attempted = sum(any((out / f"arm-{arm}" /
                                 f"group-{index:04d}-{role}{suffix}").is_file()
                                for role in ("translator", "reviewer")
                                for suffix in (".started.json", ".raw.json", ".json"))
                            or (out / f"arm-{arm}" / f"group-{index:04d}-failure.json").is_file()
                            for index in range(1, len(plan) + 1))
            _write_snapshot(out / f"arm-{arm}" / "results.json",
                            {"schemaVersion": "layer2-ab-arm-results-v2",
                             "rows": rows, "failures": failures[arm]})
            plugin_issues = plugin_status[arm]["issueGroups"]
            arm_summaries[arm] = {
                "translator": MODELS[arm], "reviewer": REVIEWER,
                "attemptedGroups": attempted, "completedGroups": len(completed_ids),
                "failedGroups": len(failed_ids),
                "inProgressGroups": attempted - len(completed_ids) - len(failed_ids),
                "failures": failures[arm],
                "semanticReviewPassGroups": sum(row["machineReviewPass"] for row in rows),
                "languagePlugin": plugin_status[arm],
                "combinedMachinePassGroups": sum(
                    row["machineReviewPass"] and row["translationGroupId"] not in plugin_issues
                    for row in rows) if plugin_issues is not None else None,
                "metrics": _receipt_metrics(out, arm, len(plan)),
                "resultPath": f"arm-{arm}/results.json",
            }
        paired = sum(all(group["translationGroupId"] in {
            row["translationGroupId"] for row in results[arm]}
            for arm in MODELS) for group in plan)
        summary = {"schemaVersion": "layer2-ab-results-v2", "status": status,
                   "pauseReason": pause_reason,
                   "humanApproval": False, "releaseEligible": False,
                   "sourceHash": identity["sourceHash"],
                   "anchorHash": identity["anchorHash"],
                   "basePolicyHash": identity["basePolicyHash"],
                   "identityMigrationPath": "run-identity-migration.json" if migration else None,
                   "localeActiveWallSeconds": wall["activeWallSeconds"],
                   "localeCalendarWallSeconds": round(time.time() - wall["firstStartedAtEpoch"], 6),
                   "lastInvocation": {"httpAttempts": budget["calls"],
                                      "cacheHits": budget["cache_hits"],
                                      "maxApiCalls": max_api_calls, "maxGroups": max_groups},
                   "groups": len(plan), "pairedGroups": paired,
                   "arms": arm_summaries}
        if status == "shadow_only":
            _blind_materials(out, requests["A"], plan, results)
            summary["blindReviewPath"] = "blind-review.json"
        _write_snapshot(comparison_path, summary)
        return summary

    for index, group in enumerate(plan, 1):
        def terminal(arm: str) -> bool:
            arm_dir = out / f"arm-{arm}"
            return ((arm_dir / f"group-{index:04d}-reviewer.json").is_file()
                    or (arm_dir / f"group-{index:04d}-failure.json").is_file())

        if not all(terminal(arm) for arm in MODELS):
            if touched_groups >= max_groups:
                return finish("incomplete", "max_groups")
            touched_groups += 1
        # Rotate arm order across groups to reduce clock-time and rate-limit bias.
        order = list(MODELS)
        order = order[(index - 1) % len(order):] + order[:(index - 1) % len(order)]
        for arm in order:
            policy, request = policies[arm], requests[arm]
            common = _common(group, index, plan, request, policy)
            stem = f"group-{index:04d}"
            arm_dir = out / f"arm-{arm}"
            failure_path = arm_dir / f"{stem}-failure.json"
            if failure_path.is_file():
                failures[arm].append(producer._load(failure_path))
                continue
            translator_path = arm_dir / f"{stem}-translator.json"
            try:
                translated = _call_with_receipt("translator", {
                    "instruction": TRANSLATOR_INSTRUCTION + policy["translator"]["promptVersion"],
                    "input": common}, policy, translator_path,
                    api_key, caller, clock, budget)
            except ExperimentPaused as pause:
                return finish("incomplete", str(pause))
            except (ValueError, json.JSONDecodeError) as error:
                if not _can_record_model_failure(error, translator_path.with_suffix(".raw.json")):
                    raise
                failures[arm].append(_failure(out, arm, index, group, "translator", error))
                continue
            draft = translated["result"]
            try:
                _validate_group(draft, group, reviewer=False)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
                failures[arm].append(_failure(out, arm, index, group,
                                              "translator", error, translated))
                continue
            reviewer_path = arm_dir / f"{stem}-reviewer.json"
            try:
                reviewed = _call_with_receipt("reviewer", {
                    "instruction": REVIEWER_INSTRUCTION + policy["reviewer"]["promptVersion"],
                    "input": {**common, "draft": draft}}, policy,
                    reviewer_path, api_key, caller, clock, budget)
            except ExperimentPaused as pause:
                return finish("incomplete", str(pause))
            except (ValueError, json.JSONDecodeError) as error:
                if not _can_record_model_failure(error, reviewer_path.with_suffix(".raw.json")):
                    raise
                failures[arm].append(_failure(out, arm, index, group, "reviewer", error))
                continue
            final = reviewed["result"]
            try:
                passed = _validate_group(final, group, reviewer=True)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError) as error:
                failures[arm].append(_failure(out, arm, index, group,
                                              "reviewer", error, reviewed))
                continue
            results[arm].append({"translationGroupId": group["translationGroupId"],
                                 "sourceUnitIds": group["sourceUnitIds"],
                                 "draftUtterances": draft["targetUtterances"],
                                 "targetUtterances": final["targetUtterances"],
                                 "coverage": final["coverage"],
                                 "semanticReview": final["semanticReview"],
                                 "machineReviewPass": passed,
                                 "translatorResponseId": translated["requestId"],
                                 "reviewerResponseId": reviewed["requestId"]})
    return finish("shadow_only")


def _ignored_or_external(path: Path) -> bool:
    root = Path(__file__).resolve().parents[2]
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        return True
    return subprocess.run(["git", "check-ignore", "-q", str(resolved)],
                          cwd=root, check=False).returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--group-plan", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--max-api-calls", type=int, required=True,
                        help=f"Hard per-invocation HTTP call cap, 0..{MAX_API_CALLS_PER_INVOCATION}")
    parser.add_argument("--max-groups", type=int, required=True,
                        help=f"New or partial groups per invocation, 1..{MAX_GROUPS_PER_INVOCATION}")
    args = parser.parse_args()
    production.require(_ignored_or_external(args.out_dir),
                       "Model text output must be ignored or outside this Git repository")
    source, anchor, policy = (producer._load(path) for path in
                              (args.english_source_package, args.anchor, args.policy))
    plan = json.loads(args.group_plan.read_text(encoding="utf-8")) if args.group_plan else None
    # Finish source/policy/plan validation before requiring a secret.
    request = producer.prepare_request(source, anchor, _arm_policy(policy, MODELS["A"]))
    production.group_plan(request, anchor, plan)
    production.require(producer.plugin_implementation_sha256(args.plugin)
                       == policy["languageReview"]["pluginImplementationSha256"],
                       "Language plugin differs from frozen policy")
    key = os.environ.get("OPENAI_API_KEY")
    production.require(bool(key), "OPENAI_API_KEY is not configured")
    result = run(source, anchor, policy, args.out_dir, key,
                 lambda api_key, payload: sermon_pipeline.chat_json(api_key, payload, retries=1),
                 custom_plan=plan, plugin_path=args.plugin,
                 max_api_calls=args.max_api_calls, max_groups=args.max_groups)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
