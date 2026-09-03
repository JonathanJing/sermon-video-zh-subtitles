#!/usr/bin/env python3
"""Export a readable, hash-audited POC pack for real human confirmation."""

from __future__ import annotations

import argparse
from collections import Counter
import html
import json
from pathlib import Path
import shutil
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402
from scripts import export_sermon_parallel_review_bundle as review_export  # noqa: E402
from scripts import verify_sermon_parallel_corpus_poc as poc_verify  # noqa: E402


PACK_SCHEMA_VERSION = "sermon-human-confirmation-pack-v1"


def timestamp(milliseconds: int) -> str:
    total = max(0, int(milliseconds)) // 1000
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def preformatted(value: str) -> str:
    return f"<pre>{html.escape(str(value), quote=False)}</pre>"


def render_segment(index: int, item: dict[str, Any]) -> str:
    review_export.validate_review_item(item)
    source = item["source"]
    candidate = item["candidate"]
    start_seconds = max(0, int(source["startMs"]) // 1000 - 4)
    youtube = (
        f"https://www.youtube.com/watch?v={item['sermonId']}&t={start_seconds}s"
    )
    issues = ", ".join(f"`{value}`" for value in item["issues"])
    scripture = json.dumps(
        candidate.get("scriptureAlignments") or [],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    proper_nouns = json.dumps(
        candidate.get("properNouns") or [],
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    notes = "\n".join(f"- {value}" for value in candidate.get("modelNotes") or [])
    return "\n".join(
        [
            f"## {index}. `{item['reviewItemId']}`",
            "",
            f"- 优先级：`{item['priority']}`",
            f"- 时间：{timestamp(source['startMs'])} – {timestamp(source['endMs'])}",
            f"- [从源视频对应时间播放]({youtube})",
            f"- 风险：{issues}",
            f"- Review payload SHA-256：`{item['reviewPayloadSha256']}`",
            "",
            "### 原始英文自动字幕（不可覆盖）",
            "",
            preformatted(source["english"]),
            "",
            "### 当前中文候选（尚未人工批准）",
            "",
            preformatted(candidate["chinese"]),
            "",
            "### 经文对齐候选",
            "",
            "```json",
            scripture,
            "```",
            "",
            "### 专名候选",
            "",
            "```json",
            proper_nouns,
            "```",
            "",
            "### 模型备注",
            "",
            notes or "- 无",
            "",
            "### 人工核对清单",
            "",
            "- [ ] 已听对应源音频，而非只读字幕",
            "- [ ] 英文选择 keep 或 corrected；修订写入决定文件，不改原始字幕",
            "- [ ] 中文选择 keep 或 corrected；没有加入当前英文不支持的信息",
            "- [ ] 经文引用与中英表达已核对",
            "- [ ] 人名、地名、机构和神学术语已核对",
            "- [ ] 数字、否定、条件、因果与对象已核对",
            "- [ ] material error 类型已记录",
            "- [ ] 最终决定为 approved / changes_required / rejected",
            "",
            "人工备注：",
            "",
            "---",
            "",
        ]
    )


def render_sermon_book(video_id: str, items: list[dict[str, Any]]) -> str:
    priorities = Counter(str(item["priority"]) for item in items)
    header = [
        f"# `{video_id}` 英中内容人工确认",
        "",
        "状态：模型候选，只供人工审核；本文件本身不是决定记录。",
        "",
        f"条目：{len(items)}；high：{priorities.get('high', 0)}；normal：{priorities.get('normal', 0)}。",
        "",
        "请先完成同一视频的 sermon-only 边界音频批准。正式决定应通过本机审核工具保存，不能直接在此 Markdown 中打勾后宣称 Gold。",
        "",
    ]
    return "\n".join(
        [*header, *(render_segment(index, item) for index, item in enumerate(items, 1))]
    )


def copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def receipts_for(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        rows.append(
            {
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": corpus.sha256_file(path),
            }
        )
    return rows


def verify_receipts(root: Path, receipts: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for receipt in receipts:
        path = root / str(receipt["path"])
        if not path.is_file():
            failures.append(f"missing:{receipt['path']}")
        elif corpus.sha256_file(path) != receipt["sha256"]:
            failures.append(f"hash:{receipt['path']}")
        elif path.stat().st_size != receipt["bytes"]:
            failures.append(f"bytes:{receipt['path']}")
    return failures


def render_readme(*, total: int, high: int, normal: int) -> str:
    return "\n".join(
        [
            "# Mariners 三篇 POC 人工确认包",
            "",
            "状态：`requires_human_confirmation`；任何 AI Agent 预审都不等于人工批准。",
            "",
            "## 先看这里",
            "",
            "本包包含两类作业：",
            "",
            "1. `01-boundary-review/`：先听六个边界时间点，完成三篇 sermon-only 起止决定。",
            f"2. `02-translation-review/`：边界批准并重新生成后，再逐条确认约 {total} 条英中内容；当前 high {high}、normal {normal}。",
            "",
            "`translator-agent-notes.zh.md` 和 `reviewer-agent-audit.zh.md` 是 AI 预审意见，只帮助定位问题。不要把它们复制为人工决定。",
            "",
            "## 当前不能做的事",
            "",
            "- 不能把模板当作已经批准的决定。",
            "- 不能修改原始英文字幕或 review item。",
            "- 不能将当前条目标为 Silver、Gold 或训练可用。",
            "- 不能因为 Agent 认为译文正确而跳过源音频审核。",
            "",
            "## 正式保存位置",
            "",
            "本文件夹是查看副本。正式 hash-bound 决定仍应回写项目中的审核目录，并运行 verifier。iCloud 副本中的勾选或文字修改不会自动进入数据集。",
            "",
            "项目中的边界决定文件：",
            "",
            "```text",
            "data/derived/sermon-boundary-operator-review-v2/<videoId>/operator-decision.json",
            "```",
            "",
            "边界批准并重新导出后，内容审核使用：",
            "",
            "```bash",
            "uv run --with-requirements requirements.txt python scripts/serve_sermon_parallel_review.py --open",
            "```",
            "",
            "## 证据",
            "",
            "`03-evidence/` 保存边界、审核包和质量目录的独立校验报告；`manifest.json` 保存本包每个文件的 SHA-256。",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review-root",
        type=Path,
        default=Path("data/derived/sermon-parallel-review-poc-v1"),
    )
    parser.add_argument(
        "--boundary-root",
        type=Path,
        default=Path("data/derived/sermon-boundary-operator-review-v2"),
    )
    parser.add_argument(
        "--out-root",
        type=Path,
        default=Path("data/derived/sermon-human-confirmation-export-v1"),
    )
    args = parser.parse_args()
    args.review_root = corpus.resolve_path(args.review_root)
    args.boundary_root = corpus.resolve_path(args.boundary_root)
    args.out_root = corpus.resolve_path(args.out_root)
    return args


def main() -> int:
    args = parse_args()
    review_path = args.review_root / "review-items.all.jsonl"
    items = corpus.read_jsonl(review_path)
    if len(items) != 117 or len({item["reviewItemId"] for item in items}) != 117:
        raise RuntimeError("Expected the frozen 117-item POC review bundle")
    for item in items:
        review_export.validate_review_item(item)
    video_ids = list(dict.fromkeys(str(item["sermonId"]) for item in items))
    if len(video_ids) != 3:
        raise RuntimeError("Expected exactly three POC sermons")

    priorities = Counter(str(item["priority"]) for item in items)
    args.out_root.mkdir(parents=True, exist_ok=True)
    (args.out_root / "README-FIRST.zh.md").write_text(
        render_readme(
            total=len(items),
            high=priorities.get("high", 0),
            normal=priorities.get("normal", 0),
        ),
        encoding="utf-8",
    )

    boundary_out = args.out_root / "01-boundary-review"
    copy_file(args.boundary_root / "README.zh.md", boundary_out / "README.zh.md")
    for video_id in video_ids:
        source_dir = args.boundary_root / video_id
        for name in (
            "review.zh.md",
            "review-packet.json",
            "operator-decision.template.json",
        ):
            copy_file(source_dir / name, boundary_out / video_id / name)

    translation_out = args.out_root / "02-translation-review"
    translation_out.mkdir(parents=True, exist_ok=True)
    for video_id in video_ids:
        sermon_items = [item for item in items if item["sermonId"] == video_id]
        (translation_out / f"{video_id}-人工确认.zh.md").write_text(
            render_sermon_book(video_id, sermon_items), encoding="utf-8"
        )
        copy_file(
            args.review_root / video_id / "review-items.jsonl",
            translation_out / "machine-readable" / video_id / "review-items.jsonl",
        )
        copy_file(
            args.review_root / video_id / "human-decisions.template.jsonl",
            translation_out
            / "machine-readable"
            / video_id
            / "human-decisions.template.jsonl",
        )
    copy_file(
        review_path,
        translation_out / "machine-readable" / "review-items.all.jsonl",
    )
    copy_file(
        args.review_root / "human-decisions.template.all.jsonl",
        translation_out / "machine-readable" / "human-decisions.template.all.jsonl",
    )

    evidence_out = args.out_root / "03-evidence"
    evidence_sources = {
        "boundary-review-v2-verification.json": REPO_ROOT
        / "data/reports/sermon-parallel-corpus-poc/boundary-review-v2-verification.json",
        "review-bundle-verification.json": REPO_ROOT
        / "data/reports/sermon-parallel-review-poc-v1/final-verification.json",
        "quality-catalog-verification.json": REPO_ROOT
        / "data/reports/sermon-parallel-quality-catalog-poc-v1/final-verification.json",
        "review-tool-check.json": REPO_ROOT
        / "data/reports/sermon-parallel-review-poc-v1/review-tool-check.json",
    }
    for name, source in evidence_sources.items():
        copy_file(source, evidence_out / name)

    receipts = receipts_for(args.out_root)
    secret_findings = poc_verify.scan_secret_markers(args.out_root)
    receipt_failures = verify_receipts(args.out_root, receipts)
    manifest = {
        "schemaVersion": PACK_SCHEMA_VERSION,
        "status": (
            "human_confirmation_pack_ready_requires_human"
            if not receipt_failures and not secret_findings
            else "failed"
        ),
        "generatedAt": corpus.utc_now(),
        "sourceReviewItemsSha256": corpus.sha256_file(review_path),
        "counts": {
            "sermons": len(video_ids),
            "segments": len(items),
            "high": priorities.get("high", 0),
            "normal": priorities.get("normal", 0),
            "humanBoundaryApprovals": 0,
            "humanContentDecisions": 0,
            "silver": 0,
            "gold": 0,
        },
        "videoIds": video_ids,
        "files": receipts,
        "receiptFailures": receipt_failures,
        "trainingEligibility": "blocked",
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "secretFindings": secret_findings,
    }
    corpus.write_json(args.out_root / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "human_confirmation_pack_ready_requires_human" else 2


if __name__ == "__main__":
    raise SystemExit(main())
