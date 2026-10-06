"""Read-only E01/E02 exporters from hash-bound, actually frozen requests.

No provider calls or writes. Historical machine answers never become gold.
E02 retains the exact reviewer prompt: a diagnostic policy stays diagnostic.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

from scripts import judge_english_source_for_translation as english
from scripts import run_target_language_models as translation
from scripts import sermon_sentence_interpretation as identity
from scripts import target_language_policy as policy_tools

LAST_MISSING: list[dict] = []
CONTENT_ADAPTERS = {"english_source_judge_v1", "translation_independent_review_v1"}


def get_content_case_report() -> dict:
    return {"missing": copy.deepcopy(LAST_MISSING), "goldEstablished": False}


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("artifact_not_object")
    return value


def _sha(value) -> str:
    return identity.json_sha256(value)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _question(name: str, instructions: str, choices: tuple[str, ...]) -> dict:
    return {"name": name, "type": "choice", "instructions": instructions,
            "choices": [{"value": v, "description": v.replace("_", " ")} for v in choices]}


def _user(payload: dict) -> dict:
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 2 or messages[0].get("role") != "system" \
            or messages[1].get("role") != "user" or not isinstance(messages[0].get("content"), str):
        raise ValueError("missing_original_request_messages")
    value = json.loads(messages[1]["content"])
    if not isinstance(value, dict):
        raise ValueError("original_input_not_object")
    return value


def _base(stage: str, evidence: dict, payload: dict, path: Path, root: Path, cluster: str,
          adapter: str, questions: list[dict], *, source_kind: str, provenance: dict) -> dict:
    evidence_sha = _sha(evidence)
    return {"caseId": f"{stage.lower()}-{evidence_sha[:16]}", "stageId": stage,
            "subtaskId": "text_and_timing_checks" if stage == "E01" else "draft_issue_projection",
            "sourceKind": source_kind, "clusterId": cluster,
            "sharedEvidence": copy.deepcopy(evidence), "evidenceSha256": evidence_sha,
            "a": {"kind": "chat", "payload": copy.deepcopy(payload), "adapter": adapter},
            "b": {"input": json.dumps(evidence, ensure_ascii=False, sort_keys=True),
                  "questions": questions},
            "expected": None, "oracleKind": "unadjudicated_real_input",
            "provenance": {"sourcePath": str(path.relative_to(root)),
                           "sourceFileSha256": _file_sha(path),
                           "baselinePayloadSha256": _sha(payload), **provenance}}


def _missing(stage: str, reason: str, path: Path | None = None, root: Path | None = None):
    row = {"stageId": stage, "reasonCode": reason}
    if path is not None and root is not None:
        row["sourcePath"] = str(path.relative_to(root))
    LAST_MISSING.append(row)


def _english_cases(root: Path, maximum: int) -> list[dict]:
    cases, seen = [], set()
    preferred = root / "artifacts/next-concurrency-605s-20261005-r12-final/source-frozen/judge-requests/cache"
    paths = sorted(preferred.glob("english-source-judge-*.json")) if preferred.is_dir() else []
    if not paths:
        paths = sorted((root / "artifacts").glob("*/source-frozen/judge-requests/cache/english-source-judge-*.json"))
    def historical_risk_first(path):
        try:
            saved = _load(path)
            parsed = json.loads(translation.completed_response_content(saved["response"], "gpt-6.1-sol", "source_judge"))
            return 0 if any(row.get("risk") == "high" for row in parsed.get("sentences", [])) else 1
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return 2
    # Deliberate challenge sampling, not a representative occurrence-rate panel.
    paths.sort(key=lambda p: (historical_risk_first(p), str(p)))
    for path in paths:
        if path.name.endswith(".started.json"):
            continue
        try:
            saved = _load(path)
            request, response = saved["request"], saved["response"]
            from scripts.run_sentence_interpretation_models import RUN_SCHEMA
            if request.get("schemaVersion") != RUN_SCHEMA:
                raise ValueError("original_request_schema_mismatch")
            if saved.get("requestSha256") != _sha(request) or saved.get("responseSha256") != _sha(response):
                raise ValueError("original_request_or_response_hash_mismatch")
            original = request["payload"]
            if original.get("model") != "gpt-6.1-sol" or original.get("reasoning_effort") != "high":
                continue
            evidence = _user(original)
            if original["messages"][0]["content"] != english.SYSTEM_PROMPT:
                raise ValueError("source_judge_prompt_version_mismatch")
            anchor = path.parents[2] / "anchor.json"
            manifest = _load(anchor)
            if evidence.get("anchorManifestJsonSha256") != _sha(manifest):
                raise ValueError("missing_or_changed_anchor_manifest")
            # Verify the recorded batch really comes from this frozen source.
            inputs = {row["sourceSentenceId"]: row for row in english._sentence_inputs(manifest)}
            batch = evidence.get("sentences")
            if not isinstance(batch, list) or not batch:
                raise ValueError("missing_original_sentence_inputs")
            for row in batch:
                if inputs.get(row.get("sourceSentenceId")) != row:
                    raise ValueError("source_sentence_identity_mismatch")
            historical_result = json.loads(translation.completed_response_content(response, original["model"], "source_judge"))
            historical_rows = english._checked_batch(historical_result, batch)
            historic_by_id = {row["sourceSentenceId"]: row for row in historical_rows}
            selected_batch = sorted(batch, key=lambda row: historic_by_id[row["sourceSentenceId"]]["risk"] != "high")
            for sentence in selected_batch:
                if sentence["sourceSentenceId"] in seen:
                    continue
                payload = english._payload([sentence], manifest_hash=evidence["anchorManifestJsonSha256"],
                    anchor_policy=evidence["anchorPolicy"], model=original["model"],
                    effort=original["reasoning_effort"])
                # Preserve bounded transport settings from the frozen request.
                for key in ("service_tier", "max_completion_tokens"):
                    if key in original:
                        payload[key] = original[key]
                shared = _user(payload)
                questions = [_question(name, english.SYSTEM_PROMPT + "\nAssess only the " + name
                    + " check for the supplied frozen sentence; choose needs_more_evidence when not assessable.",
                    ("pass", "fail", "needs_more_evidence")) for name in english.CHECKS]
                questions += [_question("risk", english.SYSTEM_PROMPT + "\nChoose boundary risk for this sentence.",
                               ("low", "medium", "high", "needs_more_evidence")),
                              _question("verdict", english.SYSTEM_PROMPT + "\nGive the overall sentence verdict.",
                               ("pass", "fail", "needs_more_evidence"))]
                case = _base("E01", shared, payload, path, root,
                    "source-" + evidence["anchorManifestJsonSha256"], "english_source_judge_v1", questions,
                    source_kind="frozen_real_source_request", provenance={
                        "originalRequestSha256": saved["requestSha256"],
                        "anchorManifestJsonSha256": _sha(manifest),
                        "selectionStratum": "historical_machine_high_risk" if historic_by_id[sentence["sourceSentenceId"]]["risk"] == "high" else "historical_source_sentence",
                        "samplingRepresentative": False,
                        "originalResponseBackend": "codex-cli" if response.get("codexReceipt") else "openai-api",
                        "historicalAnswerIsGold": False})
                cases.append(case)
                seen.add(sentence["sourceSentenceId"])
                if len(cases) >= maximum:
                    return cases
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _missing("E01", "missing_or_unverifiable_original_source_request", path, root)
    if len(cases) < maximum:
        _missing("E01", "insufficient_verified_content_cases")
    return cases


def _translation_cases(root: Path, maximum: int) -> list[dict]:
    cases, seen = [], set()
    preferred = root / "artifacts/next-concurrency-605s-20261005-r13-gemini"
    paths = sorted(preferred.rglob("group-*-sol.policy-preview.json")) if preferred.is_dir() else []
    if not paths:
        paths = sorted((root / "artifacts").rglob("group-*-sol.policy-preview.json"))
    # The first three verified cases should cover distinct locales when present.
    locale_paths: dict[str, list[Path]] = {}
    for path in paths:
        stem = path.name.removesuffix(".policy-preview.json")
        if not path.with_name(stem + ".json").is_file() or not path.with_name(stem + ".raw.json").is_file():
            _missing("E02", "incomplete_original_review_artifacts", path, root)
            continue
        locale = next((part for part in path.parts if part in {"zh-Hans", "ko", "es"}), "und")
        locale_paths.setdefault(locale, []).append(path)
    locale_order = {"zh-Hans": 0, "ko": 1, "es": 2}
    ordered_locales = sorted(locale_paths.items(), key=lambda item: (locale_order.get(item[0], 3), item[0]))
    paths = [bucket[index] for index in range(max((len(v) for v in locale_paths.values()), default=0))
             for _, bucket in ordered_locales if index < len(bucket)]
    for path in paths:
        try:
            preview = _load(path)
            payload, policy = preview["payload"], preview["policy"]
            if payload.get("model") != "gpt-6.1-sol" or payload.get("reasoning_effort") != "medium":
                continue
            if (preview.get("schemaVersion") != "sermon-target-language-consumed-policy-v1"
                    or preview.get("role") != "reviewer"
                    or preview.get("payloadSha256") != policy_tools.canonical_sha256(payload)
                    or preview.get("policySha256") != policy_tools.canonical_sha256(policy)):
                raise ValueError("original_preview_hash_mismatch")
            scope = policy.get("sourceScope", {})
            if not all(re.fullmatch(r"[a-f0-9]{64}", str(scope.get(k, ""))) for k in
                       ("englishSourcePackageJsonSha256", "anchorManifestSha256")):
                raise ValueError("missing_frozen_source_identity")
            reviewer = policy["reviewer"]
            if reviewer.get("model") != payload["model"] or reviewer.get("reasoningEffort") != payload["reasoning_effort"]:
                raise ValueError("frozen_reviewer_policy_mismatch")
            evidence = _user(payload)
            instruction = payload["messages"][0]["content"]
            if "Correct any error in final targetUtterances and coverage." not in instruction \
                    or reviewer.get("promptVersion", "__missing__") not in instruction:
                raise ValueError("missing_actual_independent_review_prompt")
            units, draft = evidence["sourceUnitIds"], evidence["astraDraft"]
            if any(key in draft for key in ("semanticReview", "gold", "expected", "adjudication")):
                raise ValueError("draft_contains_downstream_answer")
            if not units or [u.get("sourceUnitId") for u in evidence["englishUnits"]] != units \
                    or draft.get("sourceUnitIds") != units or draft.get("translationGroupId") != evidence.get("translationGroupId"):
                raise ValueError("draft_source_identity_mismatch")
            translation._utterances(draft.get("targetUtterances"), units)
            # A real completed original request is required, not a mock preview.
            stem = path.name.removesuffix(".policy-preview.json")
            saved, raw = _load(path.with_name(stem + ".json")), _load(path.with_name(stem + ".raw.json"))
            if saved.get("payloadSha256") != raw.get("payloadSha256") or saved.get("model") != payload["model"]:
                raise ValueError("original_completed_request_identity_mismatch")
            response = raw["response"]
            if saved.get("requestId") != response.get("id"):
                raise ValueError("original_response_id_mismatch")
            if str(response.get("schemaVersion", "")).startswith("codex-cli-layer2-response-"):
                from scripts.codex_layer2_transport import CodexLayer2Transport
                content = CodexLayer2Transport.completed_content(response, payload["model"], "reviewer")
                original_backend = "codex-cli"
            else:
                content = translation.completed_response_content(response, payload["model"], "reviewer")
                original_backend = "openai-api"
            parsed = json.loads(content)
            if parsed != saved.get("result"):
                raise ValueError("original_raw_result_mismatch")
            # Verify the normalizer against the actual returned result too.
            key = _sha(evidence)
            if key in seen:
                continue
            question = _question("draft_disposition", "Use the supplied frozen source, policy and draft. "
                "Determine whether the draft requires a material correction, is acceptable unchanged, "
                "or needs human/engineering evidence. This is a judgment about the original draft, "
                "not any subsequently corrected reviewer text. The original reviewer instructions "
                "below supply audit criteria only: return solely the requested choice, not a revised text "
                "or the JSON output described by those instructions. Original reviewer instructions:\n" + instruction,
                ("no_material_change", "repair_required", "human_or_engineering_required"))
            case = _base("E02", evidence, payload, path, root,
                "source-" + scope["englishSourcePackageJsonSha256"], "translation_independent_review_v1", [question],
                source_kind="frozen_diagnostic_request" if policy.get("simulationModelConfiguration") else "frozen_production_request",
                provenance={"policy": copy.deepcopy(policy), "policySha256": preview["policySha256"],
                    "sourceIdentity": copy.deepcopy(scope), "originalPayloadSha256": preview["payloadSha256"],
                    "originalTransportPayloadSha256": saved["payloadSha256"],
                    "originalRawFileSha256": _file_sha(path.with_name(stem + ".raw.json")),
                    "originalResultFileSha256": _file_sha(path.with_name(stem + ".json")),
                    "originalResponseBackend": original_backend,
                    "historicalAnswerIsGold": False})
            _normalize_parsed(case, parsed)
            cases.append(case)
            seen.add(key)
            if len(cases) >= maximum:
                return cases
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            _missing("E02", "missing_or_unverifiable_original_review_request", path, root)
    if len(cases) < maximum:
        _missing("E02", "insufficient_verified_content_cases")
    return cases


def build_content_cases(source_root: Path, max_cases: int = 3) -> list[dict]:
    """Export up to max_cases per stage; missing stages are reported, never invented."""
    if type(max_cases) is not int or max_cases < 1:
        raise ValueError("max_cases_must_be_positive_integer")
    LAST_MISSING.clear()
    root = Path(source_root).resolve()
    return _english_cases(root, max_cases) + _translation_cases(root, max_cases)


def normalize_content_a(case: dict, response: dict) -> dict:
    """Decode an actual terminal Chat Completions response and validate identities."""
    payload = case["a"]["payload"]
    parsed = json.loads(translation.completed_response_content(response, payload["model"], "content_baseline"))
    return _normalize_parsed(case, parsed)


def _normalize_parsed(case: dict, parsed: dict) -> dict:
    payload = case["a"]["payload"]
    if not isinstance(parsed, dict):
        raise ValueError("baseline_response_not_object")
    evidence = case["sharedEvidence"]
    if evidence != _user(payload) or _sha(evidence) != case["evidenceSha256"] \
            or json.loads(case["b"]["input"]) != evidence:
        raise ValueError("shared_evidence_changed")
    if case["a"]["adapter"] == "english_source_judge_v1":
        rows = english._checked_batch(parsed, evidence["sentences"])
        if len(rows) != 1:
            raise ValueError("one_sentence_case_required")
        row = rows[0]
        return {"labels": {**row["checks"], "risk": row["risk"], "verdict": row["verdict"]},
                "unresolvedIssues": row["unresolvedIssues"], "historicalAnswerIsGold": False}
    if case["a"]["adapter"] != "translation_independent_review_v1":
        raise ValueError("unknown_content_adapter")
    ids = evidence["sourceUnitIds"]
    if parsed.get("translationGroupId") != evidence["translationGroupId"] or parsed.get("sourceUnitIds") != ids:
        raise ValueError("reviewer_changed_source_identity")
    utterances = translation._utterances(parsed.get("targetUtterances"), ids)
    final = "".join(utterances)
    coverage = parsed.get("coverage")
    if not isinstance(coverage, list) or [u.get("sourceUnitId") for u in coverage] != ids \
            or not all(isinstance(u.get("targetText"), str) and translation._coverage_substring(u["targetText"], final) for u in coverage):
        raise ValueError("reviewer_coverage_invalid")
    semantic = translation.normalize_semantic_review(parsed.get("semanticReview"))
    if not isinstance(semantic, dict) or semantic.get("status") not in {"pass", "fail"} \
            or set(semantic.get("checks", {})) != set(translation.SEMANTIC_CHECKS) \
            or any(v not in {"pass", "fail"} for v in semantic["checks"].values()) \
            or not isinstance(semantic.get("evidence"), str) or not semantic["evidence"].strip() \
            or not isinstance(semantic.get("issues"), list) or not isinstance(semantic.get("uncertainty"), list):
        raise ValueError("reviewer_semantic_ledger_invalid")
    draft = "".join(translation._utterances(evidence["astraDraft"]["targetUtterances"], ids))
    changed = " ".join(draft.split()) != " ".join(final.split())
    unresolved = semantic["status"] != "pass" or any(v != "pass" for v in semantic["checks"].values()) \
        or bool(semantic["issues"] or semantic["uncertainty"])
    disposition = "human_or_engineering_required" if unresolved else "repair_required" if changed else "no_material_change"
    return {"labels": {"draft_disposition": disposition}, "finalChecks": semantic["checks"],
            "finalTextSha256": hashlib.sha256(final.encode()).hexdigest(),
            "draftTextSha256": hashlib.sha256(draft.encode()).hexdigest(),
            "projectionNeedsGoldReview": changed, "historicalAnswerIsGold": False,
            "contractEquivalent": False, "normalizationVersion": "whitespace-only-v1"}
