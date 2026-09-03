#!/usr/bin/env python3
"""Translate one frozen sermon with Spark Qwen using the GPT reference pipeline prompts.

The source segmentation is immutable. Qwen first/edit/QA outputs are isolated,
cached, and blocked from training. The script calls an OpenAI-compatible
llama.cpp endpoint and never changes the Spark runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any
import urllib.error
import urllib.request


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402


SCHEMA_VERSION = "sermon-spark-qwen-ab-v1"
DEFAULT_MODEL = "Qwen3.8-27B-UD-Q4_K_XL-Unsloth"
DEFAULT_BASE_URL = "http://127.0.0.1:18001/v1"


def public_request(
    *, model: str, system_prompt: str, user_payload: dict[str, Any], schema: dict[str, Any]
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    user_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
            },
        ],
        "temperature": 0,
        "seed": 42,
        "max_tokens": 16384,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "sermon_batch", "strict": True, "schema": schema},
        },
    }


def request_json_cached(
    *,
    base_url: str,
    cache_path: Path,
    stage: str,
    prompt_version: str,
    model: str,
    system_prompt: str,
    user_payload: dict[str, Any],
    schema: dict[str, Any],
    timeout_seconds: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    request_body = public_request(
        model=model, system_prompt=system_prompt, user_payload=user_payload, schema=schema
    )
    input_sha = corpus.stable_json_sha256(
        {"stage": stage, "promptVersion": prompt_version, "request": request_body}
    )
    if cache_path.is_file():
        cached = corpus.read_json(cache_path)
        if cached.get("inputSha256") != input_sha:
            raise RuntimeError(f"Cache identity mismatch: {cache_path}")
        return cached["result"], cached

    started = time.monotonic()
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(
                base_url.rstrip("/") + "/chat/completions",
                data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = json.load(response)
            content = raw["choices"][0]["message"]["content"]
            result = json.loads(content)
            if not isinstance(result, dict):
                raise RuntimeError("Structured output root was not an object")
            receipt = {
                "schemaVersion": 1,
                "stage": stage,
                "promptVersion": prompt_version,
                "modelRequested": model,
                "modelReturned": raw.get("model") or model,
                "inputSha256": input_sha,
                "usage": raw.get("usage") or {},
                "timings": raw.get("timings") or {},
                "elapsedSeconds": round(time.monotonic() - started, 3),
                "createdAt": corpus.utc_now(),
                "endpointRecorded": base_url,
                "credentialsIncluded": False,
                "result": result,
            }
            corpus.write_json(cache_path, receipt)
            return result, receipt
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 ** (attempt - 1))
    raise RuntimeError(f"Spark Qwen {stage} failed after retries: {last_error}")


def clean_batch(
    expected: list[dict[str, Any]], result: dict[str, Any], stage: str
) -> list[dict[str, Any]]:
    returned = [
        corpus.clean_model_segment(item)
        for item in corpus.safe_list(result.get("segments"))
        if isinstance(item, dict)
    ]
    corpus.exact_ids(expected, returned, stage)
    return returned


def run_batches(
    *,
    stage: str,
    prompt_version: str,
    system_prompt: str,
    schema: dict[str, Any],
    payload_for_batch: Any,
    segments: list[dict[str, Any]],
    out_dir: Path,
    base_url: str,
    model: str,
    batch_size: int,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    output: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for start in range(0, len(segments), batch_size):
        batch = segments[start : start + batch_size]
        result, receipt = request_json_cached(
            base_url=base_url,
            cache_path=out_dir / "cache" / stage / f"{batch[0]['id']}_{batch[-1]['id']}.json",
            stage=stage,
            prompt_version=prompt_version,
            model=model,
            system_prompt=system_prompt,
            user_payload=payload_for_batch(start, batch),
            schema=schema,
            timeout_seconds=timeout_seconds,
        )
        output.extend(clean_batch(batch, result, stage))
        receipts.append(receipt)
        print(f"{stage}: {len(output)}/{len(segments)}", flush=True)
    return output, receipts


def totals(receipts: list[dict[str, Any]]) -> dict[str, Any]:
    usage = {"requests": len(receipts), "promptTokens": 0, "completionTokens": 0, "elapsedSeconds": 0.0}
    predicted_ms = 0.0
    for receipt in receipts:
        item = receipt.get("usage") or {}
        usage["promptTokens"] += int(item.get("prompt_tokens") or 0)
        usage["completionTokens"] += int(item.get("completion_tokens") or 0)
        usage["elapsedSeconds"] += float(receipt.get("elapsedSeconds") or 0)
        predicted_ms += float((receipt.get("timings") or {}).get("predicted_ms") or 0)
    usage["elapsedSeconds"] = round(usage["elapsedSeconds"], 3)
    usage["completionTokensPerSecond"] = round(
        usage["completionTokens"] / (predicted_ms / 1000) if predicted_ms else 0,
        3,
    )
    return usage


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_dir = args.source_root / args.video_id
    out_dir = args.out_root / args.video_id
    source_segments = corpus.read_jsonl(source_dir / "segments.en.jsonl")
    gpt_first = corpus.read_jsonl(source_dir / "segments.zh.first.jsonl")
    gpt_final = corpus.read_jsonl(source_dir / "segments.zh.final.jsonl")
    source_report = corpus.read_json(source_dir / "run-report.json")
    if not source_segments or not (len(source_segments) == len(gpt_first) == len(gpt_final)):
        raise SystemExit("Frozen source/GPT segment counts are empty or inconsistent")
    expected_ids = [row["id"] for row in source_segments]
    if [row["id"] for row in gpt_first] != expected_ids or [row["id"] for row in gpt_final] != expected_ids:
        raise SystemExit("Frozen source/GPT segment IDs are inconsistent")

    bible_data = corpus.read_json(args.bible)
    speaker = str(source_report.get("speaker") or "")
    title = str(source_report.get("title") or "")

    def translation_payload(start: int, batch: list[dict[str, Any]]) -> dict[str, Any]:
        surrounding = " ".join(
            row["en"]
            for row in source_segments[max(0, start - 1) : min(len(source_segments), start + len(batch) + 1)]
        )
        return {
            "sermon": {"videoId": args.video_id, "title": title, "speaker": speaker},
            "termMap": corpus.relevant_term_map(surrounding, bible_data, speaker),
            "previousEnglish": source_segments[start - 1]["en"] if start else None,
            "segments": [{"id": row["id"], "currentEnglish": row["en"]} for row in batch],
            "nextEnglish": source_segments[start + len(batch)]["en"] if start + len(batch) < len(source_segments) else None,
        }

    translated, translate_receipts = run_batches(
        stage="first_translation",
        prompt_version="parallel-first-translation-qwen38-v1",
        system_prompt=corpus.TRANSLATION_SYSTEM_PROMPT,
        schema=corpus.translation_batch_schema(),
        payload_for_batch=translation_payload,
        segments=source_segments,
        out_dir=out_dir,
        base_url=args.base_url,
        model=args.model,
        batch_size=args.batch_size,
        timeout_seconds=args.timeout_seconds,
    )
    first = [{**source, **candidate} for source, candidate in zip(source_segments, translated)]
    corpus.write_jsonl(out_dir / "segments.qwen.first.jsonl", first)
    glossary = corpus.candidate_glossary(first)
    corpus.write_json(out_dir / "glossary.qwen.candidate.json", glossary)

    def edit_payload(start: int, batch: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "termCandidates": glossary.get("terms") or [],
            "previousContext": {"en": first[start - 1]["en"], "zh": first[start - 1]["zh"]} if start else None,
            "segments": [
                {
                    "id": row["id"], "currentEnglish": row["en"], "draftChinese": row["zh"],
                    "scriptureRefs": row.get("scriptureRefs") or [], "properNouns": row.get("properNouns") or [],
                    "potentialAsrIssues": row.get("potentialAsrIssues") or [],
                }
                for row in batch
            ],
            "nextContext": {"en": first[start + len(batch)]["en"], "zh": first[start + len(batch)]["zh"]}
            if start + len(batch) < len(first) else None,
        }

    edited_rows, edit_receipts = run_batches(
        stage="chinese_edit_pass_1",
        prompt_version="parallel-chinese-edit-qwen38-v1",
        system_prompt=corpus.EDIT_SYSTEM_PROMPT,
        schema=corpus.edit_batch_schema(),
        payload_for_batch=edit_payload,
        segments=first,
        out_dir=out_dir,
        base_url=args.base_url,
        model=args.model,
        batch_size=args.batch_size,
        timeout_seconds=args.timeout_seconds,
    )
    edited = [{**source, "firstZh": source["zh"], **candidate} for source, candidate in zip(first, edited_rows)]
    corpus.write_jsonl(out_dir / "segments.qwen.edit1.jsonl", edited)

    def qa_payload(start: int, batch: list[dict[str, Any]]) -> dict[str, Any]:
        del start
        return {"segments": [
            {
                "id": row["id"], "currentEnglish": row["en"], "candidateChinese": row["zh"],
                "firstTranslation": row.get("firstZh") or "", "scriptureRefs": row.get("scriptureRefs") or [],
                "properNouns": row.get("properNouns") or [], "priorRiskFlags": row.get("riskFlags") or [],
                "potentialAsrIssues": row.get("potentialAsrIssues") or [],
            }
            for row in batch
        ]}

    qa_rows, qa_receipts = run_batches(
        stage="bilingual_qa_pass_2",
        prompt_version="parallel-bilingual-qa-qwen38-v1",
        system_prompt=corpus.QA_SYSTEM_PROMPT,
        schema=corpus.qa_batch_schema(),
        payload_for_batch=qa_payload,
        segments=edited,
        out_dir=out_dir,
        base_url=args.base_url,
        model=args.model,
        batch_size=args.batch_size,
        timeout_seconds=args.timeout_seconds,
    )
    final = []
    for source, reviewed in zip(edited, qa_rows):
        final.append({
            **source, "edit1Zh": source["zh"], **reviewed,
            "teacher": {"provider": "local_llama_cpp", "model": args.model,
                        "promptVersions": ["parallel-first-translation-qwen38-v1", "parallel-chinese-edit-qwen38-v1", "parallel-bilingual-qa-qwen38-v1"],
                        "provenance": "spark_qwen_isolated_comparison"},
            "qualityTier": "isolated_comparison", "reviewStatus": "model_reviewed_requires_independent_audit",
            "trainingEligibility": "blocked", "trainingBlockers": list(gpt_final[0].get("trainingBlockers") or []),
        })
    corpus.write_jsonl(out_dir / "segments.qwen.final.jsonl", final)

    all_receipts = [*translate_receipts, *edit_receipts, *qa_receipts]
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "qwen_translation_completed_requires_independent_comparison",
        "videoId": args.video_id,
        "title": title,
        "segmentCount": len(final),
        "sourceBindings": {
            "englishSha256": corpus.sha256_file(source_dir / "segments.en.jsonl"),
            "gptFirstSha256": corpus.sha256_file(source_dir / "segments.zh.first.jsonl"),
            "gptFinalSha256": corpus.sha256_file(source_dir / "segments.zh.final.jsonl"),
        },
        "runtime": {"baseUrl": args.base_url, "model": args.model, "temperature": 0, "seed": 42},
        "usage": totals(all_receipts),
        "stages": {
            "first": totals(translate_receipts), "edit": totals(edit_receipts), "qa": totals(qa_receipts)
        },
        "trainingEligibility": "blocked",
        "generatedAt": corpus.utc_now(),
    }
    corpus.write_json(out_dir / "qwen-run-report.json", report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", default="nre_3kR0PHk")
    parser.add_argument("--source-root", type=Path, default=Path("data/derived/sermon-parallel-corpus-expansion-v1"))
    parser.add_argument("--out-root", type=Path, default=Path("data/derived/sermon-qwen-spark-ab-v1"))
    parser.add_argument("--bible", type=Path, default=Path("data/scripture/cmn-cu89s.json"))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 8:
        raise SystemExit("--batch-size must be between 1 and 8")
    for key in ("source_root", "out_root", "bible"):
        value = getattr(args, key)
        setattr(args, key, value if value.is_absolute() else REPO_ROOT / value)
    return args


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
