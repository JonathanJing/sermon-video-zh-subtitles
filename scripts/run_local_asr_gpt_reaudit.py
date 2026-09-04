#!/usr/bin/env python3
"""Re-audit selected ASR references with GPT-Transcribe and build a calibrated manifest."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import sermon_pipeline  # noqa: E402
from scripts.build_local_asr_model_reviewed_reference import (  # noqa: E402
    CRITICAL_TERMS,
    contains_term,
)
from scripts.run_local_asr_benchmark import normalize_words  # noqa: E402


PROMPT = (
    "Transcribe this English church-service audio exactly. Preserve complete spoken words and intelligible "
    "sung lyrics, including Bible names, personal names, ministry names, negations, and numbers. Do not "
    "invent words. If there is music but no intelligible speech or lyrics, return no spoken text."
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def read_secret(project: str, secret: str) -> str:
    result = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            "--project",
            project,
            "--secret",
            secret,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit("Unable to access the configured OpenAI API key secret")
    return result.stdout.strip()


def process_item(
    item: dict[str, Any],
    *,
    api_key: str,
    model: str,
    raw_dir: Path,
) -> dict[str, Any]:
    item_id = item["id"]
    audio_path = (REPO_ROOT / item["audioPath"]).resolve()
    if sha256_file(audio_path) != item["audioSha256"]:
        raise RuntimeError(f"Audio SHA-256 mismatch: {item_id}")
    keywords = item.get("criticalTerms", [])
    identity = sermon_pipeline.transcription_cache_identity(
        model=model,
        response_format="json",
        prompt=PROMPT,
        keywords=keywords,
        languages=["en"],
        audio_path=audio_path,
        start=0,
        end=item["durationSeconds"],
    )
    response_path = raw_dir / f"{item_id}.response.json"
    request_path = raw_dir / f"{item_id}.request.json"
    response = sermon_pipeline.read_transcription_cache(response_path, request_path, identity)
    cache_hit = response is not None
    if response is None:
        response = sermon_pipeline.transcribe_openai_audio(
            api_key,
            model,
            PROMPT,
            audio_path,
            keywords=keywords,
            languages=["en"],
        )
        sermon_pipeline.write_transcription_cache(response_path, request_path, response, identity)
    text = sermon_pipeline.clean_text(response.get("text", ""))
    return {
        "id": item_id,
        "audioPath": item["audioPath"],
        "audioSha256": item["audioSha256"],
        "durationSeconds": item["durationSeconds"],
        "model": model,
        "cacheHit": cache_hit,
        "transcript": text,
        "normalizedWordCount": len(normalize_words(text)),
        "usage": response.get("usage"),
        "responseSha256": sha256_file(response_path),
        "requestReceiptSha256": sha256_file(request_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--calibrated-manifest", type=Path, required=True)
    parser.add_argument("--model", default="gpt-transcribe")
    parser.add_argument("--gcp-project", default="ai-for-god")
    parser.add_argument("--api-key-secret", default="openai-api-key")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--confirm-billable-asr", action="store_true")
    args = parser.parse_args()
    if not args.confirm_billable_asr:
        raise SystemExit("--confirm-billable-asr is required")

    queue_path = (REPO_ROOT / args.queue).resolve()
    base_manifest_path = (REPO_ROOT / args.base_manifest).resolve()
    output_dir = (REPO_ROOT / args.output_dir).resolve()
    calibrated_path = (REPO_ROOT / args.calibrated_manifest).resolve()
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    queue = json.loads(queue_path.read_text())
    base_manifest = json.loads(base_manifest_path.read_text())
    if queue["manifestSha256"] != sha256_file(base_manifest_path):
        raise SystemExit("Calibration queue and base manifest do not match")

    api_key = read_secret(args.gcp_project, args.api_key_secret)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(
                process_item,
                item,
                api_key=api_key,
                model=args.model,
                raw_dir=raw_dir,
            ): item["id"]
            for item in queue["items"]
        }
        for future in concurrent.futures.as_completed(futures):
            item_id = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - preserve per-item failure evidence
                errors.append({"id": item_id, "error": str(exc)})
    results.sort(key=lambda row: row["id"])
    result_by_id = {row["id"]: row for row in results}

    rows = []
    for queue_item in queue["items"]:
        result = result_by_id.get(queue_item["id"])
        rows.append(
            {
                "id": queue_item["id"],
                "selectionReasons": queue_item["selectionReasons"],
                "modelReviewedReferenceText": queue_item["modelReviewedReferenceText"],
                "gptReauditText": result["transcript"] if result else None,
                "modelTranscripts": queue_item["modelTranscripts"],
                "status": "gpt_reaudited" if result else "gpt_reaudit_failed",
                "responseSha256": result["responseSha256"] if result else None,
                "usage": result["usage"] if result else None,
                "humanListeningCompleted": False,
                "humanApprovalClaimed": False,
            }
        )
    results_path = output_dir / "reaudit-results.jsonl"
    results_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )

    report = {
        "schemaVersion": "local-asr-gpt-reaudit-run-v1",
        "completedAt": datetime.now(timezone.utc).isoformat(),
        "status": "completed" if not errors else "failed_closed",
        "model": args.model,
        "credentialSource": f"gcp-secret-manager:{args.gcp_project}/{args.api_key_secret}",
        "apiKeyMaterialIncluded": False,
        "queue": str(queue_path.relative_to(REPO_ROOT)),
        "queueSha256": sha256_file(queue_path),
        "requestedItemCount": len(queue["items"]),
        "successfulItemCount": len(results),
        "errorCount": len(errors),
        "cacheHitCount": sum(row["cacheHit"] for row in results),
        "durationMinutes": queue["durationMinutes"],
        "errors": errors,
        "resultsSha256": sha256_file(results_path),
    }
    write_json(output_dir / "run-report.json", report)
    if errors:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    calibrated_items = []
    for item in base_manifest["items"]:
        result = result_by_id.get(item["id"])
        if result is None:
            calibrated_items.append(item)
            continue
        transcript = result["transcript"]
        calibrated_items.append(
            {
                **item,
                "referenceStatus": "gpt_reaudited_reference",
                "referenceText": transcript,
                "speechExpected": bool(normalize_words(transcript)),
                "criticalTerms": [term for term in CRITICAL_TERMS if contains_term(transcript, term)],
                "referenceProvenance": {
                    **item["referenceProvenance"],
                    "gptReaudit": {
                        "model": args.model,
                        "responseSha256": result["responseSha256"],
                        "requestReceiptSha256": result["requestReceiptSha256"],
                        "humanListeningCompleted": False,
                    },
                },
            }
        )
    calibrated_manifest = {
        **base_manifest,
        "datasetId": "BENCH-LIVE-ST-ASR-GPT-REAUDITED-REFERENCE-V1",
        "purpose": "quality_scoring_after_targeted_independent_gpt_transcribe_reaudit",
        "referencePolicy": "mixed_model_reviewed_and_gpt_reaudited_reference_not_human_gold",
        "baseManifest": str(base_manifest_path.relative_to(REPO_ROOT)),
        "baseManifestSha256": sha256_file(base_manifest_path),
        "gptReauditRun": str(output_dir.relative_to(REPO_ROOT)),
        "gptReauditedItemCount": len(results),
        "items": calibrated_items,
    }
    write_json(calibrated_path, calibrated_manifest)
    report["calibratedManifest"] = str(calibrated_path.relative_to(REPO_ROOT))
    report["calibratedManifestSha256"] = sha256_file(calibrated_path)
    write_json(output_dir / "run-report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
