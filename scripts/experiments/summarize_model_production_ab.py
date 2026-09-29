#!/usr/bin/env python3
"""Validate ignored A/B artifacts and emit a sermon-text-free comparison summary."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics


# OpenAI Standard, short-context USD per million tokens, checked 2026-09-28.
# Tuple: uncached input, cached input, cache writes, output.
RATES = {"gpt-6-astra": (10.0, 1.0, 12.5, 50.0),
         "gpt-6-sol": (2.0, 0.2, 2.5, 10.0),
         "gpt-6-luna": (0.1, 0.01, 0.125, 0.5)}
LOCALES = ("zh-Hans", "ko", "es")
ARMS = ("A", "B", "C")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(percent * len(ordered)) - 1], 3)


def token_cost(model: str, input_tokens: int, cached: int,
               writes: int, output_tokens: int) -> float:
    require(model in RATES and 0 <= cached + writes <= input_tokens,
            "invalid model or token split")
    uncached_rate, cached_rate, write_rate, output_rate = RATES[model]
    return ((input_tokens - cached - writes) * uncached_rate
            + cached * cached_rate + writes * write_rate
            + output_tokens * output_rate) / 1_000_000


def supervisor_summary(root: Path) -> dict:
    report = load(root / "supervisor-live-report.json")
    rows = report["cases"]
    require(report.get("backend") == "live" and len(rows) == 24,
            "Supervisor comparison is incomplete")
    require(report.get("usageReconciledFromSessionReadback") is True
            and report.get("toolTraceReconciledFromDurableItems") is True,
            "Supervisor usage or tool trace has not been reconciled")
    output = {}
    for model in ("gpt-6-sol", "gpt-6-luna"):
        subset = [row for row in rows if row["model"] == model]
        require(len(subset) == 12 and all(isinstance(row.get("usage"), dict)
                                          for row in subset),
                "Supervisor usage is incomplete")
        require(all(len(row["toolTrace"]) == row["toolCalls"] == 2
                    and {item["name"] for item in row["toolTrace"]}
                    == {"inspect_production_state", "submit_supervisor_decision"}
                    for row in subset), "Supervisor tool trace is inconsistent")
        input_tokens = sum(row["usage"]["input_tokens"] for row in subset)
        cached = sum(row["usage"]["input_tokens_details"]["cached_tokens"]
                     for row in subset)
        output_tokens = sum(row["usage"]["output_tokens"] for row in subset)
        output[model] = {
            "cases": 12,
            "actionMatches": sum(row["modelDecision"]["action"]
                                 == row["deterministicExpected"]["action"] for row in subset),
            "humanActionMatches": sum(row["modelDecision"]["human_action_required"]
                                      == row["deterministicExpected"]["human_action_required"]
                                      for row in subset),
            "acceptedDecisions": sum(row["verifiedDecision"]["modelDecisionAccepted"]
                                     for row in subset),
            "falseCompletionClaims": sum(row["falseCompletionClaim"] for row in subset),
            "completedSessions": sum(row["sessionStatus"] == "completed" for row in subset),
            "elapsedP50Seconds": percentile([row["elapsedSeconds"] for row in subset], .5),
            "elapsedP95Seconds": percentile([row["elapsedSeconds"] for row in subset], .95),
            "inputTokens": input_tokens, "cachedInputTokens": cached,
            "outputTokens": output_tokens,
            "estimatedTokenUsd": round(token_cost(model, input_tokens, cached, 0,
                                                  output_tokens), 6),
            "httpRequestIdsAvailable": sum(bool(row.get("requestIds")) for row in subset),
        }
    pairs = {row["caseId"]: {} for row in rows}
    for row in rows:
        pairs[row["caseId"]][row["model"]] = row["elapsedSeconds"]
    differences = [value["gpt-6-luna"] - value["gpt-6-sol"]
                   for value in pairs.values()]
    return {"models": output,
            "pairedLunaMinusSolMedianSeconds": round(statistics.median(differences), 3),
            "pairedFasterCases": {"luna": sum(value < 0 for value in differences),
                                  "sol": sum(value > 0 for value in differences)}}


def layer2_summary(root: Path) -> dict:
    locales = {}
    totals = {arm: Counter() for arm in ARMS}
    all_group_seconds = {arm: [] for arm in ARMS}
    source_hashes = set()
    anchor_hashes = set()
    group_plans = set()
    for locale in LOCALES:
        directory = root / f"layer2-{locale}"
        comparison = load(directory / "comparison.json")
        identity = load(directory / "run-identity-v2.json") if (directory / "run-identity-v2.json").exists() else load(directory / "run-identity.json")
        sheet_path = directory / "blind-review.json"
        sheet_bytes = sheet_path.read_bytes()
        sheet = json.loads(sheet_bytes)
        scores = load(directory / "blind-review-scores.json")
        key = load(directory / "blinding-key.json")
        require(comparison["status"] == "shadow_only" and comparison["groups"] == 45,
                f"{locale}: run incomplete")
        require(comparison["sourceHash"] == identity["sourceHash"]
                and comparison["anchorHash"] == identity["anchorHash"]
                and comparison["basePolicyHash"] == identity["basePolicyHash"],
                f"{locale}: source identity mismatch")
        source_hashes.add(comparison["sourceHash"])
        anchor_hashes.add(comparison["anchorHash"])
        group_plans.add(json.dumps(identity["plan"], sort_keys=True))
        paired = comparison["pairedGroups"]
        require(sheet["pairedGroups"] == paired
                and sheet["targetLocale"] == scores["targetLocale"] == locale
                and len(sheet["groups"]) == paired
                and len(sheet["excludedGroups"]) == 45 - paired
                and len(key["codes"]) == len(scores["ratings"]) == 3 * paired
                and {row["code"] for row in key["codes"]}
                == {row["code"] for row in scores["ratings"]}
                and scores["sourceSheetSha256"] == hashlib.sha256(sheet_bytes).hexdigest(),
                f"{locale}: blind materials mismatch")
        by_arm = {}
        group_indices = {row["translationGroupId"]: i
                         for i, row in enumerate(identity["plan"], 1)}
        for arm in ARMS:
            arm_dir = directory / f"arm-{arm}"
            summary = comparison["arms"][arm]
            result = load(arm_dir / "results.json")
            rows = result["rows"]
            failures = result["failures"]
            plugin = load(arm_dir / "language-plugin.json")
            require(summary["attemptedGroups"] == 45
                    and summary["completedGroups"] == len(rows)
                    and summary["failedGroups"] == len(failures)
                    and len(rows) + len(failures) == 45
                    and summary["inProgressGroups"] == 0,
                    f"{locale}/{arm}: group totals mismatch")
            require(len(plugin["groupReviews"]) == len(rows)
                    and sum(group["status"] == "pass" for group in plugin["groupReviews"])
                    == summary["languagePlugin"]["passGroups"],
                    f"{locale}/{arm}: plugin totals mismatch")
            raw_paths = sorted(arm_dir.glob("group-*.raw.json"))
            require(len(raw_paths) == summary["metrics"]["recordedHttpAttempts"]
                    == summary["metrics"]["logicalResponses"]
                    and summary["metrics"]["usageComplete"],
                    f"{locale}/{arm}: API usage incomplete")
            token_counts = Counter()
            estimated = 0.0
            for path in raw_paths:
                response = load(path)["response"]
                usage = response["usage"]
                details = usage["prompt_tokens_details"]
                require(response.get("service_tier") == "default",
                        f"{locale}/{arm}: non-default service tier")
                inputs = usage["prompt_tokens"]
                cached = details.get("cached_tokens", 0)
                writes = details.get("cache_write_tokens", 0)
                outputs = usage["completion_tokens"]
                token_counts.update(inputTokens=inputs, cachedInputTokens=cached,
                                    cacheWriteTokens=writes, outputTokens=outputs)
                estimated += token_cost(response["model"], inputs, cached, writes, outputs)
            group_seconds = []
            for row in rows:
                index = group_indices[row["translationGroupId"]]
                prefix = f"group-{index:04d}"
                translator = load(arm_dir / f"{prefix}-translator.timing.json")
                reviewer = load(arm_dir / f"{prefix}-reviewer.timing.json")
                require(isinstance(translator.get("elapsedSeconds"), (int, float))
                        and isinstance(reviewer.get("elapsedSeconds"), (int, float)),
                        f"{locale}/{arm}: complete group timing unavailable")
                group_seconds.append(translator["elapsedSeconds"] + reviewer["elapsedSeconds"])
            require(len(group_seconds) == len(rows),
                    f"{locale}/{arm}: complete group timing mismatch")
            all_group_seconds[arm].extend(group_seconds)
            counts = Counter(row["stage"] for row in failures)
            changed = sum(row["draftUtterances"] != row["targetUtterances"] for row in rows)
            by_arm[arm] = {
                "translator": summary["translator"], "reviewer": summary["reviewer"],
                "attemptedGroups": 45, "completedGroups": len(rows),
                "failedGroups": len(failures), "failureStages": dict(counts),
                "semanticReviewPassGroups": summary["semanticReviewPassGroups"],
                "languagePluginPassGroups": summary["languagePlugin"]["passGroups"],
                "combinedMachinePassGroups": summary["combinedMachinePassGroups"],
                "reviewerChangedGroups": changed, "apiResponses": len(raw_paths),
                **dict(token_counts),
                "completeGroupElapsedP50Seconds": round(statistics.median(group_seconds), 3),
                "completeGroupElapsedP95Seconds": percentile(group_seconds, .95),
                "estimatedTokenUsd": round(estimated, 6),
                "estimatedTokenUsdPerCompletedGroup": round(estimated / len(rows), 6),
            }
            totals[arm].update(attemptedGroups=45, completedGroups=len(rows),
                               failedGroups=len(failures),
                               combinedMachinePassGroups=summary["combinedMachinePassGroups"],
                               apiResponses=len(raw_paths))
            totals[arm]["estimatedTokenUsd"] += estimated
        locales[locale] = {"groups": 45, "pairedGroups": paired,
                           "excludedGroups": len(sheet["excludedGroups"]),
                           "blindOptions": len(scores["ratings"]),
                           "humanRatingsCompleted": scores["ratedOptions"],
                           "arms": by_arm}
    require(len(source_hashes) == len(anchor_hashes) == len(group_plans) == 1,
            "locales do not share one English source, anchor and group plan")
    aggregate = {}
    for arm, value in totals.items():
        aggregate[arm] = {key: round(number, 6) if key == "estimatedTokenUsd" else number
                          for key, number in value.items()}
        aggregate[arm]["estimatedTokenUsdPerCompletedGroup"] = round(
            value["estimatedTokenUsd"] / value["completedGroups"], 6)
        aggregate[arm]["completeGroupElapsedP50Seconds"] = round(
            statistics.median(all_group_seconds[arm]), 3)
        aggregate[arm]["completeGroupElapsedP95Seconds"] = percentile(
            all_group_seconds[arm], .95)
    return {"sharedSourceHash": next(iter(source_hashes)),
            "locales": locales, "aggregate": aggregate}


def summarize(root: Path) -> dict:
    return {"schemaVersion": "model-production-ab-summary-v1",
            "asOfLocalDate": "2026-09-28", "shadowOnly": True,
            "pricing": {"source": "https://developers.openai.com/api/docs/pricing",
                        "snapshotDate": "2026-09-28", "tierAssumption": "Standard short context",
                        "usdPerMillionTokens": {model: {"input": rates[0],
                            "cachedInput": rates[1], "cacheWrite": rates[2], "output": rates[3]}
                            for model, rates in RATES.items()},
                        "billVerified": False, "toolFeesIncluded": False,
                        "supervisorCacheWriteEvidence": "unavailable"},
            "supervisor": supervisor_summary(root),
            "layer2": layer2_summary(root),
            "humanTranslationApproval": False,
            "releaseEligible": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    print(json.dumps({"locales": list(result["layer2"]["locales"]),
                      "supervisorCases": 24, "out": str(args.out)}))


if __name__ == "__main__":
    main()
