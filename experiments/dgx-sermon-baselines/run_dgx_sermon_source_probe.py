#!/usr/bin/env python3
"""Run a reference-blind sermon translation probe against OpenAI-compatible models."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import urllib.request


SYSTEM_PROMPT = """Translate spoken English Christian sermon captions into faithful, concise Simplified Chinese subtitles.
Preserve negation, logic, Bible references, names, and theological meaning. Do not add material not present in English.
Return JSON only with keys translation, terms, and warnings."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--endpoint", action="append", required=True, help="LABEL|BASE_URL|MODEL")
    parser.add_argument("--samples-per-input", type=int, default=2)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    if args.samples_per_input < 1:
        parser.error("--samples-per-input must be positive")
    return args


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def select_rows(paths: list[Path], count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for path in paths:
        rows = read_jsonl(path)
        ranked = sorted(rows, key=lambda row: hashlib.sha256(str(row["id"]).encode("utf-8")).hexdigest())
        chosen = sorted(ranked[:count], key=lambda row: int(row.get("startMs") or 0))
        selected.extend(chosen)
        sources.append({"path": str(path), "sha256": sha256_file(path), "segmentCount": len(rows), "selectedCount": len(chosen)})
    return selected, sources


def request_translation(base_url: str, model: str, row: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"segmentId": row["id"], "english": row["en"]}, ensure_ascii=False)},
        ],
        "temperature": 0,
        "seed": 42,
        "max_tokens": 768,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    elapsed = time.monotonic() - started
    content = payload["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    return {
        "segmentId": row["id"],
        "english": row["en"],
        "prediction": parsed,
        "elapsedSeconds": round(elapsed, 3),
        "usage": payload.get("usage") or {},
        "timings": payload.get("timings") or {},
    }


def main() -> int:
    args = parse_args()
    rows, sources = select_rows(args.input, args.samples_per_input)
    endpoints = []
    for value in args.endpoint:
        label, base_url, model = value.split("|", 2)
        predictions = []
        for index, row in enumerate(rows, 1):
            predictions.append(request_translation(base_url, model, row, args.timeout_seconds))
            print(f"{label}: {index}/{len(rows)}", flush=True)
        endpoints.append({
            "label": label,
            "baseUrl": base_url,
            "model": model,
            "predictionCount": len(predictions),
            "elapsedSeconds": round(sum(item["elapsedSeconds"] for item in predictions), 3),
            "predictions": predictions,
        })
    report = {
        "schemaVersion": "live-sermon-reference-blind-dgx-source-probe-v1",
        "status": "completed_requires_reference_scoring",
        "referenceUsed": False,
        "temperature": 0,
        "seed": 42,
        "sources": sources,
        "selectedSegmentIds": [row["id"] for row in rows],
        "endpoints": endpoints,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
