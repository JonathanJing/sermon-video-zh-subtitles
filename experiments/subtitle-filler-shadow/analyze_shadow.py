#!/usr/bin/env python3
"""Score the subtitle filler shadow A/B and build the human review list.

Reads both prompt arms (v3 = production prompt, v4 = production prompt plus the
conditional filler-removal rule), the published production translations, and the
English source. Reports:

- how many qualifying filler tokens each arm emits, using the reading edition's
  patterns (including its lookahead so ``你看到`` and real questions are not counted);
- every token v4 drops but v3 kept, with enough context for a human to judge whether
  it was a filler or carried meaning;
- collateral drift on segments where no filler existed (v3 has none), which is the
  cost side of the rule;
- the subtitle QA proxies (Chinese characters per second and rendered line length).
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

RUNS = {
    "sermon_ZDQwL3K-A44": "artifacts/post-live-runs/2026-08-23/sermon_ZDQwL3K-A44/pipeline",
    "sermon_-BeFX5G2oAw": "artifacts/post-live-runs/2026-08-30/sermon_-BeFX5G2oAw/pipeline",
    "sermon_8JYwTq1xcBE": "artifacts/post-live-runs/2026-09-13/sermon_8JYwTq1xcBE/pipeline",
}
SHADOW_DIR = Path("artifacts/subtitle-filler-shadow")

# Same definitions as scripts/build_sermon_reading_edition_with_openai.py, including the
# lookahead that keeps semantic uses out of the count.
FILLER_PATTERNS = {
    "嗯": re.compile(r"嗯+"),
    "呃": re.compile(r"呃+"),
    "你知道": re.compile(r"你知道(?:吗)?(?=$|[，,。！？!?；;：:\s])"),
    "我是说": re.compile(r"我是说"),
    "好吧": re.compile(r"好吧"),
    "这样说得通吧": re.compile(r"这样说得通吧"),
    "你看": re.compile(r"你看(?=[，：])"),
}
SEMANTIC_GUARD = re.compile(r"(我要你|因为|所以|让|使|教|要|知道吗？|要你知道|明白)")

QUOTE_PAIRS = (("“", "”"), ("「", "」"), ('"', '"'))


def similarity(a: str, b: str) -> float:
    import difflib

    return round(difflib.SequenceMatcher(None, a, b).ratio(), 4)


def fillers_in(text: str) -> list[dict[str, Any]]:
    found = []
    for name, pattern in FILLER_PATTERNS.items():
        for match in pattern.finditer(text):
            start, end = match.span()
            context = text[max(0, start - 18) : min(len(text), end + 18)]
            quoted = any(context.count(left) > context.count(right) for left, right in QUOTE_PAIRS)
            found.append(
                {
                    "term": name,
                    "match": match.group(),
                    "start": start,
                    "context": context,
                    "possiblySemantic": bool(SEMANTIC_GUARD.search(context)),
                    "insideQuote": quoted,
                }
            )
    found.sort(key=lambda row: row["start"])
    return found


def load_published(pipeline: Path) -> dict[int, str]:
    out = {}
    for path in glob.glob(str(pipeline / "translation_segments" / "*.json")):
        data = json.loads(Path(path).read_text())
        out[int(data["id"])] = data.get("zh", "")
    return out


def load_arm(arm: str, run_id: str) -> dict[int, dict[str, Any]]:
    out = {}
    for path in glob.glob(str((REPO_ROOT / SHADOW_DIR / arm / run_id / "seg_*.json"))):
        data = json.loads(Path(path).read_text())
        out[int(data["segmentId"])] = data
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=SHADOW_DIR)
    args = parser.parse_args()
    output_dir = (REPO_ROOT / args.output_dir).resolve()

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for run_id, relative in RUNS.items():
        pipeline = (REPO_ROOT / relative).resolve()
        segments = json.loads((pipeline / "segments_timed_en_corrected.json").read_text())
        published = load_published(pipeline)
        v3 = load_arm("v3", run_id)
        v4 = load_arm("v4", run_id)
        for segment in segments:
            segment_id = segment["id"]
            if segment_id not in v3 or segment_id not in v4:
                missing.append(f"{run_id}#{segment_id}")
                continue
            zh3 = v3[segment_id]["zh"]
            zh4 = v4[segment_id]["zh"]
            zh_pub = published.get(segment_id, "")
            f3, f4 = fillers_in(zh3), fillers_in(zh4)
            counts3 = Counter(item["term"] for item in f3)
            counts4 = Counter(item["term"] for item in f4)
            removed = []
            for term, count in counts3.items():
                for _ in range(max(0, count - counts4.get(term, 0))):
                    removed.append(next(item for item in f3 if item["term"] == term))
            added = []
            for term, count in counts4.items():
                for _ in range(max(0, count - counts3.get(term, 0))):
                    added.append(next(item for item in f4 if item["term"] == term))
            duration = max(0.001, segment["end"] - segment["start"])
            rows.append(
                {
                    "run": run_id,
                    "id": segment_id,
                    "english": segment["text"],
                    "start": segment["start"],
                    "end": segment["end"],
                    "durationSeconds": round(duration, 3),
                    "v3": zh3,
                    "v4": zh4,
                    "published": zh_pub,
                    "similarityV3V4": similarity(zh3, zh4),
                    "similarityV3Published": similarity(zh3, zh_pub) if zh_pub else None,
                    "fillerV3": f3,
                    "fillerV4": f4,
                    "removed": removed,
                    "added": added,
                    "charsV3": len(zh3),
                    "charsV4": len(zh4),
                    "cpsV3": round(len(zh3) / duration, 2),
                    "cpsV4": round(len(zh4) / duration, 2),
                }
            )

    total_v3 = sum(len(row["fillerV3"]) for row in rows)
    total_v4 = sum(len(row["fillerV4"]) for row in rows)
    removals = [row for row in rows if row["removed"]]
    additions = [row for row in rows if row["added"]]
    clean_rows = [row for row in rows if not row["fillerV3"]]
    changed_clean = [row for row in clean_rows if row["similarityV3V4"] < 0.98]
    risky = [
        row
        for row in removals
        for item in row["removed"]
        if item["possiblySemantic"] or item["insideQuote"]
    ]
    cps_violations_v3 = [row for row in rows if row["cpsV3"] > 20]
    cps_violations_v4 = [row for row in rows if row["cpsV4"] > 20]

    summary = {
        "schemaVersion": "subtitle-filler-shadow-v1",
        "generatedAt": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "model": "gpt-6.1-sol",
        "reasoningEffort": "high",
        "runCount": len(RUNS),
        "segmentCount": len(rows),
        "missingSegments": missing,
        "fillerTokens": {"v3": total_v3, "v4": total_v4, "removed": total_v3 - total_v4},
        "segmentsWithFillerV3": sum(1 for row in rows if row["fillerV3"]),
        "segmentsWithFillerV4": sum(1 for row in rows if row["fillerV4"]),
        "segmentsWithRemoval": len(removals),
        "segmentsWithAddition": len(additions),
        "possiblySemanticOrQuotedRemovals": len(risky),
        "cleanSegments": len(clean_rows),
        "cleanSegmentsChangedOver2Percent": len(changed_clean),
        "collateralDrift": {
            "meanSimilarityCleanSegments": round(
                statistics.mean(row["similarityV3V4"] for row in clean_rows), 4
            ) if clean_rows else None,
            "changedIds": [f"{row['run']}#{row['id']}" for row in changed_clean],
        },
        "publishedVsV3Rerun": {
            "meanSimilarity": round(
                statistics.mean(row["similarityV3Published"] for row in rows if row["similarityV3Published"]), 4
            ),
            "identical": sum(1 for row in rows if row["v3"] == row["published"]),
        },
        "qaProxy": {
            "cpsOver20V3": len(cps_violations_v3),
            "cpsOver20V4": len(cps_violations_v4),
            "charactersTotalV3": sum(row["charsV3"] for row in rows),
            "charactersTotalV4": sum(row["charsV4"] for row in rows),
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# 字幕语气词影子 A/B（v3 生产 prompt vs v4 条件删除规则）",
        "",
        f"{len(rows)} 段（3 场证道），模型 `gpt-6.1-sol`、reasoning high，输入与术语表完全相同，只差系统 prompt。",
        "",
        f"- 语气词出现：v3 {total_v3} 处 / v4 {total_v4} 处（净减少 {total_v3 - total_v4}）",
        f"- 发生删除的段：{len(removals)}；新增语气词：{len(additions)}",
        f"- 自动标记「可能语义或有引号」的删除：{len(risky)}",
        f"- 无语气词段的附带漂移（相似度 <0.98）：{len(changed_clean)} / {len(clean_rows)}",
        f"- 与已发布译文对比：v3 重跑与历史译文逐字相同 {summary['publishedVsV3Rerun']['identical']}/{len(rows)}，"
        f"平均相似度 {summary['publishedVsV3Rerun']['meanSimilarity']}",
        f"- QA 代理指标：CPS>20 的段 v3 {len(cps_violations_v3)} / v4 {len(cps_violations_v4)}",
        "",
        "## 需要人工判断的删除",
        "",
    ]
    for row in removals:
        terms = "、".join(f"`{item['match']}`" for item in row["removed"])
        flags = []
        if any(item["possiblySemantic"] for item in row["removed"]):
            flags.append("可能语义")
        if any(item["insideQuote"] for item in row["removed"]):
            flags.append("引语内")
        lines.extend(
            [
                f"### {row['run']} #{row['id']} — {row['start']:g}s–{row['end']:g}s（{terms}{'，' + '、'.join(flags) if flags else ''}）",
                "",
                f"- English: {row['english']}",
                f"- v3: {row['v3']}",
                f"- v4: {row['v4']}",
                f"- published: {row['published'] or '（无）'}",
                "",
            ]
        )
    (output_dir / "review-queue.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
