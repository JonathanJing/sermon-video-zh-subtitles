#!/usr/bin/env python3
"""Bounded A/B of implicit versus no-write caching for the notes Responses path.

Only synthetic sermon data is sent. The production notes request builder and HTTP
caller are reused; the two arms differ only in prompt_cache_options.mode.
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

from scripts import generate_notes_with_openai as notes
from scripts import sermon_accounting as accounting

MODEL = "gpt-5.6"
DEFAULT_MAX_OUTPUT_TOKENS = 512
PRICE_SNAPSHOT = "2026-09-28"
INPUT_USD_PER_MILLION = 4.0  # GPT-5.6 Sol; estimate, not an invoice.
CACHED_MULTIPLIER = 0.1
WRITE_MULTIPLIER = 1.25
TOPICS = ("耐心", "盼望", "彼此服事")
PARAGRAPHS = (
    ("开场提出一个普通的问题：当原来的安排被打乱，人会怎样回应？讲者提醒听众先看清事实，再决定下一步。",
     "The opening asks how people respond when familiar plans change. The speaker invites them to observe the facts before choosing a next step."),
    ("有人急着寻找确定答案，也有人停下来倾听邻舍的需要。两种反应显示，困难不仅考验计划，也显露我们的习惯。",
     "Some people rush toward certainty while others pause to hear a neighbor. The contrast shows that difficulty reveals habits as well as plans."),
    ("讲者区分等候和放弃：等候仍然承担今天能做的责任，不把尚未到来的结果说成已经实现。",
     "The speaker distinguishes waiting from giving up. Waiting still carries today's responsibilities without claiming an outcome has already arrived."),
    ("接着的例子是一位家庭成员生病后，朋友轮流送饭。送饭没有解决全部问题，却让这个家庭知道他们并不孤单。",
     "The next example describes friends bringing meals when a family member is ill. Meals do not solve everything, but they show the family it is not alone."),
    ("讲者提醒，善意不等于替别人作决定。先询问实际需要，才能避免用自己的时间表压过当事人的处境。",
     "Good intentions do not give one person authority to decide for another. Asking about actual needs keeps our timetable from overriding theirs."),
    ("经文的应用指向群体生活：记住曾得到的帮助，也留意那些没有被看见的人；这两方面都需要具体行动。",
     "The application points to community life: remember help received and notice people who are overlooked. Both call for concrete action."),
    ("讲者承认有些问题不会很快结束，因此不把短暂好转写成完整医治，也不要求受苦的人立刻表现喜乐。",
     "Some problems do not end quickly. The speaker does not describe a brief improvement as complete healing or demand immediate joy from someone who suffers."),
    ("在回应的部分，听众被邀请写下一个可以联络的人，并选择本周一次可实现的探访或实际帮助。",
     "In response, listeners are invited to name someone they can contact and choose one feasible visit or practical act of help this week."),
    ("讲者随后谈到边界：持续关怀需要休息、诚实与团队分担；独自承担一切往往让帮助难以持续。",
     "The speaker then addresses boundaries. Lasting care needs rest, honesty, and shared work; carrying everything alone often makes help unsustainable."),
    ("结尾没有保证每个处境都会立刻改变，而是回到今天的责任：认真倾听、明确表达、按能力行动。",
     "The ending promises no immediate change in every situation. It returns to today's responsibility to listen carefully, speak clearly, and act within one's ability."),
)


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def request_pair(index: int, max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS) -> dict[str, dict]:
    theme = TOPICS[index]
    segments = [
        {"id": f"synthetic-{index + 1}-{n + 1}", "startMs": n * 180_000,
         "endMs": (n + 1) * 180_000 - 1000,
         "zh": f"关于{theme}，{zh}", "en": en}
        for n, (zh, en) in enumerate(PARAGRAPHS)
    ]
    base = notes.build_openai_request(
        slices=notes.build_note_slices(segments),
        simulation={"sermonTitle": f"合成实验：{theme}"},
        model=MODEL, reasoning_effort="high",
    )
    base["max_output_tokens"] = max_output_tokens
    implicit = copy.deepcopy(base)
    explicit_no_breakpoint = copy.deepcopy(base)
    explicit_no_breakpoint["prompt_cache_options"] = {"mode": "explicit"}
    return {"implicit": implicit, "explicit_no_breakpoint": explicit_no_breakpoint}


def estimated_input_usd(usage: dict) -> float | None:
    details = usage.get("input_tokens_details") or {}
    total = usage.get("input_tokens")
    read = details.get("cached_tokens")
    write = details.get("cache_write_tokens")
    if not all(type(value) is int and value >= 0 for value in (total, read, write)):
        return None
    if read + write > total:
        return None
    weighted = total - read - write + read * CACHED_MULTIPLIER + write * WRITE_MULTIPLIER
    return round(weighted * INPUT_USD_PER_MILLION / 1_000_000, 9)


def summarize_result(result: dict) -> dict:
    summary = {"planSha256": result["planSha256"], "byArm": {}}
    for arm in ("implicit", "explicit_no_breakpoint"):
        rows = [row for row in result["attempts"] if row["arm"] == arm]
        def total(field: str) -> int | None:
            values = [((row["usage"].get("input_tokens_details") or {}).get(field)
                       if field != "input_tokens" else row["usage"].get(field))
                      for row in rows]
            return sum(values) if values and all(type(v) is int for v in values) else None
        costs = [row.get("estimatedInputUsd") for row in rows]
        summary["byArm"][arm] = {
            "calls": len(rows), "inputTokens": total("input_tokens"),
            "cachedTokens": total("cached_tokens"),
            "cacheWriteTokens": total("cache_write_tokens"),
            "estimatedInputUsd": (round(sum(costs), 9) if costs and
                                  all(type(value) in (int, float) for value in costs) else None),
            "responseStatuses": [row.get("responseStatus") for row in rows],
        }
    return summary


def load_key(env_file: Path | None) -> str:
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key and env_file:
        from dotenv import dotenv_values
        key = str(dotenv_values(env_file).get("OPENAI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("OPENAI_API_KEY is unavailable; no request was sent")
    return key


def save_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    temp.replace(path)


def run_live(out: Path, env_file: Path | None, pairs: int,
             max_output_tokens: int) -> dict:
    key = load_key(env_file)
    plan = [(index, arm) for index in range(pairs)
            for arm in (("implicit", "explicit_no_breakpoint") if index % 2 == 0
                        else ("explicit_no_breakpoint", "implicit"))]
    plan_hash = canonical_hash({"model": MODEL, "maxOutputTokens": max_output_tokens,
                                "requests": [request_pair(i, max_output_tokens)
                                             for i in range(pairs)]})
    result_path = out / "result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else {
        "schemaVersion": "prompt-cache-notes-ab-v1", "planSha256": plan_hash,
        "model": MODEL, "priceSnapshot": PRICE_SNAPSHOT,
        "inputUsdPerMillion": INPUT_USD_PER_MILLION, "attempts": [],
    }
    if result.get("planSha256") != plan_hash:
        raise SystemExit("Existing result belongs to a different plan")
    completed = {(row["pairIndex"], row["arm"]) for row in result["attempts"]}
    with accounting.accounting_session(out / "accounting", "prompt_cache_notes_ab"):
        for index, arm in plan:
            if (index, arm) in completed:
                continue
            marker = out / f"pair-{index + 1}-{arm}.started.json"
            if marker.exists():
                raise SystemExit(f"Uncertain paid attempt: {marker}; inspect before retry")
            payload = request_pair(index, max_output_tokens)[arm]
            save_json(marker, {"pairIndex": index + 1, "arm": arm,
                               "requestSha256": canonical_hash(payload),
                               "status": "started_response_unconfirmed"})
            start = time.perf_counter()
            response = notes.request_openai_notes(payload, key)
            elapsed = time.perf_counter() - start
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
            output_json_valid = False
            if response.get("status") == "completed":
                try:
                    output_json_valid = isinstance(
                        notes.parse_json_object(notes.extract_response_text(response)), dict)
                except (SystemExit, ValueError, TypeError, KeyError):
                    pass
            row = {"pairIndex": index + 1, "arm": arm,
                   "requestSha256": canonical_hash(payload),
                   "responseId": response.get("id"), "returnedModel": response.get("model"),
                   "responseStatus": response.get("status"),
                   "outputJsonValid": output_json_valid,
                   "elapsedSeconds": round(elapsed, 3),
                   "usage": usage, "estimatedInputUsd": estimated_input_usd(usage)}
            result["attempts"].append(row)
            save_json(result_path, result)
            marker.unlink()
            print(f"pair {index + 1} {arm}: input={usage.get('input_tokens')} "
                  f"read={(usage.get('input_tokens_details') or {}).get('cached_tokens')} "
                  f"write={(usage.get('input_tokens_details') or {}).get('cache_write_tokens')} "
                  f"estimated_input_usd={row['estimatedInputUsd']}", flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send at most six paid API requests")
    parser.add_argument("--env-file", type=Path, help="Existing local dotenv file (never copied)")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "prompt-cache-notes-ab")
    parser.add_argument("--summarize", type=Path, help="Read an existing local result.json without API calls")
    parser.add_argument("--pairs", type=int, default=len(TOPICS),
                        help="Number of frozen synthetic input pairs, 1..3")
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    args = parser.parse_args()
    if not 1 <= args.pairs <= len(TOPICS) or not 1 <= args.max_output_tokens <= 8192:
        parser.error("--pairs must be 1..3 and --max-output-tokens must be 1..8192")
    if args.summarize:
        print(json.dumps(summarize_result(json.loads(args.summarize.read_text())),
                         ensure_ascii=False, indent=2))
        return
    if not args.live:
        pairs = [request_pair(i, args.max_output_tokens) for i in range(args.pairs)]
        print(json.dumps({"model": MODEL, "pairs": len(pairs), "maximumPaidCalls": 2 * len(pairs),
                          "baseRequestBytes": [len(json.dumps(pair["implicit"], ensure_ascii=False).encode())
                                               for pair in pairs],
                          "armsDifferOnlyByCacheMode": all(
                              {k: v for k, v in pair["explicit_no_breakpoint"].items()
                               if k != "prompt_cache_options"} == pair["implicit"] for pair in pairs)},
                         ensure_ascii=False, indent=2))
        return
    print(json.dumps(summarize_result(run_live(args.out, args.env_file,
                                               args.pairs, args.max_output_tokens)),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
