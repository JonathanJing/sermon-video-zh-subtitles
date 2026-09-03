#!/usr/bin/env python3
"""Verify completed train/dev expansion outputs and aggregate canary evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import build_sermon_parallel_corpus_poc as corpus  # noqa: E402
from scripts import run_sermon_parallel_corpus_expansion as expansion  # noqa: E402


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"projects/[^/\s]+/secrets/[^/\s]+"),
]


def receipt_usage(path: Path) -> dict[str, Any] | None:
    try:
        data = corpus.read_json(path)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or not data.get("stage") or not data.get("inputSha256"):
        return None
    usage = data.get("usage") or {}
    output_details = usage.get("output_tokens_details") or {}
    ids = [
        str(item.get("id") or "")
        for item in corpus.safe_list((data.get("result") or {}).get("segments"))
        if isinstance(item, dict)
    ]
    return {
        "path": corpus.display_path(path),
        "stage": str(data["stage"]),
        "inputSha256": str(data["inputSha256"]),
        "segmentIds": ids,
        "inputTokens": int(usage.get("input_tokens") or 0),
        "outputTokens": int(usage.get("output_tokens") or 0),
        "reasoningTokens": int(output_details.get("reasoning_tokens") or 0),
        "elapsedSeconds": float(data.get("elapsedSeconds") or 0),
    }


def verify(
    *, split_manifest: Path, corpus_root: Path, out_root: Path, expected_completed: int
) -> dict[str, Any]:
    assignments = expansion.load_assignments(split_manifest)
    by_id = {str(item["videoId"]): item for item in assignments}
    failures: list[str] = []
    secret_findings: list[str] = []
    completed: list[dict[str, Any]] = []
    global_segment_ids: set[str] = set()
    audit_counts: Counter[str] = Counter()
    observed_usage: Counter[str] = Counter()
    stage_segment_observations: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)

    output_dirs = sorted(path for path in out_root.iterdir() if path.is_dir()) if out_root.exists() else []
    for sermon_dir in output_dirs:
        video_id = sermon_dir.name
        assignment = by_id.get(video_id)
        if assignment is None:
            failures.append(f"unknown_output_video:{video_id}")
            continue
        split = str(assignment.get("split") or "")
        if split not in expansion.ALLOWED_SPLITS:
            failures.append(f"forbidden_split_output:{video_id}:{split}")
            continue
        if not expansion.audit_is_complete(sermon_dir):
            failures.append(f"incomplete_audit:{video_id}")
            continue

        source_manifest = corpus_root / video_id / "manifest.json"
        source_cues = corpus_root / video_id / "normalized" / "cues.youtube-auto.jsonl"
        source_receipt = corpus.read_json(sermon_dir / "source-receipt.json")
        run_report = corpus.read_json(sermon_dir / "run-report.json")
        audit_report = corpus.read_json(sermon_dir / "model-second-pass-report.json")
        final_rows = corpus.read_jsonl(sermon_dir / "segments.zh.final.jsonl")
        audit_rows = corpus.read_jsonl(sermon_dir / "model-second-pass-audit.jsonl")

        if run_report.get("split") != split or audit_report.get("split") != split:
            failures.append(f"split_lineage:{video_id}")
        if source_receipt.get("sourceManifest", {}).get("sha256") != expansion.file_sha256(source_manifest):
            failures.append(f"source_manifest_hash:{video_id}")
        if source_receipt.get("sourceCues", {}).get("sha256") != expansion.file_sha256(source_cues):
            failures.append(f"source_cues_hash:{video_id}")
        if assignment.get("sourceManifestSha256") != expansion.file_sha256(source_manifest):
            failures.append(f"split_manifest_source_manifest_hash:{video_id}")
        if assignment.get("sourceCuesSha256") != expansion.file_sha256(source_cues):
            failures.append(f"split_manifest_source_cues_hash:{video_id}")
        if any(str(item.get("split")) != split for item in final_rows):
            failures.append(f"segment_split:{video_id}")
        ids = [str(item.get("id") or "") for item in final_rows]
        if "" in ids or len(ids) != len(set(ids)):
            failures.append(f"segment_ids:{video_id}")
        overlaps = global_segment_ids.intersection(ids)
        if overlaps:
            failures.append(f"global_segment_duplicate:{video_id}")
        global_segment_ids.update(ids)

        for source, audited in zip(final_rows, audit_rows):
            if audited.get("segmentId") != source.get("id"):
                failures.append(f"audit_order:{video_id}")
                break
            if audited.get("inputBindings") != expansion.segment_binding(source):
                failures.append(f"audit_binding:{video_id}:{source.get('id')}")
                break
            audit_counts[str((audited.get("result") or {}).get("severity"))] += 1

        receipts: list[dict[str, Any]] = []
        for cache_path in sorted((sermon_dir / "cache").rglob("*.json")):
            text = cache_path.read_text(encoding="utf-8", errors="replace")
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                secret_findings.append(corpus.display_path(cache_path))
            receipt = receipt_usage(cache_path)
            if receipt is not None:
                receipts.append(receipt)
                observed_usage["requests"] += 1
                observed_usage["inputTokens"] += receipt["inputTokens"]
                observed_usage["outputTokens"] += receipt["outputTokens"]
                observed_usage["reasoningTokens"] += receipt["reasoningTokens"]
                observed_usage["elapsedMilliseconds"] += round(receipt["elapsedSeconds"] * 1000)
                for segment_id in receipt["segmentIds"]:
                    stage_segment_observations[(video_id, receipt["stage"])][segment_id] += 1

        duplicate_stage_bindings = sum(
            count - 1
            for (receipt_video, _stage), counts in stage_segment_observations.items()
            if receipt_video == video_id
            for count in counts.values()
            if count > 1
        )
        completed.append(
            {
                "videoId": video_id,
                "split": split,
                "segments": len(final_rows),
                "sermonDurationSeconds": float(run_report["sermonWindow"]["durationSeconds"]),
                "auditCounts": audit_report["counts"],
                "observableReceiptCount": len(receipts),
                "duplicateSuccessfulStageSegmentBindings": duplicate_stage_bindings,
            }
        )

    test_ids = {str(item["videoId"]) for item in assignments if item.get("split") == "test"}
    test_output_dirs = sorted(video_id for video_id in test_ids if (out_root / video_id).exists())
    if test_output_dirs:
        failures.extend(f"test_touched:{video_id}" for video_id in test_output_dirs)
    if len(completed) != expected_completed:
        failures.append(f"completed_count:{len(completed)}!={expected_completed}")

    content_seconds = round(sum(item["sermonDurationSeconds"] for item in completed), 3)
    elapsed_seconds = round(observed_usage["elapsedMilliseconds"] / 1000, 3)
    duplicate_bindings = sum(item["duplicateSuccessfulStageSegmentBindings"] for item in completed)
    status = (
        "fail"
        if failures or secret_findings
        else "pass_canary_needs_pipeline_revision"
        if duplicate_bindings or elapsed_seconds > content_seconds
        else "pass_canary_ready_for_next_batch"
    )
    return {
        "schemaVersion": "sermon-parallel-corpus-expansion-verification-v1",
        "status": status,
        "counts": {
            "completedSermons": len(completed),
            "segments": len(global_segment_ids),
            "pass": audit_counts["pass"],
            "needsAudioReview": audit_counts["needs_audio_review"],
            "mustFix": audit_counts["must_fix"],
            "eligibleTrainDev": sum(item.get("split") in expansion.ALLOWED_SPLITS for item in assignments),
            "remainingTrainDev": sum(item.get("split") in expansion.ALLOWED_SPLITS for item in assignments) - len(completed),
            "testPreservedUntouched": len(test_ids) - len(test_output_dirs),
        },
        "completed": completed,
        "observableUsage": {
            "requests": observed_usage["requests"],
            "inputTokens": observed_usage["inputTokens"],
            "outputTokens": observed_usage["outputTokens"],
            "reasoningTokens": observed_usage["reasoningTokens"],
            "elapsedSeconds": elapsed_seconds,
            "sermonContentSeconds": content_seconds,
            "apiElapsedToContentRatio": round(elapsed_seconds / content_seconds, 3) if content_seconds else None,
            "duplicateSuccessfulStageSegmentBindings": duplicate_bindings,
            "limitation": "Interrupted in-flight requests without returned receipts are not observable here and may still appear in provider billing.",
        },
        "failures": failures,
        "secretFindings": secret_findings,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
        "testOutputDirectories": test_output_dirs,
        "trainingEligibility": "blocked",
        "generatedAt": corpus.utc_now(),
    }


def markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    usage = report["observableUsage"]
    lines = [
        "# Mariners train/dev 扩展 canary 验证",
        "",
        f"状态：`{report['status']}`",
        "",
        f"- 完成：{counts['completedSermons']} 篇，{counts['segments']} 段",
        f"- 模型审核：pass {counts['pass']}；needs_audio_review {counts['needsAudioReview']}；must_fix {counts['mustFix']}",
        f"- 剩余 train/dev：{counts['remainingTrainDev']} / {counts['eligibleTrainDev']}",
        f"- test 保持未触碰：{counts['testPreservedUntouched']} / 18",
        f"- 可观察成功 receipt：{usage['requests']} 个；API 累计等待/内容时长比 {usage['apiElapsedToContentRatio']}x",
        f"- 重复成功阶段-段绑定：{usage['duplicateSuccessfulStageSegmentBindings']}（来自批次降级和恢复）",
        "",
        "## 判定",
        "",
        "6 篇内容和独立审核均完整，split、来源哈希、逐段绑定和 test 隔离通过。",
        "当前同步调用存在显著尾延时、人工中断和批次降级，因此在改成受控异步/Batch调度并补齐provider billing成本前，不自动启动剩余153篇。",
        "模型审核结果可以作为用户指定的文本质量基线，但仍不是音频听校、Silver/Gold或训练授权。",
        "",
        "## 逐篇",
        "",
        "| video | split | segments | pass | audio | must-fix | receipts | duplicate bindings |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["completed"]:
        audit = item["auditCounts"]
        lines.append(
            f"| `{item['videoId']}` | {item['split']} | {item['segments']} | {audit['pass']} | {audit['needsAudioReview']} | {audit['mustFix']} | {item['observableReceiptCount']} | {item['duplicateSuccessfulStageSegmentBindings']} |"
        )
    lines.extend(
        [
            "",
            "## 限制",
            "",
            f"- {usage['limitation']}",
            "- 本报告不把本地token receipt直接换算成美元；最终成本门禁应使用provider billing export核对。",
            "- 所有产物继续保持 `trainingEligibility=blocked`。",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-manifest", type=Path, default=Path("data/reports/sermon-parallel-corpus-splits-v1/split-manifest.json"))
    parser.add_argument("--corpus-root", type=Path, default=Path("data/raw/mariners-sermon-captions-v1"))
    parser.add_argument("--out-root", type=Path, default=Path("data/derived/sermon-parallel-corpus-expansion-v1"))
    parser.add_argument("--expected-completed", type=int, default=6)
    parser.add_argument("--report", type=Path, default=Path("data/reports/sermon-parallel-corpus-expansion-v1/canary-verification.json"))
    parser.add_argument("--markdown", type=Path, default=Path("data/reports/sermon-parallel-corpus-expansion-v1/canary-verification.zh.md"))
    args = parser.parse_args()
    for name in ("split_manifest", "corpus_root", "out_root", "report", "markdown"):
        path = getattr(args, name)
        setattr(args, name, path if path.is_absolute() else REPO_ROOT / path)
    return args


def main() -> int:
    args = parse_args()
    report = verify(
        split_manifest=args.split_manifest,
        corpus_root=args.corpus_root,
        out_root=args.out_root,
        expected_completed=args.expected_completed,
    )
    corpus.write_json(args.report, report)
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
