"""Read-only QC approval validation and artifact-bound scope for planned runs.

Legacy v1 approvals retain their original contract. New v4 approvals bind one
locale, environment and frozen source/anchor/policy; drivers must supply that
same context before constructing any paid transport.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

AUTH_V1 = "sermon-machine-qc-api-budget-authorization-v1"
AUTH_V2 = "sermon-machine-qc-api-budget-authorization-v2"
AUTH_V3 = "sermon-machine-qc-api-budget-authorization-v3"
AUTH_V4 = "sermon-machine-qc-api-budget-authorization-v4"
APPROVAL_V1 = "sermon-machine-qc-api-budget-approval-v1"
APPROVAL_V2 = "sermon-machine-qc-api-budget-approval-v2"
APPROVAL_V3 = "sermon-machine-qc-api-budget-approval-v3"
APPROVAL_V4 = "sermon-machine-qc-api-budget-approval-v4"
CONTEXT_SCHEMA = "sermon-machine-qc-budget-context-v3"


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def credential_fingerprint(api_key):
    if not isinstance(api_key,str) or not api_key:
        raise ValueError('qc_budget_runtime_credential_missing')
    return hashlib.sha256(api_key.encode()).hexdigest()


def context_from_paths(paths, locale, environment, *, route, credential_sha256):
    if locale not in {"zh-Hans", "ko", "es"} or environment not in {"dev", "prod"}:
        raise ValueError("invalid_qc_budget_context")
    from scripts.sermon_openai_runtime import safe_route
    if not isinstance(route,dict) or safe_route(route) != route or route['environment'] != environment:
        raise ValueError('invalid_qc_budget_runtime_route')
    if not isinstance(credential_sha256,str) or len(credential_sha256)!=64 or any(c not in '0123456789abcdef' for c in credential_sha256):
        raise ValueError('invalid_qc_budget_credential_fingerprint')
    source, anchor, policy = (read(paths[name]) for name in ("source", "anchor", "policy"))
    from scripts import produce_target_language_candidate as producer, target_language_policy as policies
    producer.validate_source_for_translation(source, anchor)
    policies.validate_policy(policy)
    policies.validate_source_scope(policy, source, anchor)
    from scripts import machine_quality_waiver as waiver
    source_sha = canonical_sha(source)
    if policy.get("targetLocale") != locale:
        raise ValueError("qc_budget_policy_locale_changed")
    return {"schemaVersion": CONTEXT_SCHEMA, "runId": source_sha, "environment": environment,
            "targetLocale": locale, "openaiRoute": dict(route), "credentialSha256": credential_sha256, "englishSourcePackageJsonSha256": source_sha,
            "anchorManifestJsonSha256": canonical_sha(anchor),
            "targetLanguagePolicyJsonSha256": canonical_sha(policy),
            "qcImplementationSha256": waiver.implementation_sha256()}


def contexts_from_manifest(path, locales):
    path = Path(path).resolve()
    value = read(path)
    if (value.get("schemaVersion") != "sermon-machine-qc-inputs-v3"
            or set(value) != {"schemaVersion", "environment", "openaiRoute", "credentialSha256", "source", "anchor", "policies"}
            or not set(locales) <= set(value["policies"])):
        raise ValueError("invalid_qc_inputs_manifest")
    def local(name):
        return str((path.parent / name).resolve())
    return {locale: context_from_paths({"source": local(value["source"]), "anchor": local(value["anchor"]),
                                      "policy": local(value["policies"][locale])}, locale, value["environment"], route=value["openaiRoute"], credential_sha256=value["credentialSha256"])
            for locale in locales}


def validate(path, *, context=None, require_scope=False):
    from scripts.sermon_provider_limits import validate_request_limits
    path = Path(path).resolve()
    value = read(path)
    scoped = value.get("schemaVersion") == AUTH_V4
    if value.get("schemaVersion") not in {AUTH_V1, AUTH_V4} or require_scope and not scoped:
        raise ValueError("invalid_qc_budget_authorization_version")
    keys = {"schemaVersion", "budgetRoot", "authority", "approvalReceipt"}
    if scoped:
        keys.add("qcContext")
    if "reuseBudgetRoots" in value:
        if not scoped:
            raise ValueError("legacy_v1_cannot_use_reuse_roots")
        keys.add("reuseBudgetRoots")
    if set(value) != keys:
        raise ValueError("invalid_qc_budget_authorization_fields")
    receipt = path.parent / value["approvalReceipt"]
    approval = read(receipt)
    authority = value["authority"]
    bounds = authority["bounds"]
    limits = validate_request_limits(authority["requestLimits"])
    if (set(bounds) != {"globalBounds", "requestLimits"} or bounds["requestLimits"] != limits
            or set(bounds["globalBounds"]) != {"requests", "wallTimeMs", "costMicrousd"}
            or any(type(n) is not int or not 0 < n <= 10**15 for n in bounds["globalBounds"].values())
            or not Path(value["budgetRoot"]).is_absolute()):
        raise ValueError("invalid_qc_budget_bounds")
    binding = {"budgetRoot": value["budgetRoot"], **bounds}
    if "reuseBudgetRoots" in value:
        roots = value["reuseBudgetRoots"]
        if (not isinstance(roots, list) or len(set(roots)) != len(roots)
                or any(not isinstance(root, str) or not Path(root).is_absolute() for root in roots)
                or str(Path(value["budgetRoot"]).resolve()) in {str(Path(root).resolve()) for root in roots}):
            raise ValueError("invalid_qc_reuse_roots")
        if roots:
            binding["reuseBudgetRoots"] = roots
    if scoped:
        observed = value["qcContext"]
        from scripts.sermon_openai_runtime import safe_route
        required = {"schemaVersion", "runId", "environment", "targetLocale", "openaiRoute", "credentialSha256", "englishSourcePackageJsonSha256",
                    "anchorManifestJsonSha256", "targetLanguagePolicyJsonSha256", "qcImplementationSha256"}
        if (not isinstance(observed, dict) or set(observed) != required
                or observed["schemaVersion"] != CONTEXT_SCHEMA
                or observed["environment"] not in {"dev", "prod"}
                or observed["targetLocale"] not in {"zh-Hans", "ko", "es"}
                or not isinstance(observed["openaiRoute"],dict)
                or safe_route(observed["openaiRoute"]) != observed["openaiRoute"]
                or observed["openaiRoute"]["environment"] != observed["environment"]
                or any(not isinstance(observed[k], str) or len(observed[k]) != 64
                       or any(c not in "0123456789abcdef" for c in observed[k])
                       for k in ("runId", "credentialSha256", "englishSourcePackageJsonSha256", "anchorManifestJsonSha256",
                                 "targetLanguagePolicyJsonSha256", "qcImplementationSha256"))
                or observed["runId"] != observed["englishSourcePackageJsonSha256"]):
            raise ValueError("invalid_qc_budget_context")
        binding["qcContext"] = observed
        if context is not None and observed != context:
            raise ValueError("qc_budget_context_changed")
    if (authority["approvalSha256"] != hashlib.sha256(receipt.read_bytes()).hexdigest()
            or scoped and approval.get("schemaVersion") != APPROVAL_V4
            or approval.get("binding") != binding or approval.get("humanApproval") is not True
            or approval.get("decision") != "approved"
            or scoped and (not approval.get("reviewedBy") or not approval.get("reviewedAt") or not approval.get("operatorEvidence"))):
        raise ValueError("qc_budget_approval_not_bound")
    return value
