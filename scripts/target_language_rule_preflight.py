"""Inspect pinned Layer 2 rules before dispatch; no models or human approval.

The plugin's executable checks remain authoritative at candidate admission.
Static inspection deliberately does not execute a plugin to discover metadata.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path

try:
    from scripts import produce_target_language_candidate as producer
    from scripts import target_language_policy as policy_tools
except ImportError:
    import produce_target_language_candidate as producer
    import target_language_policy as policy_tools

SCHEMA = "sermon-target-language-rule-preflight-v1"
BUNDLE_SCHEMA = "sermon-target-language-model-rules-v1"
CONSUMERS = ("translator", "reviewer", "language_plugin", "candidate")
INSTRUCTION = (
    "Consume the frozen modelRules in the input. Preserve complete source scripture "
    "clauses and every reviewed exact quotation fragment; never shorten, duplicate, "
    "or extend one to fill a timing window. Distinguish quoted wording from speaker "
    "paraphrase. Preserve numbers in their spoken context. Do not add editorial or "
    "parenthetical Bible references absent from the spoken English. If English only "
    "says 'verse 5', keep that specificity; do not add an unspoken book or chapter "
    "even when context identifies it. Exact quotation text does not authorize speaking "
    "its metadata reference. Flag missing or uncertain quote evidence; never invent it. "
)


def require(condition, reason):
    if not condition:
        raise ValueError("Layer 2 rule preflight: " + reason)


def _sha_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _literals(path):
    """Read literal assignments without importing/executing the pinned plugin."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values = {}
    def literal(node):
        if isinstance(node, ast.Name) and node.id in values:
            return copy.deepcopy(values[node.id])
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            items = [literal(child) for child in node.elts]
            return tuple(items) if isinstance(node, ast.Tuple) else set(items) if isinstance(node, ast.Set) else items
        if isinstance(node, ast.Dict):
            return {literal(key): literal(value) for key, value in zip(node.keys, node.values)}
        return ast.literal_eval(node)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            continue
        if isinstance(target, ast.Name):
            try:
                values[target.id] = literal(node.value)
            except (ValueError, TypeError):
                pass
    # Older plugins keep their required list inside review_group.
    if "REQUIRED" not in values:
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "required"):
                try:
                    values["REQUIRED"] = literal(node.value)
                except (ValueError, TypeError):
                    pass
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for argument in node.keywords:
                if argument.arg == "edition":
                    try:
                        values["EXPECTED_EDITION"] = literal(argument.value)
                    except (ValueError, TypeError):
                        pass
    return values


def _quoted_rules(facts, request, policy, plan):
    rows = {row["sourceUnitId"]: row["english"] for row in request["sourceUnits"]}
    quotes = []
    if 'DIAGNOSTIC_QUOTE_BINDINGS' in facts:
        from scripts.language_review_plugins.diagnostic_pinned_quotes import validate_bindings
        require(facts.get('DIAGNOSTIC_ONLY') is True and facts.get('DIAGNOSTIC_PINNED_QUOTES') is True,
                'pinned diagnostic quote plugin must remain diagnostic-only')
        bindings = facts['DIAGNOSTIC_QUOTE_BINDINGS']
        for quote in validate_bindings(bindings, request, policy, plan):
            for part in quote['parts']:
                quotes.append({'sourceUnitIds': [part['sourceUnitId']],
                    'translationGroupId': quote['translationGroupId'],
                    'englishStartOffset': part['englishStartOffset'], 'englishEndOffset': part['englishEndOffset'],
                    'english': part['englishExcerpt'], 'targetText': part['targetText'],
                    'targetTextSha256': part['targetTextSha256'], 'reference': quote['reference'],
                    'classification': 'diagnostic_pinned_excerpt', 'citationUseStatus': 'pending',
                    'provenance': copy.deepcopy(bindings['provenance'])})
    if "SOURCE_SHA256" in facts:
        require(facts["SOURCE_SHA256"] == request["englishSourcePackageJsonSha256"],
                "plugin source differs from request")
    if "QUOTED_UNITS" in facts:
        require(policy["scripture"]["quoteCheckPolicy"] == "source_bound_exact_quote",
                "exact-quote plugin differs from scripture policy")
        for unit_id, (english, target) in facts["QUOTED_UNITS"].items():
            require(rows.get(unit_id) == english, "approved English quote unit changed")
            require(any(group["sourceUnitIds"] == [unit_id] for group in plan),
                    "exact quote must occupy its approved group")
            quotes.append({"sourceUnitIds": [unit_id], "english": english,
                           "targetText": target, "targetTextSha256": _sha_text(target)})
        for excerpt, digest in facts.get("APPROVED_EXCERPTS", {}).values():
            require(_sha_text(excerpt) == digest, "approved quote excerpt hash changed")
    approval = facts.get("APPROVED_BOUNDARY_REVIEW")
    if "APPROVED_BOUNDARY_REVIEW" in facts:
        require(isinstance(approval, dict) and approval.get("humanApproval") is True
                and approval.get("decision") == "approved"
                and approval.get("englishSourcePackageJsonSha256") == request["englishSourcePackageJsonSha256"]
                and approval.get("anchorManifestJsonSha256") == request["anchorManifestSha256"],
                "quote boundary receipt is missing or belongs to another source")
        require(policy["scripture"]["quoteCheckPolicy"] == "source_bound_exact_quote"
                and policy["scripture"]["editionId"] == facts.get("CUV_EDITION_ID"),
                "quote edition or policy differs from plugin")
        # Reuse the checked-in scripture library, without importing the plugin.
        try:
            from scripts.cuv_scripture import CuvLibrary
        except ImportError:
            from cuv_scripture import CuvLibrary
        library = CuvLibrary.from_path()
        decisions = approval.get("decisions", [])
        candidates = facts["CANDIDATE_VERSES"]
        require(len(decisions) == len(candidates)
                and {row.get("candidateId") for row in decisions} == set(candidates),
                "quote decisions do not cover plugin candidates")
        for decision in decisions:
            candidate_id = decision["candidateId"]
            allowed = facts["CANDIDATE_QUOTE_UNITS"][candidate_id]
            parts = decision.get("parts", [])
            paraphrase = decision.get("paraphraseUnitIds", [])
            require(decision.get("classification") in {"direct_quote", "partial_direct_quote", "speaker_paraphrase"}
                    and (decision["classification"] == "speaker_paraphrase") == (not parts),
                    "quote classification differs from approved parts")
            quoted = {part["sourceUnitId"] for part in parts}
            require(not quoted.intersection(paraphrase) and quoted | set(paraphrase) == allowed,
                    "quote and paraphrase coverage differs from plugin")
            for part in parts:
                unit_id = part["sourceUnitId"]
                start, end = part["englishStartOffset"], part["englishEndOffset"]
                require(unit_id in rows and type(start) is int and type(end) is int
                        and 0 <= start < end <= len(rows[unit_id]), "quote span is outside source unit")
                lower, upper = facts.get("MIXED_UNIT_QUOTE_LIMITS", {}).get(unit_id, (0, len(rows[unit_id])))
                require(lower <= start < end <= upper, "quote span includes speaker commentary")
                require(_sha_text(rows[unit_id][start:end]) == part["englishExcerptSha256"],
                        "approved English quote span changed")
                require(part["reference"] in candidates[candidate_id], "quote reference differs from plugin")
                selected = library.lookup(part["reference"], excerpt=part["cuvExcerpt"])
                require(selected["textSha256"] == part["cuvExcerptSha256"], "pinned quote excerpt changed")
                quotes.append({"sourceUnitIds": [unit_id], "englishStartOffset": start,
                               "englishEndOffset": end, "english": rows[unit_id][start:end],
                               "targetText": part["cuvExcerpt"], "targetTextSha256": part["cuvExcerptSha256"],
                               "reference": part["reference"], "classification": decision["classification"]})
            _bind_quote_group(plan, rows, decision, parts, library)
    return quotes


def _bind_quote_group(plan, rows, decision, parts, library):
    """Keep one approved quotation inside one translation group."""
    if not parts:
        return
    order = list(rows)
    quoted_ids = [part["sourceUnitId"] for part in parts]
    require(len(quoted_ids) == len(set(quoted_ids)), "quote units repeat inside one decision")
    indexes = [order.index(unit_id) for unit_id in quoted_ids]
    require(indexes == sorted(indexes), "quote units were reordered in the source")
    if decision["classification"] == "direct_quote":
        require(indexes == list(range(indexes[0], indexes[-1] + 1)),
                "quote units are not contiguous in the source")
    matches = [group for group in plan if set(quoted_ids) <= set(group["sourceUnitIds"])]
    require(len(matches) == 1, "quote units were split across groups or omitted")
    group_ids = matches[0]["sourceUnitIds"]
    require([unit_id for unit_id in group_ids if unit_id in quoted_ids] == quoted_ids,
            "quote units were reordered inside the translation group")
    if decision["classification"] != "direct_quote":
        return
    references = [part["reference"] for part in parts]
    combined = "".join(part["cuvExcerpt"] for part in parts)
    require(len(set(references)) == 1 and library.lookup(references[0])["text"] == combined,
            "complete direct quote was split or shortened")
    require(group_ids == quoted_ids, "complete quotation group was split or extended")


def preflight(request, policy, plugin_path: Path, plan, *, consumer_bindings=None):
    """Validate actual policy/plugin/source inputs and freeze model-facing rules.

Consumer bindings describe the inputs to be consumed, not completed plugin or
candidate execution. Callers can validate independently collected bindings.
"""
    require(request.get("translationPolicySha256") == policy_tools.canonical_sha256(policy),
            "request policy hash differs")
    require(request.get("targetLocale") == policy.get("targetLocale"), "request locale differs")
    for component in ("translator", "reviewer", "terminology", "scripture", "languageReview", "formatting"):
        require(policy["componentSha256"].get(component) == policy_tools.canonical_sha256(policy[component]),
                "policy component changed: " + component)
    require(policy["terminology"]["seriesTableSha256"] == policy_tools.file_sha256(policy_tools.SERIES_TABLE),
            "terminology table changed")
    actual_plugin = producer.plugin_implementation_sha256(plugin_path)
    require(actual_plugin == policy["languageReview"].get("pluginImplementationSha256"),
            "plugin implementation differs from frozen policy")
    facts = _literals(plugin_path)
    require(facts.get("PLUGIN_ID") == policy["languageReview"]["pluginId"]
            and isinstance(facts.get("PLUGIN_VERSION"), str) and bool(facts["PLUGIN_VERSION"]),
            "plugin ID or version differs")
    if "REQUIRED" in facts:
        require(facts["REQUIRED"] == policy["languageReview"]["requiredChecks"],
                "plugin required checks differ from policy")
    if "EXPECTED_EDITION" in facts:
        require(policy["scripture"]["editionId"] == facts["EXPECTED_EDITION"],
                "plugin scripture edition differs from policy")
    if plugin_path.name == "zh_hans_sermon.py":
        require(policy["scripture"]["editionId"] == "CUV", "Chinese exact-quote plugin requires CUV")
    # Weekly reference plugins deliberately make no edition quotation claim.
    if plugin_path.name in producer.WEEKLY_REFERENCE_PLUGIN_NAMES:
        require(policy["scripture"]["quoteCheckPolicy"] == "references_only"
                and policy["scripture"]["editionId"] is None, "reference-only plugin differs from scripture policy")
    if plugin_path.name in producer.LAODICEA_PLUGIN_NAMES:
        shared = _literals(plugin_path.parent / "laodicea_common.py")
        require(shared["SOURCE_SHA256"] == request["englishSourcePackageJsonSha256"],
                "Laodicea plugin source differs from request")
        require(policy["scripture"]["quoteCheckPolicy"] == "references_only",
                "Laodicea plugin requires reference-only policy")
    quotes = _quoted_rules(facts, request, policy, plan)
    if plugin_path.name in {"ko_sermon.py", "es_sermon.py"}:
        shared = _literals(plugin_path.parent / "common.py")
        require(shared["SOURCE_SHA256"] == request["englishSourcePackageJsonSha256"],
                "locale exact-quote plugin source differs from request")
        require(policy["scripture"]["quoteCheckPolicy"] == "source_bound_exact_quote",
                "locale plugin requires exact-quote policy")
        rows = {row["sourceUnitId"]: row["english"] for row in request["sourceUnits"]}
        for unit_id, english in shared["ENGLISH_QUOTES"].items():
            require(rows.get(unit_id) == english, "locale approved English quote text changed")
        for key, unit_ids in (("EXCERPT_2", [shared["QUOTE_2_UNIT"]]),
                              ("EXCERPT_3", list(shared["QUOTE_3_GROUP"]))):
            text, digest = facts[key]
            require(_sha_text(text) == digest, "locale quote excerpt hash changed")
            require(any(group["sourceUnitIds"] == unit_ids for group in plan),
                    "locale complete quotation group was split or extended")
            quotes.append({"sourceUnitIds": unit_ids, "targetText": text, "targetTextSha256": digest})
    plugin_names = facts.get("NAMES", {})
    for term in policy["terminology"]["properNames"]:
        if term["source"] in plugin_names:
            expected_names = plugin_names[term["source"]]
            expected_names = [expected_names] if isinstance(expected_names, str) else expected_names
            require(term["target"] in expected_names, "plugin proper-name form differs from frozen terminology")
    bundle = {"schemaVersion": BUNDLE_SCHEMA, "targetLocale": policy["targetLocale"],
              "terminology": copy.deepcopy(policy["terminology"]),
              "scripture": copy.deepcopy(policy["scripture"]),
              "formatting": copy.deepcopy(policy["formatting"]),
              "registerRules": copy.deepcopy(policy["languageReview"]["registerRules"]),
              "citationRule": "preserve_spoken_specificity_no_editorial_additions",
              "numberRule": "preserve_source_number_and_context",
              "quotationRule": "preserve_complete_approved_fragments_no_timing_truncation",
              "modelInstruction": INSTRUCTION,
              "pluginNumberForms": copy.deepcopy(facts.get("NUMBERS", facts.get("ENGLISH_NUMBERS", {}))),
              "pluginNameForms": copy.deepcopy(plugin_names),
              "exactQuotes": quotes}
    if facts.get('DIAGNOSTIC_PINNED_QUOTES') is True:
        bundle['quotationRule'] = 'preserve_complete_diagnostic_pinned_fragments_pending_provenance'
        bundle['modelInstruction'] = (
            'This is an isolated diagnostic baseline, not an approved Bible edition. '
            'Preserve every frozen target fragment exactly and in source order within its full bound group, '
            'including surrounding speaker commentary. Do not reproduce it in another group or speak '
            'its reference metadata. Target provenance and citation permission remain pending. '
            'Do not claim NKRV, RVR60, CUV, edition verification or human approval. ' + INSTRUCTION)
    # Literal plugin tuples must have the same JSON types after durable readback.
    bundle = json.loads(json.dumps(bundle, ensure_ascii=False))
    rule_hash = policy_tools.canonical_sha256(bundle)
    expected = {"ruleBundleSha256": rule_hash,
                "terminologySha256": policy["componentSha256"]["terminology"],
                "scriptureSha256": policy["componentSha256"]["scripture"]}
    bindings = consumer_bindings if consumer_bindings is not None else {role: copy.deepcopy(expected) for role in CONSUMERS}
    require(set(bindings) == set(CONSUMERS) and all(bindings[role] == expected for role in CONSUMERS),
            "translator/reviewer/plugin/candidate rule bindings differ")
    return {"schemaVersion": SCHEMA, "status": "inputs_frozen_not_execution_evidence",
            "humanApproval": False, "modelCalls": 0,
            "translationPolicySha256": request["translationPolicySha256"],
            "englishSourcePackageJsonSha256": request["englishSourcePackageJsonSha256"],
            "anchorManifestSha256": request["anchorManifestSha256"],
            "pluginImplementationSha256": actual_plugin, "pluginId": facts["PLUGIN_ID"],
            "pluginVersion": facts["PLUGIN_VERSION"], "consumerBindings": copy.deepcopy(bindings),
            "modelConfiguration": {role: copy.deepcopy(policy[role]) for role in ("translator", "reviewer")},
            "ruleBundleSha256": rule_hash, "modelRules": bundle,
            "inspectionScope": "recognized_literal_plugin_rules" if quotes or "REQUIRED" in facts else "policy_and_plugin_identity_only"}


def group_rules(receipt, source_unit_ids):
    bundle = copy.deepcopy(receipt["modelRules"])
    bundle["exactQuotes"] = [quote for quote in bundle["exactQuotes"] if set(quote["sourceUnitIds"]) & set(source_unit_ids)]
    return {"ruleBundleSha256": receipt["ruleBundleSha256"], **bundle}


def verify_model_prompt(role, prompt, receipt, policy):
    """Check the actual prompt immediately before its cache/dispatch marker."""
    require(role in {"translator", "reviewer"}, "unknown model consumer")
    require(receipt["modelConfiguration"][role] == policy[role], "model configuration differs from frozen preflight")
    actual = prompt.get("input", {})
    require(actual.get("modelRules") == group_rules(receipt, actual.get("sourceUnitIds", [])),
            "actual model rule input differs from frozen preflight")
    for key in ("terminology", "scripture", "formatting"):
        require(actual.get(key) == receipt["modelRules"][key], "actual model input differs: " + key)
    require(INSTRUCTION in prompt.get("instruction", ""), "model instruction omits frozen rule requirement")


def verify_consumer_receipt(request, policy, plugin_path, evidence, receipt):
    plan = [{"translationGroupId": group["translationGroupId"], "sourceUnitIds": group["sourceUnitIds"]}
            for group in evidence.get("groups", [])]
    expected = preflight(request, policy, plugin_path, plan)
    require(receipt == expected, "plugin/candidate inputs differ from frozen preflight receipt")
    return expected


def verify_prior_model_inputs(directory, request, policy, plan, receipt, *, transport_identity=None):
    """Reject an unproven historical carry-forward before creating a new attempt.

Exact frozen payloads prove which rules were sent; this does not establish a
successful provider outcome or authorize copying a human approval.
"""
    stored = directory / "rule-preflight.json"
    require(stored.is_file() and producer._load(stored) == receipt,
            "prior cache lacks matching frozen rule receipt; explicit migration required")
    rows = request["sourceUnits"]
    offset = 0
    for index, group in enumerate(plan, 1):
        english = rows[offset:offset + len(group["sourceUnitIds"])]
        context = {"before": rows[max(0, offset - 3):offset],
                   "after": rows[offset + len(english):offset + len(english) + 2]}
        offset += len(english)
        for role, suffix in (("translator", "astra"), ("reviewer", "sol")):
            cache = directory / f"group-{index:04d}-{suffix}.json"
            if not cache.is_file():
                continue
            preview_path = cache.with_suffix(".policy-preview.json")
            require(preview_path.is_file(), "prior cache lacks frozen model payload; explicit migration required")
            preview = producer._load(preview_path)
            payload = preview.get("payload")
            fingerprint = policy_tools.canonical_sha256(
                {"payload": payload, "modelTransportIdentity": transport_identity}
                if transport_identity is not None else payload)
            cached = producer._load(cache)
            require(isinstance(payload, dict)
                    and preview.get("role") == role
                    and payload.get("model") == policy[role]["model"]
                    and payload.get("reasoning_effort") == policy[role]["reasoningEffort"]
                    and preview.get("policySha256") == policy_tools.canonical_sha256(policy)
                    and preview.get("policy") == policy
                    and preview.get("payloadSha256") == policy_tools.canonical_sha256(payload)
                    and cached.get("payloadSha256") == fingerprint,
                    "prior model payload does not match cached response")
            raw_path = cache.with_suffix(".raw.json")
            if raw_path.is_file():
                raw = producer._load(raw_path)
                require(raw.get("payloadSha256") == fingerprint
                        and isinstance(raw.get("response"), dict)
                        and raw["response"].get("id") == cached.get("requestId"),
                        "prior raw response transport or request identity differs")
            messages = payload.get("messages", [])
            require(len(messages) == 2 and messages[0].get("role") == "system"
                    and messages[1].get("role") == "user", "prior model payload messages changed")
            actual = json.loads(messages[1]["content"])
            require(actual.get("translationGroupId") == group["translationGroupId"]
                    and actual.get("sourceUnitIds") == group["sourceUnitIds"]
                    and actual.get("englishUnits") == english and actual.get("context") == context,
                    "prior model source or context differs")
            verify_model_prompt(role, {"instruction": messages[0]["content"], "input": actual}, receipt, policy)


def change_plan(before, after):
    """Separate plugin revalidation from model-facing changes; never authorize reuse."""
    for receipt in (before, after):
        require(receipt.get("schemaVersion") == SCHEMA
                and receipt.get("ruleBundleSha256") == policy_tools.canonical_sha256(receipt.get("modelRules")),
                "preflight receipt rule hash changed")
    same_rules = (before["ruleBundleSha256"] == after["ruleBundleSha256"]
                  and before["modelConfiguration"] == after["modelConfiguration"])
    same_source = all(before[key] == after[key] for key in ("englishSourcePackageJsonSha256", "anchorManifestSha256"))
    plugin_changed = before["pluginImplementationSha256"] != after["pluginImplementationSha256"]
    return {"schemaVersion": "sermon-target-language-rule-change-plan-v1",
            "classification": "plugin_only_revalidate" if same_rules and same_source and plugin_changed else "unchanged" if same_rules and same_source else "model_rules_or_source_changed",
            "requiresModelRecompute": not (same_rules and same_source),
            "requiredStages": ["language_plugin", "candidate", "approval_binding", "downstream_binding"] if same_rules and same_source and plugin_changed else [],
            "automaticReuseAuthorized": False, "humanApproval": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("request", "policy", "plugin", "group-plan"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    print(json.dumps(preflight(load(args.request), load(args.policy), args.plugin, load(args.group_plan)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
