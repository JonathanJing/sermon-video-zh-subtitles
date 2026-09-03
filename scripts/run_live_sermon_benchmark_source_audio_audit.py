#!/usr/bin/env python3
"""Audit frozen benchmark English caption segments against selected audio clips.

This stage deliberately runs before Terra/Sol reference generation. It keeps the
caption as the draft English reference, records GPT-Transcribe as independent
audio evidence, and sends disagreements to later Sol review instead of silently
overwriting the source.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BENCHMARK_ROOT = Path("data/benchmarks/live-sermon-translation-v1")
DEFAULT_PIPELINE_REPO = REPO_ROOT.with_name("sermon-video-zh-subtitles-ios-design")
DEFAULT_COLLECTOR_ROOT = REPO_ROOT.with_name("account-video-transcript-collector")
SECRET_RE = re.compile(r"(?:sk-|sess-|eyJ)[A-Za-z0-9._-]+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-root", type=Path, default=DEFAULT_BENCHMARK_ROOT)
    parser.add_argument("--pipeline-repo", type=Path, default=DEFAULT_PIPELINE_REPO)
    parser.add_argument("--collector-root", type=Path, default=DEFAULT_COLLECTOR_ROOT)
    parser.add_argument("--api-key-env-file", type=Path)
    parser.add_argument("--sample-rate", type=float, default=0.05)
    parser.add_argument("--padding-ms", type=int, default=750)
    parser.add_argument("--asr-model", default="gpt-transcribe")
    parser.add_argument("--asr-workers", type=int, default=3)
    parser.add_argument("--asr-retries", type=int, default=3)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-billable-asr", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.sample_rate <= 1:
        parser.error("--sample-rate must be between 0 and 1")
    if args.padding_ms < 0:
        parser.error("--padding-ms must be non-negative")
    if args.execute and not args.confirm_billable_asr:
        parser.error("--execute requires --confirm-billable-asr")
    return args


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pipeline_module(pipeline_repo: Path) -> Any:
    path = pipeline_repo / "scripts" / "run_full_sermon_dataset_preparation.py"
    if not path.is_file():
        raise RuntimeError(f"Dataset pipeline is missing: {path}")
    name = "sermon_dataset_pipeline_for_benchmark"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load dataset pipeline: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_risk_reasons(pipeline: Any, segment: dict[str, Any], sample_rate: float) -> list[str]:
    probe = {**segment, "severity": "pass", "categories": [], "potentialAsrIssues": []}
    return pipeline.audio_audit_reasons(probe, sample_rate=sample_rate)


def select_source_segments(pipeline: Any, segments: list[dict[str, Any]], sample_rate: float) -> list[dict[str, Any]]:
    selected = []
    for segment in segments:
        reasons = source_risk_reasons(pipeline, segment, sample_rate)
        if reasons:
            selected.append({**segment, "audioAuditReasons": reasons})
    if not selected and segments:
        fallback = min(segments, key=lambda row: hashlib.sha256(str(row["id"]).encode("utf-8")).hexdigest())
        selected.append({**fallback, "audioAuditReasons": ["deterministic_per_sermon_floor_sample"]})
    return selected


def build_plan(args: argparse.Namespace, manifest: dict[str, Any], pipeline: Any) -> dict[str, Any]:
    benchmark_root = resolve(args.benchmark_root)
    items: list[dict[str, Any]] = []
    total_selected = 0
    total_ms = 0
    for item in manifest["items"]:
        video_id = str(item["videoId"])
        segments = read_jsonl(benchmark_root / "source" / video_id / "segments.en.jsonl")
        selected_segments = select_source_segments(pipeline, segments, args.sample_rate)
        selected = [{"segmentId": row["id"], "reasons": row["audioAuditReasons"]} for row in selected_segments]
        selected_ids = {row["segmentId"] for row in selected}
        selected_ms = sum(
            int(row["endMs"]) - int(row["startMs"])
            for row in segments
            if row["id"] in selected_ids
        )
        total_selected += len(selected)
        total_ms += selected_ms
        items.append({"videoId": video_id, "segmentCount": len(segments), "selected": selected, "selectedMinutes": round(selected_ms / 60000, 3)})
    return {
        "schemaVersion": "live-sermon-benchmark-source-audio-audit-v1",
        "goalId": manifest["goalId"],
        "status": "dry_run_only",
        "asrModel": args.asr_model,
        "sampleRate": args.sample_rate,
        "paddingMs": args.padding_ms,
        "selectedSegmentCount": total_selected,
        "selectedMinutesWithoutPadding": round(total_ms / 60000, 3),
        "projectedAsrCostUsdAt0_0045PerMinute": round(total_ms / 60000 * 0.0045, 2),
        "items": items,
        "generatedAt": utc_now(),
    }


def audit_item(args: argparse.Namespace, manifest_item: dict[str, Any], pipeline: Any, api_key: str, credential_source: str) -> dict[str, Any]:
    benchmark_root = resolve(args.benchmark_root)
    video_id = str(manifest_item["videoId"])
    segments = read_jsonl(benchmark_root / "source" / video_id / "segments.en.jsonl")
    selected = select_source_segments(pipeline, segments, args.sample_rate)
    raw_manifest_path = args.pipeline_repo / "data" / "raw" / "mariners-sermon-captions-v1" / video_id / "manifest.json"
    raw_manifest = read_json(raw_manifest_path)
    tools = pipeline.require_tools(("yt-dlp", "ffmpeg", "ffprobe"))
    work_root = benchmark_root / "work" / "source-audio-audit"
    audio_path, download_status = pipeline.download_audio(
        manifest=raw_manifest,
        audio_dir=work_root / "audio",
        yt_dlp=tools["yt-dlp"],
    )
    profile = pipeline.stable_hash({
        "videoId": video_id,
        "sourceSegmentsSha256": sha256_file(benchmark_root / "source" / video_id / "segments.en.jsonl"),
        "asrModel": args.asr_model,
        "sampleRate": args.sample_rate,
        "paddingMs": args.padding_ms,
        "selected": [{"id": row["id"], "startMs": row["startMs"], "endMs": row["endMs"], "reasons": row["audioAuditReasons"]} for row in selected],
    })
    profile_root = work_root / video_id / "profiles" / profile
    chunks = pipeline.cut_audio_segments(
        video_id=video_id,
        audio_path=audio_path,
        segments=selected,
        clips_dir=profile_root / "clips",
        ffmpeg=tools["ffmpeg"],
        padding_ms=args.padding_ms,
    )
    transcriber = pipeline.load_transcribe_module(args.collector_root)
    results = transcriber.transcribe_chunks(
        chunks,
        transcripts_dir=profile_root / "transcripts",
        api_key=api_key,
        model=args.asr_model,
        language="en",
        languages=(),
        max_workers=args.asr_workers,
        retries=args.asr_retries,
        prompt=pipeline.DEFAULT_ASR_PROMPT,
        keywords=(),
    )
    result_by_index = {int(result.chunk_index): result for result in results}
    evidence_rows: list[dict[str, Any]] = []
    evidence_by_id: dict[str, dict[str, Any]] = {}
    source_audio_sha256 = sha256_file(audio_path)
    for index, (segment, chunk) in enumerate(zip(selected, chunks)):
        result = result_by_index.get(index)
        transcript_path = Path(result.transcript_txt_path) if result is not None else Path()
        transcript = pipeline.compact(transcript_path.read_text(encoding="utf-8")) if result is not None and result.status in {"transcribed", "skipped_existing"} and transcript_path.is_file() else ""
        quality = pipeline.asr_quality(pipeline.compact(segment.get("captionEn") or segment.get("en")), transcript, float(chunk["duration_seconds"]))
        if result is None or result.status == "failed":
            quality = {**quality, "status": "excluded", "fatalIssues": [*quality["fatalIssues"], "transcription_failed"]}
        supported = quality["status"] != "excluded" and float(quality["captionAsrWordSimilarity"]) >= 0.72
        row = {
            "schemaVersion": "live-sermon-benchmark-source-audio-audit-v1",
            "segmentId": segment["id"],
            "audioAuditReasons": segment["audioAuditReasons"],
            "captionEn": pipeline.compact(segment.get("captionEn") or segment.get("en")),
            "gptTranscribeEn": transcript,
            "asrQuality": quality,
            "decision": "audio_evidence_supports_caption" if supported else "requires_sol_source_reconciliation",
            "audioEvidence": {
                "sourceAudioSha256": source_audio_sha256,
                "clipSha256": sha256_file(Path(chunk["chunk_path"])),
                "targetStartMs": int(segment["startMs"]),
                "targetEndMs": int(segment["endMs"]),
                "transcriptionModel": args.asr_model,
                "transcriptArtifactSha256": sha256_file(transcript_path) if transcript_path.is_file() else None,
                "humanListeningCompleted": False,
            },
            "humanApprovalClaimed": False,
        }
        evidence_rows.append(row)
        evidence_by_id[str(segment["id"])] = row
    draft_rows = []
    for segment in segments:
        evidence = evidence_by_id.get(str(segment["id"]))
        draft_rows.append({
            **segment,
            "englishReferenceDraft": pipeline.compact(segment.get("captionEn") or segment.get("en")),
            "englishReferenceStatus": (
                "audio_evidence_supports_caption" if evidence and evidence["decision"] == "audio_evidence_supports_caption"
                else "requires_sol_source_reconciliation" if evidence
                else "not_selected_for_preteacher_audio_audit"
            ),
            "sourceAudioAudit": evidence,
            "humanApprovalClaimed": False,
            "eligibleForTraining": False,
        })
    out_dir = benchmark_root / "reference" / video_id
    write_jsonl(out_dir / "source-audio-audit.jsonl", evidence_rows)
    write_jsonl(out_dir / "segments.en.reference.draft.jsonl", draft_rows)
    decisions = Counter(row["decision"] for row in evidence_rows)
    report = {
        "schemaVersion": "live-sermon-benchmark-source-audio-audit-v1",
        "status": "source_audio_audit_completed",
        "videoId": video_id,
        "totalSegmentCount": len(segments),
        "selectedSegmentCount": len(selected),
        "decisionCounts": dict(sorted(decisions.items())),
        "sourceSegmentsSha256": sha256_file(benchmark_root / "source" / video_id / "segments.en.jsonl"),
        "sourceAudioSha256": source_audio_sha256,
        "audioDownloadStatus": download_status,
        "audioAuditSha256": sha256_file(out_dir / "source-audio-audit.jsonl"),
        "englishReferenceDraftSha256": sha256_file(out_dir / "segments.en.reference.draft.jsonl"),
        "asrModel": args.asr_model,
        "credentialSource": credential_source,
        "apiKeyMaterialIncluded": False,
        "humanApprovalClaimed": False,
        "eligibleForTraining": False,
        "generatedAt": utc_now(),
    }
    write_json(out_dir / "source-audio-audit-report.json", report)
    return report


def main() -> int:
    args = parse_args()
    args.pipeline_repo = resolve(args.pipeline_repo)
    args.collector_root = resolve(args.collector_root)
    pipeline = load_pipeline_module(args.pipeline_repo)
    benchmark_root = resolve(args.benchmark_root)
    manifest = read_json(benchmark_root / "benchmark-manifest.json")
    plan = build_plan(args, manifest, pipeline)
    runs_dir = benchmark_root / "runs" / "source-audio-audit"
    write_json(runs_dir / "latest-plan.json", plan)
    if not args.execute:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    env_file = resolve(args.api_key_env_file) if args.api_key_env_file else args.collector_root / ".env"
    api_key, credential_source = pipeline.load_api_key(env_file)
    reports = []
    for index, item in enumerate(manifest["items"], 1):
        try:
            report = audit_item(args, item, pipeline, api_key, credential_source)
            reports.append({"videoId": item["videoId"], "status": "completed", "report": report})
        except Exception as exc:  # noqa: BLE001 - preserve batch progress and sanitized evidence.
            reports.append({"videoId": item["videoId"], "status": "failed", "error": SECRET_RE.sub("REDACTED", str(exc))[-2000:]})
        print(f"source audio audit progress: {index}/{len(manifest['items'])} video={item['videoId']} status={reports[-1]['status']}", flush=True)
    status_counts = Counter(row["status"] for row in reports)
    batch = {
        **{key: value for key, value in plan.items() if key != "status"},
        "status": "completed" if status_counts.get("failed", 0) == 0 else "completed_with_failures",
        "statusCounts": dict(sorted(status_counts.items())),
        "results": reports,
        "credentialSource": credential_source,
        "apiKeyMaterialIncluded": False,
        "finishedAt": utc_now(),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    write_json(runs_dir / f"batch-{stamp}.json", batch)
    write_json(runs_dir / "latest.json", batch)
    print(json.dumps(batch, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if batch["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
