#!/usr/bin/env python3
"""Run the DeepSeek ASR vs OpenAI gpt-transcribe A/B on the frozen 60-clip ASR reference set.

Arms (identical 16 kHz mono PCM WAV audio, one API call per clip):

- ``deepseek-asr``: POST https://api.deepseek.com/v1/tools/asr. The endpoint accepts
  no prompt and no language hint, so the arm sends none.
- ``openai-gpt-transcribe-nohint``: the project transcription model with
  ``language=en``, an empty prompt and no keywords, i.e. the same information the
  DeepSeek endpoint can receive.
- ``openai-gpt-transcribe-hinted``: the same model plus the project re-audit prompt
  and the manifest's critical terms as keywords, which is the domain hint DeepSeek
  cannot accept. It is a third arm, not part of the primary head-to-head.

Every call keeps a request identity, the raw response body and its SHA-256, the
observed latency and the provider usage, so a finished arm can be re-scored
without paying again. Re-running the same output directory reuses those receipts.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import resource
import subprocess
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
if str(REPO_ROOT / "experiments" / "local-asr") not in sys.path:
    sys.path.append(str(REPO_ROOT / "experiments" / "local-asr"))

from run_local_asr_benchmark import (  # noqa: E402
    SCORABLE_REFERENCE_STATUSES,
    contains_term,
    edit_distance,
    normalize_words,
    percentile,
)
import scripts.tongxing_host  # noqa: E402,F401  binds the production package ports

DEFAULT_MANIFEST = "data/benchmarks/live-sermon-translation-v1/local-asr-gpt-reaudited-reference-v1.json"
DEFAULT_OUTPUT = "artifacts/deepseek-asr-ab"
DEEPSEEK_URL = "https://api.deepseek.com/v1/tools/asr"
DEEPSEEK_PRICE_USD_PER_AUDIO_HOUR = {"limited_time": 0.058, "list": 0.116}
DEEPSEEK_PRICE_SOURCE = "https://api-docs.deepseek.com/guides/asr (read 2026-11-14)"
OPENAI_PRICE_USD_PER_AUDIO_MINUTE = 0.0045
OPENAI_PRICE_SOURCE = "packages/production/src/tongxing_production/compute/transcription_request.py PRICE_SOURCE (verified 2026-09-30)"
DEEPSEEK_MAX_SECONDS = 120.0
DEEPSEEK_MAX_BYTES = 8 * 1024 * 1024

# Frozen re-audit prompt from experiments/local-asr/run_local_asr_gpt_reaudit.py.
REAUDIT_PROMPT = (
    "Transcribe this English church-service audio exactly. Preserve complete spoken words and intelligible "
    "sung lyrics, including Bible names, personal names, ministry names, negations, and numbers. Do not "
    "invent words. If there is music but no intelligible speech or lyrics, return no spoken text."
)

ARMS = {
    "deepseek-asr": {
        "provider": "deepseek",
        "modelId": "deepseek-asr",
        "prompt": "",
        "keywords": "none",
        "languageHints": [],
    },
    "openai-gpt-transcribe-nohint": {
        "provider": "openai",
        "modelId": "gpt-transcribe",
        "prompt": "",
        "keywords": "none",
        "languageHints": ["en"],
    },
    "openai-gpt-transcribe-hinted": {
        "provider": "openai",
        "modelId": "gpt-transcribe",
        "prompt": REAUDIT_PROMPT,
        "keywords": "item",
        "languageHints": ["en"],
    },
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ffmpeg_wav(source: Path, dest: Path) -> None:
    """Convert to the one format both providers accept: 16-bit PCM WAV, 16 kHz, mono."""
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_suffix(".tmp.wav")
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ar",
            "16000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(temporary),
        ],
        check=False,
    ).returncode
    if result != 0:
        raise RuntimeError("ffmpeg_convert_failed")
    write_json(
        dest.with_suffix(".json"),
        {
            "source": str(source.relative_to(REPO_ROOT)),
            "sourceSha256": sha256_file(source),
            "wav": str(dest.relative_to(REPO_ROOT)),
            "wavSha256": sha256_file(temporary),
            "conversion": {"codec": "pcm_s16le", "sampleRate": 16000, "channels": 1},
        },
    )
    temporary.replace(dest)


def call_deepseek(api_key: str, wav_path: Path) -> dict[str, Any]:
    import requests

    attempts = []
    for attempt in range(2):
        started = time.perf_counter()
        with wav_path.open("rb") as handle:
            response = requests.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                files={"file": (wav_path.name, handle, "audio/wav")},
                timeout=300,
            )
        latency = time.perf_counter() - started
        attempts.append({"httpStatus": response.status_code, "latencySeconds": round(latency, 4)})
        if response.status_code == 200:
            return {"ok": True, "latency": latency, "attempts": attempts, "body": response.text,
                    "requestId": response.headers.get("x-request-id")}
        # 429/503/504 are documented transient outcomes for this endpoint; one retry only.
        if response.status_code in (429, 503, 504) and attempt == 0:
            time.sleep(10)
            continue
        return {"ok": False, "latency": latency, "attempts": attempts, "body": response.text,
                "error": f"http_{response.status_code}", "requestId": response.headers.get("x-request-id")}
    raise AssertionError("unreachable")


def call_openai(api_key: str, model: str, prompt: str, wav_path: Path,
                keywords: list[str], languages: list[str]) -> dict[str, Any]:
    from tongxing_production.workflows.dual_pdf import pipeline as sermon_pipeline

    started = time.perf_counter()
    response = sermon_pipeline.transcribe_openai_audio(
        api_key, model, prompt, wav_path, keywords=keywords, languages=languages
    )
    latency = time.perf_counter() - started
    return {"ok": True, "latency": latency, "attempts": [{"httpStatus": 200, "latencySeconds": round(latency, 4)}],
            "response": response}


def read_cache(request_path: Path, response_path: Path, identity: dict[str, Any]) -> dict[str, Any] | None:
    if not request_path.exists() or not response_path.exists():
        return None
    try:
        if json.loads(request_path.read_text()) != identity:
            return None
        return json.loads(response_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def process_item(item: dict[str, Any], arm: str, *, api_key: str, wav_dir: Path, run_dir: Path) -> dict[str, Any]:
    spec = ARMS[arm]
    item_id = item["id"]
    source_audio = (REPO_ROOT / item["audioPath"]).resolve()
    if sha256_file(source_audio) != item["audioSha256"]:
        raise RuntimeError(f"source audio SHA-256 mismatch: {item_id}")
    wav_path = wav_dir / f"{item_id}.wav"
    ffmpeg_wav(source_audio, wav_path)
    wav_sha = sha256_file(wav_path)
    size = wav_path.stat().st_size
    if size > DEEPSEEK_MAX_BYTES or item["durationSeconds"] > DEEPSEEK_MAX_SECONDS:
        raise RuntimeError(f"deepseek_request_bounds_exceeded: {item_id}")
    keywords = [] if spec["keywords"] == "none" else list(item.get("criticalTerms", []))
    identity = {
        "schemaVersion": "deepseek-asr-ab-request-v1",
        "arm": arm,
        "provider": spec["provider"],
        "model": spec["modelId"],
        "endpoint": DEEPSEEK_URL if spec["provider"] == "deepseek" else "https://api.openai.com/v1/audio/transcriptions",
        "promptSha256": hashlib.sha256(spec["prompt"].encode()).hexdigest(),
        "keywords": keywords,
        "languages": spec["languageHints"],
        "audioSha256": wav_sha,
        "sourceAudioSha256": item["audioSha256"],
        "durationSeconds": item["durationSeconds"],
    }
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    request_path = raw_dir / f"{item_id}.request.json"
    response_path = raw_dir / f"{item_id}.response.json"
    cached = read_cache(request_path, response_path, identity)
    if cached is not None:
        return {**cached, "cacheHit": True}
    write_json(request_path, identity)
    if spec["provider"] == "deepseek":
        outcome = call_deepseek(api_key, wav_path)
        payload = None
        if outcome["ok"]:
            try:
                payload = json.loads(outcome["body"])
            except json.JSONDecodeError:
                payload = None
        if payload is not None:
            record = {
                "id": item_id,
                "transcript": payload.get("text") or "",
                "providerText": payload.get("text"),
                "providerDurationMs": payload.get("duration_ms"),
                "providerRequestId": payload.get("request_id"),
                "usage": None,
            }
        else:
            record = {
                "id": item_id,
                "transcript": "",
                "providerError": {"error": outcome.get("error"), "body": outcome.get("body", "")[:2000]},
                "usage": None,
            }
    else:
        outcome = call_openai(api_key, spec["modelId"], spec["prompt"], wav_path, keywords, spec["languageHints"])
        response = outcome["response"]
        record = {
            "id": item_id,
            "transcript": response.get("text") or "",
            "providerText": response.get("text"),
            "usage": response.get("usage"),
            "providerLanguages": response.get("languages"),
        }
    record.update(
        {
            "ok": outcome["ok"],
            "latencySeconds": round(outcome["latency"], 4),
            "attempts": outcome["attempts"],
            "requestReceiptSha256": sha256_file(request_path),
            "responseSha256": hashlib.sha256(
                json.dumps(record, ensure_ascii=False, sort_keys=True).encode()
            ).hexdigest(),
            "receivedAt": now(),
        }
    )
    write_json(response_path, record)
    return {**record, "cacheHit": False}


def build_run_report(arm: str, items: list[dict[str, Any]], records: list[dict[str, Any]],
                     manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    spec = ARMS[arm]
    by_id = {row["id"]: row for row in records}
    predictions = []
    audio_seconds = 0.0
    for item in items:
        record = by_id[item["id"]]
        transcript = record["transcript"]
        speech_expected = item.get("speechExpected", True)
        if item["referenceStatus"] not in SCORABLE_REFERENCE_STATUSES:
            raise RuntimeError(f"unscorable reference: {item['id']}")
        reference_words = normalize_words(item["referenceText"])
        if speech_expected and not reference_words:
            raise RuntimeError(f"speech item has empty reference: {item['id']}")
        hyp_words = normalize_words(transcript)
        latency = float(record.get("latencySeconds") or 0.0)
        duration = float(item["durationSeconds"])
        audio_seconds += duration
        error = None if record.get("ok") else record.get("providerError", {}).get("error", "provider_error")
        parse_error = error
        predictions.append(
            {
                "id": item["id"],
                "arm": arm,
                "provider": spec["provider"],
                "modelId": spec["modelId"],
                "transcript": transcript,
                "referenceStatus": item["referenceStatus"],
                "speechExpected": speech_expected,
                "nonempty": bool(hyp_words),
                "exitCode": 0 if record.get("ok") else 1,
                "parseError": parse_error,
                "outputValid": bool(
                    record.get("ok") and parse_error is None and (hyp_words or not speech_expected)
                ),
                "durationSeconds": duration,
                "latencySeconds": latency,
                "rtf": round(latency / duration, 4) if duration else None,
                "peakRssGiB": None,
                "wordErrorCount": edit_distance(reference_words, hyp_words),
                "referenceWordCount": len(reference_words),
                "criticalTermHits": sum(contains_term(transcript, term) for term in item.get("criticalTerms", [])),
                "criticalTermCount": len(item.get("criticalTerms", [])),
                "usage": record.get("usage"),
                "providerDurationMs": record.get("providerDurationMs"),
                "cacheHit": record.get("cacheHit", False),
                "responseSha256": record.get("responseSha256"),
            }
        )
    predictions.sort(key=lambda row: row["id"])
    prediction_path = output_dir / "predictions.jsonl"
    prediction_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in predictions),
        encoding="utf-8",
    )
    latencies = [row["latencySeconds"] for row in predictions]
    rtfs = [row["rtf"] for row in predictions if row["rtf"] is not None]
    reference_words = sum(row["referenceWordCount"] for row in predictions)
    term_count = sum(row["criticalTermCount"] for row in predictions)
    silence_items = [row for row in predictions if not row["speechExpected"]]
    human_gold = [row for row in predictions if row["referenceStatus"] == "human_gold"]
    model_reviewed = [row for row in predictions if row["referenceStatus"] == "model_reviewed_reference"]
    gpt_reaudited = [row for row in predictions if row["referenceStatus"] == "gpt_reaudited_reference"]
    peak_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 ** 3)
    usage_seconds = sum(
        (row["usage"] or {}).get("seconds", 0) for row in predictions if isinstance(row["usage"], dict)
    )
    deepseek_seconds = sum(row["durationSeconds"] for row in predictions)
    report = {
        "schemaVersion": "local-asr-run-report-v1",
        "completedAt": now(),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "manifestSha256": sha256_file(manifest_path),
        "modelId": spec["modelId"],
        "modelSha256": None,
        "modelArtifact": None,
        "arm": arm,
        "provider": spec["provider"],
        "runtime": {
            "transport": "multipart/form-data over HTTPS",
            "audioFormat": "16 kHz mono 16-bit PCM WAV",
            "promptSha256": hashlib.sha256(spec["prompt"].encode()).hexdigest(),
            "promptSent": bool(spec["prompt"]),
            "keywordMode": spec["keywords"],
            "languageHints": spec["languageHints"],
            "peakRssScope": "http_client_process_no_local_model",
        },
        "decoding": {
            "backend": spec["provider"],
            "device": None,
            "language": "auto" if not spec["languageHints"] else spec["languageHints"][0],
            "threads": None,
            "beamSize": None,
            "bestOf": None,
            "temperature": None,
            "temperatureFallback": None,
            "vad": False,
        },
        "itemCount": len(predictions),
        "successCount": sum(row["outputValid"] for row in predictions),
        "nonemptyCount": sum(row["nonempty"] for row in predictions),
        "emptyExpectedSpeechCount": sum(row["speechExpected"] and not row["nonempty"] for row in predictions),
        "errorCount": sum(not row["outputValid"] for row in predictions),
        "totalAudioMinutes": round(audio_seconds / 60, 3),
        "latencySeconds": {
            "mean": round(statistics.mean(latencies), 4),
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "max": round(max(latencies), 4),
        },
        "rtf": {
            "mean": round(statistics.mean(rtfs), 4),
            "p50": percentile(rtfs, 0.50),
            "p95": percentile(rtfs, 0.95),
            "max": round(max(rtfs), 4),
        },
        "peakPerInvocationRssGiB": round(peak_rss, 4),
        "quality": {
            "status": (
                "scored_human_gold"
                if human_gold and not model_reviewed
                else "scored_model_reviewed_reference"
                if model_reviewed and not human_gold
                else "scored_mixed_reference_tiers"
            ),
            "scoredItemCount": len(predictions),
            "humanGoldItemCount": len(human_gold),
            "modelReviewedReferenceItemCount": len(model_reviewed),
            "gptReauditedReferenceItemCount": len(gpt_reaudited),
            "wer": round(sum(row["wordErrorCount"] for row in predictions) / reference_words, 6),
            "criticalTermRecall": round(sum(row["criticalTermHits"] for row in predictions) / term_count, 6),
            "silenceItemCount": len(silence_items),
            "silenceHallucinationCount": sum(row["nonempty"] for row in silence_items) if silence_items else None,
        },
        "performanceInterpretation": (
            "Per-clip remote API call; latency includes upload, queue and recognition, and excludes the local "
            "ffmpeg conversion. peakPerInvocationRssGiB is the client process peak, not model memory. "
            "Reference texts are GPT-Transcribe derived, so this score is not human Gold and is biased toward "
            "the OpenAI arms."
        ),
        "providerUsage": {
            "openaiReportedSeconds": usage_seconds,
            "deepseekAudioSeconds": round(deepseek_seconds, 3),
            "deepseekReportedDurationMsSum": sum(row["providerDurationMs"] or 0 for row in predictions),
            "estimatedCostUsd": (
                round(usage_seconds / 60 * OPENAI_PRICE_USD_PER_AUDIO_MINUTE, 4)
                if spec["provider"] == "openai"
                else round(deepseek_seconds / 3600 * DEEPSEEK_PRICE_USD_PER_AUDIO_HOUR["limited_time"], 4)
            ),
            "estimatedCostAtListPriceUsd": (
                round(usage_seconds / 60 * OPENAI_PRICE_USD_PER_AUDIO_MINUTE, 4)
                if spec["provider"] == "openai"
                else round(deepseek_seconds / 3600 * DEEPSEEK_PRICE_USD_PER_AUDIO_HOUR["list"], 4)
            ),
            "priceBasis": OPENAI_PRICE_SOURCE if spec["provider"] == "openai" else DEEPSEEK_PRICE_SOURCE,
            "invoiceVerified": False,
        },
        "predictionsSha256": sha256_file(prediction_path),
    }
    write_json(output_dir / "run-report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path(DEFAULT_MANIFEST))
    parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT))
    parser.add_argument("--arms", default=",".join(ARMS))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--confirm-billable", action="store_true")
    args = parser.parse_args()
    if not args.confirm_billable:
        raise SystemExit("--confirm-billable is required: this runner dispatches paid provider calls")

    manifest_path = (REPO_ROOT / args.manifest).resolve()
    output_dir = (REPO_ROOT / args.output_dir).resolve()
    manifest = json.loads(manifest_path.read_text())
    items = manifest["items"][: args.limit]
    wav_dir = output_dir / "audio"
    arms = [arm.strip() for arm in args.arms.split(",") if arm.strip()]
    for arm in arms:
        if arm not in ARMS:
            raise SystemExit(f"unknown arm: {arm}")

    from tongxing_production.observability.accounting import accounting_session

    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if "deepseek-asr" in arms and not deepseek_key:
        raise SystemExit("DEEPSEEK_API_KEY missing; run through tools/ops/run_with_openai_environment.py")
    if any(arm.startswith("openai") for arm in arms) and not openai_key:
        raise SystemExit("OPENAI_API_KEY missing; run through tools/ops/run_with_openai_environment.py")

    for arm in arms:
        run_dir = output_dir / "runs" / arm
        run_dir.mkdir(parents=True, exist_ok=True)
        spec = ARMS[arm]
        records: list[dict[str, Any]] = []
        with accounting_session(run_dir / "accounting", f"deepseek_asr_ab_{arm.replace('-', '_')}"):
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
                futures = {
                    executor.submit(
                        copy_context().run,
                        process_item,
                        item,
                        arm,
                        api_key=deepseek_key if spec["provider"] == "deepseek" else openai_key,
                        wav_dir=wav_dir,
                        run_dir=run_dir,
                    ): item["id"]
                    for item in items
                }
                for future in concurrent.futures.as_completed(futures):
                    item_id = futures[future]
                    try:
                        records.append(future.result())
                    except Exception as exc:  # noqa: BLE001 - keep per-item failure evidence
                        records.append(
                            {
                                "id": item_id,
                                "transcript": "",
                                "ok": False,
                                "providerError": {"error": f"runner_error: {exc}"},
                                "latencySeconds": 0.0,
                                "attempts": [],
                                "usage": None,
                            }
                        )
        report = build_run_report(arm, items, records, manifest_path, run_dir)
        print(json.dumps({"arm": arm, "quality": report["quality"], "errors": report["errorCount"],
                          "latencyP50": report["latencySeconds"]["p50"],
                          "costUsd": report["providerUsage"]["estimatedCostUsd"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
