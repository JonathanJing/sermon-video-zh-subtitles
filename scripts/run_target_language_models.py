#!/usr/bin/env python3
"""Run source-bound Layer 2 Astra translation and Sol independent group review.

Outputs are recoverable machine evidence. Human approval remains a separate gate.
An unfinished request marker deliberately blocks automatic paid retries.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import copy_context
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable

try:
    from scripts import four_layer_measure as measure
    from scripts import produce_target_language_candidate as producer
    from scripts import sermon_accounting as accounting
    from scripts import sermon_cache_observation as cache_observation
    from scripts import sermon_pipeline
    from scripts import target_language_policy as policy_tools
    from scripts import sermon_workflow_jobs as jobs
except ImportError:
    import four_layer_measure as measure
    import produce_target_language_candidate as producer
    import sermon_accounting as accounting
    import sermon_cache_observation as cache_observation
    import sermon_pipeline
    import target_language_policy as policy_tools
    import sermon_workflow_jobs as jobs


# Timing-only edits do not change the model request or group admission rules.
# Use the direct dev parent's runner hash for existing in-place paid runs.
RUNNER_PRODUCTION_IDENTITY_SHA256 = "1922f23b881363ac4f1a32a99de7184fecd1ae445befde5f2282d400bd762e40"
COMPATIBLE_RUNNER_IDENTITIES = {
    # Existing run directories created after the W40 merge or on its release side.
    "8bcd568926f2062919268c185a6d67bf2be4113158e28cd8ca1b6e6e1d7071f3",
}


MODEL_ROLES = {"translator": "gpt-6-astra", "reviewer": "gpt-6-sol"}
SEMANTIC_CHECKS = ("completeMeaning", "negationsNumbersNames", "quotationAttribution", "noAddedMeaning")
REVISION_BRIEF_SCHEMA = "sermon-target-language-group-revision-brief-v1"


def revision_boundary_instruction(target_locale: str, *, revising: bool) -> str:
    if not revising or target_locale != "ko":
        return ""
    return ("For Korean spoken units, a complete polite predicate may end with a "
            "period even when the next English unit begins with 'because'. The next "
            "Korean unit may state that reason as its own sentence. Do not force a "
            "trailing comma merely to mirror the English clause boundary. ")
PARTIAL_REPAIR_SCHEMA = "sermon-target-language-partial-repair-brief-v1"


def scripture_prompt_instruction(policy: dict[str, Any]) -> str:
    """Put the frozen scripture rule at system priority for both model roles."""
    scripture = policy["scripture"]
    if scripture["quoteCheckPolicy"] == "references_only":
        return ("For Bible passages, cite the book, chapter, and verse when known, "
                "and paraphrase the speaker's meaning in the target language. "
                "Do not present the text as an exact quotation from any Bible edition. ")
    if scripture["quoteCheckPolicy"] == "source_bound_exact_quote":
        return ("For a direct Bible quotation, use only the reviewed source-bound "
                "wording from the pinned edition. Flag uncertainty if the quote "
                "boundary or exact wording is unavailable; never invent it. ")
    raise ValueError("Scripture quotation policy is unresolved")


def surrounding_context(request: dict[str, Any], plan: list[dict[str, Any]],
                        group_index: int) -> dict[str, list[dict[str, str]]]:
    """Give short, source-bound context on both sides of one translation group."""
    start = sum(len(group["sourceUnitIds"]) for group in plan[:group_index])
    end = start + len(plan[group_index]["sourceUnitIds"])
    rows = request["sourceUnits"]
    return {
        "before": copy.deepcopy(rows[max(0, start - 3):start]),
        "after": copy.deepcopy(rows[end:end + 2]),
    }


def register_prompt_instruction(policy: dict[str, Any]) -> str:
    return ("Follow the locale's public-sermon register consistently: "
            + "; ".join(policy["languageReview"]["registerRules"]) + ". ")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def save_new(path: Path, value: object, *, private=False) -> None:
    # Exclusive creation arbitrates concurrent callers. Sync the file and every
    # containing entry before returning: the started marker must survive a host
    # crash before a paid request, even when its parent directories are new.
    path.parent.mkdir(parents=True, exist_ok=True)
    opener = (lambda name, flags: os.open(name, flags, 0o600)) if private else None
    with open(path, "x", encoding="utf-8", opener=opener) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    jobs._sync_directory_ancestry(path.parent)


def group_plan(request: dict[str, Any], anchor: dict[str, Any],
               custom: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    expected = [unit["sourceUnitId"] for unit in request["sourceUnits"]]
    if custom is None:
        anchor_plan = anchor.get("translationRequests")
        if isinstance(anchor_plan, list) and anchor_plan:
            plan = [{"translationGroupId": row["translationGroupId"],
                     "sourceUnitIds": row["sourceUnitIds"]} for row in anchor_plan]
        else:
            plan = [{"translationGroupId": f"translation-{unit_id}",
                     "sourceUnitIds": [unit_id]} for unit_id in expected]
    else:
        plan = custom
    require(isinstance(plan, list) and bool(plan), "Group plan must be a nonempty array")
    require(all(isinstance(row, dict)
                and set(row) == {"translationGroupId", "sourceUnitIds"}
                and isinstance(row["translationGroupId"], str) and row["translationGroupId"]
                and isinstance(row["sourceUnitIds"], list) and row["sourceUnitIds"]
                for row in plan), "Invalid group plan")
    ids = [row["translationGroupId"] for row in plan]
    assigned = [unit_id for row in plan for unit_id in row["sourceUnitIds"]]
    require(len(set(ids)) == len(ids) and assigned == expected,
            "Group plan must cover source units exactly once and in order")
    return plan


def require_plugin_identity(plugin_path, expected):
    actual = producer.plugin_implementation_sha256(plugin_path)
    try:
        require(actual == expected, "Language plugin implementation differs from frozen policy")
    except ValueError as exc:
        def observe():
            accounting.record_workload("layer2.plugin_binding", {
                "expectedPluginSha256": expected, "actualPluginSha256": actual})
            accounting.record_log("layer2_admission_rejected", fields={
                "status": "blocked", "reasonCode": "plugin_implementation_mismatch"})
        accounting._finalize(observe, exc)
        raise


def completed_response_content(response, model, role):
    """Validate the same terminal envelope for fresh and strict cached calls."""
    require(isinstance(response, dict) and isinstance(response.get("id"), str)
            and response["id"] and response.get("model") == model,
            f"{role} response lacks exact model and request identity")
    choices = response.get("choices")
    require(isinstance(choices, list) and len(choices) == 1
            and isinstance(choices[0], dict) and choices[0].get("finish_reason") == "stop",
            f"{role} response is incomplete")
    message = choices[0].get("message")
    require(isinstance(message, dict) and isinstance(message.get("content"), str),
            f"{role} response has no JSON content")
    return message["content"]


def model_payload(role, prompt, policy, request_limits=None):
    model = policy[role]["model"]
    payload = {"model": model, "reasoning_effort": policy[role]["reasoningEffort"],
               "messages": [{"role": "system", "content": prompt["instruction"]},
                            {"role": "user", "content": json.dumps(prompt["input"], ensure_ascii=False)}],
               "response_format": {"type": "json_object"}}
    if request_limits is not None:
        from scripts.sermon_provider_limits import bounded_payload
        payload = bounded_payload(payload, request_limits)
    return payload


def _model_call(role: str, prompt: dict[str, Any], policy: dict[str, Any],
                output: Path, api_key: str,
                caller: Callable[[str, dict[str, Any]], dict[str, Any]],
                reuse_from: Path | None = None, *, cache_only: bool = False,
                response_observer=None, request_limits=None) -> dict[str, Any]:
    model = policy[role]["model"]
    save_options = {"private": True} if response_observer is not None else {}
    payload = model_payload(role, prompt, policy, request_limits)
    fingerprint = policy_tools.canonical_sha256(payload)
    if reuse_from is not None and not output.exists():
        require(reuse_from.is_file(), f"Missing reusable {role} cache: {reuse_from}")
        cached = producer._load(reuse_from)
        require(cached.get("payloadSha256") == fingerprint
                and cached.get("model") == model
                and isinstance(cached.get("requestId"), str) and cached["requestId"]
                and isinstance(cached.get("result"), dict),
                f"Reusable {role} cache belongs to different inputs: {reuse_from}")
        previous_raw = reuse_from.with_suffix(".raw.json")
        if previous_raw.is_file():
            raw = producer._load(previous_raw)
            require(raw.get("payloadSha256") == fingerprint
                    and isinstance(raw.get("response"), dict),
                    f"Reusable {role} raw response belongs to different inputs: {previous_raw}")
        save_new(output, cached)
        if previous_raw.is_file():
            shutil.copyfile(previous_raw, output.with_suffix(".raw.json"))
    if output.exists():
        saved = producer._load(output)
        require(saved.get("payloadSha256") == fingerprint
                and saved.get("model") == model
                and isinstance(saved.get("requestId"), str) and saved["requestId"]
                and isinstance(saved.get("result"), dict),
                f"Cached {role} response belongs to different inputs: {output}")
        cache_observation.record(role, saved, output, mode="validated_cache", origin=reuse_from)
        return saved
    marker = output.with_suffix(".started.json")
    raw_path = output.with_suffix(".raw.json")
    recovered_raw = raw_path.exists()
    if recovered_raw:
        raw = producer._load(raw_path)
        require(raw.get("payloadSha256") == fingerprint
                and isinstance(raw.get("response"), dict),
                f"Saved raw {role} response belongs to different inputs: {raw_path}")
        response = raw["response"]
    else:
        require(not cache_only, f"Cache-only recovery has no returned {role} response: {output}")
        require(not marker.exists(), f"Uncertain paid {role} call; inspect before retry: {marker}")
        save_new(marker, {"role": role, "payloadSha256": fingerprint,
                          "status": "started_response_unconfirmed"}, **save_options)
        if response_observer is None:
            response = caller(api_key, payload)
        else:
            response = caller(api_key, payload, response_observer=response_observer)
        # Persist the actual completed API response before any identity, finish, or
        # JSON checks; an invalid paid response must remain inspectable and reusable.
        if response_observer is not None:
            require(raw_path.is_file(), "Strict transport did not persist its returned response")
            observed = producer._load(raw_path)
            require(observed.get("payloadSha256") == fingerprint and observed.get("response") == response,
                    "Strict persisted response differs from transport return")
        else:
            save_new(raw_path, {"payloadSha256": fingerprint, "response": response})
    content = completed_response_content(response, model, role)
    if response_observer is not None:
        from scripts.sermon_review_contracts import decode_json
        parsed = decode_json(content.encode("utf-8"))
    else:
        parsed = json.loads(content)
    require(isinstance(parsed, dict), f"{role} response must be a JSON object")
    saved = {"payloadSha256": fingerprint, "requestId": response["id"],
             "model": model, "result": parsed}
    save_new(output, saved, **save_options)
    # Both the raw response and validated cache are durable before retiring the
    # uncertainty marker. A failed sync propagates and leaves it for recovery.
    marker.unlink(missing_ok=True)
    if recovered_raw:
        cache_observation.record(role, saved, output, mode="raw_response_recovery")
    return saved


def _utterances(value: object) -> list[str]:
    require(isinstance(value, list) and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value),
            "Model must return nonempty targetUtterances")
    return [item.strip() for item in value]


def _coverage_substring(covered: str, target: str) -> bool:
    """Allow only whitespace differences at model utterance boundaries."""
    compact = lambda value: re.sub(r"\s+", "", value)
    return bool(covered.strip()) and compact(covered) in compact(target)


def normalize_semantic_review(value: object) -> object:
    """Adapt common JSON type variants while keeping saved model responses raw.

    Only explicit boolean checks map to pass/fail. A nonempty uncertainty or
    issue remains a blocking item; an unknown shape still fails validation.
    """
    if not isinstance(value, dict):
        return value
    semantic = copy.deepcopy(value)
    checks = semantic.get("checks")
    if isinstance(checks, dict):
        semantic["checks"] = {
            name: ("pass" if result is True else "fail" if result is False else result)
            for name, result in checks.items()
        }
    for field in ("uncertainty", "issues"):
        item = semantic.get(field)
        if item is None or item is False or item == "":
            semantic[field] = []
        elif item is True:
            semantic[field] = [f"model_reported_{field}"]
        elif isinstance(item, str):
            semantic[field] = [item]
    return semantic


def validate_revision_brief(brief: dict[str, Any] | None,
                            request: dict[str, Any],
                            plan: list[dict[str, Any]],
                            prior_evidence: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if brief is None:
        return {}
    require(isinstance(prior_evidence, dict),
            "Group revision brief requires prior complete evidence")
    require(isinstance(brief, dict)
            and set(brief) == {"schemaVersion", "targetLocale",
                               "englishSourcePackageJsonSha256", "anchorManifestSha256",
                               "translationPolicySha256", "groups"}
            and brief["schemaVersion"] == REVISION_BRIEF_SCHEMA,
            "Invalid group revision brief")
    for key in ("targetLocale", "englishSourcePackageJsonSha256",
                "anchorManifestSha256", "translationPolicySha256"):
        require(brief[key] == request[key] and prior_evidence.get(key) == request[key],
                f"Group revision source or policy changed: {key}")
    require(prior_evidence.get("sourceUnits") == request["sourceUnits"],
            "Prior translation evidence belongs to different English units")
    prior_groups = prior_evidence.get("groups")
    require(isinstance(prior_groups, list)
            and [(row.get("translationGroupId"), row.get("sourceUnitIds"))
                 for row in prior_groups] ==
                [(row["translationGroupId"], row["sourceUnitIds"]) for row in plan],
            "Prior translation group plan changed")
    entries = brief["groups"]
    require(isinstance(entries, list) and entries, "Revision brief needs changed groups")
    prior_by_id = {row["translationGroupId"]: row for row in prior_groups}
    plan_by_id = {row["translationGroupId"]: row for row in plan}
    result: dict[str, dict[str, Any]] = {}
    for row in entries:
        require(isinstance(row, dict) and set(row) == {
            "translationGroupId", "sourceUnitIds", "priorTargetTextSha256",
            "proposedTargetText"}, "Invalid group revision row")
        group_id = row["translationGroupId"]
        require(group_id in plan_by_id and group_id not in result
                and row["sourceUnitIds"] == plan_by_id[group_id]["sourceUnitIds"],
                f"Unknown, duplicate, or changed revision group: {group_id}")
        old = "".join(prior_by_id[group_id]["targetUtterances"])
        proposal = row["proposedTargetText"]
        require(row["priorTargetTextSha256"] == hashlib.sha256(old.encode()).hexdigest()
                and isinstance(proposal, str) and proposal.strip()
                and proposal.strip() != old,
                f"Revision proposal lacks matching prior target text: {group_id}")
        result[group_id] = row
    return result


def validate_partial_repair_brief(brief: dict[str, Any] | None,
                                  request: dict[str, Any],
                                  plan: list[dict[str, Any]],
                                  reuse_from: Path | None) -> dict[str, dict[str, Any]]:
    """Bind a new revision to a failed cache in an incomplete prior run.

    The old model response remains untouched. A changed group gets a fresh
    Astra request and an independent Sol request; all other matching caches
    can be copied from the prior run, even when it has no evidence.json yet.
    """
    if brief is None:
        return {}
    require(reuse_from is not None and (reuse_from / "request.json").is_file(),
            "Partial repair requires a prior run request")
    require(producer._load(reuse_from / "request.json") == request,
            "Partial repair prior request belongs to another source or policy")
    require(isinstance(brief, dict)
            and set(brief) == {"schemaVersion", "targetLocale",
                               "englishSourcePackageJsonSha256", "anchorManifestSha256",
                               "translationPolicySha256", "groups"}
            and brief["schemaVersion"] == PARTIAL_REPAIR_SCHEMA,
            "Invalid partial repair brief")
    for key in ("targetLocale", "englishSourcePackageJsonSha256",
                "anchorManifestSha256", "translationPolicySha256"):
        require(brief[key] == request[key], f"Partial repair source or policy changed: {key}")
    entries = brief["groups"]
    require(isinstance(entries, list) and entries, "Partial repair needs failed groups")
    plan_by_id = {row["translationGroupId"]: (index, row)
                  for index, row in enumerate(plan, 1)}
    result: dict[str, dict[str, Any]] = {}
    for row in entries:
        require(isinstance(row, dict) and set(row) == {
            "translationGroupId", "sourceUnitIds", "failedRole",
            "failedCacheSha256", "failureReason", "instruction"},
            "Invalid partial repair row")
        group_id = row["translationGroupId"]
        require(group_id in plan_by_id and group_id not in result,
                f"Unknown or duplicate partial repair group: {group_id}")
        index, group = plan_by_id[group_id]
        require(row["sourceUnitIds"] == group["sourceUnitIds"]
                and row["failedRole"] in {"translator", "reviewer"}
                and isinstance(row["failureReason"], str) and row["failureReason"].strip()
                and isinstance(row["instruction"], str) and row["instruction"].strip()
                and len(row["instruction"]) <= 2000,
                f"Invalid partial repair source, role, or instruction: {group_id}")
        suffix = "astra" if row["failedRole"] == "translator" else "sol"
        failed_cache = reuse_from / f"group-{index:04d}-{suffix}.json"
        require(failed_cache.is_file()
                and row["failedCacheSha256"] == hashlib.sha256(failed_cache.read_bytes()).hexdigest(),
                f"Partial repair failed cache is missing or changed: {group_id}")
        saved = producer._load(failed_cache)
        prior_result = saved.get("result")
        require(saved.get("model") == MODEL_ROLES[row["failedRole"]]
                and isinstance(saved.get("payloadSha256"), str)
                and isinstance(prior_result, dict)
                and prior_result.get("translationGroupId") == group_id
                and prior_result.get("sourceUnitIds") == group["sourceUnitIds"],
                f"Partial repair failed cache has different group identity: {group_id}")
        result[group_id] = row
    return result


def reusable_cache(prior_run: Path | None, stem: str, role: str) -> Path | None:
    """Return a complete old cache, but never retry an uncertain old request."""
    if prior_run is None:
        return None
    path = prior_run / f"{stem}-{role}.json"
    if path.is_file():
        return path
    require(not path.with_suffix(".started.json").exists()
            and not path.with_suffix(".raw.json").exists(),
            f"Prior {role} request needs inspection before retry: {path}")
    return None


def carry_forward_group(prior_run: Path, out: Path, index: int,
                        group: dict[str, Any], prior_row: dict[str, Any],
                        policy: dict[str, Any]) -> dict[str, Any]:
    """Preserve a completed group's exact paid responses and reviewed text."""
    require(prior_row.get("translationGroupId") == group["translationGroupId"]
            and prior_row.get("sourceUnitIds") == group["sourceUnitIds"]
            and prior_row.get("semanticReview", {}).get("status") == "pass"
            and not prior_row["semanticReview"].get("uncertainty")
            and not prior_row["semanticReview"].get("issues")
            and all(value == "pass" for value in
                    prior_row["semanticReview"].get("checks", {}).values()),
            f"Prior complete evidence has an unresolved group: {group['translationGroupId']}")
    for role, suffix, request_key in (("translator", "astra", "translatorRequestId"),
                                      ("reviewer", "sol", "reviewerRequestId")):
        source = prior_run / f"group-{index:04d}-{suffix}.json"
        require(source.is_file(), f"Prior complete evidence lacks {role} cache: {source}")
        cached = producer._load(source)
        require(cached.get("model") == policy[role]["model"]
                and cached.get("requestId") == prior_row.get(request_key)
                and isinstance(cached.get("payloadSha256"), str)
                and isinstance(cached.get("result"), dict)
                and cached["result"].get("translationGroupId") == group["translationGroupId"]
                and cached["result"].get("sourceUnitIds") == group["sourceUnitIds"],
                f"Prior complete evidence/cache identity differs: {source}")
        raw = source.with_suffix(".raw.json")
        if raw.is_file():
            raw_record = producer._load(raw)
            require(raw_record.get("payloadSha256") == cached["payloadSha256"]
                    and isinstance(raw_record.get("response"), dict)
                    and raw_record["response"].get("id") == cached["requestId"],
                    f"Prior complete raw response differs: {raw}")
        target = out / source.name
        if target.exists():
            require(target.read_bytes() == source.read_bytes(),
                    f"Carried-forward cache changed: {target}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        if raw.is_file():
            target_raw = out / raw.name
            if target_raw.exists():
                require(target_raw.read_bytes() == raw.read_bytes(),
                        f"Carried-forward raw response changed: {target_raw}")
            else:
                shutil.copyfile(raw, target_raw)
        cache_observation.record(role, cached, target, mode="carried_forward_group", origin=source)
    return copy.deepcopy(prior_row)

def ordered_group_results(items: list, worker, workers: int) -> list:
    """Keep only a bounded set of paid groups in flight and merge in source order."""
    require(type(workers) is int and 1 <= workers <= 16, "Group workers must be 1..16")
    if workers == 1 or len(items) < 2:
        return [worker(item) for item in items]
    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        source = iter(enumerate(items))
        pending = {}
        for _ in range(min(workers, len(items))):
            index, item = next(source)
            pending[pool.submit(copy_context().run, worker, item)] = index
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            completed_count = 0
            for future in sorted(done, key=lambda item: pending[item]):
                index = pending.pop(future)
                try:
                    results[index] = future.result()
                except BaseException:
                    for remaining in pending:
                        remaining.cancel()
                    raise
                completed_count += 1
            for _ in range(completed_count):
                next_item = next(source, None)
                if next_item is not None:
                    next_index, item = next_item
                    pending[pool.submit(copy_context().run, worker, item)] = next_index
    return [results[index] for index in range(len(items))]


def require_reconciled_requests(*directories: Path | None) -> None:
    """Block the whole dispatch before any group can replay an unknown call.

    Returned raw responses and validated caches remain recoverable. A marker
    without either is an unknown outcome, including in a prior repair attempt;
    inspection/reconciliation must precede any further paid work in this batch.
    Never remove markers here or infer a failed request from a transport error.
    """
    for directory in directories:
        if directory is None or not directory.exists():
            continue
        for marker in sorted(directory.glob("group-*.started.json")):
            stem = marker.name.removesuffix(".started.json")
            role = {"astra": "translator", "sol": "reviewer"}.get(stem.rsplit("-", 1)[-1], "model")
            require((directory / f"{stem}.json").is_file()
                    or (directory / f"{stem}.raw.json").is_file(),
                    f"Uncertain paid {role} call; inspect before retry or dispatch: {marker}")


def run(source: dict[str, Any], anchor: dict[str, Any], policy: dict[str, Any],
        out: Path, api_key: str,
        caller: Callable[[str, dict[str, Any]], dict[str, Any]],
        custom_plan: list[dict[str, Any]] | None = None,
        plugin_path: Path | None = None,
        revision_brief: dict[str, Any] | None = None,
        reuse_from: Path | None = None,
        partial_repair_brief: dict[str, Any] | None = None,
        resume_cache_from: Path | None = None) -> dict[str, Any]:
    with accounting.stage(f"layer2.source_admission.{policy['targetLocale']}",
                          depends_on=[], executor_type="deterministic_program",
                          work_unit_id=f"l2.{policy['targetLocale']}.source_admission") as source_span:
        request = producer.prepare_request(source, anchor, policy)
    return _run_prepared_groups(
        request, anchor, policy, out, api_key, caller, custom_plan, plugin_path,
        revision_brief, reuse_from, partial_repair_brief, resume_cache_from,
        source_admission_span=source_span)


def _run_prepared_groups(request: dict[str, Any], anchor: dict[str, Any],
                         policy: dict[str, Any], out: Path, api_key: str,
                         caller: Callable[[str, dict[str, Any]], dict[str, Any]],
                         custom_plan: list[dict[str, Any]] | None = None,
                         plugin_path: Path | None = None,
                         revision_brief: dict[str, Any] | None = None,
                         reuse_from: Path | None = None,
                         partial_repair_brief: dict[str, Any] | None = None,
                         resume_cache_from: Path | None = None,
                         *, simulation_only: bool = False, cache_only: bool = False,
                         progress_callback=None,
                         source_admission_span: str | None = None,
                         completion_spans: list[str] | None = None) -> dict[str, Any]:
    """Shared group loop; the formal entry above still enforces Layer 1 approval.

    Simulated requests carry an extra marker that prevents formal candidate
    admission, and cannot reuse or repair a production response cache.
    """
    with accounting.stage(f"layer2.run_admission.{request['targetLocale']}",
                          depends_on=[source_admission_span] if source_admission_span else [],
                          executor_type="deterministic_program",
                          work_unit_id=f"l2.{request['targetLocale']}.run_admission") as admission_span:
        if simulation_only:
            require(request.get("simulationOnly") is True
                    and request.get("schemaVersion") == "sermon-dry-run-layer2-request-v1"
                    and reuse_from is None and resume_cache_from is None
                    and revision_brief is None and partial_repair_brief is None
                    and plugin_path is None,
                    "Simulated group loop requires an isolated request and new output")
        else:
            require("simulationOnly" not in request,
                    "Formal group loop cannot consume a simulated request")
        for role, expected in MODEL_ROLES.items():
            require(policy[role]["model"] == expected,
                    f"Production {role} model must be {expected}; freeze a new policy")
        workers = policy["batching"].get("workers")
        require(policy["batching"].get("batchSize") == 1
                and type(workers) is int and 1 <= workers <= 16,
                "Per-group production runner requires batchSize=1 and workers=1..16")
        if plugin_path is not None:
            require_plugin_identity(plugin_path, policy["languageReview"]["pluginImplementationSha256"])
        plan = group_plan(request, anchor, custom_plan)
        require(revision_brief is None or partial_repair_brief is None,
                "Use one changed-group revision mechanism at a time")
        prior_evidence = (producer._load(reuse_from / "evidence.json")
                          if reuse_from and (reuse_from / "evidence.json").is_file() else None)
        if prior_evidence is not None:
            for key in ("schemaVersion", "sourceLocale", "targetLocale",
                        "englishSourcePackageJsonSha256", "anchorManifestSha256",
                        "translationPolicySha256", "sourceUnits"):
                require(prior_evidence.get(key) == request[key],
                        f"Prior complete evidence source or policy changed: {key}")
            prior_groups = prior_evidence.get("groups")
            require(isinstance(prior_groups, list)
                    and [(row.get("translationGroupId"), row.get("sourceUnitIds"))
                         for row in prior_groups] ==
                    [(row["translationGroupId"], row["sourceUnitIds"]) for row in plan],
                    "Prior complete evidence group plan changed")
        briefs = validate_revision_brief(revision_brief, request, plan, prior_evidence)
        repairs = validate_partial_repair_brief(partial_repair_brief, request, plan,
                                                 reuse_from)
        if reuse_from is not None:
            require(reuse_from.resolve() != out.resolve(), "Reuse source and output must differ")
        if resume_cache_from is not None:
            require(reuse_from is not None and resume_cache_from.resolve() != out.resolve()
                    and resume_cache_from.resolve() != reuse_from.resolve()
                    and (resume_cache_from / "request.json").is_file()
                    and producer._load(resume_cache_from / "request.json") == request,
                    "Resume cache must be a separate attempt for this source and policy")
        identity = {"request": request, "groupPlan": plan,
                    "runnerImplementationSha256": RUNNER_PRODUCTION_IDENTITY_SHA256}
        if revision_brief is not None:
            identity["revisionBriefSha256"] = policy_tools.canonical_sha256(revision_brief)
        if partial_repair_brief is not None:
            identity["partialRepairBriefSha256"] = policy_tools.canonical_sha256(
                partial_repair_brief)
        if resume_cache_from is not None:
            identity["resumeCacheFrom"] = str(resume_cache_from.resolve())
        identity_hash = policy_tools.canonical_sha256(identity)
        manifest = out / "run-identity.json"
        if manifest.exists():
            accepted_hashes = {policy_tools.canonical_sha256({
                **identity, "runnerImplementationSha256": implementation_hash})
                for implementation_hash in
                {RUNNER_PRODUCTION_IDENTITY_SHA256, *COMPATIBLE_RUNNER_IDENTITIES}}
            require(producer._load(manifest) in
                    [{"sha256": accepted_hash} for accepted_hash in accepted_hashes],
                    "Output directory belongs to another source, policy, or group plan")
        else:
            require(not out.exists() or all(entry.name == "accounting" and entry.is_dir()
                                            for entry in out.iterdir()),
                    "Output directory is not empty")
            save_new(manifest, {"sha256": identity_hash})
        request_path = out / "request.json"
        if not request_path.exists():
            save_new(request_path, request)
        else:
            require(producer._load(request_path) == request, "Cached request changed")
        require_reconciled_requests(out, reuse_from, resume_cache_from)
        accounting.record_workload("layer2.concurrency", {
            "workers": workers, "maxInFlightGroups": workers,
            "translationGroups": len(plan), "aggregationOrder": "source"})
        units = {row["sourceUnitId"]: row["english"] for row in request["sourceUnits"]}
    def _process_group(item):
        index, group = item
        with accounting.stage(f"layer2.prepare.{request['targetLocale']}.group-{index:04d}",
                              cache_hit=prior_evidence is not None and group['translationGroupId'] not in briefs
                                        and group['translationGroupId'] not in repairs,
                              depends_on=[admission_span], executor_type="deterministic_program",
                              work_unit_id=f"l2.{request['targetLocale']}.group-{index:04d}.prepare") as prepare_span:
            brief = briefs.get(group["translationGroupId"])
            repair = repairs.get(group["translationGroupId"])
            if prior_evidence is not None and brief is None and repair is None:
                return carry_forward_group(reuse_from, out, index, group,
                                           prior_evidence["groups"][index - 1], policy), prepare_span
            source_rows = [{"sourceUnitId": unit_id, "english": units[unit_id]}
                           for unit_id in group["sourceUnitIds"]]
            context = surrounding_context(request, plan, index - 1)
            korean_boundary = revision_boundary_instruction(
                request["targetLocale"], revising=brief is not None)
            common = {"translationGroupId": group["translationGroupId"],
                      "sourceUnitIds": group["sourceUnitIds"], "englishUnits": source_rows,
                      "context": context, "targetLocale": request["targetLocale"],
                      "terminology": policy["terminology"], "scripture": policy["scripture"],
                      "formatting": policy["formatting"]}
            if brief is not None:
                common["revisionBrief"] = {
                    "instruction": ("This is a shorter spoken adaptation for a fixed video cue. "
                                    "Use proposedTargetText as the wording and length target, "
                                    "not as verified source truth. Keep it when it conveys the "
                                    "source's facts and rhetorical purpose. Repair only a specific "
                                    "missing or changed fact, name, number, negation, quotation, "
                                    "theological distinction, or necessary rhetorical beat. "
                                    "Prefer a concise repair over restoring the prior full "
                                    "translation. Do not restore conversational filler or expand "
                                    "for style. Do not add parenthetical verse citations or "
                                    "editorial references that are absent from the spoken English. "
                                    "Keep references at the speaker's spoken specificity: if "
                                    "English only says 'verse 5', do not add a book or chapter "
                                    "name even when context identifies it. "
                                    "Preserve an unfinished source clause when the next source "
                                    "unit completes it; do not finish or repeat that continuation "
                                    "inside this group. " + korean_boundary +
                                    "If the essential meaning cannot fit, report the "
                                    "conflict in independent review."),
                    "priorTargetTextSha256": brief["priorTargetTextSha256"],
                    "proposedTargetText": brief["proposedTargetText"],
                }
            if repair is not None:
                common["partialRepair"] = {
                    "priorFailedRole": repair["failedRole"],
                    "priorFailedCacheSha256": repair["failedCacheSha256"],
                    "failureReason": repair["failureReason"],
                    "instruction": repair["instruction"],
                }
            repair_instruction = (
                " This group is a new revision after a prior machine failure. "
                "Follow the source-bound repair instruction while independently "
                "checking the English source; do not assume the prior answer was correct. "
                + repair["instruction"] + " " if repair is not None else "")
            translate_prompt = {
                "instruction": (("Revise the proposed shorter spoken text against the English "
                                "sermon group. Stay close to the proposal's length and wording; "
                                "change it only to repair a specific essential meaning error. "
                                "Preserve the source's facts, negations, numbers, names, quotations, "
                                "theological distinctions and rhetorical purpose. "
                                "Do not add parenthetical verse citations or editorial references "
                                "absent from the spoken English. "
                                "If English only says a relative verse number, do not add an "
                                "unspoken book or chapter name. "
                                "Keep unfinished clauses open for the next source unit instead "
                                "of completing or repeating the next unit's words. "
                                if brief is not None else
                                "Translate the English sermon group into the target locale. Preserve every "
                                "meaning, negation, number, name, quotation and theological distinction. ") +
                                korean_boundary +
                                scripture_prompt_instruction(policy) +
                                register_prompt_instruction(policy) +
                                repair_instruction +
                                "Resolve pronouns and elliptical repetitions using the surrounding "
                                "source units; translate only the requested English units. "
                                "Use context only for interpretation. Return JSON with exactly "
                                "translationGroupId, sourceUnitIds, targetUtterances and coverage. "
                                "Coverage has one sourceUnitId and exact targetText substring per source unit. "
                                "Do not claim human approval. Prompt version: " + policy["translator"]["promptVersion"]),
                "input": common}
            stem = f"group-{index:04d}"
            astra_path = out / f"{stem}-astra.json"
            prior_cache_root = resume_cache_from if resume_cache_from is not None else reuse_from if brief is None and repair is None else None
            translator_cached = (astra_path.exists() or astra_path.with_suffix(".raw.json").exists()
                                 or (prior_cache_root is not None and (prior_cache_root / f"{stem}-astra.json").is_file()))
        with measure.producer_substage("initial_translation",
                                       billing="local" if simulation_only or cache_only else "api"):
            with accounting.stage(f"layer2.translator.{request['targetLocale']}.{stem}",
                                  cache_hit=translator_cached, billing="local" if simulation_only or cache_only or translator_cached else "api",
                                  work_unit_id=f"l2.{request['targetLocale']}.{stem}.translator",
                                  depends_on=[prepare_span],
                                  executor_type="deterministic_program" if simulation_only or cache_only or translator_cached else "production_model") as translator_span:
                translated = _model_call("translator", translate_prompt, policy,
                                         astra_path, api_key, caller,
                                         reusable_cache(resume_cache_from, stem, "astra")
                                         if resume_cache_from is not None else
                                         reusable_cache(reuse_from, stem, "astra")
                                         if brief is None and repair is None else None, cache_only=cache_only)
                if progress_callback is not None:
                    progress_callback('translator_response_saved')
        with accounting.stage(f"layer2.draft_validation.{request['targetLocale']}.{stem}",
                              depends_on=[translator_span], executor_type="deterministic_program",
                              work_unit_id=f"l2.{request['targetLocale']}.{stem}.draft_validation") as draft_span:
            draft = translated["result"]
            require(draft.get("translationGroupId") == group["translationGroupId"]
                    and draft.get("sourceUnitIds") == group["sourceUnitIds"],
                    f"Astra group identity changed: {stem}")
            draft_text = "".join(_utterances(draft.get("targetUtterances")))
            require(isinstance(draft.get("coverage"), list)
                    and [row.get("sourceUnitId") for row in draft["coverage"]] == group["sourceUnitIds"]
                    and all(isinstance(row.get("targetText"), str)
                            and _coverage_substring(row["targetText"], draft_text)
                            for row in draft["coverage"]),
                    f"Astra source coverage is incomplete: {stem}")
            review_prompt = {
                "instruction": ("Independently compare the English source and Astra draft, one group at a time. "
                                + ("This is a shorter spoken adaptation: keep the final text close "
                                   "to proposedTargetText in wording and length. Expand only to fix "
                                   "a specific essential error; do not restore filler or stylistic "
                                   "detail from the prior full translation. Explain any necessary "
                                   "expansion in semanticReview.evidence. Do not restore "
                                   "parenthetical verse citations or editorial references "
                                   "absent from the spoken English. Keep a relative verse "
                                   "reference relative; do not add an unspoken book or chapter "
                                   "name. Check adjacent source units: preserve an unfinished "
                                   "clause and do not duplicate its completion in this group. "
                                   if brief is not None else "")
                                + korean_boundary
                                + scripture_prompt_instruction(policy) +
                                register_prompt_instruction(policy) +
                                repair_instruction +
                                "Check that pronouns and elliptical repetitions retain the intended "
                                "referent and predicate from surrounding source units. "
                                "Correct any error in final targetUtterances and coverage. Check every English "
                                "unit for omitted or added meaning, negations, numbers, names, and quotation "
                                "attribution. If uncertain or unresolved, mark fail. Return JSON with exactly "
                                "translationGroupId, sourceUnitIds, targetUtterances, coverage, semanticReview. "
                                "semanticReview has status, checks (completeMeaning, negationsNumbersNames, "
                                "quotationAttribution, noAddedMeaning), evidence, uncertainty, issues. "
                                "Each check value must be the string pass or fail. uncertainty and issues "
                                "must be arrays of unresolved concerns only; if you correct an Astra draft "
                                "issue in the final text, describe that correction in evidence and leave "
                                "issues empty. Mark status fail for any unresolved concern. "
                                "Do not claim human approval. Prompt version: " + policy["reviewer"]["promptVersion"]),
                "input": {**common, "astraDraft": draft}}
            sol_path = out / f"{stem}-sol.json"
            reviewer_cached = (sol_path.exists() or sol_path.with_suffix(".raw.json").exists()
                               or (prior_cache_root is not None and (prior_cache_root / f"{stem}-sol.json").is_file()))
        with measure.producer_substage("independent_review",
                                       billing="local" if simulation_only or cache_only else "api"):
            with accounting.stage(f"layer2.reviewer.{request['targetLocale']}.{stem}",
                                  cache_hit=reviewer_cached, billing="local" if simulation_only or cache_only or reviewer_cached else "api",
                                  work_unit_id=f"l2.{request['targetLocale']}.{stem}.reviewer",
                                  depends_on=[draft_span],
                                  executor_type="deterministic_program" if simulation_only or cache_only or reviewer_cached else "production_model") as reviewer_span:
                reviewed_response = _model_call("reviewer", review_prompt, policy,
                                                sol_path, api_key, caller,
                                                reusable_cache(resume_cache_from, stem, "sol")
                                                if resume_cache_from is not None else
                                                reusable_cache(reuse_from, stem, "sol")
                                                if brief is None and repair is None else None, cache_only=cache_only)
                if progress_callback is not None:
                    progress_callback('reviewer_response_saved')
        with accounting.stage(f"layer2.review_validation.{request['targetLocale']}.{stem}",
                              depends_on=[reviewer_span], executor_type="deterministic_program",
                              work_unit_id=f"l2.{request['targetLocale']}.{stem}.review_validation") as validation_span:
            result = reviewed_response["result"]
            require(result.get("translationGroupId") == group["translationGroupId"]
                    and result.get("sourceUnitIds") == group["sourceUnitIds"],
                    f"Sol group identity changed: {stem}")
            utterances = _utterances(result.get("targetUtterances"))
            final_text = "".join(utterances)
            coverage = result.get("coverage")
            require(isinstance(coverage, list)
                    and [row.get("sourceUnitId") for row in coverage] == group["sourceUnitIds"]
                    and all(isinstance(row.get("targetText"), str)
                            and _coverage_substring(row["targetText"], final_text)
                            for row in coverage),
                    f"Sol source coverage is incomplete: {stem}")
            semantic = normalize_semantic_review(result.get("semanticReview"))
            require(isinstance(semantic, dict) and semantic.get("status") in {"pass", "fail"}
                    and isinstance(semantic.get("checks"), dict)
                    and set(semantic["checks"]) == set(SEMANTIC_CHECKS)
                    and all(value in {"pass", "fail"} for value in semantic["checks"].values())
                    and isinstance(semantic.get("evidence"), str) and semantic["evidence"].strip()
                    and isinstance(semantic.get("uncertainty"), list)
                    and isinstance(semantic.get("issues"), list),
                    f"Sol semantic review is incomplete: {stem}")
            reviewed_row = {**copy.deepcopy(group), "targetUtterances": utterances,
                            "coverage": coverage, "semanticReview": semantic,
                            "translatorRequestId": translated["requestId"],
                            "reviewerRequestId": reviewed_response["requestId"]}
            if semantic["status"] != "pass" or any(value != "pass" for value in semantic["checks"].values()) \
                    or semantic["uncertainty"] or semantic["issues"]:
                raise ValueError(f"Sol flagged group {stem}; inspect saved response before admission")
            return reviewed_row, validation_span
    def process_group(item):
        index, _ = item
        with accounting.stage(f"layer2.group.{request['targetLocale']}.{index:04d}",
                              billing="orchestrator"):
            return _process_group(item)
    results = ordered_group_results(list(enumerate(plan, 1)), process_group, workers)
    dependencies = accounting.bounded_dependencies(
        f"layer2.evidence_join.{request['targetLocale']}", [span for _, span in results],
        work_unit_id=f"l2.{request['targetLocale']}.evidence_join")
    with accounting.stage(f"layer2.evidence_assembly.{request['targetLocale']}",
                          depends_on=dependencies, executor_type="deterministic_program",
                          work_unit_id=f"l2.{request['targetLocale']}.evidence_assembly") as assembly_span:
        reviewed = [row for row, _ in results]
        translator_ids = list(dict.fromkeys(row["translatorRequestId"] for row in reviewed))
        reviewer_ids = list(dict.fromkeys(row["reviewerRequestId"] for row in reviewed))
        require(len(translator_ids) == len(reviewed) and len(reviewer_ids) == len(reviewed)
                and not set(translator_ids).intersection(reviewer_ids),
                "Model response IDs must be distinct across groups and roles")
        evidence = copy.deepcopy(request)
        evidence["generation"] = {role: {"model": policy[role]["model"],
                                         "promptVersion": policy[role]["promptVersion"],
                                         "requestIds": ids}
                                  for role, ids in (("translator", translator_ids),
                                                    ("reviewer", reviewer_ids))}
        evidence["groups"] = reviewed
        evidence_path = out / "evidence.json"
        if evidence_path.exists():
            require(producer._load(evidence_path) == evidence, "Cached evidence changed")
        else:
            save_new(evidence_path, evidence)
        accounting.record_workload("layer2.evidence_identity", {"evidenceSha256": policy_tools.canonical_sha256(evidence)})
    # Export only after the completion event is durable. Trace identity never
    # enters the canonical evidence payload or its hashes.
    if completion_spans is not None:
        completion_spans.append(assembly_span)
    return evidence


def run_accounted(source: dict, anchor: dict, policy: dict, out_dir: Path,
                  api_key: str, call, group_plan_data, plugin: Path,
                  revision_brief: dict | None, reuse_from: Path | None,
                  *, partial_repair_brief: dict | None = None,
                  resume_cache_from: Path | None = None,
                  progress_ledger: Path | None = None,
                  cache_only: bool = False, progress_callback=None,
                  predecessor_spans=(), completion_spans: list[str] | None = None) -> dict:
    locale = policy["targetLocale"]
    with measure.producer_step(progress_ledger, f"L2-02@{locale}", locale=locale) as metrics:
        with accounting.accounting_session(out_dir / "accounting", "layer2_models",
                                           {"targetLocale": locale},
                                           evidence_directory=out_dir):
            with accounting.stage(f"layer2.source_admission.{locale}", depends_on=list(predecessor_spans),
                                  executor_type="deterministic_program",
                                  work_unit_id=f"l2.{locale}.source_admission") as source_span:
                request = producer.prepare_request(source, anchor, policy)
                plan = group_plan(request, anchor, group_plan_data)
                window = source["source"]["approvedWindow"]
                accounting.record_workload("layer2.source_identity", {
                    **{k: request[k] for k in ("englishSourcePackageJsonSha256", "anchorManifestSha256", "translationPolicySha256")},
                    "sourceDurationSeconds": window["endSeconds"] - window["startSeconds"],
                    "sourceMediaSha256": source["source"]["media"]["sha256"],
                    "translationGroups": len(plan), "sourceUnits": len(request["sourceUnits"])})
            metrics.update(translationGroups=len(plan), sourceUnits=len(request["sourceUnits"]))
            evidence = _run_prepared_groups(
                request, anchor, policy, out_dir, api_key, call, plan, plugin,
                revision_brief, reuse_from, partial_repair_brief, resume_cache_from,
                source_admission_span=source_span, cache_only=cache_only,
                progress_callback=progress_callback, completion_spans=completion_spans)
        metrics["doneUnits"] = len(evidence["groups"])
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--english-source-package", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--group-plan", type=Path)
    parser.add_argument("--revision-brief", type=Path,
                        help="Source-bound changed-group proposal; requires --reuse-from")
    parser.add_argument("--reuse-from", type=Path,
                        help="Prior model run; unchanged requests reuse verified caches")
    parser.add_argument("--partial-repair-brief", type=Path,
                        help="Source-bound failed-group repair; accepts an incomplete prior run")
    parser.add_argument("--resume-cache-from", type=Path,
                        help="Reuse verified paid responses from an incomplete attempt of this revision")
    parser.add_argument("--progress-ledger", type=Path,
                        help="Record checkpoint and per-group substage timing in the four-layer ledger")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    require(args.revision_brief is None or args.reuse_from is not None,
            "--revision-brief requires --reuse-from")
    require(args.partial_repair_brief is None or args.reuse_from is not None,
            "--partial-repair-brief requires --reuse-from")
    require(args.revision_brief is None or args.partial_repair_brief is None,
            "Choose either --revision-brief or --partial-repair-brief")
    require(args.resume_cache_from is None or args.partial_repair_brief is not None,
            "--resume-cache-from requires --partial-repair-brief")
    source, anchor, policy = (producer._load(path) for path in
                              (args.english_source_package, args.anchor, args.policy))
    # Validate all policy/source/plan conditions before requiring a secret or making a paid call.
    request = producer.prepare_request(source, anchor, policy)
    plan = group_plan(request, anchor, json.loads(args.group_plan.read_text(encoding="utf-8"))
                      if args.group_plan else None)
    require_plugin_identity(args.plugin, policy["languageReview"]["pluginImplementationSha256"])
    api_key = os.environ.get("OPENAI_API_KEY")
    require(bool(api_key), "OPENAI_API_KEY is not configured")
    evidence = run_accounted(
        source, anchor, policy, args.out_dir, api_key,
        lambda key, payload: sermon_pipeline.chat_json(key, payload, retries=1),
        plan, args.plugin,
        producer._load(args.revision_brief) if args.revision_brief else None,
        args.reuse_from,
        partial_repair_brief=producer._load(args.partial_repair_brief)
        if args.partial_repair_brief else None,
        resume_cache_from=args.resume_cache_from,
        progress_ledger=args.progress_ledger)
    print(json.dumps({"status": "independent_model_review_pass",
                      "groups": len(evidence["groups"]),
                      "evidence": str((args.out_dir / "evidence.json").resolve())}))


if __name__ == "__main__":
    main()
