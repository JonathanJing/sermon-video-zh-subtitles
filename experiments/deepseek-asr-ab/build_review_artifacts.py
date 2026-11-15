#!/usr/bin/env python3
"""Build the human listening queue and the per-clip transcript diff for the A/B run.

Nothing here scores anything: it turns the frozen predictions and the blind
adjudication records into the short list a human should actually listen to,
because the adjudication is machine listening, not human Gold.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "experiments" / "local-asr") not in sys.path:
    sys.path.append(str(REPO_ROOT / "experiments" / "local-asr"))

from run_local_asr_benchmark import normalize_words  # noqa: E402

MANIFEST = "data/benchmarks/live-sermon-translation-v1/local-asr-gpt-reaudited-reference-v1.json"
RUNS = "artifacts/deepseek-asr-ab/runs"
ADJUDICATIONS = "artifacts/deepseek-asr-ab/adjudication-v2/adjudications.jsonl"
AUDIO = "artifacts/deepseek-asr-ab/audio"
OUTPUT = "artifacts/deepseek-asr-ab"


def load_predictions(arm: str) -> dict[str, dict[str, Any]]:
    path = (REPO_ROOT / RUNS / arm / "predictions.jsonl").resolve()
    return {row["id"]: row for row in (json.loads(line) for line in path.read_text().splitlines() if line.strip())}


def main() -> int:
    items = {
        item["id"]: item
        for item in json.loads((REPO_ROOT / MANIFEST).read_text())["items"]
    }
    deepseek = load_predictions("deepseek-asr")
    openai = load_predictions("openai-gpt-transcribe-nohint")
    adjudications: dict[str, list[dict[str, Any]]] = {}
    for row in (json.loads(line) for line in (REPO_ROOT / ADJUDICATIONS).resolve().read_text().splitlines() if line.strip()):
        adjudications.setdefault(row["id"], []).append(row)

    rows = []
    for item_id, item in items.items():
        ds, oa = deepseek[item_id], openai[item_id]
        verdicts = [row["winnerArm"] for row in adjudications.get(item_id, []) if row["winnerArm"]]
        if len(verdicts) < 2:
            consensus = "incomplete"
        elif len(set(verdicts)) == 1:
            consensus = verdicts[0]
        else:
            consensus = "split"
        rows.append(
            {
                "id": item_id,
                "sourceGroupId": item["id"].split("_gold_")[0],
                "windowSeconds": [
                    item["referenceProvenance"].get("timelineStartSeconds"),
                    item["referenceProvenance"].get("timelineEndSeconds"),
                ],
                "referenceText": item["referenceText"],
                "deepseekText": ds["transcript"],
                "openaiText": oa["transcript"],
                "deepseekWordErrors": ds["wordErrorCount"],
                "openaiWordErrors": oa["wordErrorCount"],
                "deepseekLatencySeconds": ds["latencySeconds"],
                "openaiLatencySeconds": oa["latencySeconds"],
                "adjudicationConsensus": consensus,
                "adjudicationVerdicts": verdicts,
                "judgeReasons": [row["reason"] for row in adjudications.get(item_id, []) if row["reason"]],
                "audioPath": f"{AUDIO}/{item_id}.wav",
            }
        )

    consensus_deepseek = [row for row in rows if row["adjudicationConsensus"] == "deepseek-asr"]
    consensus_openai = [row for row in rows if row["adjudicationConsensus"] == "openai-gpt-transcribe-nohint"]
    splits = [row for row in rows if row["adjudicationConsensus"] == "split"]
    incomplete = [row for row in rows if row["adjudicationConsensus"] == "incomplete"]
    consensus_deepseek.sort(key=lambda row: row["deepseekWordErrors"] - row["openaiWordErrors"], reverse=True)
    consensus_openai.sort(key=lambda row: row["openaiWordErrors"] - row["deepseekWordErrors"], reverse=True)

    def block(row: dict[str, Any]) -> list[str]:
        start, end = row["windowSeconds"]
        return [
            f"### `{row['id']}` — {row['sourceGroupId']} {start:g}s–{end:g}s",
            "",
            f"- audio: `{row['audioPath']}`",
            f"- adjudication: **{row['adjudicationConsensus']}** (per-pass verdicts: {', '.join(row['adjudicationVerdicts']) or 'none'})",
            f"- word errors vs frozen reference: deepseek {row['deepseekWordErrors']} / openai {row['openaiWordErrors']}",
            f"- judge reasons: {' | '.join(reason for reason in row['judgeReasons'][:2]) or 'n/a'}",
            "",
            f"- reference: {row['referenceText'].strip()}",
            f"- deepseek: {row['deepseekText'].strip()}",
            f"- openai: {row['openaiText'].strip()}",
            "",
        ]

    lines = [
        "# Human listening queue — DeepSeek ASR vs OpenAI gpt-transcribe",
        "",
        "The scores in the run report come from machine adjudication. Before either provider is adopted for",
        "production, a human should listen to the clips where the two arms disagree. Each item below is one",
        "30-second block; play the WAV and decide which transcript is faithful to the audio.",
        "",
        f"Clips where the blind judge agreed on deepseek-asr: {len(consensus_deepseek)}",
        f"Clips where the blind judge agreed on openai-gpt-transcribe-nohint: {len(consensus_openai)}",
        f"Clips where the two label orders disagreed: {len(splits)}",
        f"Clips with fewer than two usable judgments: {len(incomplete)}",
        "",
        "## A. DeepSeek wins but the frozen reference says OpenAI is closer (highest value to verify)",
        "",
    ]
    for row in consensus_deepseek[:8]:
        lines.extend(block(row))
    lines.extend(["## B. OpenAI wins and the frozen reference agrees", ""])
    for row in consensus_openai[:4]:
        lines.extend(block(row))
    lines.extend(["## C. Label orders disagreed (unresolved by machine adjudication)", ""])
    for row in splits:
        lines.extend(block(row))
    queue_path = (REPO_ROOT / OUTPUT / "human-review-queue.md").resolve()
    queue_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    diff_lines = [
        "# Per-clip transcript differences — DeepSeek ASR vs OpenAI gpt-transcribe",
        "",
        "All 60 clips. Reference text is GPT-Transcribe derived; the two arms are the freshly run predictions.",
        "",
    ]
    differing = [
        row for row in rows
        if normalize_words(row["deepseekText"]) != normalize_words(row["openaiText"])
    ]
    for row in differing:
        start, end = row["windowSeconds"]
        diff_lines.extend(
            [
                f"## `{row['id']}` — {start:g}s–{end:g}s",
                "",
                f"reference: {row['referenceText'].strip()}",
                "",
                f"deepseek: {row['deepseekText'].strip()}",
                "",
                f"openai: {row['openaiText'].strip()}",
                "",
            ]
        )
    diff_path = (REPO_ROOT / OUTPUT / "transcript-diffs.md").resolve()
    diff_path.write_text("\n".join(diff_lines) + "\n", encoding="utf-8")
    summary = {
        "clipCount": len(rows),
        "differingClipCount": len(differing),
        "identicalClipCount": len(rows) - len(differing),
        "consensusDeepseekWins": [row["id"] for row in consensus_deepseek],
        "consensusOpenAIWins": [row["id"] for row in consensus_openai],
        "consensusSplits": [row["id"] for row in splits],
        "consensusIncomplete": [row["id"] for row in incomplete],
        "humanListeningCompleted": False,
    }
    (REPO_ROOT / OUTPUT / "review-artifacts.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2)[:2000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
