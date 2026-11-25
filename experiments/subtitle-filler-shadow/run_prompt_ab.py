#!/usr/bin/env python3
"""Shadow A/B for the subtitle translation prompt: production v3 versus a candidate that
may drop semantically empty fillers.

Both arms send the identical production request payload (same segments, same neighbour
context, same glossary, same model and reasoning effort) and differ only in the system
prompt text, so the delta is the rule and model sampling, not a changed input.

The historical translations were produced by ``gpt-5.6``, which the bounded provider
contract no longer accepts. Both arms therefore run on the current default
``gpt-6.1-sol``; comparisons against the published text are reported separately as drift.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import statistics
import sys
import time
from contextvars import copy_context
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "packages" / "production" / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "production" / "src"))

import scripts.tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.compute.legacy_openai import chat_json  # noqa: E402
from tongxing_production.source import backend as source_backend  # noqa: E402
from tongxing_production.source.post_live_english import clean_text  # noqa: E402
from tongxing_production.observability.accounting import accounting_session  # noqa: E402
from tongxing_production.source import review_prompts  # noqa: E402
from tongxing_production.workflows.dual_pdf import pipeline as sermon_pipeline  # noqa: E402

MODEL = "gpt-6.1-sol"
REASONING = "high"
DEFAULT_RUNS = (
    "artifacts/post-live-runs/2026-08-23/sermon_ZDQwL3K-A44/pipeline",
    "artifacts/post-live-runs/2026-08-30/sermon_-BeFX5G2oAw/pipeline",
    "artifacts/post-live-runs/2026-09-13/sermon_8JYwTq1xcBE/pipeline",
)
FILLER_RULE_V4 = """
- Omit a non-semantic speech filler only when removing it cannot change the segment's meaning:
  a standalone "嗯"/"呃"; "你知道"/"你知道吗" used as a discourse marker and followed by a comma;
  "你看" followed by a comma or a colon; "我是说" that only restarts the same sentence, which you
  render with a dash while keeping the corrected content.
- Never omit any of them when the phrase carries meaning: "我要你知道……", "因为你知道……",
  "你知道……吗？" or any real question, and "我是说" that adds new content. Keep the sentence's own verbs.
- Never omit or reword anything inside a quotation of someone else's speech.
- When unsure, keep the filler: a slightly spoken subtitle is better than one that lost meaning."""


def sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def system_prompt(arm: str, terminology: str) -> str:
    base = review_prompts.CHINESE_TRANSLATION_SYSTEM_PROMPT
    if arm == "v4":
        base = base.rstrip() + "\n" + FILLER_RULE_V4
    return base + "\n" + terminology


def build_payload(arm: str, *, system: str, glossary: dict[str, Any], segments: list[dict[str, Any]],
                  index: int) -> dict[str, Any]:
    segment = segments[index]
    context = {
        "glossary": sermon_pipeline.glossary_terms(glossary),
        "zh_term_map": sermon_pipeline.zh_term_map(glossary),
        "previous_english": segments[index - 1]["text"] if index > 0 else "",
        "current_id": segment["id"],
        "current_english": segment["text"],
        "next_english": segments[index + 1]["text"] if index + 1 < len(segments) else "",
    }
    payload = {
        "model": MODEL,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "<glossary>\n"
                    + sermon_pipeline.glossary_lines(glossary)
                    + "\n</glossary>\n<context>\n"
                    + json.dumps(context, ensure_ascii=False)
                    + "\n</context>"
                ),
            },
        ],
        "reasoning_effort": REASONING,
    }
    return payload


def translate_one(job: dict[str, Any], *, api_key: str, out_dir: Path) -> dict[str, Any]:
    payload = job["payload"]
    cache_path = out_dir / job["run"] / f"seg_{job['segmentId']:04d}.json"
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text())
            if cached.get("requestSha256") == job["requestSha256"]:
                return {**cached, "cacheHit": True}
        except (OSError, json.JSONDecodeError):
            pass
    started = time.perf_counter()
    result = chat_json(api_key, payload)
    latency = time.perf_counter() - started
    parsed = json.loads(result["choices"][0]["message"]["content"])
    record = {
        "run": job["run"],
        "arm": job["arm"],
        "segmentId": job["segmentId"],
        "zh": clean_text(parsed.get("zh", "")),
        "returnedModel": result.get("model"),
        "usage": result.get("usage"),
        "latencySeconds": round(latency, 3),
        "requestSha256": job["requestSha256"],
        "responseSha256": hashlib.sha256(result["choices"][0]["message"]["content"].encode()).hexdigest(),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    write_json(cache_path, record)
    return {**record, "cacheHit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", default=list(DEFAULT_RUNS))
    parser.add_argument("--arms", default="v3,v4")
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/subtitle-filler-shadow"))
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--shard", default=None, help="INDEX/COUNT: only run jobs where index %% COUNT == INDEX")
    parser.add_argument("--confirm-billable", action="store_true")
    args = parser.parse_args()
    if not args.confirm_billable:
        raise SystemExit("--confirm-billable is required: this dispatches paid model calls")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing; run through tools/ops/run_with_openai_environment.py")

    output_dir = (REPO_ROOT / args.output_dir).resolve()
    terminology = source_backend.current().terminology.prompt_instruction()
    glossary = sermon_pipeline.load_glossary(None)
    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]

    jobs: list[dict[str, Any]] = []
    for run in args.runs:
        pipeline_dir = (REPO_ROOT / run).resolve()
        segments = json.loads((pipeline_dir / "segments_timed_en_corrected.json").read_text())
        if args.limit:
            segments = segments[: args.limit]
        for arm in arms:
            system = system_prompt(arm, terminology)
            for index in range(len(segments)):
                payload = build_payload(arm, system=system, glossary=glossary, segments=segments, index=index)
                jobs.append(
                    {
                        "run": pipeline_dir.parent.name,
                        "arm": arm,
                        "segmentId": segments[index]["id"],
                        "requestSha256": sha256_json(
                            {"run": pipeline_dir.parent.name, "payload": payload,
                             "promptArm": arm, "system": system}
                        ),
                        "payload": payload,
                    }
                )

    if args.shard:
        index_text, count_text = args.shard.split("/")
        shard_index, shard_count = int(index_text), int(count_text)
        jobs = [job for position, job in enumerate(jobs) if position % shard_count == shard_index]
    accounting_dir = output_dir / (f"accounting-shard-{args.shard.replace('/', '-')}" if args.shard else "accounting")

    with accounting_session(accounting_dir, "subtitle_filler_shadow"):
        for arm in arms:
            arm_jobs = [job for job in jobs if job["arm"] == arm]
            out_dir = output_dir / arm
            results: list[dict[str, Any]] = []
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(copy_context().run, translate_one, job, api_key=api_key, out_dir=out_dir):
                    (job["run"], job["segmentId"])
                    for job in arm_jobs
                }
                for future in concurrent.futures.as_completed(futures):
                    try:
                        results.append(future.result())
                    except Exception as exc:  # noqa: BLE001 - keep per-segment failure evidence
                        run_id, segment_id = futures[future]
                        results.append(
                            {"run": run_id, "arm": arm, "segmentId": segment_id, "zh": "", "error": str(exc)}
                        )
            errors = [row for row in results if row.get("error") or not row.get("zh")]
            latencies = [row["latencySeconds"] for row in results if row.get("latencySeconds")]
            summary = {
                "arm": arm,
                "model": MODEL,
                "reasoningEffort": REASONING,
                "glossarySource": "pipeline.load_glossary(None) as of this run (the historical glossary was not saved)",
                "runCount": len(args.runs),
                "segmentCount": len(arm_jobs),
                "translatedCount": len(results) - len(errors),
                "errorCount": len(errors),
                "cacheHitCount": sum(1 for row in results if row.get("cacheHit")),
                "latencySeconds": {
                    "mean": round(statistics.mean(latencies), 3) if latencies else None,
                    "p50": round(statistics.median(latencies), 3) if latencies else None,
                    "max": round(max(latencies), 3) if latencies else None,
                },
                "usage": {
                    "promptTokens": sum((row.get("usage") or {}).get("prompt_tokens", 0) for row in results),
                    "completionTokens": sum((row.get("usage") or {}).get("completion_tokens", 0) for row in results),
                    "reasoningTokens": sum(
                        ((row.get("usage") or {}).get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
                        for row in results
                    ),
                },
                "errors": errors[:20],
                "completedAt": datetime.now(timezone.utc).isoformat(),
            }
            write_json(output_dir / f"{arm}-summary.json", summary)
            print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
