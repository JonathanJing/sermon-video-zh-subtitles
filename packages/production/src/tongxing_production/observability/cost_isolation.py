"""Offline routing checks and daily cost reconciliation; never dispatches requests.

Inputs are local, normalized evidence, not native provider API responses. This
module never loads credentials, environment variables, or provider clients.
Errors contain bounded reason codes; output contains only validated fields.
"""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import re
import sys

VERSION = "sermon-cost-isolation-v1"  # Legacy strict per-workload credentials.
SHARED_VERSION = "sermon-cost-isolation-v2"
SUPPORTED_VERSIONS = (VERSION, SHARED_VERSION)
ENVIRONMENTS = ("dev", "prod")
WORKLOADS = ("transcription", "translation", "reviewer")
TOKEN_FIELDS = ("inputTokens", "outputTokens", "cachedInputTokens", "cacheWriteTokens", "reasoningTokens")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class IsolationError(ValueError):
    """Safe error with no input values or underlying exception text."""


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error echoes rejected argument values, which may
        # themselves be credentials. All subparsers inherit this class.
        raise IsolationError("invalid_cli_arguments")


def _fail(code):
    raise IsolationError(code)


def _object(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        _fail("invalid_fields")


def _label(value, nullable=False):
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not LABEL.fullmatch(value) or "sk-" in value.lower():
        _fail("invalid_identifier")
    return value


def _choice(value, choices, code):
    if not isinstance(value, str) or value not in choices:
        _fail(code)
    return value


def _amount(value, nullable=False):
    if value is None and nullable:
        return None
    # JSON is read using Decimal. Reject binary float inputs to the library.
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        _fail("invalid_decimal_amount")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        _fail("invalid_decimal_amount")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        _fail("invalid_decimal_amount")
    if not result.is_finite() or result < 0 or len(result.as_tuple().digits) > 30 or abs(result.as_tuple().exponent) > 18:
        _fail("invalid_decimal_amount")
    return result


def _decimal_text(value):
    return None if value is None else format(value, "f")


def _sum(values):
    values = list(values)
    # Enough precision for every accepted decimal and any carry from the count;
    # do not inherit a caller's possibly smaller Decimal context.
    with localcontext() as context:
        context.prec = 80 + len(str(len(values)))
        return sum(values, Decimal(0))


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail("invalid_daily_interval")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        _fail("invalid_daily_interval")


def _window(value):
    _object(value, ("startDay", "endDayExclusive"))
    start, end = _day(value["startDay"]), _day(value["endDayExclusive"])
    if start >= end:
        _fail("invalid_query_window")
    return start, end


def _in_window(day, window):
    value = _day(day)
    if not window[0] <= value < window[1]:
        _fail("outside_query_window")


def validate_config(config):
    """Validate isolated environments; v2 permits shared workload aliases within one."""
    _object(config, ("schemaVersion", "kind", "environments"))
    if config["schemaVersion"] not in SUPPORTED_VERSIONS or config["kind"] != "config":
        _fail("unsupported_schema")
    _object(config["environments"], ENVIRONMENTS)
    projects, aliases = set(), {}
    for environment in ENVIRONMENTS:
        item = config["environments"][environment]
        _object(item, ("projectId", "keyAliases"))
        project = _label(item["projectId"])
        if project in projects:
            _fail("cross_environment_project")
        projects.add(project)
        _object(item["keyAliases"], WORKLOADS)
        for workload in WORKLOADS:
            alias = _label(item["keyAliases"][workload], nullable=workload == "transcription")
            if alias is None:
                continue
            if alias in aliases and (config["schemaVersion"] == VERSION or aliases[alias] != environment):
                _fail("reused_key_alias")
            aliases[alias] = environment
    return {"schemaVersion": config["schemaVersion"], "kind": "config_validation", "valid": True,
            "environments": list(ENVIRONMENTS), "workloads": list(WORKLOADS),
            "credentialValuesRead": False, "providerDispatch": False}


def resolve_route(config, environment, workload, provider="openai"):
    validate_config(config)
    _choice(environment, ENVIRONMENTS, "unknown_environment")
    _choice(workload, WORKLOADS, "unknown_workload")
    _choice(provider, ("openai", "local", "non_openai"), "unknown_provider")
    if provider != "openai":
        if workload != "transcription":
            _fail("unsupported_local_workload")
        return {"environment": environment, "workload": workload, "provider": provider,
                "projectId": None, "keyAlias": None}
    item = config["environments"][environment]
    alias = item["keyAliases"][workload]
    if alias is None:
        _fail("missing_openai_key_alias")
    return {"environment": environment, "workload": workload, "provider": provider,
            "projectId": item["projectId"], "keyAlias": alias}


def _attempt(config, value):
    identity_fields = ("pricingVersion", "model", "jobId", "stage", "providerRequestId")
    _object(value, ("attemptId", "day", "environment", "workload", "provider", "status", "projectId", "apiKeyId", "keyAlias", "usage", "cost"), identity_fields)
    attempt_id = _label(value["attemptId"])
    _day(value["day"])
    identities = {name: _label(value.get(name), nullable=True) for name in identity_fields}
    # Local ASR does not need an OpenAI transcription alias. OpenAI attempts
    # must have a configured route, even when observed attribution is unknown.
    route = resolve_route(config, value["environment"], value["workload"], value["provider"])
    project = _label(value["projectId"], nullable=True)
    key_id = _label(value["apiKeyId"], nullable=True)
    alias = _label(value["keyAlias"], nullable=True)
    if project is not None and project != route["projectId"]:
        _fail("attempt_project_mismatch")
    if alias is not None and alias != route["keyAlias"]:
        _fail("attempt_alias_mismatch")
    if value["provider"] != "openai" and (project is not None or key_id is not None or alias is not None):
        _fail("local_asr_openai_attribution")
    status = _choice(value["status"], ("completed", "failed", "unknown_outcome", "not_dispatched"), "unknown_attempt_status")
    _object(value["usage"], (), TOKEN_FIELDS)
    usage = {field: value["usage"].get(field) for field in TOKEN_FIELDS}
    for token in usage.values():
        if token is not None and (type(token) is not int or token < 0):
            _fail("invalid_token_count")
    total, cached = (usage[name] for name in ("inputTokens", "cachedInputTokens"))
    if total is not None and cached is not None and cached > total:
        _fail("cached_tokens_exceed_input")
    _object(value["cost"], ("status", "estimatedUsd", "currency"))
    cost_status = _choice(value["cost"]["status"], ("estimated", "unknown", "not_incurred"), "unknown_cost_status")
    if value["cost"]["currency"] != "USD":
        _fail("unsupported_currency")
    estimated = _amount(value["cost"]["estimatedUsd"], nullable=True)
    if cost_status == "estimated" and identities["pricingVersion"] is None:
        _fail("missing_pricing_version")
    if ((cost_status == "unknown") != (estimated is None)
            or (cost_status == "not_incurred" and (estimated != 0 or status != "not_dispatched"))
            or (status == "not_dispatched" and cost_status != "not_incurred")):
        _fail("inconsistent_cost_evidence")
    return {"attemptId": attempt_id, "day": value["day"], **identities, **{k: value[k] for k in ("environment", "workload", "provider")},
            "status": status, "projectId": project, "apiKeyId": key_id, "keyAlias": alias,
            "attributionStatus": "observed_project" if project is not None else "unattributed",
            "usage": usage, "nonCachedInputTokens": total - cached if total is not None and cached is not None else None,
            "cost": {"status": cost_status, "estimatedUsd": _decimal_text(estimated), "currency": "USD"}}


def _daily(config, evidence):
    _object(evidence, ("schemaVersion", "kind", "scope", "queryWindow", "paginationComplete", "settlementStatus", "pages"))
    if evidence["schemaVersion"] not in SUPPORTED_VERSIONS or evidence["kind"] != "daily_costs":
        _fail("unsupported_schema")
    if type(evidence["paginationComplete"]) is not bool or not isinstance(evidence["pages"], list):
        _fail("invalid_pagination")
    _choice(evidence["settlementStatus"], ("pending", "settled"), "invalid_settlement_status")
    _choice(evidence["scope"], ("project_api_key_partitions",), "unsupported_cost_scope")
    window = _window(evidence["queryWindow"])
    projects = {config["environments"][env]["projectId"]: env for env in ENVIRONMENTS}
    page_ids, bucket_ids, dimensions, key_partitions, rows = set(), set(), set(), set(), []
    for index, page in enumerate(evidence["pages"]):
        _object(page, ("pageId", "nextPageId", "buckets"))
        page_id = _label(page["pageId"])
        next_id = _label(page["nextPageId"], nullable=True)
        if page_id in page_ids:
            _fail("duplicate_page")
        page_ids.add(page_id)
        if index and evidence["pages"][index - 1]["nextPageId"] != page_id:
            _fail("broken_page_chain")
        if not isinstance(page["buckets"], list):
            _fail("invalid_buckets")
        for bucket in page["buckets"]:
            _object(bucket, ("bucketId", "day", "projectId", "apiKeyId", "amountUsd", "currency"))
            bucket_id = _label(bucket["bucketId"])
            day = bucket["day"]
            _in_window(day, window)
            project = _label(bucket["projectId"], nullable=True)
            key_id = _label(bucket["apiKeyId"], nullable=True)
            if project is not None and project not in projects:
                _fail("unknown_cost_project")
            dimension = (day, project, key_id)
            if bucket_id in bucket_ids or dimension in dimensions:
                _fail("duplicate_cost_bucket")
            if key_id is not None:
                key_partition = (day, key_id)
                if key_partition in key_partitions:
                    _fail("duplicate_api_key_partition")
                key_partitions.add(key_partition)
            bucket_ids.add(bucket_id)
            dimensions.add(dimension)
            if bucket["currency"] != "USD":
                _fail("unsupported_currency")
            amount = _amount(bucket["amountUsd"])
            rows.append({"bucketId": bucket_id, "day": day, "projectId": project, "apiKeyId": key_id,
                         "environment": projects.get(project), "attributionStatus": "unattributed" if project is None else "observed_project",
                         "amountUsd": _decimal_text(amount), "currency": "USD"})
        if index == len(evidence["pages"]) - 1 and (evidence["paginationComplete"] != (next_id is None)):
            _fail("inconsistent_pagination_completion")
    if not evidence["pages"] and not evidence["paginationComplete"]:
        _fail("invalid_pagination")
    # Parent all-project buckets and child key buckets overlap. They cannot be
    # safely added without an explicit distinct source partition.
    for day, project, key in dimensions:
        if key is not None and (day, project, None) in dimensions:
            _fail("overlapping_cost_buckets")
    return rows


def reconcile(config, attempt_evidence, daily_evidence):
    validate_config(config)
    _object(attempt_evidence, ("schemaVersion", "kind", "scope", "queryWindow", "attempts"))
    if attempt_evidence["schemaVersion"] not in SUPPORTED_VERSIONS or attempt_evidence["kind"] != "attempts":
        _fail("unsupported_schema")
    if not isinstance(attempt_evidence["attempts"], list):
        _fail("invalid_attempts")
    _choice(attempt_evidence["scope"], ("complete_openai_project_attempts", "partial_attempts"), "unsupported_attempt_scope")
    window = _window(attempt_evidence["queryWindow"])
    if not isinstance(daily_evidence, dict):
        _fail("invalid_fields")
    if _window(daily_evidence.get("queryWindow")) != window:
        _fail("query_window_mismatch")
    attempts = [_attempt(config, value) for value in attempt_evidence["attempts"]]
    for attempt in attempts:
        _in_window(attempt["day"], window)
    ids = [value["attemptId"] for value in attempts]
    if len(ids) != len(set(ids)):
        _fail("duplicate_attempt")
    request_ids = set()
    for attempt in attempts:
        request_id = attempt["providerRequestId"]
        if attempt["provider"] == "openai" and request_id is not None:
            if request_id in request_ids:
                _fail("duplicate_provider_request")
            request_ids.add(request_id)
    # Observed key IDs bind to an environment and credential route. v2 permits
    # roles sharing the same configured alias, even when observed alias is null.
    bindings = {}
    for attempt in attempts:
        key = attempt["apiKeyId"]
        if key is None:
            continue
        credential_route = (config["environments"][attempt["environment"]]["keyAliases"][attempt["workload"]]
                            if config["schemaVersion"] == SHARED_VERSION else attempt["workload"])
        binding = (attempt["environment"], credential_route)
        if key in bindings and bindings[key] != binding:
            _fail("reused_api_key_id")
        bindings[key] = binding
    buckets = _daily(config, daily_evidence)
    actual_key_environments = {}
    for bucket in buckets:
        key = bucket["apiKeyId"]
        env = bucket["environment"]
        if key is not None and env is not None:
            if key in actual_key_environments and actual_key_environments[key] != env:
                _fail("cost_api_key_environment_mismatch")
            actual_key_environments[key] = env
        if key is not None and key in bindings and bucket["environment"] is not None and bindings[key][0] != bucket["environment"]:
            _fail("cost_api_key_environment_mismatch")
    summaries = {}
    for env in ENVIRONMENTS:
        selected = [a for a in attempts if a["environment"] == env]
        known = [Decimal(a["cost"]["estimatedUsd"]) for a in selected if a["provider"] == "openai" and a["cost"]["estimatedUsd"] is not None]
        actual = [Decimal(b["amountUsd"]) for b in buckets if b["environment"] == env]
        summaries[env] = {"attemptCount": len(selected), "unknownCostAttempts": sum(a["cost"]["estimatedUsd"] is None for a in selected),
                          "unknownOutcomeAttempts": sum(a["status"] == "unknown_outcome" for a in selected),
                          "unattributedAttempts": sum(a["projectId"] is None for a in selected),
                          "knownEstimatedUsd": _decimal_text(_sum(known)),
                          "observedDailyActualUsd": _decimal_text(_sum(actual)) if actual else None, "actualBucketCount": len(actual)}
    comparisons = []
    days = sorted({a["day"] for a in attempts} | {b["day"] for b in buckets})
    for day in days:
        for env in ENVIRONMENTS:
            selected = [a for a in attempts if a["day"] == day and a["environment"] == env]
            actual_rows = [b for b in buckets if b["day"] == day and b["environment"] == env]
            if not selected and not actual_rows:
                continue
            known = [Decimal(a["cost"]["estimatedUsd"]) for a in selected if a["provider"] == "openai" and a["cost"]["estimatedUsd"] is not None]
            estimate = _sum(known) if known else None
            actual = _sum(Decimal(b["amountUsd"]) for b in actual_rows) if actual_rows else None
            unknown_costs = sum(a["cost"]["estimatedUsd"] is None for a in selected)
            unknown_outcomes = sum(a["status"] == "unknown_outcome" for a in selected)
            unattributed = sum(a["projectId"] is None for a in selected)
            unattributed_actual = sum(b["day"] == day and b["projectId"] is None for b in buckets)
            # A declared complete project attempt scope cannot be compared to
            # a different key subset. A project aggregate (null key) covers
            # the whole project; key partitions need identical known key sets.
            actual_keys = {b["apiKeyId"] for b in actual_rows}
            attempt_keys = {a["apiKeyId"] for a in selected if a["provider"] == "openai"}
            key_coverage_matches = (None in actual_keys or (None not in attempt_keys and attempt_keys == actual_keys))
            complete = (daily_evidence["paginationComplete"] and daily_evidence["settlementStatus"] == "settled"
                        and attempt_evidence["scope"] == "complete_openai_project_attempts"
                        and bool(selected) and bool(actual_rows) and not (unknown_costs or unknown_outcomes or unattributed or unattributed_actual)
                        and all(a["provider"] == "openai" for a in selected) and key_coverage_matches)
            comparisons.append({"day": day, "environment": env, "attemptCount": len(selected),
                                "actualBucketCount": len(actual_rows), "knownEstimatedUsd": _decimal_text(estimate),
                                "observedActualUsd": _decimal_text(actual),
                                "estimateActualDifferenceUsd": _decimal_text(_sum((estimate, actual.copy_negate()))) if estimate is not None and actual is not None else None,
                                "differenceDefinition": "known_estimate_minus_observed_daily_actual",
                                "unknownCostAttempts": unknown_costs, "unknownOutcomeAttempts": unknown_outcomes,
                                "nonOpenaiAttempts": sum(a["provider"] != "openai" for a in selected),
                                "unattributedAttempts": unattributed, "unattributedActualBucketCount": unattributed_actual,
                                "keyCoverageMatches": key_coverage_matches,
                                "comparisonCompleteness": "complete" if complete else "partial"})
    return {"schemaVersion": config["schemaVersion"], "kind": "reconciliation", "providerDispatch": False,
            "credentialValuesRead": False, "attempts": attempts, "dailyActualBuckets": buckets,
            "queryWindow": dict(attempt_evidence["queryWindow"]), "attemptScope": attempt_evidence["scope"],
            "costScope": daily_evidence["scope"], "estimateScope": "openai_attempts", "dailyComparisons": comparisons,
            "environments": summaries,
            "unattributedActualUsd": _decimal_text(_sum(Decimal(b["amountUsd"]) for b in buckets if b["projectId"] is None)),
            "actualCoverage": "complete" if buckets and daily_evidence["paginationComplete"] and daily_evidence["settlementStatus"] == "settled" else "partial",
            "paginationComplete": daily_evidence["paginationComplete"], "settlementStatus": daily_evidence["settlementStatus"],
            "actualGranularity": "daily_project_api_key", "requestActualCostsAvailable": False,
            "invoiceVerified": False}


def _read(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                _fail("duplicate_json_field")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"), parse_float=Decimal,
                          parse_constant=lambda _: _fail("invalid_json_number"), object_pairs_hook=unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _fail("input_unreadable")


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-config", help="Check local routing configuration; print safe summary.")
    validate.add_argument("--config", required=True)
    reconciliation = sub.add_parser("reconcile", help="Read normalized offline attempts and daily Costs; print allowlisted summary.")
    for name in ("config", "attempts", "daily-costs"):
        reconciliation.add_argument("--" + name, required=True)
    try:
        args = parser.parse_args(argv)
        config = _read(args.config)
        if args.command == "validate-config":
            result = validate_config(config)
        else:
            result = reconcile(config, _read(args.attempts), _read(args.daily_costs))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except IsolationError as error:
        print(json.dumps({"valid": False, "reasonCode": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
