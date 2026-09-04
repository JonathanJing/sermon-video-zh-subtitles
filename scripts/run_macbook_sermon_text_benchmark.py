#!/usr/bin/env python3
"""Run the frozen sermon text benchmark through Ollama or an MLX OpenAI server."""

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


PROMPTS = {
    "milmmt": (
        "milmmt-46-official-english-to-chinese-simplified-v1",
        "Translate this from English to Chinese (Simplified):\n"
        "English: {english}\n"
        "Chinese (Simplified):",
    ),
    "sermon-a0-completion": (
        "sermon-a0-base-completion-v1",
        "Translate the following spoken English Christian sermon subtitle into faithful, concise Simplified Chinese.\n"
        "Preserve negation, logical relationships, Bible references, names, and theological meaning. Do not add information.\n"
        "Output only the Chinese translation, with no explanation or labels.\n\n"
        "English:\n{english}\n\nSimplified Chinese:\n",
    ),
    "sermon-a0": (
        "macbook-sermon-a0-chat-v1",
        "Translate the following spoken English Christian sermon subtitle into faithful, concise Simplified Chinese.\n"
        "Preserve negation, logical relationships, Bible references, names, and theological meaning. Do not add information.\n"
        "Output only the Chinese translation, with no explanation or labels.\n\n{english}",
    ),
    "hymt2": (
        "hymt2-official-default-translation-en-chinese-v1",
        "Translate the following text into Chinese. Note that you should only output the translated result without any additional explanation:\n\n{english}",
    ),
}

PROMPT_STOPS = {
    "sermon-a0-completion": ["\n\nEnglish:"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend",
        choices=("ollama", "ollama-generate", "openai-chat", "openai-completion"),
        required=True,
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True, help="Model name exposed by the local server")
    parser.add_argument("--model-id", required=True, help="Canonical upstream model ID")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--runtime-fingerprint", required=True)
    parser.add_argument("--prompt-profile", choices=tuple(PROMPTS), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--repeat-penalty", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--limit", type=int)
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


def post_json(url: str, body: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=canonical_json(body),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.load(response)


def request_translation(args: argparse.Namespace, english: str) -> dict[str, Any]:
    _, template = PROMPTS[args.prompt_profile]
    message = template.format(english=english)
    started = time.monotonic()
    if args.backend == "ollama-generate":
        payload = post_json(
            args.base_url.rstrip("/") + "/api/generate",
            {
                "model": args.model,
                "prompt": message,
                "raw": True,
                "stream": False,
                "options": {
                    "temperature": args.temperature,
                    "top_p": args.top_p,
                    "top_k": args.top_k,
                    "repeat_penalty": args.repeat_penalty,
                    "seed": args.seed,
                    "num_predict": args.max_tokens,
                    "stop": PROMPT_STOPS.get(args.prompt_profile, []),
                },
            },
            args.timeout_seconds,
        )
        elapsed = time.monotonic() - started
        raw_text = str(payload.get("response") or "")
        prompt_tokens = int(payload.get("prompt_eval_count") or 0)
        completion_tokens = int(payload.get("eval_count") or 0)
        prompt_ns = int(payload.get("prompt_eval_duration") or 0)
        completion_ns = int(payload.get("eval_duration") or 0)
        return {
            "rawText": raw_text,
            "finishReason": payload.get("done_reason"),
            "elapsedSeconds": elapsed,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "timings": {
                "loadNanoseconds": int(payload.get("load_duration") or 0),
                "totalNanoseconds": int(payload.get("total_duration") or 0),
                "promptTokens": prompt_tokens,
                "promptNanoseconds": prompt_ns,
                "completionTokens": completion_tokens,
                "completionNanoseconds": completion_ns,
            },
        }

    if args.backend == "ollama":
        payload = post_json(
            args.base_url.rstrip("/") + "/api/chat",
            {
                "model": args.model,
                "messages": [{"role": "user", "content": message}],
                "stream": False,
                "options": {
                    "temperature": args.temperature,
                    "top_p": args.top_p,
                    "top_k": args.top_k,
                    "repeat_penalty": args.repeat_penalty,
                    "seed": args.seed,
                    "num_predict": args.max_tokens,
                },
            },
            args.timeout_seconds,
        )
        elapsed = time.monotonic() - started
        raw_text = str((payload.get("message") or {}).get("content") or "")
        prompt_tokens = int(payload.get("prompt_eval_count") or 0)
        completion_tokens = int(payload.get("eval_count") or 0)
        prompt_ns = int(payload.get("prompt_eval_duration") or 0)
        completion_ns = int(payload.get("eval_duration") or 0)
        return {
            "rawText": raw_text,
            "finishReason": payload.get("done_reason"),
            "elapsedSeconds": elapsed,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "timings": {
                "loadNanoseconds": int(payload.get("load_duration") or 0),
                "totalNanoseconds": int(payload.get("total_duration") or 0),
                "promptTokens": prompt_tokens,
                "promptNanoseconds": prompt_ns,
                "completionTokens": completion_tokens,
                "completionNanoseconds": completion_ns,
            },
        }

    if args.backend == "openai-completion":
        payload = post_json(
            args.base_url.rstrip("/") + "/completions",
            {
                "model": args.model,
                "prompt": message,
                "temperature": args.temperature,
                "top_p": args.top_p,
                "top_k": args.top_k,
                "repetition_penalty": args.repeat_penalty,
                "seed": args.seed,
                "max_tokens": args.max_tokens,
            },
            args.timeout_seconds,
        )
    else:
        payload = post_json(
            args.base_url.rstrip("/") + "/chat/completions",
            {
                "model": args.model,
                "messages": [{"role": "user", "content": message}],
                "temperature": args.temperature,
                "top_p": args.top_p,
                "top_k": args.top_k,
                "repetition_penalty": args.repeat_penalty,
                "seed": args.seed,
                "max_tokens": args.max_tokens,
            },
            args.timeout_seconds,
        )
    elapsed = time.monotonic() - started
    choice = payload["choices"][0]
    return {
        "rawText": (
            str(choice.get("text") or "")
            if args.backend == "openai-completion"
            else str((choice.get("message") or {}).get("content") or "")
        ),
        "finishReason": choice.get("finish_reason"),
        "elapsedSeconds": elapsed,
        "usage": payload.get("usage") or {},
        "timings": payload.get("timings") or {},
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
    prompt_version, prompt_template = PROMPTS[args.prompt_profile]
    identity = {
        "schemaVersion": "live-sermon-macbook-text-run-identity-v1",
        "referenceUsedForGeneration": False,
        "hardwareProfileId": "macbook-pro-m1-max-64gb-v1",
        "backend": args.backend,
        "baseUrl": args.base_url,
        "model": args.model,
        "modelId": args.model_id,
        "revision": args.revision,
        "artifactSha256": args.artifact_sha256,
        "runtimeFingerprint": args.runtime_fingerprint,
        "promptProfile": args.prompt_profile,
        "promptVersion": prompt_version,
        "promptSha256": hashlib.sha256(prompt_template.encode("utf-8")).hexdigest(),
        "temperature": args.temperature,
        "topP": args.top_p,
        "topK": args.top_k,
        "repeatPenalty": args.repeat_penalty,
        "stop": PROMPT_STOPS.get(args.prompt_profile) if args.backend == "ollama-generate" else None,
        "seed": args.seed,
        "maxTokens": args.max_tokens,
        "sources": sources,
        "selectedSegmentIds": [str(row["id"]) for row in rows],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    identity_path = args.output_dir / "run-identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text(encoding="utf-8")) != identity:
        raise RuntimeError("existing run identity differs; refusing to mix predictions")
    identity_path.write_text(json.dumps(identity, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    prediction_path = args.output_dir / "predictions.jsonl"
    predictions: dict[str, dict[str, Any]] = {}
    if prediction_path.exists():
        predictions = {
            item["segmentId"]: item
            for item in (json.loads(line) for line in prediction_path.read_text(encoding="utf-8").splitlines() if line.strip())
        }
    with prediction_path.open("a", encoding="utf-8") as output:
        for index, row in enumerate(rows, 1):
            segment_id = str(row["id"])
            if segment_id in predictions:
                print(f"resume: {index}/{len(rows)} {segment_id}", flush=True)
                continue
            last_error: Exception | None = None
            for attempt in range(args.retries + 1):
                try:
                    response = request_translation(args, str(row["en"]))
                    raw_text = response["rawText"]
                    translation = raw_text.strip()
                    item = {
                        "schemaVersion": "live-sermon-macbook-text-prediction-v1",
                        "segmentId": segment_id,
                        "sermonId": row["sermonId"],
                        "startMs": row.get("startMs"),
                        "endMs": row.get("endMs"),
                        "sourceTextSha256": row.get("sourceTextSha256"),
                        "english": row["en"],
                        "translation": translation,
                        "rawCompletion": raw_text,
                        "nonempty": bool(translation),
                        "containsCjk": any("\u3400" <= char <= "\u9fff" for char in translation),
                        "finishReason": response["finishReason"],
                        "elapsedSeconds": round(float(response["elapsedSeconds"]), 3),
                        "usage": response["usage"],
                        "timings": response["timings"],
                        "generatedAt": utc_now(),
                    }
                    if last_error is not None:
                        item["recoveredAfterError"] = type(last_error).__name__
                    break
                except (OSError, KeyError, TypeError, ValueError, urllib.error.HTTPError) as error:
                    last_error = error
                    if attempt < args.retries:
                        time.sleep(2**attempt)
                        continue
                    item = {
                        "schemaVersion": "live-sermon-macbook-text-prediction-v1",
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
            output.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            output.flush()
            predictions[segment_id] = item
            print(f"run: {index}/{len(rows)} {segment_id}", flush=True)

    ordered = [predictions[str(row["id"])] for row in rows]
    latencies = [float(item["elapsedSeconds"]) for item in ordered if "elapsedSeconds" in item]
    completion_tokens = sum(int((item.get("usage") or {}).get("completion_tokens") or 0) for item in ordered)
    completion_ns = sum(int((item.get("timings") or {}).get("completionNanoseconds") or 0) for item in ordered)
    error_count = sum("error" in item for item in ordered)
    report = {
        **identity,
        "schemaVersion": "live-sermon-macbook-text-run-report-v1",
        "status": "completed_with_errors" if error_count else "completed",
        "completedAt": utc_now(),
        "predictionPath": str(prediction_path),
        "predictionSha256": sha256_file(prediction_path),
        "predictionCount": len(ordered),
        "nonemptyCount": sum(bool(item.get("nonempty")) for item in ordered),
        "containsCjkCount": sum(bool(item.get("containsCjk")) for item in ordered),
        "errorCount": error_count,
        "latencySeconds": {
            "total": round(sum(latencies), 3),
            "mean": round(statistics.mean(latencies), 3) if latencies else None,
            "p50": percentile(latencies, 0.50),
            "p90": percentile(latencies, 0.90),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "throughput": {
            "completionTokens": completion_tokens,
            "completionNanoseconds": completion_ns,
            "decodeTokensPerSecond": round(completion_tokens * 1_000_000_000 / completion_ns, 3) if completion_ns else None,
            "decodeRateSource": "ollama_eval_duration" if completion_ns else "unavailable_from_backend",
        },
        "resourceEvidenceStatus": "requires_external_macbook_sampler",
    }
    report_path = args.output_dir / "run-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(report_path)
    return 0 if error_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
