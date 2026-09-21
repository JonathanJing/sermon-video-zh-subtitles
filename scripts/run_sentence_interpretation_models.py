#!/usr/bin/env python3
"""Run cached GPT translation and independent review for sentence anchors.

The caller supplies ``OPENAI_API_KEY`` in the process environment.  The key is
never written to requests or artifacts.  Outputs remain semantic candidates;
measured natural-rate TTS and human listening approval are separate gates.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sermon_sentence_interpretation as contract  # noqa: E402
from scripts import series_terminology  # noqa: E402
from scripts.sermon_pipeline import chat_json  # noqa: E402


SEMANTIC_SCHEMA = "sermon-sentence-semantic-candidate-v1"
RUN_SCHEMA = "sermon-sentence-model-run-v1"


def batches(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size < 1:
        raise ValueError("batch size must be positive")
    return [items[index:index + size] for index in range(0, len(items), size)]


def _model_result(response: dict[str, Any], requested_model: str) -> dict[str, Any]:
    model = response.get("model")
    choices = response.get("choices")
    if not isinstance(model, str) or not model.startswith(requested_model):
        raise ValueError("Unexpected response model")
    if not isinstance(choices, list) or len(choices) != 1 or choices[0].get("finish_reason") != "stop":
        raise ValueError("Model response did not complete")
    try:
        result = json.loads(choices[0]["message"]["content"])
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Model response was not a JSON object") from exc
    if not isinstance(result, dict):
        raise ValueError("Model response was not an object")
    return result


def cached_call(*, out: Path, stage: str, payload: dict[str, Any], api_key: str,
                requested_model: str, caller: Callable[..., dict[str, Any]] = chat_json) -> tuple[dict[str, Any], dict[str, Any]]:
    request = {"schemaVersion": RUN_SCHEMA, "stage": stage, "payload": payload}
    request_hash = contract.json_sha256(request)
    path = out / "cache" / f"{stage}-{request_hash}.json"
    if path.exists():
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("requestSha256") != request_hash or receipt.get("request") != request:
            raise ValueError("Cached model request identity changed")
    else:
        response = caller(api_key, payload)
        receipt = {
            "schemaVersion": RUN_SCHEMA,
            "request": request,
            "requestSha256": request_hash,
            "response": response,
            "responseSha256": contract.json_sha256(response),
        }
        contract.write_json(path, receipt)
    return _model_result(receipt["response"], requested_model), {
        "path": str(path.resolve()),
        "sha256": contract.sha256(path),
        "requestSha256": request_hash,
        "responseId": receipt["response"].get("id"),
        "model": receipt["response"].get("model"),
    }


def _translation_payload(*, manifest_hash: str, request_batch: list[dict[str, Any]],
                         model: str, effort: str, terminology: dict[str, Any]) -> dict[str, Any]:
    expected = [{
        "translationGroupId": item["translationGroupId"],
        "sourceUnitIds": item["sourceUnitIds"],
    } for item in request_batch]
    user = {
        "anchorManifestSha256": manifest_hash,
        "seriesTerminology": terminology,
        "requests": request_batch,
        "outputContract": {
            "schemaVersion": contract.DRAFT_SCHEMA,
            "groupsInExactOrder": expected,
            "groupShape": {
                "translationGroupId": "copy exactly",
                "sourceUnitIds": ["copy exactly"],
                "chineseUtterances": ["one or more complete natural spoken Chinese utterances"],
                "chinese": "exact concatenation of chineseUtterances without inserted spaces",
                "coverage": [{
                    "sourceUnitId": "copy exactly",
                    "targetText": "nonempty exact substring of chinese expressing the complete source unit",
                }],
            },
            "issues": [],
        },
    }
    return {
        "model": model,
        "reasoning_effort": effort,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": contract.TRANSLATION_SYSTEM_PROMPT + "\n" + terminology["rules"]},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }


def _checked_translation_batch(result: dict[str, Any], expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if result.get("schemaVersion") != contract.DRAFT_SCHEMA or result.get("issues") != []:
        raise ValueError("Translation batch returned the wrong schema or unresolved issues")
    groups = result.get("groups")
    if not isinstance(groups, list) or len(groups) != len(expected):
        raise ValueError("Translation batch group count differs")
    for group, request in zip(groups, expected):
        if (group.get("translationGroupId") != request["translationGroupId"]
                or group.get("sourceUnitIds") != request["sourceUnitIds"]):
            raise ValueError("Translation batch changed source identities")
    return groups


def _review_payload(*, manifest_hash: str, draft_hash: str, groups: list[dict[str, Any]],
                    request_by_group: dict[str, dict[str, Any]], model: str, effort: str,
                    terminology: dict[str, Any]) -> dict[str, Any]:
    review_groups = []
    for group in groups:
        request = request_by_group[group["translationGroupId"]]
        review_groups.append({
            "translationGroupId": group["translationGroupId"],
            "sourceUnitIds": group["sourceUnitIds"],
            "contextBefore": request["contextBefore"],
            "targetEnglish": request["targetEnglish"],
            "contextAfter": request["contextAfter"],
            "draftChineseUtterances": group["chineseUtterances"],
            "draftChinese": group["chinese"],
            "draftCoverage": group["coverage"],
        })
    user = {
        "anchorManifestSha256": manifest_hash,
        "draftSha256": draft_hash,
        "seriesTerminology": terminology,
        "groups": review_groups,
        "outputContract": {
            "schemaVersion": contract.REVIEW_SCHEMA,
            "groupsInExactOrder": [{
                "translationGroupId": group["translationGroupId"],
                "sourceUnitIds": group["sourceUnitIds"],
            } for group in groups],
            "groupShape": {
                "translationGroupId": "copy exactly",
                "sourceUnitIds": ["copy exactly"],
                "chineseUtterances": ["final corrected natural spoken Chinese"],
                "chinese": "exact concatenation of chineseUtterances",
                "coverage": [{"sourceUnitId": "copy exactly", "targetText": "exact substring of final chinese"}],
                "review": {
                    "status": "pass or fail",
                    "sourceUnits": [{
                        "sourceUnitId": "copy exactly",
                        "checks": {name: "pass or fail" for name in contract.CHECKS},
                        "evidence": "specific bilingual findings",
                        "uncertainty": [],
                        "issues": [],
                    }],
                },
            },
            "issues": [],
        },
    }
    return {
        "model": model,
        "reasoning_effort": effort,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": contract.REVIEW_SYSTEM_PROMPT + "\n" + terminology["rules"]},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
    }


def _checked_review_batch(result: dict[str, Any], expected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if result.get("schemaVersion") != contract.REVIEW_SCHEMA or result.get("issues") != []:
        raise ValueError("Review batch returned the wrong schema or unresolved global issues")
    groups = result.get("groups")
    if not isinstance(groups, list) or len(groups) != len(expected):
        raise ValueError("Review batch group count differs")
    for group, source in zip(groups, expected):
        source_ids = source["sourceUnitIds"]
        if (group.get("translationGroupId") != source["translationGroupId"]
                or group.get("sourceUnitIds") != source_ids):
            raise ValueError("Review batch changed source identities")
        review = group.get("review")
        rows = review.get("sourceUnits") if isinstance(review, dict) else None
        if (not isinstance(review, dict) or review.get("status") not in {"pass", "fail"}
                or not isinstance(rows, list)
                or [row.get("sourceUnitId") for row in rows] != source_ids):
            raise ValueError("Review batch returned an invalid source-unit ledger")
        for row in rows:
            checks = row.get("checks")
            if (not isinstance(checks, dict)
                    or set(checks) != set(contract.CHECKS)
                    or any(value not in {"pass", "fail"} for value in checks.values())
                    or not isinstance(row.get("evidence"), str) or not row["evidence"].strip()
                    or not isinstance(row.get("uncertainty"), list)
                    or not isinstance(row.get("issues"), list)):
                raise ValueError("Review batch returned invalid checks or evidence")
    return groups


def run(*, manifest_path: Path, out: Path, model: str, effort: str,
        batch_size: int, workers: int, api_key: str,
        caller: Callable[..., dict[str, Any]] = chat_json) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not contract.is_supported_anchor_manifest(manifest) or manifest.get("issues") != []:
        raise ValueError("Model run requires a clean sentence anchor manifest")
    manifest_hash = contract.json_sha256(manifest)
    requests = manifest.get("translationRequests")
    if not isinstance(requests, list) or len(requests) != len(manifest["sourceUnits"]):
        raise ValueError("Anchor translation requests are incomplete")
    if workers < 1:
        raise ValueError("workers must be positive")
    terminology = series_terminology.context()
    out.mkdir(parents=True, exist_ok=True)

    translation_batches = batches(requests, batch_size)
    def translate_one(item: tuple[int, list[dict[str, Any]]]):
        index, batch = item
        payload = _translation_payload(
            manifest_hash=manifest_hash, request_batch=batch, model=model, effort=effort,
            terminology=terminology,
        )
        result, receipt = cached_call(
            out=out, stage=f"translate-{index:03d}", payload=payload, api_key=api_key,
            requested_model=model, caller=caller,
        )
        return index, _checked_translation_batch(result, batch), receipt

    translated = []
    translation_receipts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(translate_one, item) for item in enumerate(translation_batches)]
        for completed, future in enumerate(futures, start=1):
            index, groups, receipt = future.result()
            translated.append((index, groups))
            translation_receipts.append((index, receipt))
            print(f"translated sentence batches {completed}/{len(futures)}", flush=True)
    translated_groups = [group for _, groups in sorted(translated) for group in groups]
    draft = {
        "schemaVersion": contract.DRAFT_SCHEMA,
        "anchorManifestSha256": manifest_hash,
        "translator": {
            "model": model,
            "reasoningEffort": effort,
            "promptVersion": contract.PROMPT_VERSION,
            "batchReceipts": [receipt for _, receipt in sorted(translation_receipts)],
        },
        "seriesTerminologySha256": terminology["sha256"],
        "groups": translated_groups,
        "issues": [],
    }
    contract._checked_draft_groups(manifest, draft)
    contract.write_json(out / "translation-draft.json", draft)
    draft_hash = contract.json_sha256(draft)

    request_by_group = {item["translationGroupId"]: item for item in requests}
    review_batches = batches(translated_groups, batch_size)
    def review_one(item: tuple[int, list[dict[str, Any]]]):
        index, batch = item
        payload = _review_payload(
            manifest_hash=manifest_hash, draft_hash=draft_hash, groups=batch,
            request_by_group=request_by_group, model=model, effort=effort, terminology=terminology,
        )
        result, receipt = cached_call(
            out=out, stage=f"review-{index:03d}", payload=payload, api_key=api_key,
            requested_model=model, caller=caller,
        )
        return index, _checked_review_batch(result, batch), receipt

    reviewed = []
    review_receipts = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(review_one, item) for item in enumerate(review_batches)]
        for completed, future in enumerate(futures, start=1):
            index, groups, receipt = future.result()
            reviewed.append((index, groups))
            review_receipts.append((index, receipt))
            print(f"reviewed sentence batches {completed}/{len(futures)}", flush=True)
    reviewed_groups = [group for _, groups in sorted(reviewed) for group in groups]
    contract._checked_draft_groups(manifest, {"groups": reviewed_groups})

    review = {
        "schemaVersion": contract.REVIEW_SCHEMA,
        "anchorManifestSha256": manifest_hash,
        "draftSha256": draft_hash,
        "reviewer": {
            "model": model,
            "reasoningEffort": effort,
            "promptVersion": contract.REVIEW_PROMPT_VERSION,
            "batchReceipts": [receipt for _, receipt in sorted(review_receipts)],
        },
        "groups": reviewed_groups,
        "issues": [],
    }
    contract.write_json(out / "independent-review.json", review)
    semantic_review_issues: list[dict[str, Any]] = []
    semantic_pass_count = 0
    for group in reviewed_groups:
        if contract._review_pass(group, group["sourceUnitIds"], semantic_review_issues):
            semantic_pass_count += len(group["sourceUnitIds"])
    all_semantic_pass = semantic_pass_count == len(manifest["sourceUnits"])
    semantic = {
        "schemaVersion": SEMANTIC_SCHEMA,
        "status": ("model_review_pass_tts_and_human_review_pending" if all_semantic_pass
                   else "model_review_requires_resolution"),
        "releaseEligible": False,
        "anchorManifestSha256": manifest_hash,
        "translationDraftSha256": draft_hash,
        "independentReviewSha256": contract.json_sha256(review),
        "translator": draft["translator"],
        "reviewer": review["reviewer"],
        "seriesTerminologySha256": terminology["sha256"],
        "groups": reviewed_groups,
        "counts": {
            "sourceUnits": len(manifest["sourceUnits"]),
            "translationGroups": len(reviewed_groups),
            "machineSemanticReviewPass": semantic_pass_count,
            "machineSemanticReviewNeedsResolution": len(manifest["sourceUnits"]) - semantic_pass_count,
        },
        "semanticReviewIssues": semantic_review_issues,
        "pending": ["measured_natural_rate_tts", "rolling_lag_validation", "human_bilingual_review", "full_playback_review"],
        "humanApproval": False,
    }
    contract.write_json(out / "semantic-candidate.json", semantic)
    return semantic


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchor-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default="gpt-6-astra")
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--api-key-secret", help="Google Secret Manager resource for OPENAI_API_KEY")
    args = parser.parse_args()
    if args.api_key_secret:
        from backend.cloud import access_secret
        api_key = access_secret(args.api_key_secret)
    else:
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY is not set and --api-key-secret was not provided")
    result = run(
        manifest_path=args.anchor_manifest,
        out=args.out,
        model=args.model,
        effort=args.reasoning_effort,
        batch_size=args.batch_size,
        workers=args.workers,
        api_key=api_key,
    )
    print(json.dumps({
        "status": result["status"],
        "sourceUnits": result["counts"]["sourceUnits"],
        "translationGroups": result["counts"]["translationGroups"],
        "releaseEligible": result["releaseEligible"],
        "out": str((args.out / "semantic-candidate.json").resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "model_review_pass_tts_and_human_review_pending" else 2


if __name__ == "__main__":
    raise SystemExit(main())
