#!/usr/bin/env python3
"""Run source-bound Layer 2 Astra translation and Sol independent group review.

Outputs are recoverable machine evidence. Human approval remains a separate gate.
An unfinished request marker deliberately blocks automatic paid retries.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Callable

try:
    from scripts import produce_target_language_candidate as producer
    from scripts import sermon_pipeline
    from scripts import target_language_policy as policy_tools
except ImportError:
    import produce_target_language_candidate as producer
    import sermon_pipeline
    import target_language_policy as policy_tools


MODEL_ROLES = {"translator": "gpt-6-astra", "reviewer": "gpt-6-sol"}
SEMANTIC_CHECKS = ("completeMeaning", "negationsNumbersNames", "quotationAttribution", "noAddedMeaning")
REVISION_BRIEF_SCHEMA = "sermon-target-language-group-revision-brief-v1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def save_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


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


def _model_call(role: str, prompt: dict[str, Any], policy: dict[str, Any],
                output: Path, api_key: str,
                caller: Callable[[str, dict[str, Any]], dict[str, Any]],
                reuse_from: Path | None = None) -> dict[str, Any]:
    model = policy[role]["model"]
    payload = {"model": model, "reasoning_effort": policy[role]["reasoningEffort"],
               "messages": [{"role": "system", "content": prompt["instruction"]},
                            {"role": "user", "content": json.dumps(prompt["input"], ensure_ascii=False)}],
               "response_format": {"type": "json_object"}}
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
        return saved
    marker = output.with_suffix(".started.json")
    raw_path = output.with_suffix(".raw.json")
    if raw_path.exists():
        raw = producer._load(raw_path)
        require(raw.get("payloadSha256") == fingerprint
                and isinstance(raw.get("response"), dict),
                f"Saved raw {role} response belongs to different inputs: {raw_path}")
        response = raw["response"]
    else:
        require(not marker.exists(), f"Uncertain paid {role} call; inspect before retry: {marker}")
        save_new(marker, {"role": role, "payloadSha256": fingerprint,
                          "status": "started_response_unconfirmed"})
        response = caller(api_key, payload)
        # Persist the actual completed API response before any identity, finish, or
        # JSON checks; an invalid paid response must remain inspectable and reusable.
        save_new(raw_path, {"payloadSha256": fingerprint, "response": response})
    require(isinstance(response, dict) and isinstance(response.get("id"), str)
            and response["id"] and response.get("model") == model,
            f"{role} response lacks exact model and request identity")
    choices = response.get("choices")
    require(isinstance(choices, list) and len(choices) == 1
            and choices[0].get("finish_reason") == "stop", f"{role} response is incomplete")
    content = choices[0].get("message", {}).get("content")
    require(isinstance(content, str), f"{role} response has no JSON content")
    parsed = json.loads(content)
    require(isinstance(parsed, dict), f"{role} response must be a JSON object")
    saved = {"payloadSha256": fingerprint, "requestId": response["id"],
             "model": model, "result": parsed}
    save_new(output, saved)
    marker.unlink(missing_ok=True)
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


def run(source: dict[str, Any], anchor: dict[str, Any], policy: dict[str, Any],
        out: Path, api_key: str,
        caller: Callable[[str, dict[str, Any]], dict[str, Any]],
        custom_plan: list[dict[str, Any]] | None = None,
        plugin_path: Path | None = None,
        revision_brief: dict[str, Any] | None = None,
        reuse_from: Path | None = None) -> dict[str, Any]:
    request = producer.prepare_request(source, anchor, policy)
    for role, expected in MODEL_ROLES.items():
        require(policy[role]["model"] == expected,
                f"Production {role} model must be {expected}; freeze a new policy")
    require(policy["batching"] == {"batchSize": 1, "workers": 1},
            "Per-group production runner requires batchSize=1 and workers=1")
    if plugin_path is not None:
        require(producer.plugin_implementation_sha256(plugin_path)
                == policy["languageReview"]["pluginImplementationSha256"],
                "Language plugin implementation differs from frozen policy")
    plan = group_plan(request, anchor, custom_plan)
    prior_evidence = producer._load(reuse_from / "evidence.json") if reuse_from else None
    briefs = validate_revision_brief(revision_brief, request, plan, prior_evidence)
    if reuse_from is not None:
        require(reuse_from.resolve() != out.resolve(), "Reuse source and output must differ")
    identity = {"request": request, "groupPlan": plan,
                "runnerImplementationSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    if revision_brief is not None:
        identity["revisionBriefSha256"] = policy_tools.canonical_sha256(revision_brief)
    identity_hash = policy_tools.canonical_sha256(identity)
    manifest = out / "run-identity.json"
    if manifest.exists():
        require(producer._load(manifest) == {"sha256": identity_hash},
                "Output directory belongs to another source, policy, or group plan")
    else:
        require(not out.exists() or not any(out.iterdir()), "Output directory is not empty")
        save_new(manifest, {"sha256": identity_hash})
    request_path = out / "request.json"
    if not request_path.exists():
        save_new(request_path, request)
    else:
        require(producer._load(request_path) == request, "Cached request changed")
    units = {row["sourceUnitId"]: row["english"] for row in request["sourceUnits"]}
    reviewed = []
    for index, group in enumerate(plan, 1):
        source_rows = [{"sourceUnitId": unit_id, "english": units[unit_id]}
                       for unit_id in group["sourceUnitIds"]]
        context = {"before": units[request["sourceUnits"][sum(len(row["sourceUnitIds"])
                         for row in plan[:index-1]) - 1]["sourceUnitId"]]
                   if index > 1 else "",
                   "after": units[request["sourceUnits"][sum(len(row["sourceUnitIds"])
                         for row in plan[:index])]["sourceUnitId"]]
                   if index < len(plan) else ""}
        common = {"translationGroupId": group["translationGroupId"],
                  "sourceUnitIds": group["sourceUnitIds"], "englishUnits": source_rows,
                  "context": context, "targetLocale": request["targetLocale"],
                  "terminology": policy["terminology"], "scripture": policy["scripture"],
                  "formatting": policy["formatting"]}
        brief = briefs.get(group["translationGroupId"])
        if brief is not None:
            common["revisionBrief"] = {
                "instruction": ("Treat proposedTargetText as a duration-motivated draft, not "
                                "as verified source truth. Produce concise natural target-language "
                                "text while "
                                "preserving every English meaning, name, number, negation, "
                                "quotation, and rhetorical repetition. Report unresolved "
                                "semantic concerns in independent review."),
                "priorTargetTextSha256": brief["priorTargetTextSha256"],
                "proposedTargetText": brief["proposedTargetText"],
            }
        translate_prompt = {
            "instruction": ("Translate the English sermon group into the target locale. Preserve every "
                            "meaning, negation, number, name, quotation and theological distinction. "
                            "Use context only for interpretation. Return JSON with exactly "
                            "translationGroupId, sourceUnitIds, targetUtterances and coverage. "
                            "Coverage has one sourceUnitId and exact targetText substring per source unit. "
                            "Do not claim human approval. Prompt version: " + policy["translator"]["promptVersion"]),
            "input": common}
        stem = f"group-{index:04d}"
        translated = _model_call("translator", translate_prompt, policy,
                                 out / f"{stem}-astra.json", api_key, caller,
                                 reuse_from / f"{stem}-astra.json"
                                 if reuse_from and brief is None else None)
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
        reviewed_response = _model_call("reviewer", review_prompt, policy,
                                        out / f"{stem}-sol.json", api_key, caller,
                                        reuse_from / f"{stem}-sol.json"
                                        if reuse_from and brief is None else None)
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
        reviewed.append({**copy.deepcopy(group), "targetUtterances": utterances,
                         "coverage": coverage, "semanticReview": semantic,
                         "translatorRequestId": translated["requestId"],
                         "reviewerRequestId": reviewed_response["requestId"]})
        if semantic["status"] != "pass" or any(value != "pass" for value in semantic["checks"].values()) \
                or semantic["uncertainty"] or semantic["issues"]:
            raise ValueError(f"Sol flagged group {stem}; inspect saved response before admission")
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
                        help="Prior complete model run; unchanged requests reuse verified caches")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    require(args.revision_brief is None or args.reuse_from is not None,
            "--revision-brief requires --reuse-from")
    source, anchor, policy = (producer._load(path) for path in
                              (args.english_source_package, args.anchor, args.policy))
    # Validate all policy/source/plan conditions before requiring a secret or making a paid call.
    request = producer.prepare_request(source, anchor, policy)
    group_plan(request, anchor, json.loads(args.group_plan.read_text(encoding="utf-8"))
               if args.group_plan else None)
    require(producer.plugin_implementation_sha256(args.plugin)
            == policy["languageReview"]["pluginImplementationSha256"],
            "Language plugin implementation differs from frozen policy")
    api_key = os.environ.get("OPENAI_API_KEY")
    require(bool(api_key), "OPENAI_API_KEY is not configured")
    evidence = run(source, anchor, policy, args.out_dir, api_key,
                   lambda key, payload: sermon_pipeline.chat_json(key, payload, retries=1),
                   json.loads(args.group_plan.read_text(encoding="utf-8"))
                   if args.group_plan else None, args.plugin,
                   producer._load(args.revision_brief) if args.revision_brief else None,
                   args.reuse_from)
    print(json.dumps({"status": "independent_model_review_pass",
                      "groups": len(evidence["groups"]),
                      "evidence": str((args.out_dir / "evidence.json").resolve())}))


if __name__ == "__main__":
    main()
