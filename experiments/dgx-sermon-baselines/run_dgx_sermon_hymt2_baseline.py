#!/usr/bin/env python3
"""Run a resumable, reference-blind Hy-MT2 sermon translation benchmark."""

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


PROMPT_VERSION = "hymt2-official-default-translation-en-chinese-v1"
PROMPT_TEMPLATE = """Translate the following text into Chinese. Note that you should only output the translated result without any additional explanation:

{english}"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--runtime-fingerprint", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--retries", type=int, default=2)
    return parser.parse_args()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            if row["id"] in seen:
                raise ValueError(f"duplicate segment id: {row['id']}")
            seen.add(row["id"])
            rows.append(row)
        sources.append({"path": str(path), "sha256": sha256_file(path), "segmentCount": len(file_rows)})
    return rows, sources


def request_translation(args: argparse.Namespace, row: dict[str, Any]) -> dict[str, Any]:
    body = {
        "model": args.model,
        "messages": [{"role": "user", "content": PROMPT_TEMPLATE.format(english=row["en"])}],
        "temperature": 0.7,
        "top_p": 0.6,
        "top_k": 20,
        "repeat_penalty": 1.05,
        "seed": 42,
        "max_tokens": args.max_tokens,
    }
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    started = time.monotonic()
    with urllib.request.urlopen(request, timeout=args.timeout_seconds) as response:
        payload = json.load(response)
    elapsed = time.monotonic() - started
    choice = payload["choices"][0]
    raw_text = str(choice["message"].get("content") or "")
    translation = raw_text.strip()
    return {
        "schemaVersion": "live-sermon-hymt2-prediction-v1",
        "segmentId": row["id"],
        "sermonId": row["sermonId"],
        "startMs": row.get("startMs"),
        "endMs": row.get("endMs"),
        "sourceTextSha256": row.get("sourceTextSha256"),
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
    return round(ordered[round((len(ordered) - 1) * fraction)], 3)


def main() -> int:
    args = parse_args()
    rows, sources = load_sources(args.input)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be positive")
        rows = rows[: args.limit]
    identity = {
        "schemaVersion": "live-sermon-hymt2-run-identity-v1",
        "referenceUsedForGeneration": False,
        "model": args.model,
        "modelId": args.model_id,
        "revision": args.revision,
        "runtimeFingerprint": args.runtime_fingerprint,
        "requestMode": "openai_compatible_chat_completions",
        "promptVersion": PROMPT_VERSION,
        "promptSha256": hashlib.sha256(PROMPT_TEMPLATE.encode("utf-8")).hexdigest(),
        "temperature": 0.7,
        "topP": 0.6,
        "topK": 20,
        "repeatPenalty": 1.05,
        "seed": 42,
        "maxTokens": args.max_tokens,
        "sources": sources,
        "selectedSegmentIds": [row["id"] for row in rows],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    identity_path = args.output_dir / "run-identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text(encoding="utf-8")) != identity:
        raise RuntimeError("existing run identity differs; refusing to mix predictions")
    identity_path.write_text(json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    prediction_path = args.output_dir / "predictions.jsonl"
    predictions: dict[str, dict[str, Any]] = {}
    if prediction_path.exists():
        predictions = {item["segmentId"]: item for item in (json.loads(line) for line in prediction_path.read_text(encoding="utf-8").splitlines() if line.strip())}
    with prediction_path.open("a", encoding="utf-8") as output:
        for index, row in enumerate(rows, 1):
            if row["id"] in predictions:
                print(f"resume: {index}/{len(rows)} {row['id']}", flush=True)
                continue
            item: dict[str, Any]
            for attempt in range(args.retries + 1):
                try:
                    item = request_translation(args, row)
                    break
                except (OSError, KeyError, ValueError, urllib.error.HTTPError) as error:
                    if attempt < args.retries:
                        time.sleep(2**attempt)
                        continue
                    item = {
                        "schemaVersion": "live-sermon-hymt2-prediction-v1",
                        "segmentId": row["id"], "sermonId": row["sermonId"],
                        "startMs": row.get("startMs"), "endMs": row.get("endMs"),
                        "sourceTextSha256": row.get("sourceTextSha256"), "english": row["en"],
                        "translation": "", "rawCompletion": "", "nonempty": False, "containsCjk": False,
                        "errorType": type(error).__name__, "error": str(error), "attemptCount": attempt + 1,
                        "generatedAt": utc_now(),
                    }
            output.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            output.flush()
            predictions[row["id"]] = item
            print(f"run: {index}/{len(rows)} {row['id']}", flush=True)

    ordered = [predictions[row["id"]] for row in rows]
    latencies = [float(item["elapsedSeconds"]) for item in ordered if "elapsedSeconds" in item]
    predicted_tokens = sum((item.get("timings") or {}).get("predicted_n", 0) for item in ordered)
    predicted_ms = sum((item.get("timings") or {}).get("predicted_ms", 0) for item in ordered)
    prompt_tokens = sum((item.get("timings") or {}).get("prompt_n", 0) for item in ordered)
    prompt_ms = sum((item.get("timings") or {}).get("prompt_ms", 0) for item in ordered)
    usage_keys = {key for item in ordered for key, value in (item.get("usage") or {}).items() if isinstance(value, (int, float))}
    error_count = sum("error" in item for item in ordered)
    report = {
        **identity,
        "schemaVersion": "live-sermon-hymt2-run-report-v1",
        "status": "completed_with_errors" if error_count else "completed",
        "completedAt": utc_now(),
        "predictionPath": str(prediction_path),
        "predictionSha256": sha256_file(prediction_path),
        "predictionCount": len(ordered),
        "nonemptyCount": sum(bool(item.get("nonempty")) for item in ordered),
        "containsCjkCount": sum(bool(item.get("containsCjk")) for item in ordered),
        "errorCount": error_count,
        "finishReasonCounts": {reason: sum(item.get("finishReason") == reason for item in ordered) for reason in sorted({item.get("finishReason") for item in ordered if item.get("finishReason")})},
        "latencySeconds": {
            "total": round(sum(latencies), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else None,
            "p50": percentile(latencies, 0.50), "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "throughput": {
            "predictedTokens": predicted_tokens, "predictedMilliseconds": round(predicted_ms, 3),
            "predictedTokensPerSecond": round(predicted_tokens * 1000 / predicted_ms, 3) if predicted_ms else None,
            "promptTokensEvaluated": prompt_tokens, "promptMilliseconds": round(prompt_ms, 3),
            "promptTokensPerSecond": round(prompt_tokens * 1000 / prompt_ms, 3) if prompt_ms else None,
        },
        "usage": {key: sum((item.get("usage") or {}).get(key, 0) for item in ordered) for key in sorted(usage_keys)},
    }
    report_path = args.output_dir / "run-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if error_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
