#!/usr/bin/env python3
"""Run a resumable, reference-blind A0 translation baseline on a completions API."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time
from typing import Any
import urllib.error
import urllib.request


PROMPT_VERSION = "sermon-a0-base-completion-v1"
PROMPT_TEMPLATE = """Translate the following spoken English Christian sermon subtitle into faithful, concise Simplified Chinese.
Preserve negation, logical relationships, Bible references, names, and theological meaning. Do not add information.
Output only the Chinese translation, with no explanation or labels.

English:
{english}

Simplified Chinese:
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True, help="Model name exposed by the server")
    parser.add_argument("--model-id", required=True, help="Canonical upstream model ID")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--runtime-fingerprint", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if args.max_tokens < 1 or args.timeout_seconds < 1 or args.retries < 0:
        parser.error("token, timeout, and retry values are invalid")
    return args


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sources(paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        file_rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for row in file_rows:
            segment_id = str(row["id"])
            if segment_id in seen:
                raise ValueError(f"duplicate segment id: {segment_id}")
            seen.add(segment_id)
            rows.append(row)
        sources.append({"path": str(path), "sha256": sha256_file(path), "segmentCount": len(file_rows)})
    return rows, sources


def request_completion(args: argparse.Namespace, row: dict[str, Any]) -> dict[str, Any]:
    prompt = PROMPT_TEMPLATE.format(english=row["en"])
    body = {
        "model": args.model,
        "prompt": prompt,
        "temperature": 0,
        "seed": 42,
        "max_tokens": args.max_tokens,
        "stop": ["\n\nEnglish:"],
    }
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/completions",
        data=canonical_json(body),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
        payload = json.load(response)
    elapsed = time.monotonic() - started
    choice = payload["choices"][0]
    raw_text = str(choice.get("text") or "")
    translation = raw_text.strip()
    return {
        "schemaVersion": "live-sermon-a0-prediction-v1",
        "segmentId": row["id"],
        "sermonId": row["sermonId"],
        "startMs": row.get("startMs"),
        "endMs": row.get("endMs"),
        "sourceTextSha256": row.get("sourceTextSha256") or sha256_bytes(str(row["en"]).encode("utf-8")),
        "english": row["en"],
        "translation": translation,
        "rawCompletion": raw_text,
        "nonempty": bool(translation),
        "containsCjk": any("\u3400" <= char <= "\u9fff" for char in translation),
        "finishReason": choice.get("finish_reason"),
        "elapsedSeconds": round(elapsed, 3),
        "usage": payload.get("usage") or {},
        "timings": payload.get("timings") or {},
        "generatedAt": utc_now(),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 3)


def main() -> int:
    args = parse_args()
    rows, sources = load_sources(args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    prompt_sha256 = sha256_bytes(PROMPT_TEMPLATE.encode("utf-8"))
    run_identity = {
        "schemaVersion": "live-sermon-a0-run-identity-v1",
        "referenceUsedForGeneration": False,
        "model": args.model,
        "modelId": args.model_id,
        "revision": args.revision,
        "runtimeFingerprint": args.runtime_fingerprint,
        "requestMode": "openai_compatible_completions",
        "promptVersion": PROMPT_VERSION,
        "promptSha256": prompt_sha256,
        "temperature": 0,
        "seed": 42,
        "maxTokens": args.max_tokens,
        "stop": ["\n\nEnglish:"],
        "sources": sources,
        "selectedSegmentIds": [row["id"] for row in rows],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    identity_path = args.output_dir / "run-identity.json"
    if identity_path.exists():
        existing = json.loads(identity_path.read_text(encoding="utf-8"))
        if existing != run_identity:
            raise RuntimeError("existing run identity differs; refusing to mix predictions")
    else:
        identity_path.write_text(json.dumps(run_identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    prediction_path = args.output_dir / "predictions.jsonl"
    predictions: dict[str, dict[str, Any]] = {}
    if prediction_path.exists():
        for line in prediction_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                predictions[item["segmentId"]] = item

    with prediction_path.open("a", encoding="utf-8") as output:
        for index, row in enumerate(rows, 1):
            segment_id = str(row["id"])
            if segment_id in predictions:
                print(f"resume: {index}/{len(rows)} {segment_id}", flush=True)
                continue
            last_error: Exception | None = None
            for attempt in range(args.retries + 1):
                try:
                    item = request_completion(args, row)
                    break
                except (OSError, KeyError, ValueError, urllib.error.HTTPError) as error:
                    last_error = error
                    if attempt >= args.retries:
                        item = {
                            "schemaVersion": "live-sermon-a0-prediction-v1",
                            "segmentId": segment_id,
                            "sermonId": row["sermonId"],
                            "startMs": row.get("startMs"),
                            "endMs": row.get("endMs"),
                            "sourceTextSha256": row.get("sourceTextSha256"),
                            "english": row["en"],
                            "translation": "",
                            "rawCompletion": "",
                            "nonempty": False,
                            "containsCjk": False,
                            "errorType": type(error).__name__,
                            "error": str(error),
                            "attemptCount": attempt + 1,
                            "generatedAt": utc_now(),
                        }
                        break
                    time.sleep(2 ** attempt)
            if last_error is not None and not item.get("error"):
                item["recoveredAfterError"] = type(last_error).__name__
            output.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            output.flush()
            predictions[segment_id] = item
            print(f"run: {index}/{len(rows)} {segment_id}", flush=True)

    ordered = [predictions[str(row["id"])] for row in rows]
    latencies = [float(item["elapsedSeconds"]) for item in ordered if "elapsedSeconds" in item]
    usage_keys = {key for item in ordered for key in (item.get("usage") or {}) if isinstance((item.get("usage") or {}).get(key), (int, float))}
    total_usage = {key: sum((item.get("usage") or {}).get(key, 0) for item in ordered) for key in sorted(usage_keys)}
    predicted_tokens = sum((item.get("timings") or {}).get("predicted_n", 0) for item in ordered)
    predicted_ms = sum((item.get("timings") or {}).get("predicted_ms", 0) for item in ordered)
    prompt_tokens = sum((item.get("timings") or {}).get("prompt_n", 0) for item in ordered)
    prompt_ms = sum((item.get("timings") or {}).get("prompt_ms", 0) for item in ordered)
    finish_reasons = sorted({str(item.get("finishReason")) for item in ordered if item.get("finishReason") is not None})
    error_count = sum("error" in item for item in ordered)
    sermon_ids = list(dict.fromkeys(str(row["sermonId"]) for row in rows))
    per_sermon = []
    for sermon_id in sermon_ids:
        sermon_items = [item for item in ordered if item["sermonId"] == sermon_id]
        sermon_latencies = [float(item["elapsedSeconds"]) for item in sermon_items if "elapsedSeconds" in item]
        per_sermon.append({
            "sermonId": sermon_id,
            "predictionCount": len(sermon_items),
            "nonemptyCount": sum(bool(item.get("nonempty")) for item in sermon_items),
            "containsCjkCount": sum(bool(item.get("containsCjk")) for item in sermon_items),
            "errorCount": sum("error" in item for item in sermon_items),
            "latencySeconds": {
                "mean": round(statistics.mean(sermon_latencies), 3) if sermon_latencies else None,
                "p95": percentile(sermon_latencies, 0.95),
            },
        })
    completed_at = utc_now()
    report = {
        **run_identity,
        "schemaVersion": "live-sermon-a0-run-report-v1",
        "status": "completed_with_errors" if error_count else "completed",
        "startedAt": min((item.get("generatedAt", completed_at) for item in ordered), default=completed_at),
        "completedAt": completed_at,
        "predictionPath": str(prediction_path),
        "predictionSha256": sha256_file(prediction_path),
        "predictionCount": len(ordered),
        "nonemptyCount": sum(bool(item.get("nonempty")) for item in ordered),
        "containsCjkCount": sum(bool(item.get("containsCjk")) for item in ordered),
        "errorCount": error_count,
        "finishReasonCounts": {reason: sum(str(item.get("finishReason")) == reason for item in ordered) for reason in finish_reasons},
        "latencySeconds": {
            "total": round(sum(latencies), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else None,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "usage": total_usage,
        "throughput": {
            "predictedTokens": predicted_tokens,
            "predictedMilliseconds": round(predicted_ms, 3),
            "predictedTokensPerSecond": round(predicted_tokens * 1000 / predicted_ms, 3) if predicted_ms else None,
            "promptTokensEvaluated": prompt_tokens,
            "promptMilliseconds": round(prompt_ms, 3),
            "promptTokensPerSecond": round(prompt_tokens * 1000 / prompt_ms, 3) if prompt_ms else None,
        },
        "perSermon": per_sermon,
    }
    report_path = args.output_dir / "run-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if report["errorCount"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
