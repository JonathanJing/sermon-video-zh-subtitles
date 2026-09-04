#!/usr/bin/env python3
"""Export a guarded Sunday Runtime Pack from an existing Saturday production run."""

from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REPO_ROOT = Path(__file__).resolve().parents[1]
POC_ROOT = REPO_ROOT / "experiments" / "local-live-poc"
SEGMENT_SCHEMA_VERSION = "saturday-sermon-segment-v1"
MANIFEST_SCHEMA_VERSION = "weekly-context-pack-v2"
ALLOWED_MESSAGE_MATCH_STATUSES = {"unknown", "inferred", "human_confirmed", "rejected"}
ALLOWED_AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav", ".webm"}


class ExportError(RuntimeError):
    pass


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ExportError(f"{field} must be YYYY-MM-DD") from error


def _read_json(path: Path, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ExportError(f"unable to read {label} at {path}: {error}") from error


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_relative(path: Path, run_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(run_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _find_source_audio(run_root: Path) -> Path:
    download_dir = run_root / "download"
    candidates = sorted(
        path
        for path in download_dir.glob("source_audio.*")
        if path.is_file() and path.suffix.lower() in ALLOWED_AUDIO_SUFFIXES
    )
    if not candidates:
        raise ExportError(f"no completed source_audio file found under {download_dir}")
    if len(candidates) > 1:
        raise ExportError(
            "multiple completed source_audio files found; pass --source-audio explicitly: "
            + ", ".join(str(path) for path in candidates)
        )
    return candidates[0]


def _normalize_phrase_candidates(values: Iterable[str]) -> list[str]:
    unique: dict[str, str] = {}
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            unique.setdefault(cleaned.casefold(), cleaned)
    return [unique[key] for key in sorted(unique)]


def _segment_id(index: int) -> str:
    return f"seg_{index + 1:06d}"


def _coerce_seconds(value: Any, field: str, segment_id: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ExportError(f"{segment_id} {field} must be numeric") from error
    if number < 0:
        raise ExportError(f"{segment_id} {field} must not be negative")
    return number


def convert_pipeline_segments(
    english_segments: Any,
    chinese_segments: Any | None,
) -> list[dict[str, Any]]:
    if not isinstance(english_segments, list) or not english_segments:
        raise ExportError("segments_timed_en_corrected.json must contain a non-empty array")
    if chinese_segments is not None and not isinstance(chinese_segments, list):
        raise ExportError("segments_timed_zh.json must contain an array when present")

    chinese_by_id: dict[Any, dict[str, Any]] = {}
    for row in chinese_segments or []:
        if not isinstance(row, dict) or "id" not in row:
            raise ExportError("each Chinese segment must be an object with an id")
        if row["id"] in chinese_by_id:
            raise ExportError(f"duplicate Chinese segment id: {row['id']}")
        chinese_by_id[row["id"]] = row

    rows: list[dict[str, Any]] = []
    seen_source_ids: set[Any] = set()
    previous_start_ms = -1
    for index, english in enumerate(english_segments):
        if not isinstance(english, dict) or "id" not in english:
            raise ExportError("each English segment must be an object with an id")
        source_id = english["id"]
        if source_id in seen_source_ids:
            raise ExportError(f"duplicate English segment id: {source_id}")
        seen_source_ids.add(source_id)

        segment_id = _segment_id(index)
        source_text = _clean_text(english.get("text"))
        if not source_text:
            raise ExportError(f"{segment_id} is missing English text")
        start_seconds = _coerce_seconds(english.get("start"), "start", segment_id)
        end_seconds = _coerce_seconds(english.get("end"), "end", segment_id)
        if end_seconds < start_seconds:
            raise ExportError(f"{segment_id} ends before it starts")
        start_ms = round(start_seconds * 1000)
        end_ms = round(end_seconds * 1000)
        if start_ms < previous_start_ms:
            raise ExportError(f"{segment_id} is out of chronological order")
        previous_start_ms = start_ms

        chinese = chinese_by_id.get(source_id)
        target_text = ""
        if chinese is not None:
            chinese_source = _clean_text(chinese.get("text"))
            if chinese_source and chinese_source != source_text:
                raise ExportError(f"{segment_id} English/Chinese source text mismatch")
            chinese_start = _coerce_seconds(chinese.get("start"), "Chinese start", segment_id)
            chinese_end = _coerce_seconds(chinese.get("end"), "Chinese end", segment_id)
            if abs(chinese_start - start_seconds) > 0.001 or abs(chinese_end - end_seconds) > 0.001:
                raise ExportError(f"{segment_id} English/Chinese timing mismatch")
            target_text = _clean_text(chinese.get("zh"))

        row: dict[str, Any] = {
            "schemaVersion": SEGMENT_SCHEMA_VERSION,
            "segmentId": segment_id,
            "startMs": start_ms,
            "endMs": end_ms,
            "sourceTextEn": source_text,
            "translationStatus": "machine_generated" if target_text else "missing",
            "transcriptStatus": "machine_generated",
            "scriptureRefs": [],
            "terms": [],
        }
        if target_text:
            row["targetTextZh"] = target_text
        section_id = _clean_text(english.get("sectionId"))
        section_title = _clean_text(english.get("sectionTitle"))
        if section_id:
            row["sectionId"] = section_id
        if section_title:
            row["sectionTitle"] = section_title
        rows.append(row)

    extra_chinese_ids = set(chinese_by_id) - seen_source_ids
    if extra_chinese_ids:
        raise ExportError(
            "Chinese segments contain ids missing from English: "
            + ", ".join(str(value) for value in sorted(extra_chinese_ids, key=str))
        )
    return rows


def _timing_metadata(summary: dict[str, Any], english_segments: list[dict[str, Any]]) -> dict[str, str]:
    precision = _clean_text(summary.get("timingPrecision"))
    sources = sorted({_clean_text(row.get("source")) for row in english_segments if _clean_text(row.get("source"))})
    source = ",".join(sources) or "unknown"
    if precision == "synthetic_reading_layout_only" or all(
        _clean_text(row.get("timingQuality")) == "synthetic_not_for_subtitles"
        for row in english_segments
    ):
        return {"quality": "synthetic_sequence_only", "source": source}
    if precision == "whisper_segments":
        return {"quality": "model_segment_timestamps", "source": source}
    raise ExportError(f"unsupported or unverified timing precision: {precision or 'missing'}")


def _summarize_pack(pack: dict[str, Any], phrase_count: int) -> tuple[dict[str, bool], dict[str, int]]:
    approved_terms: set[tuple[str, str]] = set()
    verified_scripture: set[str] = set()
    reviewed_examples = 0
    for entry in pack.get("entries", []):
        for term in entry.get("injectableTerms", []):
            approved_terms.add((_clean_text(term.get("source")), _clean_text(term.get("preferredZh"))))
        verified_scripture.update(_clean_text(value) for value in entry.get("injectableScriptureRefs", []))
        if entry.get("canInjectTranslation"):
            reviewed_examples += 1
    approved_terms.discard(("", ""))
    verified_scripture.discard("")
    counts = {
        "asrPhraseCandidateCount": phrase_count,
        "reviewedTermCount": len(approved_terms),
        "verifiedScriptureCount": len(verified_scripture),
        "reviewedExampleCount": reviewed_examples,
    }
    capabilities = {
        "englishMapReady": bool(pack.get("entries")),
        "asrPhraseCandidatesReady": phrase_count > 0,
        "approvedTermsReady": counts["reviewedTermCount"] > 0,
        "verifiedScriptureReady": counts["verifiedScriptureCount"] > 0,
        "reviewedExamplesReady": counts["reviewedExampleCount"] > 0,
    }
    return capabilities, counts


def _run_command(command: list[str], *, cwd: Path, allow_invalid_readiness: bool = False) -> None:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    allowed_codes = {0, 2} if allow_invalid_readiness else {0}
    if completed.returncode not in allowed_codes:
        detail = (completed.stderr or completed.stdout).strip()
        raise ExportError(f"command failed ({completed.returncode}): {' '.join(command)}\n{detail}")


def export_context(
    *,
    run_root: Path,
    output_dir: Path,
    target_sunday: str,
    source_service_date: str,
    message_key: str,
    message_match_status: str,
    source_id: str | None = None,
    source_audio: Path | None = None,
    sermon_clip: Path | None = None,
    message_approval: Path | None = None,
    valid_until: str | None = None,
    timezone_name: str = "America/Los_Angeles",
    phrase_candidates: Iterable[str] = (),
    now: datetime | None = None,
    _staging: bool = False,
) -> dict[str, Any]:
    if not _staging:
        final_output_dir = output_dir.resolve()
        final_output_dir.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=".saturday-context-pack-",
            dir=final_output_dir.parent,
        ) as temporary:
            staged_output_dir = Path(temporary)
            result = export_context(
                run_root=run_root,
                output_dir=staged_output_dir,
                target_sunday=target_sunday,
                source_service_date=source_service_date,
                message_key=message_key,
                message_match_status=message_match_status,
                source_id=source_id,
                source_audio=source_audio,
                sermon_clip=sermon_clip,
                message_approval=message_approval,
                valid_until=valid_until,
                timezone_name=timezone_name,
                phrase_candidates=phrase_candidates,
                now=now,
                _staging=True,
            )
            final_output_dir.mkdir(parents=True, exist_ok=True)
            artifact_names = (
                "saturday-segments.jsonl",
                "asr-phrases.candidate.txt",
                "message-identity-approval.json",
                "weekly-pack.json",
                "pack-readiness.json",
                "manifest.json",
            )
            for name in artifact_names:
                (staged_output_dir / name).replace(final_output_dir / name)
            result["outputDir"] = str(final_output_dir)
            result["paths"] = {
                key: str(final_output_dir / Path(value).name)
                for key, value in result["paths"].items()
            }
            return result

    run_root = run_root.resolve()
    output_dir = output_dir.resolve()
    target_date = _parse_date(target_sunday, "targetSunday")
    source_date = _parse_date(source_service_date, "sourceServiceDate")
    valid_until_date = _parse_date(valid_until or target_sunday, "validUntil")
    if target_date.weekday() != 6:
        raise ExportError("targetSunday must be a Sunday")
    if source_date > target_date:
        raise ExportError("sourceServiceDate must not be after targetSunday")
    if valid_until_date < target_date:
        raise ExportError("validUntil must not be before targetSunday")
    if message_match_status not in ALLOWED_MESSAGE_MATCH_STATUSES:
        raise ExportError(f"unsupported message match status: {message_match_status}")
    if not _clean_text(message_key):
        raise ExportError("messageKey is required")
    try:
        local_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise ExportError(f"unknown timezone: {timezone_name}") from error
    evaluation_time = now or datetime.now(timezone.utc)
    if evaluation_time.tzinfo is None:
        evaluation_time = evaluation_time.replace(tzinfo=timezone.utc)
    created_at = evaluation_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    pipeline_dir = run_root / "pipeline"
    english_path = pipeline_dir / "segments_timed_en_corrected.json"
    chinese_path = pipeline_dir / "segments_timed_zh.json"
    summary_path = pipeline_dir / "summary.json"
    approval_path = run_root / "operator-window-approval.json"
    message_approval_source = (
        message_approval or run_root / "message-identity-approval.json"
    ).resolve()
    source_audio_path = (source_audio or _find_source_audio(run_root)).resolve()
    sermon_clip_path = (sermon_clip or pipeline_dir / "source_clip.m4a").resolve()
    for required, label in (
        (source_audio_path, "source audio"),
        (sermon_clip_path, "sermon clip"),
        (english_path, "English segments"),
        (summary_path, "pipeline summary"),
        (approval_path, "operator approval"),
    ):
        if not required.is_file():
            raise ExportError(f"missing {label}: {required}")

    approval = _read_json(approval_path, "operator approval")
    if not (
        isinstance(approval, dict)
        and approval.get("status") == "approved"
        and approval.get("humanApproval") is True
    ):
        raise ExportError("operator approval must be human-approved")
    source_url_hash = _clean_text(approval.get("sourceUrlHash"))
    if not source_url_hash:
        raise ExportError("operator approval is missing sourceUrlHash")
    approval_sunday = _clean_text(approval.get("sunday"))
    if approval_sunday and approval_sunday != target_sunday:
        raise ExportError("operator approval Sunday does not match targetSunday")

    if message_match_status == "human_confirmed":
        if not message_approval_source.is_file():
            raise ExportError(
                "human_confirmed requires a message identity approval file; "
                "pass --message-approval or create message-identity-approval.json"
            )
        source_message_approval = _read_json(
            message_approval_source,
            "message identity approval",
        )
        if not isinstance(source_message_approval, dict):
            raise ExportError("message identity approval must contain a JSON object")
        expected_approval = {
            "schemaVersion": "saturday-message-identity-approval-v1",
            "status": "approved",
            "humanApproval": True,
            "matchStatus": "human_confirmed",
            "messageKey": _clean_text(message_key),
            "targetSunday": target_sunday,
            "sourceServiceDate": source_service_date,
        }
        for key, expected in expected_approval.items():
            if source_message_approval.get(key) != expected:
                raise ExportError(f"message identity approval {key} does not match export request")
        approved_by = _clean_text(source_message_approval.get("approvedBy"))
        approved_at = _clean_text(source_message_approval.get("approvedAt"))
        if not approved_by:
            raise ExportError("message identity approval is missing approvedBy")
        try:
            parsed_approval_time = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ExportError("message identity approval approvedAt must be ISO-8601") from error
        if parsed_approval_time.tzinfo is None:
            raise ExportError("message identity approval approvedAt must include a timezone")
        message_approval_record = {
            **expected_approval,
            "approvedBy": approved_by,
            "approvedAt": parsed_approval_time.isoformat().replace("+00:00", "Z"),
        }
    else:
        message_approval_record = {
            "schemaVersion": "saturday-message-identity-approval-v1",
            "status": "pending",
            "humanApproval": False,
            "matchStatus": message_match_status,
            "messageKey": _clean_text(message_key),
            "targetSunday": target_sunday,
            "sourceServiceDate": source_service_date,
            "recordedAt": created_at,
        }

    english_segments = _read_json(english_path, "English segments")
    chinese_segments = _read_json(chinese_path, "Chinese segments") if chinese_path.is_file() else None
    summary = _read_json(summary_path, "pipeline summary")
    if not isinstance(summary, dict):
        raise ExportError("pipeline summary must contain a JSON object")
    segment_rows = convert_pipeline_segments(english_segments, chinese_segments)
    timing = _timing_metadata(summary, english_segments)
    phrases = _normalize_phrase_candidates(phrase_candidates)

    output_dir.mkdir(parents=True, exist_ok=True)
    segments_path = output_dir / "saturday-segments.jsonl"
    phrase_path = output_dir / "asr-phrases.candidate.txt"
    message_approval_path = output_dir / "message-identity-approval.json"
    pack_path = output_dir / "weekly-pack.json"
    manifest_path = output_dir / "manifest.json"
    readiness_path = output_dir / "pack-readiness.json"
    _write_jsonl(segments_path, segment_rows)
    _write_text(phrase_path, "".join(f"{phrase}\n" for phrase in phrases))
    _write_json(message_approval_path, message_approval_record)
    stable_source_id = _clean_text(source_id) or f"{source_service_date}:{run_root.name}"
    builder_command = [
        sys.executable,
        "-m",
        "backend.build_weekly_pack",
        "--segments",
        str(segments_path),
        "--service-date",
        source_service_date,
        "--source-id",
        stable_source_id,
        "--audio",
        str(sermon_clip_path),
        "--valid-until",
        valid_until_date.isoformat(),
        "--timezone",
        timezone_name,
        "--output",
        str(pack_path),
    ]
    _run_command(builder_command, cwd=POC_ROOT)
    pack = _read_json(pack_path, "weekly pack")
    if not isinstance(pack, dict):
        raise ExportError("weekly pack must contain a JSON object")
    capabilities, counts = _summarize_pack(pack, len(phrases))

    not_before = datetime.combine(source_date, time.min, local_timezone)
    local_valid_until = datetime.combine(valid_until_date, time(23, 59, 59), local_timezone)
    source_audio_sha = _sha256_file(source_audio_path)
    sermon_clip_sha = _sha256_file(sermon_clip_path)
    segments_sha = _sha256_file(segments_path)
    pack_sha = _sha256_file(pack_path)
    phrase_sha = _sha256_file(phrase_path)
    message_approval_sha = _sha256_file(message_approval_path)
    manifest = {
        "schemaVersion": MANIFEST_SCHEMA_VERSION,
        "packId": pack.get("packVersion"),
        "createdAt": created_at,
        "targetSunday": target_date.isoformat(),
        "messageIdentity": {
            "messageKey": _clean_text(message_key),
            "matchStatus": message_match_status,
            "sourceServiceDate": source_date.isoformat(),
            "approval": {
                "sha256": message_approval_sha,
                "approvedBy": message_approval_record.get("approvedBy"),
                "approvedAt": message_approval_record.get("approvedAt"),
            },
        },
        "provenance": {
            "sourceId": stable_source_id,
            "sourceUrlHash": source_url_hash,
            "sourceAudioSha256": source_audio_sha,
            "sermonClipSha256": sermon_clip_sha,
            "segmentSourceSha256": segments_sha,
            "pipelineInputFingerprint": summary.get("pipelineInputFingerprint"),
        },
        "capabilities": capabilities,
        "timing": timing,
        "validity": {
            "notBefore": not_before.isoformat(),
            "validUntil": local_valid_until.isoformat(),
            "timezone": timezone_name,
        },
        "review": {
            "machineChineseInjectable": False,
            **counts,
        },
        "policy": {
            "currentLiveEnglishIsSourceOfTruth": True,
            "machineTranslationInjectable": False,
        },
        "pipeline": {
            "outputMode": summary.get("outputMode"),
            "timingPrecision": summary.get("timingPrecision"),
            "models": summary.get("models"),
        },
        "artifacts": {
            "sourceAudio": {
                "path": _run_relative(source_audio_path, run_root),
                "sha256": source_audio_sha,
            },
            "sermonClip": {
                "path": _run_relative(sermon_clip_path, run_root),
                "sha256": sermon_clip_sha,
            },
            "saturdaySegments": {"path": segments_path.name, "sha256": segments_sha},
            "weeklyPack": {"path": pack_path.name, "sha256": pack_sha},
            "asrPhraseCandidates": {"path": phrase_path.name, "sha256": phrase_sha},
            "messageIdentityApproval": {
                "path": message_approval_path.name,
                "sha256": message_approval_sha,
            },
        },
    }
    _write_json(manifest_path, manifest)

    readiness_command = [
        sys.executable,
        "-m",
        "backend.pack_readiness",
        "--manifest",
        str(manifest_path),
        "--pack",
        str(pack_path),
        "--segments",
        str(segments_path),
        "--phrases",
        str(phrase_path),
        "--message-approval",
        str(message_approval_path),
        "--expected-target-sunday",
        target_sunday,
        "--now",
        evaluation_time.isoformat(),
        "--output",
        str(readiness_path),
    ]
    _run_command(readiness_command, cwd=POC_ROOT, allow_invalid_readiness=True)
    readiness = _read_json(readiness_path, "pack readiness")
    return {
        "schemaVersion": "saturday-context-export-v1",
        "outputDir": str(output_dir),
        "packVersion": pack.get("packVersion"),
        "segmentCount": len(segment_rows),
        "timingQuality": timing["quality"],
        "runtimeMode": readiness.get("runtimeMode"),
        "readinessStatus": readiness.get("status"),
        "paths": {
            "segments": str(segments_path),
            "pack": str(pack_path),
            "manifest": str(manifest_path),
            "readiness": str(readiness_path),
            "asrPhraseCandidates": str(phrase_path),
            "messageApproval": str(message_approval_path),
        },
    }


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--run-root", type=Path, required=True)
    command.add_argument("--output-dir", type=Path, required=True)
    command.add_argument("--target-sunday", required=True)
    command.add_argument("--source-service-date", required=True)
    command.add_argument("--message-key", required=True)
    command.add_argument(
        "--message-match-status",
        choices=sorted(ALLOWED_MESSAGE_MATCH_STATUSES),
        default="unknown",
    )
    command.add_argument("--source-id")
    command.add_argument("--source-audio", type=Path)
    command.add_argument("--sermon-clip", type=Path)
    command.add_argument("--message-approval", type=Path)
    command.add_argument("--valid-until")
    command.add_argument("--timezone", default="America/Los_Angeles")
    command.add_argument("--asr-phrase", action="append", default=[])
    return command


def main() -> None:
    arguments = parser().parse_args()
    report = export_context(
        run_root=arguments.run_root,
        output_dir=arguments.output_dir,
        target_sunday=arguments.target_sunday,
        source_service_date=arguments.source_service_date,
        message_key=arguments.message_key,
        message_match_status=arguments.message_match_status,
        source_id=arguments.source_id,
        source_audio=arguments.source_audio,
        sermon_clip=arguments.sermon_clip,
        message_approval=arguments.message_approval,
        valid_until=arguments.valid_until,
        timezone_name=arguments.timezone,
        phrase_candidates=arguments.asr_phrase,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
