#!/usr/bin/env python3
"""Measure output tokens/s for a model over the OpenAI API, default vs fast tier.

Run only through the explicit dev launcher, so the dev project and dev key are used:

  python3 scripts/run_with_openai_environment.py --environment dev -- \
    python3 scripts/measure_openai_model_tps.py --rounds 3

Each request is a streamed chat completion with the same fixed prompt, the same
reasoning effort and a capped max_completion_tokens. Tiers alternate within each
round, and the order flips every round, so service drift does not favour one arm.
Failed or unknown calls are recorded and never retried. Model output text is not
stored; only character counts, token usage and timings are.

Two rates are reported. End-to-end uses the whole request wall time. Generation
uses the time from the first streamed content delta to the end, which excludes the
wait before the first visible token (including any hidden reasoning).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import statistics
import sys
import time
import urllib.error
import urllib.request

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sermon_openai_runtime import bind_request, selected_route  # noqa: E402

CHAT_URL = "https://api.openai.com/v1/chat/completions"
TIERS = ("default", "fast")
PROMPT = (
    "请用简体中文写一篇约1500字的说明文，主题是：一个双语字幕团队如何保持术语前后一致。"
    "分为八个小节，每节一个小标题，包含两到三个要点和一个具体例子。不要使用表格。"
)
SCHEMA_VERSION = "openai-model-tps-v1"


def build_payload(model, tier, reasoning_effort, max_completion_tokens):
    return {
        "model": model,
        "reasoning_effort": reasoning_effort,
        "service_tier": tier,
        "max_completion_tokens": max_completion_tokens,
        "stream": True,
        "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": PROMPT}],
    }


def parse_error(body):
    try:
        error = json.loads(body.decode("utf-8")).get("error") or {}
    except (ValueError, AttributeError):
        return {}
    return {"errorType": error.get("type"), "errorCode": error.get("code")}


def timing_metrics(usage, start, first_event, first_content, end):
    """Pure timing and rate maths; times are perf_counter values."""
    total_s = end - start
    basis = "first_content" if first_content is not None else "first_event"
    anchor = first_content if first_content is not None else first_event
    gen_s = end - anchor if anchor is not None else None
    metrics = {"totalS": round(total_s, 4),
               "ttftS": round(anchor - start, 4) if anchor is not None else None,
               "genS": round(gen_s, 4) if gen_s is not None else None,
               "timingBasis": basis if anchor is not None else None,
               "completionTokens": None, "promptTokens": None, "reasoningTokens": None,
               "outputTpsEndToEnd": None, "outputTpsGeneration": None}
    if usage:
        completion = usage.get("completion_tokens")
        metrics["completionTokens"] = completion
        metrics["promptTokens"] = usage.get("prompt_tokens")
        metrics["reasoningTokens"] = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        if isinstance(completion, int) and total_s > 0:
            metrics["outputTpsEndToEnd"] = round(completion / total_s, 2)
        if isinstance(completion, int) and gen_s and gen_s > 0:
            metrics["outputTpsGeneration"] = round(completion / gen_s, 2)
    return metrics


def stream_once(payload, timeout):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(CHAT_URL, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + os.environ["OPENAI_API_KEY"])
    bind_request(request)
    record = {"outcome": "ok", "httpStatus": None, "errorType": None, "errorCode": None,
              "appliedServiceTier": None, "serverModel": None, "contentChars": 0}
    usage = None
    first_event = first_content = None
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            record["httpStatus"] = response.status
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                now = time.perf_counter()
                if first_event is None:
                    first_event = now
                record["appliedServiceTier"] = event.get("service_tier") or record["appliedServiceTier"]
                record["serverModel"] = event.get("model") or record["serverModel"]
                for choice in event.get("choices") or []:
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        record["contentChars"] += len(text)
                        if first_content is None:
                            first_content = now
                if event.get("usage"):
                    usage = event["usage"]
    except urllib.error.HTTPError as exc:
        record.update(outcome="http_error", httpStatus=exc.code)
        record.update(parse_error(exc.read()))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # The request may have been accepted before the failure, so the outcome is unknown.
        record.update(outcome="unknown_transport_error", errorType=type(exc).__name__)
    end = time.perf_counter()
    if record["outcome"] == "ok" and usage is None:
        record["outcome"] = "no_usage_reported"
    record.update(timing_metrics(usage, start, first_event, first_content, end))
    return record


def median_or_none(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else None


def summarize(results, tiers):
    summary = {}
    for tier in tiers:
        rows = [r for r in results if r["requestedTier"] == tier]
        ok = [r for r in rows if r["outcome"] == "ok" and r["completionTokens"]]
        summary[tier] = {
            "requested": len(rows),
            "ok": len(ok),
            "notOk": len(rows) - len(ok),
            "appliedServiceTiers": sorted({str(r["appliedServiceTier"]) for r in ok}),
            "medianTtftS": median_or_none([r["ttftS"] for r in ok]),
            "medianTotalS": median_or_none([r["totalS"] for r in ok]),
            "medianCompletionTokens": median_or_none([r["completionTokens"] for r in ok]),
            "medianReasoningTokens": median_or_none([r["reasoningTokens"] for r in ok]),
            "medianOutputTpsEndToEnd": median_or_none([r["outputTpsEndToEnd"] for r in ok]),
            "medianOutputTpsGeneration": median_or_none([r["outputTpsGeneration"] for r in ok]),
            "minOutputTpsGeneration": min((r["outputTpsGeneration"] for r in ok
                                           if r["outputTpsGeneration"] is not None), default=None),
            "maxOutputTpsGeneration": max((r["outputTpsGeneration"] for r in ok
                                           if r["outputTpsGeneration"] is not None), default=None),
        }
    return summary


def print_summary(summary, model):
    print(f"\nModel {model}: output tokens/s (median over successful calls)")
    header = f"{'tier':<9}{'ok/req':>8}{'TTFT s':>9}{'total s':>9}{'tokens':>8}{'reason':>8}{'E2E t/s':>9}{'gen t/s':>9}{'gen min':>9}{'gen max':>9}  applied"
    print(header)
    for tier, row in summary.items():
        print(f"{tier:<9}{str(row['ok']) + '/' + str(row['requested']):>8}"
              f"{str(row['medianTtftS']):>9}{str(row['medianTotalS']):>9}"
              f"{str(row['medianCompletionTokens']):>8}{str(row['medianReasoningTokens']):>8}"
              f"{str(row['medianOutputTpsEndToEnd']):>9}{str(row['medianOutputTpsGeneration']):>9}"
              f"{str(row['minOutputTpsGeneration']):>9}{str(row['maxOutputTpsGeneration']):>9}"
              f"  {','.join(row['appliedServiceTiers']) or '-'}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--reasoning-effort", default="medium", choices=("low", "medium", "high"))
    parser.add_argument("--tiers", nargs="+", default=list(TIERS), choices=TIERS)
    parser.add_argument("--rounds", type=int, default=3, help="Calls per tier, 1-5.")
    parser.add_argument("--max-completion-tokens", type=int, default=2048)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "artifacts" / "openai-model-tps" / "summary.json")
    args = parser.parse_args(argv)
    if not 1 <= args.rounds <= 5:
        parser.error("--rounds must be between 1 and 5")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        route = selected_route()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if route is None or route["environment"] != "dev":
        print("Run through: scripts/run_with_openai_environment.py --environment dev -- ...", file=sys.stderr)
        return 2
    if not os.environ.get("OPENAI_API_KEY"):
        print("selected_openai_key_missing", file=sys.stderr)
        return 2

    results = []
    for round_index in range(args.rounds):
        order = list(args.tiers) if round_index % 2 == 0 else list(reversed(args.tiers))
        for tier in order:
            payload = build_payload(args.model, tier, args.reasoning_effort, args.max_completion_tokens)
            record = stream_once(payload, args.timeout)
            record.update(round=round_index + 1, requestedTier=tier)
            results.append(record)
            print(f"round {round_index + 1} {tier:<8} {record['outcome']:<24} "
                  f"tokens={record['completionTokens']} gen_tps={record['outputTpsGeneration']}",
                  flush=True)

    summary = summarize(results, args.tiers)
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "route": route,
        "model": args.model,
        "reasoningEffort": args.reasoning_effort,
        "maxCompletionTokens": args.max_completion_tokens,
        "promptChars": len(PROMPT),
        "rounds": args.rounds,
        "results": results,
        "summary": summary,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(summary, args.model)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
