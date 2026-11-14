#!/usr/bin/env python3
"""Summarize the DeepSeek ASR vs OpenAI A/B: frozen-reference scores, paired wins and
blind-adjudication consensus at the clip level.

The frozen-reference numbers reuse exactly the score definition of
experiments/local-asr/compare_local_asr_quality_runs.py:

    MRQS = 60 * (1 - WER) + 30 * critical-term recall + 5 * completeness
           + 5 * silence discipline

The adjudication numbers are the honest head-to-head: each clip has two blind
judgments, one per label order. Both agreeing on an arm is a clip win; different
labels are a split and are not scored for either arm.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "experiments" / "local-asr") not in sys.path:
    sys.path.append(str(REPO_ROOT / "experiments" / "local-asr"))

from run_local_asr_benchmark import (  # noqa: E402
    contains_term,
    normalize_words,
    percentile,
    sha256_file,
)

MANIFEST = "data/benchmarks/live-sermon-translation-v1/local-asr-gpt-reaudited-reference-v1.json"
DEFAULT_RUNS = "artifacts/deepseek-asr-ab/runs"
ADJUDICATION_SETS = [
    # (arm_a, arm_b, rubric, adjudications.jsonl)
    ("deepseek-asr", "openai-gpt-transcribe-nohint", "v1", "artifacts/deepseek-asr-ab/adjudication-v1/adjudications.jsonl"),
    ("deepseek-asr", "openai-gpt-transcribe-nohint", "v2", "artifacts/deepseek-asr-ab/adjudication-v2/adjudications.jsonl"),
    ("deepseek-asr", "openai-gpt-transcribe-hinted", "v2", "artifacts/deepseek-asr-ab/adjudication-vs-hinted-v2/adjudications.jsonl"),
]


def arm_summary(run_dir: Path, items: dict[str, dict[str, Any]]) -> dict[str, Any]:
    report = json.loads((run_dir / "run-report.json").read_text())
    predictions = {
        row["id"]: row
        for row in (
            json.loads(line)
            for line in (run_dir / "predictions.jsonl").read_text().splitlines()
            if line.strip()
        )
    }
    if set(predictions) != set(items):
        raise SystemExit(f"prediction item mismatch: {run_dir}")
    if report["predictionsSha256"] != sha256_file(run_dir / "predictions.jsonl"):
        raise SystemExit(f"predictions hash mismatch: {run_dir}")
    quality = report["quality"]
    completeness = report["successCount"] / report["itemCount"]
    silence_discipline = 1 - quality["silenceHallucinationCount"] / quality["silenceItemCount"]
    mrqs = (
        60 * (1 - quality["wer"])
        + 30 * quality["criticalTermRecall"]
        + 5 * completeness
        + 5 * silence_discipline
    )
    exact_matches = sum(
        1 for item_id, row in predictions.items()
        if normalize_words(row["transcript"]) == normalize_words(items[item_id]["referenceText"])
    )
    per_clip = {item_id: row["wordErrorCount"] for item_id, row in predictions.items()}
    return {
        "arm": report["arm"],
        "provider": report["provider"],
        "modelId": report["modelId"],
        "runDirectory": str(run_dir.relative_to(REPO_ROOT)),
        "runReportSha256": sha256_file(run_dir / "run-report.json"),
        "predictionsSha256": report["predictionsSha256"],
        "mrqs": round(mrqs, 3),
        "scoreComponents": {
            "werFidelityPoints": round(60 * (1 - quality["wer"]), 3),
            "criticalTermPoints": round(30 * quality["criticalTermRecall"], 3),
            "completeOutputPoints": round(5 * completeness, 3),
            "silenceDisciplinePoints": round(5 * silence_discipline, 3),
        },
        "wer": quality["wer"],
        "criticalTermRecall": quality["criticalTermRecall"],
        "validOutputs": report["successCount"],
        "itemCount": report["itemCount"],
        "emptyExpectedSpeechCount": report["emptyExpectedSpeechCount"],
        "silenceHallucinationCount": quality["silenceHallucinationCount"],
        "latencySeconds": report["latencySeconds"],
        "rtf": report["rtf"],
        "totalAudioMinutes": report["totalAudioMinutes"],
        "providerUsage": report["providerUsage"],
        "exactMatchesWithReference": exact_matches,
        "perClipWordErrors": per_clip,
        "gates": {
            "completeOutput": report["errorCount"] == 0
            and report["emptyExpectedSpeechCount"] == 0,
            "criticalTermRecallAtLeast95Percent": quality["criticalTermRecall"] >= 0.95,
            "zeroSilenceHallucinations": quality["silenceHallucinationCount"] == 0,
        },
    }


def clip_consensus(rows_path: Path, arm_a: str, arm_b: str) -> dict[str, Any]:
    rows = [json.loads(line) for line in rows_path.read_text().splitlines() if line.strip()]
    by_item: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_item.setdefault(row["id"], []).append(row)
    decided = {arm_a: [], arm_b: [], "tie": [], "split": [], "incomplete": []}
    for item_id, pair in sorted(by_item.items()):
        winners = [row["winnerArm"] for row in pair if row["winnerArm"]]
        if len(winners) < 2:
            decided["incomplete"].append(item_id)
        elif all(winner == arm_a for winner in winners):
            decided[arm_a].append(item_id)
        elif all(winner == arm_b for winner in winners):
            decided[arm_b].append(item_id)
        elif all(winner == "tie" for winner in winners):
            decided["tie"].append(item_id)
        else:
            decided["split"].append(item_id)
    judgments = [row for row in rows if row["winnerArm"]]
    return {
        "itemCount": len(by_item),
        "judgmentCount": len(rows),
        "successfulJudgments": sum(row["ok"] for row in rows),
        "clipWins": {arm_a: len(decided[arm_a]), arm_b: len(decided[arm_b])},
        "clipTies": len(decided["tie"]),
        "clipSplits": len(decided["split"]),
        "clipIncomplete": len(decided["incomplete"]),
        "clipWinItems": {arm_a: decided[arm_a], arm_b: decided[arm_b]},
        "clipSplitItems": decided["split"],
        "judgmentWins": {
            arm_a: sum(1 for row in judgments if row["winnerArm"] == arm_a),
            arm_b: sum(1 for row in judgments if row["winnerArm"] == arm_b),
            "tie": sum(1 for row in judgments if row["winnerArm"] == "tie"),
        },
        "meanJudgeLatencySeconds": round(statistics.mean(row["latencySeconds"] for row in rows), 3),
    }


def paired_word_errors(arm_a: dict[str, Any], arm_b: dict[str, Any]) -> dict[str, int]:
    wins_a = wins_b = ties = 0
    for item_id, errors in arm_a["perClipWordErrors"].items():
        other = arm_b["perClipWordErrors"][item_id]
        if errors < other:
            wins_a += 1
        elif other < errors:
            wins_b += 1
        else:
            ties += 1
    return {arm_a["arm"]: wins_a, arm_b["arm"]: wins_b, "ties": ties}


def markdown_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=MANIFEST)
    parser.add_argument("--runs-dir", default=DEFAULT_RUNS)
    parser.add_argument("--output-json", default="artifacts/deepseek-asr-ab/leaderboard.json")
    parser.add_argument("--output-md", default="artifacts/deepseek-asr-ab/leaderboard.md")
    args = parser.parse_args()

    manifest_path = (REPO_ROOT / args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text())
    items = {item["id"]: item for item in manifest["items"]}
    runs_dir = (REPO_ROOT / args.runs_dir).resolve()
    arms = [arm_summary(path, items) for path in sorted(runs_dir.iterdir()) if (path / "run-report.json").exists()]
    arms.sort(key=lambda row: row["mrqs"], reverse=True)
    by_arm = {row["arm"]: row for row in arms}

    adjudications = {}
    for arm_a, arm_b, rubric, rows_path in ADJUDICATION_SETS:
        key = f"{arm_a}|{arm_b}|{rubric}"
        adjudications[key] = {
            "rubric": rubric,
            **clip_consensus((REPO_ROOT / rows_path).resolve(), arm_a, arm_b),
        }

    paired = {
        f"{arm_a}|{arm_b}": paired_word_errors(by_arm[arm_a], by_arm[arm_b])
        for arm_a, arm_b in (
            ("deepseek-asr", "openai-gpt-transcribe-nohint"),
            ("deepseek-asr", "openai-gpt-transcribe-hinted"),
        )
    }
    payload = {
        "schemaVersion": "deepseek-asr-ab-leaderboard-v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "manifest": args.manifest,
        "manifestSha256": sha256_file(manifest_path),
        "referenceTier": manifest.get("referencePolicy"),
        "referenceBias": (
            "Reference texts are GPT-Transcribe derived; exact-match and WER therefore favour the OpenAI arms."
        ),
        "itemCount": len(items),
        "totalAudioMinutes": round(sum(item["durationSeconds"] for item in items.values()) / 60, 3),
        "scoreDefinition": {
            "mrqs": "60 * (1 - WER) + 30 * critical-term recall + 5 * completeness + 5 * silence discipline",
            "hardGatesRemainAuthoritative": True,
        },
        "arms": arms,
        "pairedWordErrorWins": paired,
        "adjudications": adjudications,
        "humanListeningCompleted": False,
        "productionSelectionAllowed": False,
    }
    output_json = (REPO_ROOT / args.output_json).resolve()
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    lines = ["# DeepSeek ASR vs OpenAI gpt-transcribe — frozen 60-clip ASR set", ""]
    lines.append(
        f"{len(items)} clips / {payload['totalAudioMinutes']} minutes of English church-service audio, "
        f"reference tier `{manifest.get('referencePolicy')}`."
    )
    lines.append("")
    lines.extend(
        markdown_table(
            ["Arm", "MRQS / 100", "WER", "Term recall", "Valid", "Mrqs gates", "Exact vs ref", "Latency p50", "Cost USD"],
            [
                [
                    arm["arm"],
                    f"{arm['mrqs']:.3f}",
                    f"{arm['wer']:.2%}",
                    f"{arm['criticalTermRecall']:.2%}",
                    f"{arm['validOutputs']}/{arm['itemCount']}",
                    "PASS" if all(arm["gates"].values()) else "FAIL",
                    f"{arm['exactMatchesWithReference']}/{arm['itemCount']}",
                    f"{arm['latencySeconds']['p50']:.2f}s",
                    f"{arm['providerUsage']['estimatedCostUsd']:.4f}",
                ]
                for arm in arms
            ],
        )
    )
    lines.extend(["", "## Blind adjudication (independent audio model)", ""])
    lines.extend(
        markdown_table(
            ["Pair", "Rubric", "Clip wins A", "Clip wins B", "Ties", "Splits", "Failed judgments", "Judgment wins A/B/tie"],
            [
                [
                    " vs ".join(key.split("|")[:2]),
                    value["rubric"],
                    str(value["clipWins"][key.split("|")[0]]),
                    str(value["clipWins"][key.split("|")[1]]),
                    str(value["clipTies"]),
                    str(value["clipSplits"]),
                    str(value["clipIncomplete"]),
                    f"{value['judgmentWins'][key.split('|')[0]]}/{value['judgmentWins'][key.split('|')[1]]}/{value['judgmentWins']['tie']}",
                ]
                for key, value in adjudications.items()
            ],
        )
    )
    lines.extend(["", "## Paired word-error wins (same clip, fewer errors wins)", ""])
    lines.extend(
        markdown_table(
            ["Pair", "A better", "B better", "Equal"],
            [
                [key.replace("|", " vs "), str(value[key.split("|")[0]]), str(value[key.split("|")[1]]), str(value["ties"])]
                for key, value in paired.items()
            ],
        )
    )
    lines.extend(
        [
            "",
            "Reference-derived numbers favour the OpenAI arms because the reference was produced by GPT-Transcribe; "
            "the exact-match column shows that self-consistency. The blind adjudication is rubric-sensitive: rubric v1 "
            "rewarded preserved filler and repeated words, rubric v2 scores only meaning-bearing errors. "
            "Neither is human Gold; the per-clip queue is what a human must decide.",
        ]
    )
    output_md = (REPO_ROOT / args.output_md).resolve()
    output_md.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
