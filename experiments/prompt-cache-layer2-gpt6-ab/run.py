#!/usr/bin/env python3
"""GPT-6 Layer 2 cache A/B using the production runner's captured request bodies.

The runner is invoked with its existing fake caller and synthetic test fixture;
only the resulting frozen request bodies are sent to OpenAI in live mode.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from scripts import run_target_language_models as layer2
from tests.test_run_target_language_models import RunTargetLanguageModelsTests

MODELS = {"translator": "gpt-6-astra", "reviewer": "gpt-6-sol"}
INPUT_RATES = {"gpt-6-astra": 10.0, "gpt-6-sol": 2.0}
STABLE_KEYS = ("targetLocale", "terminology", "scripture", "formatting")
MAX_COMPLETION_TOKENS = 1024
PRICE_SNAPSHOT = "2026-09-28"


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def captured_production_payloads() -> dict[str, list[dict]]:
    fixture = RunTargetLanguageModelsTests(methodName="test_astra_then_sol_each_group_and_admit_human_pending")
    fixture.setUp()
    try:
        layer2.run(fixture.fixture.source, fixture.fixture.anchor, fixture.fixture.policy,
                   fixture.out, "fixture-key", fixture.fake_call)
        calls = fixture.calls
        if [call["model"] for call in calls] != ["gpt-6-astra", "gpt-6-sol"] * 2:
            raise ValueError("Captured production model order changed")
        return {role: [copy.deepcopy(calls[index])
                       for index in ((0, 2) if role == "translator" else (1, 3))]
                for role in MODELS}
    finally:
        fixture.doCleanups()


def stable_first(payload: dict) -> dict:
    candidate = copy.deepcopy(payload)
    data = json.loads(candidate["messages"][1]["content"])
    ordered = {key: data[key] for key in STABLE_KEYS}
    ordered.update({key: value for key, value in data.items() if key not in STABLE_KEYS})
    candidate["messages"][1]["content"] = json.dumps(ordered, ensure_ascii=False)
    if json.loads(candidate["messages"][1]["content"]) != data:
        raise ValueError("A/B changed Layer 2 input values")
    return candidate


def payloads(weekly_policy: Path | None = None,
             long_source: bool = False) -> dict[str, dict[str, list[dict]]]:
    captured = captured_production_payloads()
    policy = json.loads(weekly_policy.read_text(encoding="utf-8")) if weekly_policy else None
    for role, originals in captured.items():
        if policy is not None:
            if policy[role]["model"] != MODELS[role]:
                raise ValueError("Weekly policy model differs from experiment model")
        for original in originals:
            data = json.loads(original["messages"][1]["content"])
            if policy is not None:
                for key in STABLE_KEYS:
                    data[key] = policy[key]
                original["reasoning_effort"] = policy[role]["reasoningEffort"]
                original["messages"][0]["content"] = original["messages"][0]["content"].rsplit(
                    "Prompt version: ", 1)[0] + "Prompt version: " + policy[role]["promptVersion"]
            if long_source:
                source = ("The speaker explains a promise and asks the audience to consider "
                          "how mercy and patience shape their response today. ") * 14
                data["englishUnits"][0]["english"] = source
            original["messages"][1]["content"] = json.dumps(data, ensure_ascii=False)
    result = {}
    for role, originals in captured.items():
        baseline = []
        candidate = []
        for original in originals:
            original["max_completion_tokens"] = MAX_COMPLETION_TOKENS
            baseline.append(original)
            candidate.append(stable_first(original))
        result[role] = {"current_order": baseline, "stable_first": candidate}
    return result


def shared_prefix_chars(first: str, second: str) -> int:
    return next((index for index, (a, b) in enumerate(zip(first, second)) if a != b),
                min(len(first), len(second)))


def input_cost(model: str, usage: dict) -> float | None:
    details = usage.get("prompt_tokens_details") or {}
    total = usage.get("prompt_tokens")
    read = details.get("cached_tokens")
    write = details.get("cache_write_tokens")
    if not all(type(value) is int and value >= 0 for value in (total, read, write)):
        return None
    if read + write > total:
        return None
    return round((total - read - write + read * 0.1 + write * 1.25)
                 * INPUT_RATES[model] / 1_000_000, 9)


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")
    temp.replace(path)


def load_key(env_file: Path | None) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and env_file:
        from dotenv import dotenv_values
        key = str(dotenv_values(env_file).get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is unavailable; no request was sent")
    return key


def plan(all_payloads: dict) -> list[tuple[str, str, int, dict]]:
    steps = []
    for role in MODELS:
        for arm in ("current_order", "stable_first"):
            for group_index, payload in enumerate(all_payloads[role][arm], 1):
                steps.append((role, arm, group_index, payload))
        steps.append((role, "stable_first_repeat", 1,
                      all_payloads[role]["stable_first"][0]))
    return steps


def run_live(out: Path, env_file: Path | None, all_payloads: dict) -> dict:
    key = load_key(env_file)
    steps = plan(all_payloads)
    plan_hash = digest({"models": MODELS, "steps": steps})
    result_path = out / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else {
        "schemaVersion": "prompt-cache-layer2-gpt6-ab-v1", "planSha256": plan_hash,
        "priceSnapshot": PRICE_SNAPSHOT, "attempts": [],
    }
    if result.get("planSha256") != plan_hash:
        raise SystemExit("Existing result belongs to another experiment plan")
    completed = {(row["role"], row["arm"], row["groupIndex"])
                 for row in result["attempts"]}
    for role, arm, group_index, payload in steps:
        if (role, arm, group_index) in completed:
            continue
        marker = out / f"{role}-{arm}-{group_index}.started.json"
        if marker.exists():
            raise SystemExit(f"Uncertain paid attempt: {marker}; inspect before retry")
        save_json(marker, {"role": role, "arm": arm, "groupIndex": group_index,
                           "requestSha256": digest(payload),
                           "status": "started_response_unconfirmed"})
        start = time.perf_counter()
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload, timeout=120)
        except requests.RequestException as exc:
            raise SystemExit(f"Request failed ({type(exc).__name__}); inspect marker before retry") from exc
        if response.status_code >= 400:
            error = response.json().get("error") if response.headers.get("content-type", "").startswith("application/json") else None
            code = error.get("code") if isinstance(error, dict) else None
            raise SystemExit(f"HTTP {response.status_code}, code={code}; inspect marker before retry")
        body = response.json()
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        row = {"role": role, "arm": arm, "groupIndex": group_index,
               "requestSha256": digest(payload), "responseId": body.get("id"),
               "returnedModel": body.get("model"), "finishReason":
               (body.get("choices") or [{}])[0].get("finish_reason"),
               "elapsedSeconds": round(time.perf_counter() - start, 3),
               "usage": usage, "estimatedInputUsd": input_cost(MODELS[role], usage)}
        result["attempts"].append(row)
        save_json(result_path, result)
        marker.unlink()
        details = usage.get("prompt_tokens_details") or {}
        print(f"{role} {arm} group={group_index}: input={usage.get('prompt_tokens')} "
              f"read={details.get('cached_tokens')} write={details.get('cache_write_tokens')} "
              f"input_usd={row['estimatedInputUsd']}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send at most ten paid requests")
    parser.add_argument("--env-file", type=Path, help="Existing local dotenv file")
    parser.add_argument("--weekly-policy", type=Path,
                        help="Frozen weekly policy; combines its reusable fields with synthetic source")
    parser.add_argument("--long-source", action="store_true",
                        help="Length-match synthetic source to production groups")
    parser.add_argument("--out", type=Path,
                        help="Ignored results directory; required for a weekly-policy run")
    args = parser.parse_args()
    if args.weekly_policy and not args.out:
        parser.error("--weekly-policy requires a separate --out")
    all_payloads = payloads(args.weekly_policy, args.long_source)
    if not args.live:
        stats = {}
        for role, arms in all_payloads.items():
            stats[role] = {arm: {
                "systemChars": len(rows[0]["messages"][0]["content"]),
                "sharedUserPrefixChars": shared_prefix_chars(
                    rows[0]["messages"][1]["content"],
                    rows[1]["messages"][1]["content"]),
                "sameParsedInputs": [json.loads(row["messages"][1]["content"])
                                     for row in rows] == [json.loads(row["messages"][1]["content"])
                                                       for row in arms["current_order"]],
            } for arm, rows in arms.items()}
        print(json.dumps({"steps": len(plan(all_payloads)), "models": MODELS,
                          "prefix": stats}, ensure_ascii=False, indent=2))
        return
    run_live(args.out or ROOT / "artifacts" / "prompt-cache-layer2-gpt6-ab",
             args.env_file, all_payloads)


if __name__ == "__main__":
    main()
