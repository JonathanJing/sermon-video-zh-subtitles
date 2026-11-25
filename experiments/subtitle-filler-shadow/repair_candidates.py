#!/usr/bin/env python3
"""Prototype the alternative to a prompt-only filler rule: deterministic detection plus a
targeted repair call, only on the subtitle segments that actually carry a candidate filler.

The reading edition keeps its Chinese clean because it has a hard QA gate and a repair
loop, not because its prompt asks nicely. This script applies the same shape to the
subtitle layer at its real incidence (a handful of segments per sermon):

1. run the reading edition's filler patterns over the published subtitle translations;
2. for every flagged segment, send English + Chinese + the matched term and ask only
   whether the term is a discourse filler, keeping it verbatim when it carries meaning,
   is inside quoted speech, or is uncertain;
3. report which segments changed and whether any semantic use was touched.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from contextvars import copy_context
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
for extra in (REPO_ROOT, REPO_ROOT / "packages" / "production" / "src", REPO_ROOT / "experiments" / "subtitle-filler-shadow"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import scripts.tongxing_host  # noqa: E402,F401  binds the production package ports
import analyze_shadow as shadow  # noqa: E402
from tongxing_production.compute.legacy_openai import chat_json  # noqa: E402
from tongxing_production.observability.accounting import accounting_session  # noqa: E402
from tongxing_production.source.post_live_english import clean_text  # noqa: E402

MODEL = "gpt-6.1-sol"
REASONING = "high"
SYSTEM = """You are repairing one Chinese subtitle segment of an English sermon translation.

The segment was flagged because it contains a term that is sometimes a discourse filler: 嗯, 呃, 你知道,
你知道吗, 我是说, 好吧, 你看, 这样说得通吧. Decide whether the flagged term is a filler in THIS sentence and
whether the Chinese can be improved without changing meaning.

Rules:
- Keep the translation faithful; never add, remove or change meaning other than the filler.
- Remove a filler only when the sentence stays complete and natural without it. For 我是说 introducing a
  self-correction, keep the correction and use a dash instead of the phrase.
- Keep the term unchanged when it carries meaning ("我要你知道……", "因为你知道……", "我知道……"), is a real
  question ("你知道……吗？"), is part of quoted speech by someone else, or when you are not sure.
- Do not touch anything else in the sentence. Do not re-translate, re-style or shorten content.
- Return the complete repaired segment text, not a diff.

Return one JSON object only: {"action": "removed" | "rewritten" | "kept", "zh": string, "reason": string}"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/subtitle-filler-shadow/repair"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--confirm-billable", action="store_true")
    args = parser.parse_args()
    if not args.confirm_billable:
        raise SystemExit("--confirm-billable is required")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing; run through tools/ops/run_with_openai_environment.py")
    output_dir = (REPO_ROOT / args.output_dir).resolve()

    jobs = []
    for run_id, relative in shadow.RUNS.items():
        pipeline = (REPO_ROOT / relative).resolve()
        segments = {segment["id"]: segment for segment in json.loads((pipeline / "segments_timed_en_corrected.json").read_text())}
        published = shadow.load_published(pipeline)
        for segment_id, zh in sorted(published.items()):
            found = shadow.fillers_in(zh)
            if not found:
                continue
            jobs.append(
                {
                    "run": run_id,
                    "id": segment_id,
                    "english": segments[segment_id]["text"],
                    "zh": zh,
                    "terms": sorted({item["match"] for item in found}),
                    "flags": {
                        "semantic": any(item["possiblySemantic"] for item in found),
                        "quote": any(item["insideQuote"] for item in found),
                    },
                }
            )

    results = []

    def repair(job: dict[str, Any]) -> dict[str, Any]:
        user = json.dumps(
            {
                "current_id": job["id"],
                "english": job["english"],
                "chinese": job["zh"],
                "flaggedTerms": job["terms"],
            },
            ensure_ascii=False,
        )
        payload = {
            "model": MODEL,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            "reasoning_effort": REASONING,
        }
        cache_dir = output_dir / job["run"]
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"seg_{job['id']:04d}.json"
        request_sha = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if cache_path.exists():
            cached = json.loads(cache_path.read_text())
            if cached.get("requestSha256") == request_sha:
                return {**cached, "cacheHit": True}
        response = chat_json(api_key, payload)
        parsed = json.loads(response["choices"][0]["message"]["content"])
        record = {
            **job,
            "action": parsed.get("action"),
            "repaired": clean_text(parsed.get("zh", "")),
            "reason": parsed.get("reason"),
            "requestSha256": request_sha,
            "createdAt": datetime.now(timezone.utc).isoformat(),
        }
        record["fillersBefore"] = [item["match"] for item in shadow.fillers_in(job["zh"])]
        record["fillersAfter"] = [item["match"] for item in shadow.fillers_in(record["repaired"])]
        cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        return {**record, "cacheHit": False}

    with accounting_session(output_dir / "accounting", "subtitle_filler_repair"):
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(copy_context().run, repair, job): job for job in jobs}
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())

    results.sort(key=lambda row: (row["run"], row["id"]))
    resolved = [row for row in results if row["action"] in ("removed", "rewritten") and row["fillersAfter"] != row["fillersBefore"]]
    touched_semantic = [row for row in resolved if row["flags"]["semantic"] or row["flags"]["quote"]]
    summary = {
        "schemaVersion": "subtitle-filler-repair-v1",
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "flaggedSegments": len(results),
        "resolvedSegments": len(resolved),
        "keptSegments": sum(1 for row in results if row["action"] == "kept"),
        "touchedSemanticOrQuoted": [
            {"run": row["run"], "id": row["id"], "before": row["zh"], "after": row["repaired"], "reason": row["reason"]}
            for row in touched_semantic
        ],
        "changes": [
            {"run": row["run"], "id": row["id"], "action": row["action"], "before": row["zh"], "after": row["repaired"],
             "reason": row["reason"], "fillersBefore": row["fillersBefore"], "fillersAfter": row["fillersAfter"]}
            for row in results
        ],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: summary[k] for k in ("flaggedSegments", "resolvedSegments", "keptSegments")}, ensure_ascii=False))
    for row in summary["changes"]:
        print(f"\n{row['run']} #{row['id']} [{row['action']}] {row['fillersBefore']} -> {row['fillersAfter']}")
        print("  before:", row["before"][:160])
        print("  after :", row["after"][:160])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
