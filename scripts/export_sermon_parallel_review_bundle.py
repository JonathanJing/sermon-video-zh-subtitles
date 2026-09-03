#!/usr/bin/env python3
"""Export immutable, hash-bound review items and blank human decision templates."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402


REVIEW_SCHEMA_VERSION = "sermon-parallel-review-v1"
DECISION_SCHEMA_VERSION = "sermon-parallel-human-decision-v1"


def review_payload_sha256(item: dict[str, Any]) -> str:
    payload = dict(item)
    payload.pop("reviewPayloadSha256", None)
    return corpus.stable_json_sha256(payload)


def validate_review_item(item: dict[str, Any]) -> None:
    if item.get("schemaVersion") != REVIEW_SCHEMA_VERSION:
        raise ValueError("Unexpected review item schemaVersion")
    if item.get("reviewPayloadSha256") != review_payload_sha256(item):
        raise ValueError(f"Review payload hash mismatch: {item.get('reviewItemId')}")
    if item.get("reviewItemId") != item.get("segmentId"):
        raise ValueError("reviewItemId must equal the immutable segmentId")
    if item.get("reviewStatus") != "pending_human":
        raise ValueError("Exported review items must remain pending_human")
    if item.get("trainingEligibility") != "blocked":
        raise ValueError("Review export cannot grant training eligibility")
    source = item.get("source") or {}
    if source.get("textSha256") != corpus.sha256_bytes(
        str(source.get("english") or "").encode("utf-8")
    ):
        raise ValueError("English text hash mismatch")
    candidate = item.get("candidate") or {}
    if candidate.get("chineseSha256") != corpus.sha256_bytes(
        str(candidate.get("chinese") or "").encode("utf-8")
    ):
        raise ValueError("Chinese candidate hash mismatch")
    if int(source.get("endMs") or 0) <= int(source.get("startMs") or -1):
        raise ValueError("Review item timeline is invalid")


def decision_template(item: dict[str, Any]) -> dict[str, Any]:
    validate_review_item(item)
    return {
        "schemaVersion": DECISION_SCHEMA_VERSION,
        "reviewItemId": item["reviewItemId"],
        "reviewPayloadSha256": item["reviewPayloadSha256"],
        "status": "pending_human_input",
        "reviewer": "",
        "reviewerRole": "",
        "reviewedAt": "",
        "audioChecked": False,
        "englishDecision": "pending",
        "approvedEnglish": item["source"]["english"],
        "chineseDecision": "pending",
        "approvedChinese": item["candidate"]["chinese"],
        "scriptureChecked": False,
        "properNounsChecked": False,
        "numbersChecked": False,
        "materialErrorTypes": [],
        "adjudicationComplete": False,
        "notes": "",
    }


def model_notes(segment: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    for field in ("reviewNotes", "changeReasons", "riskFlags"):
        for value in corpus.safe_list(segment.get(field)):
            text = corpus.compact_text(value)
            if text:
                notes.append(text)
    for issue in corpus.safe_list(segment.get("potentialAsrIssues")):
        if not isinstance(issue, dict):
            continue
        source = corpus.compact_text(issue.get("sourceSpan"))
        suggestion = corpus.compact_text(issue.get("suggestion"))
        reason = corpus.compact_text(issue.get("reason"))
        text = f"ASR: {source} -> {suggestion} ({reason})".strip()
        if text:
            notes.append(text)
    return list(dict.fromkeys(notes))


def scripture_for_segment(
    segment: dict[str, Any], scripture: dict[str, Any]
) -> list[dict[str, Any]]:
    requested = {corpus.compact_text(value).lower() for value in segment.get("scriptureRefs") or []}
    if not requested:
        return []
    rows = [
        item
        for item in [*(scripture.get("resolved") or []), *(scripture.get("unresolved") or [])]
        if corpus.compact_text(item.get("reference")).lower() in requested
    ]
    return rows


def build_review_item(
    *,
    segment: dict[str, Any],
    queue_item: dict[str, Any],
    source_receipt: dict[str, Any],
    boundary: dict[str, Any],
    scripture: dict[str, Any],
) -> dict[str, Any]:
    queue_issues = [str(value) for value in queue_item.get("issues") or []]
    boolean_flags = [
        name
        for name in (
            "omissionRisk",
            "additionRisk",
            "numberMismatch",
            "scriptureMismatch",
            "properNounRisk",
            "sourceAsrRisk",
            "needsHumanReview",
        )
        if segment.get(name) is True
    ]
    candidate_zh = str(segment["zh"])
    source_en = str(segment["en"])
    item = {
        "schemaVersion": REVIEW_SCHEMA_VERSION,
        "reviewItemId": str(segment["id"]),
        "sermonId": str(segment["sermonId"]),
        "segmentId": str(segment["id"]),
        "split": str(segment["split"]),
        "priority": str(queue_item["priority"]),
        "issues": queue_issues,
        "source": {
            "captionKind": str(segment["sourceCaptionKind"]),
            "reviewStatus": str(segment["sourceReviewStatus"]),
            "manifestSha256": source_receipt["sourceManifest"]["sha256"],
            "cuesSha256": source_receipt["sourceCues"]["sha256"],
            "textSha256": corpus.sha256_bytes(source_en.encode("utf-8")),
            "cueIds": [str(value) for value in segment["cueIds"]],
            "startMs": int(segment["startMs"]),
            "endMs": int(segment["endMs"]),
            "english": source_en,
        },
        "candidate": {
            "chinese": candidate_zh,
            "chineseSha256": corpus.sha256_bytes(candidate_zh.encode("utf-8")),
            "contentType": str(segment["contentType"]),
            "scriptureRefs": [str(value) for value in segment.get("scriptureRefs") or []],
            "scriptureAlignments": scripture_for_segment(segment, scripture),
            "properNouns": [
                {"source": str(value.get("source") or ""), "zh": str(value.get("zh") or "")}
                for value in segment.get("properNouns") or []
                if isinstance(value, dict)
            ],
            "modelFlags": list(dict.fromkeys([*queue_issues, *boolean_flags])),
            "modelNotes": model_notes(segment),
            "teacher": segment["teacher"],
            "modelReviewStatus": str(segment["reviewStatus"]),
        },
        "boundary": {
            "status": str(boundary["status"]),
            "contentScope": str(boundary["contentScope"]),
            "approvedByHuman": boundary.get("approvedByHuman") is True,
            "startCueId": str(boundary["startCueId"]),
            "endCueId": str(boundary["endCueId"]),
            "boundarySha256": corpus.stable_json_sha256(boundary),
        },
        "reviewStatus": "pending_human",
        "trainingEligibility": "blocked",
    }
    item["reviewPayloadSha256"] = review_payload_sha256(item)
    validate_review_item(item)
    return item


def render_guide(items: list[dict[str, Any]]) -> str:
    priorities = Counter(item["priority"] for item in items)
    issues = Counter(value for item in items for value in item["issues"])
    issue_lines = [f"- `{name}`：{count}" for name, count in issues.most_common()]
    return "\n".join(
        [
            "# 证道中英平行语料人工审核包",
            "",
            "状态：`requires_human_review`；模板中预填文本不代表批准。",
            "",
            f"总条目：{len(items)}；high：{priorities.get('high', 0)}；normal：{priorities.get('normal', 0)}。",
            "",
            "## 建议顺序",
            "",
            "1. 先完成 sermon-only 边界音频审批。",
            "2. 先审 high，再审 normal；每条都必须对照相应源音频。",
            "3. 英文若修正，保留原始自动字幕不变，只写入 approvedEnglish。",
            "4. 中文选择 keep 或 corrected；不得从周六稿或邻段补写当前英文没有的内容。",
            "5. 经文、专名、数字三个 check 必须逐项完成；有 material error 时记录类型。",
            "6. 可按每篇 `human-decisions.template.jsonl` 作业；只把已经完成的 final rows 合并到根目录 `human-decisions.jsonl`，不得混入 `pending_human_input`。",
            "7. 切勿编辑 `review-items*.jsonl`；边界或候选改变后必须重新导出，并重新绑定新的 review payload hash。",
            "",
            "## 自动标记计数",
            "",
            *issue_lines,
            "",
            "Gold 需要内容人工批准和对应证道边界人工批准。Silver candidate 只表示自动规则通过；训练资格仍由 rights 和 teacher-use 门禁单独决定。",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--poc-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-corpus-poc-v1"),
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-review-poc-v1"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/reports/sermon-parallel-review-poc-v1/export-summary.json"),
    )
    args = parser.parse_args()
    args.poc_root = corpus.resolve_path(args.poc_root)
    args.out_root = corpus.resolve_path(args.out_root)
    args.report = corpus.resolve_path(args.report)
    return args


def main() -> int:
    args = parse_args()
    selection = corpus.read_json(args.poc_root / "pilot-selection.json")
    video_ids = [str(value) for value in selection.get("videoIds") or []]
    all_items: list[dict[str, Any]] = []
    by_sermon: list[dict[str, Any]] = []
    for video_id in video_ids:
        sermon_dir = args.poc_root / video_id
        segments = corpus.read_jsonl(sermon_dir / "segments.zh.final.jsonl")
        queue = corpus.read_jsonl(sermon_dir / "human-review-queue.jsonl")
        queue_by_id = {str(item["segmentId"]): item for item in queue}
        if set(queue_by_id) != {str(item["id"]) for item in segments}:
            raise RuntimeError(f"Review queue coverage mismatch: {video_id}")
        receipt = corpus.read_json(sermon_dir / "source-receipt.json")
        boundary = corpus.read_json(sermon_dir / "boundary-candidate.json")
        scripture = corpus.read_json(sermon_dir / "scripture-alignments.json")
        items = [
            build_review_item(
                segment=segment,
                queue_item=queue_by_id[str(segment["id"])],
                source_receipt=receipt,
                boundary=boundary,
                scripture=scripture,
            )
            for segment in segments
        ]
        sermon_out = args.out_root / video_id
        corpus.write_jsonl(sermon_out / "review-items.jsonl", items)
        corpus.write_jsonl(
            sermon_out / "human-decisions.template.jsonl",
            [decision_template(item) for item in items],
        )
        (sermon_out / "README.zh.md").write_text(render_guide(items), encoding="utf-8")
        by_sermon.append(
            {
                "videoId": video_id,
                "items": len(items),
                "high": sum(1 for item in items if item["priority"] == "high"),
                "normal": sum(1 for item in items if item["priority"] == "normal"),
                "reviewItemsSha256": corpus.sha256_file(sermon_out / "review-items.jsonl"),
                "decisionTemplateSha256": corpus.sha256_file(
                    sermon_out / "human-decisions.template.jsonl"
                ),
            }
        )
        all_items.extend(items)

    if len({item["reviewItemId"] for item in all_items}) != len(all_items):
        raise RuntimeError("Cross-sermon duplicate review item IDs")
    args.out_root.mkdir(parents=True, exist_ok=True)
    corpus.write_jsonl(args.out_root / "review-items.all.jsonl", all_items)
    corpus.write_jsonl(
        args.out_root / "human-decisions.template.all.jsonl",
        [decision_template(item) for item in all_items],
    )
    (args.out_root / "README.zh.md").write_text(render_guide(all_items), encoding="utf-8")
    issue_counts = Counter(value for item in all_items for value in item["issues"])
    report = {
        "schemaVersion": REVIEW_SCHEMA_VERSION,
        "status": "review_bundle_exported_requires_human",
        "sourcePocRoot": corpus.display_path(args.poc_root),
        "sermons": by_sermon,
        "totals": {
            "sermons": len(video_ids),
            "items": len(all_items),
            "high": sum(1 for item in all_items if item["priority"] == "high"),
            "normal": sum(1 for item in all_items if item["priority"] == "normal"),
            "issueCounts": dict(sorted(issue_counts.items())),
        },
        "reviewItemsAllSha256": corpus.sha256_file(args.out_root / "review-items.all.jsonl"),
        "decisionTemplateAllSha256": corpus.sha256_file(
            args.out_root / "human-decisions.template.all.jsonl"
        ),
        "approvedHumanDecisions": 0,
        "trainingEligibility": "blocked",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "generatedAt": corpus.utc_now(),
    }
    corpus.write_json(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
