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
                caller: Callable[[str, dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
    model = policy[role]["model"]
    payload = {"model": model, "reasoning_effort": policy[role]["reasoningEffort"],
               "messages": [{"role": "system", "content": prompt["instruction"]},
                            {"role": "user", "content": json.dumps(prompt["input"], ensure_ascii=False)}],
               "response_format": {"type": "json_object"}}
    fingerprint = policy_tools.canonical_sha256(payload)
    if output.exists():
        saved = producer._load(output)
        require(saved.get("payloadSha256") == fingerprint
                and saved.get("model") == model
                and isinstance(saved.get("requestId"), str) and saved["requestId"]
                and isinstance(saved.get("result"), dict),
                f"Cached {role} response belongs to different inputs: {output}")
        return saved
    marker = output.with_suffix(".started.json")
    require(not marker.exists(), f"Uncertain paid {role} call; inspect before retry: {marker}")
    save_new(marker, {"role": role, "payloadSha256": fingerprint,
                      "status": "started_response_unconfirmed"})
    response = caller(api_key, payload)
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
    marker.unlink()
    return saved


def _utterances(value: object) -> list[str]:
    require(isinstance(value, list) and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value),
            "Model must return nonempty targetUtterances")
    return [item.strip() for item in value]


def run(source: dict[str, Any], anchor: dict[str, Any], policy: dict[str, Any],
        out: Path, api_key: str,
        caller: Callable[[str, dict[str, Any]], dict[str, Any]],
        custom_plan: list[dict[str, Any]] | None = None,
        plugin_path: Path | None = None) -> dict[str, Any]:
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
    identity = {"request": request, "groupPlan": plan,
                "runnerImplementationSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
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
                                 out / f"{stem}-astra.json", api_key, caller)
        draft = translated["result"]
        require(draft.get("translationGroupId") == group["translationGroupId"]
                and draft.get("sourceUnitIds") == group["sourceUnitIds"],
                f"Astra group identity changed: {stem}")
        draft_text = "".join(_utterances(draft.get("targetUtterances")))
        require(isinstance(draft.get("coverage"), list)
                and [row.get("sourceUnitId") for row in draft["coverage"]] == group["sourceUnitIds"]
                and all(isinstance(row.get("targetText"), str) and row["targetText"].strip()
                        and row["targetText"] in draft_text for row in draft["coverage"]),
                f"Astra source coverage is incomplete: {stem}")
        review_prompt = {
            "instruction": ("Independently compare the English source and Astra draft, one group at a time. "
                            "Correct any error in final targetUtterances and coverage. Check every English "
                            "unit for omitted or added meaning, negations, numbers, names, and quotation "
                            "attribution. If uncertain or unresolved, mark fail. Return JSON with exactly "
                            "translationGroupId, sourceUnitIds, targetUtterances, coverage, semanticReview. "
                            "semanticReview has status, checks (completeMeaning, negationsNumbersNames, "
                            "quotationAttribution, noAddedMeaning), evidence, uncertainty, issues. "
                            "Do not claim human approval. Prompt version: " + policy["reviewer"]["promptVersion"]),
            "input": {**common, "astraDraft": draft}}
        reviewed_response = _model_call("reviewer", review_prompt, policy,
                                        out / f"{stem}-sol.json", api_key, caller)
        result = reviewed_response["result"]
        require(result.get("translationGroupId") == group["translationGroupId"]
                and result.get("sourceUnitIds") == group["sourceUnitIds"],
                f"Sol group identity changed: {stem}")
        utterances = _utterances(result.get("targetUtterances"))
        final_text = "".join(utterances)
        coverage = result.get("coverage")
        require(isinstance(coverage, list)
                and [row.get("sourceUnitId") for row in coverage] == group["sourceUnitIds"]
                and all(isinstance(row.get("targetText"), str) and row["targetText"].strip()
                        and row["targetText"] in final_text for row in coverage),
                f"Sol source coverage is incomplete: {stem}")
        semantic = result.get("semanticReview")
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
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
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
                   if args.group_plan else None, args.plugin)
    print(json.dumps({"status": "independent_model_review_pass",
                      "groups": len(evidence["groups"]),
                      "evidence": str((args.out_dir / "evidence.json").resolve())}))


if __name__ == "__main__":
    main()
