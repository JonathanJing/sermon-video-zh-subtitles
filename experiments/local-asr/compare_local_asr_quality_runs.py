#!/usr/bin/env python3
"""Compare local ASR runs against one frozen reference manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
NON_SPEECH_CUE_RE = re.compile(
    r"[\[(][^\])]*(?:music|applause|laughter|cheering|silence)[^\])]*[\])]",
    re.IGNORECASE,
)
STANDALONE_NON_SPEECH_CUE_RE = re.compile(
    r"^\s*(?:(?:music|applause|laughter|cheering|silence)[\s.,!?;:/&+_-]*)+$",
    re.IGNORECASE,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_words(text: str) -> list[str]:
    without_cues = NON_SPEECH_CUE_RE.sub(" ", text)
    if STANDALONE_NON_SPEECH_CUE_RE.fullmatch(without_cues):
        return []
    return re.findall(r"[a-z0-9']+", without_cues.casefold())


def contains_term(text: str, term: str) -> bool:
    words = normalize_words(text)
    term_words = normalize_words(term)
    return bool(term_words) and any(
        words[index : index + len(term_words)] == term_words
        for index in range(len(words) - len(term_words) + 1)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    args = parser.parse_args()

    manifest_path = (REPO_ROOT / args.manifest).resolve()
    manifest_sha = sha256_file(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    items = {item["id"]: item for item in manifest["items"]}
    comparisons: list[dict] = []
    prediction_sets: dict[str, dict[str, dict]] = {}
    run_completion_times: list[str] = []

    for run_arg in args.run_dir:
        run_dir = (REPO_ROOT / run_arg).resolve()
        report_path = run_dir / "run-report.json"
        prediction_path = run_dir / "predictions.jsonl"
        report = json.loads(report_path.read_text())
        run_completion_times.append(report["completedAt"])
        if report["manifestSha256"] != manifest_sha:
            raise SystemExit(f"Manifest mismatch: {run_dir}")
        if report["predictionsSha256"] != sha256_file(prediction_path):
            raise SystemExit(f"Predictions hash mismatch: {run_dir}")
        predictions = {
            row["id"]: row
            for row in (json.loads(line) for line in prediction_path.read_text().splitlines())
        }
        if set(predictions) != set(items):
            raise SystemExit(f"Prediction item mismatch: {run_dir}")

        quality = report["quality"]
        completeness = report["successCount"] / report["itemCount"]
        silence_discipline = 1 - (
            quality["silenceHallucinationCount"] / quality["silenceItemCount"]
        )
        score = (
            60 * (1 - quality["wer"])
            + 30 * quality["criticalTermRecall"]
            + 5 * completeness
            + 5 * silence_discipline
        )
        missing_terms = []
        for item_id, item in items.items():
            for term in item.get("criticalTerms", []):
                if not contains_term(predictions[item_id]["transcript"], term):
                    missing_terms.append({"id": item_id, "term": term})
        invalid_items = [
            {
                "id": item_id,
                "referenceText": items[item_id]["referenceText"],
                "transcript": prediction["transcript"],
            }
            for item_id, prediction in predictions.items()
            if not prediction["outputValid"]
        ]
        gate_results = {
            "completeOutput": report["errorCount"] == 0,
            "criticalTermRecallAtLeast95Percent": quality["criticalTermRecall"] >= 0.95,
            "zeroSilenceHallucinations": quality["silenceHallucinationCount"] == 0,
        }
        comparisons.append(
            {
                "modelId": report["modelId"],
                "runDirectory": str(run_dir.relative_to(REPO_ROOT)),
                "runReportSha256": sha256_file(report_path),
                "predictionsSha256": report["predictionsSha256"],
                "modelReviewedQualityScore": round(score, 3),
                "scoreComponents": {
                    "werFidelityPoints": round(60 * (1 - quality["wer"]), 3),
                    "criticalTermPoints": round(30 * quality["criticalTermRecall"], 3),
                    "completeOutputPoints": round(5 * completeness, 3),
                    "silenceDisciplinePoints": round(5 * silence_discipline, 3),
                },
                "wer": quality["wer"],
                "criticalTermRecall": quality["criticalTermRecall"],
                "successCount": report["successCount"],
                "itemCount": report["itemCount"],
                "silenceHallucinationCount": quality["silenceHallucinationCount"],
                "meanRtf": report["rtf"]["mean"],
                "p95Rtf": report["rtf"]["p95"],
                "peakPerInvocationRssGiB": report["peakPerInvocationRssGiB"],
                "gateResults": gate_results,
                "allCurrentOfflineQualityGatesPassed": all(gate_results.values()),
                "missingCriticalTerms": missing_terms,
                "invalidItems": invalid_items,
            }
        )
        prediction_sets[report["modelId"]] = predictions

    comparisons.sort(key=lambda row: row["modelReviewedQualityScore"], reverse=True)
    paired = None
    if len(comparisons) == 2:
        first, second = (row["modelId"] for row in comparisons)
        paired = {first: 0, second: 0, "ties": 0}
        for item_id in items:
            first_errors = prediction_sets[first][item_id]["wordErrorCount"]
            second_errors = prediction_sets[second][item_id]["wordErrorCount"]
            if first_errors < second_errors:
                paired[first] += 1
            elif second_errors < first_errors:
                paired[second] += 1
            else:
                paired["ties"] += 1

    payload = {
        "schemaVersion": "local-asr-model-reviewed-quality-leaderboard-v1",
        "createdAt": max(run_completion_times),
        "referenceTier": manifest.get(
            "referencePolicy", "model_reviewed_reference_not_human_gold"
        ),
        "manifest": str(manifest_path.relative_to(REPO_ROOT)),
        "manifestSha256": manifest_sha,
        "itemCount": len(items),
        "totalAudioMinutes": round(sum(item["durationSeconds"] for item in items.values()) / 60, 3),
        "scoreDefinition": {
            "range": "0_to_100_higher_is_better",
            "werFidelityWeight": 0.60,
            "criticalTermRecallWeight": 0.30,
            "completeOutputWeight": 0.05,
            "silenceDisciplineWeight": 0.05,
            "hardGatesRemainAuthoritative": True,
        },
        "results": comparisons,
        "pairedLowerWordErrorWins": paired,
        "decision": {
            "provisionalOfflineWinner": comparisons[0]["modelId"],
            "productionSelectionAllowed": False,
            "reason": "Human listening confirmation, streaming replay, and MiLMMT co-residency remain pending.",
        },
    }
    output_json = (REPO_ROOT / args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Local ASR model-reviewed quality leaderboard",
        "",
        f"Reference: `{payload['referenceTier']}`; {payload['itemCount']} clips / {payload['totalAudioMinutes']} minutes.",
        "",
        "| Model | MRQS / 100 | WER | Critical-term recall | Valid | Silence hallucinations | Mean RTF | Peak RSS GiB | Gates |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for result in comparisons:
        lines.append(
            "| {modelId} | {modelReviewedQualityScore:.3f} | {wer:.2%} | "
            "{criticalTermRecall:.2%} | {successCount}/{itemCount} | "
            "{silenceHallucinationCount} | {meanRtf:.4f} | {peakPerInvocationRssGiB:.4f} | {gates} |".format(
                gates="PASS" if result["allCurrentOfflineQualityGatesPassed"] else "FAIL",
                **result,
            )
        )
    lines.extend(
        [
            "",
            "MRQS = 60% WER fidelity + 30% critical-term recall + 5% complete output + 5% silence discipline. Hard gates override the scalar score.",
            "",
            "This is a provisional comparison against GPT-Transcribe reference tiers, not human Gold. It cannot authorize production selection until human listening confirmation, streaming replay, and co-residency soak are complete.",
        ]
    )
    output_md = (REPO_ROOT / args.output_md).resolve()
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(lines) + "\n")
    print(json.dumps(payload["decision"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
