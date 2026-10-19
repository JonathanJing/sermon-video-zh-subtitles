"""Per-group budget: what the selected groups may spend, never sized from the first round (DEV-GRP-003).

docs/design/per-group-independent-pipeline.zh.md section 6:

    limit(g)        = remaining tries(g) x per-try upper bound
    remaining(g)    = per-unit repair cap - attempts the repair ledger already holds for g
    per-try bound   = translator + reviewer (2 calls at the enforced request bound)
                    + back-translation + comparison (2 calls)
                    + condensation (shorten groups only, up to its attempt cap)
                    + secondary ASR (one flagged unit)

A group the operator names is budgeted for every try it has left; a group the plan
marks stale only for one pass of the paid steps that will run again. Steps the plan
marks fresh cost nothing ($0 reused). Groups are reserved in order against each paid
system's cap from the weekly run profile; a group that does not fit is marked
``repair_spend_cap`` and reserves nothing, and groups already reserved keep their
reservation. The result is read-only: an operator approval binds it by hash before
any dispatch, and the dispatcher admits a group with ``admit``.

Caps, request limits, prices and attempt caps come from their owners (the run
profile, ``compute.provider_limits``, ``compute.transcription_request``,
``review.text_qc``, ``review.condensation``); nothing is copied here.
"""
from __future__ import annotations

import math
from typing import Any

from . import group_records as records


SCHEMA = "sermon-group-budget-v1"
PROFILE_SCHEMA = "sermon-weekly-run-profile-v3"
SYSTEMS = ("layer2", "qc", "secondaryAsr")
PAID_TEXT_STAGES = ("T", "R", "Q", "C")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _microusd(usd: Any) -> int:
    _require(isinstance(usd, (int, float)) and not isinstance(usd, bool) and usd >= 0, "invalid_profile_cap")
    return int(round(usd * 1_000_000))


def per_try_bounds(profile: dict, policy: dict, qc_model: str) -> dict:
    """Worst-case requests and cost of each paid step, at the profile's enforced request limits."""
    from ..compute import provider_limits as limits
    from ..compute import transcription_request as transcription
    from ..review import condensation
    _require(profile.get("schemaVersion") == PROFILE_SCHEMA, "unsupported_run_profile")
    layer2 = limits.validate_request_limits(profile["layer2"]["requestLimits"])
    qc = limits.validate_request_limits(profile["qc"]["requestLimits"])
    pair = sum(limits._cost(policy[role]["model"], layer2["maxInputTokens"], layer2["maxCompletionTokens"])
               for role in ("translator", "reviewer"))
    qc_call = limits._cost(qc_model, qc["maxInputTokens"], qc["maxCompletionTokens"])
    asr = math.ceil(transcription.MAX_DURATION_SECONDS / 60) * transcription.MICROUSD_PER_MINUTE
    return {
        "translation": {"system": "layer2", "requests": 2, "costMicrousd": pair},
        "textQc": {"system": "qc", "requests": 2, "costMicrousd": 2 * qc_call},
        "condensation": {"system": "qc", "requests": condensation.MAX_ATTEMPTS,
                         "costMicrousd": condensation.MAX_ATTEMPTS * qc_call},
        "secondaryAsr": {"system": "secondaryAsr", "requests": 1, "costMicrousd": asr},
        "priceAssumptions": {model: limits.PRICE_ASSUMPTION_VERSION_BY_MODEL[model]
                             for model in sorted({policy["translator"]["model"], policy["reviewer"]["model"],
                                                  qc_model})},
    }


def caps(profile: dict, scale: str) -> dict:
    """Per-locale cap of each paid system, from the run profile."""
    _require(scale in profile["layer2"]["capUsdPerLocale"], f"unknown_profile_scale:{scale}")
    return {"layer2": _microusd(profile["layer2"]["capUsdPerLocale"][scale]),
            "qc": _microusd(profile["qc"]["capUsdPerLocale"][scale]),
            "secondaryAsr": _microusd(profile["qc"]["secondaryAsr"]["capUsdPerLocale"][scale])}


def _steps(statuses: dict, shorten: bool, *, every_step: bool) -> list[str]:
    """Paid steps one try runs: all of them for a named group, otherwise only the unsettled ones."""
    # The steps the plan would redo: unsettled ones, and byte-producing ones that failed or stopped.
    unsettled = {stage for stage, value in statuses.items()
                 if value in {"stale", "missing", "conflict"}
                 or (stage in records.PRODUCES and value in {"failed", "stopped"})}
    steps = []
    if every_step or unsettled & {"T", "R"}:
        steps.append("translation")
    if every_step or "Q" in unsettled:
        steps.append("textQc")
    if shorten and (every_step or "C" in unsettled):
        steps.append("condensation")
    # New audio may be flagged by the primary ASR; unchanged audio keeps its paid secondary result.
    if every_step or "S" in unsettled:
        steps.append("secondaryAsr")
    return steps


def group_rows(groups: list[dict], selected: dict[str, dict], directives: list[str], bounds: dict) -> list[dict]:
    """One row per group that will spend money, named groups first in the operator's order.

    ``groups`` are plan rows (``translationGroupId`` and per-stage ``status``); ``selected``
    maps group IDs to the plan's selected records (the Q record gives the repair ledger's
    attempts so far and whether the group is shortened).
    """
    from ..review import text_qc
    by_id = {row["translationGroupId"]: row for row in groups}
    _require(len(set(directives)) == len(directives) and set(directives) <= set(by_id), "invalid_budget_directives")
    order = list(directives) + [row["translationGroupId"] for row in groups if row["translationGroupId"] not in directives]
    rows = []
    for group_id in order:
        statuses = {stage: value["status"] for stage, value in by_id[group_id]["stages"].items()}
        quality = (selected.get(group_id) or {}).get("Q")
        provenance = quality["provenance"] if quality else {}
        shorten = provenance.get("mode") == "shorten" or "C" in (selected.get(group_id) or {})
        named = group_id in directives
        if named:
            used = int(provenance.get("failedAttempts") or 0)
            tries = max(0, text_qc.MAX_TEXT_REPAIR_ATTEMPTS - used)
            basis = "operator_directive"
        else:
            used, tries, basis = None, 1, "stale_steps"
        steps = _steps(statuses, shorten, every_step=named)
        if not named and not steps:
            continue  # every paid step reused: $0, no reservation
        per_try = {system: {"requests": 0, "costMicrousd": 0} for system in SYSTEMS}
        for step in steps:
            bound = bounds[step]
            per_try[bound["system"]]["requests"] += bound["requests"]
            per_try[bound["system"]]["costMicrousd"] += bound["costMicrousd"]
        rows.append({"translationGroupId": group_id, "basis": basis, "steps": steps,
                     "ledgerAttempts": used, "tries": tries, "perTry": per_try,
                     "reserve": {system: {key: value * tries for key, value in per_try[system].items()}
                                 for system in SYSTEMS},
                     "status": "repair_limit_reached" if named and tries == 0 else "pending"})
    return rows


def reserve(rows: list[dict], cap: dict) -> dict:
    """Reserve rows in order; a row that does not fit any system's remainder reserves nothing."""
    remaining = dict(cap)
    for row in rows:
        if row["status"] == "repair_limit_reached":
            continue
        need = {system: row["reserve"][system]["costMicrousd"] for system in SYSTEMS}
        if all(need[system] <= remaining[system] for system in SYSTEMS):
            for system in SYSTEMS:
                remaining[system] -= need[system]
            row["status"] = "reserved"
        else:
            row["status"] = "repair_spend_cap"
    reserved = [row for row in rows if row["status"] == "reserved"]
    return {"capMicrousd": dict(cap), "remainingMicrousd": remaining,
            "reservedMicrousd": {system: sum(row["reserve"][system]["costMicrousd"] for row in reserved)
                                 for system in SYSTEMS},
            "reservedRequests": {system: sum(row["reserve"][system]["requests"] for row in reserved)
                                 for system in SYSTEMS},
            "counts": {status: sum(row["status"] == status for row in rows)
                       for status in ("reserved", "repair_spend_cap", "repair_limit_reached")}}


def budget(layer1: dict, locale: str, groups: list[dict], selected: dict[str, dict], directives: list[str],
           policy: dict, profile: dict, scale: str, *, profile_sha256: str | None = None) -> dict:
    quality_models = sorted({chosen["Q"]["provenance"].get("model") for chosen in selected.values()
                             if chosen.get("Q") and chosen["Q"]["provenance"].get("model")})
    _require(len(quality_models) == 1, f"text_qc_model_not_unique:{locale}")
    bounds = per_try_bounds(profile, policy, quality_models[0])
    rows = group_rows(groups, selected, directives, bounds)
    totals = reserve(rows, caps(profile, scale))
    return {"schemaVersion": SCHEMA, "mode": "read_only", "dispatched": False, "layer1": layer1,
            "targetLocale": locale, "runProfile": {"schemaVersion": profile["schemaVersion"], "scale": scale,
                                                   "sha256": profile_sha256},
            "perTry": {key: bounds[key] for key in ("translation", "textQc", "condensation", "secondaryAsr")},
            "priceAssumptions": bounds["priceAssumptions"], "groups": rows, "totals": totals,
            "reusedGroupCount": len(groups) - len(rows),
            "approval": "required_before_dispatch", "humanApproval": False, "releaseEligible": False}


def admit(document: dict, translation_group_id: str) -> dict:
    """The reservation a dispatcher may spend for one group, or a refusal before any call."""
    _require(document.get("schemaVersion") == SCHEMA, "invalid_group_budget")
    row = next((row for row in document["groups"] if row["translationGroupId"] == translation_group_id), None)
    _require(row is not None, f"group_not_budgeted:{translation_group_id}")
    _require(row["status"] == "reserved", f"{row['status']}:{translation_group_id}")
    return row["reserve"]
