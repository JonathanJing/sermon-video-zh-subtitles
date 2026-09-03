#!/usr/bin/env python3
"""Extract public YouTube automatic English captions into a resumable corpus.

The extractor is intentionally narrow:

- reads an already-audited sermon inventory;
- downloads caption files only, never audio or video;
- uses anonymous public access only;
- preserves the original VTT and produces explicitly non-Gold normalized text;
- verifies hashes and timeline coverage before marking an asset complete.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_INVENTORY = Path(
    "data/reports/mariners-channel-audit-20260830/sermon-vods.jsonl"
)
DEFAULT_OUTPUT_ROOT = Path("data/raw/mariners-sermon-captions-v1")
DEFAULT_REPORT_DIR = Path("data/reports/mariners-caption-extraction-v1")
SCHEMA_VERSION = "mariners-caption-extraction-v1"
CAPTION_LANGUAGE = "en-orig"
TIMESTAMP_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})(?P<settings>.*)"
)


@dataclass(frozen=True)
class Cue:
    start_ms: int
    end_ms: int
    text: str
    settings: str = ""
    identifier: str | None = None


def main() -> int:
    args = parse_args()
    yt_dlp = require_executable(args.yt_dlp)
    rows = load_jsonl(args.inventory)
    candidates = eligible_candidates(rows)
    selected, already_complete = select_candidates(
        candidates,
        output_root=args.output_root,
        batch_size=args.batch_size,
        requested_ids=args.video_id,
        force=args.force,
    )

    started_at = utc_now()
    results: list[dict[str, Any]] = []
    for row in selected:
        results.append(
            extract_asset(
                row,
                inventory=args.inventory,
                output_root=args.output_root,
                yt_dlp=yt_dlp,
                force=args.force,
            )
        )

    completed = [item["assetId"] for item in results if item["status"] == "ok"]
    reused = [item["assetId"] for item in results if item["status"] == "already_complete"]
    failed = [item for item in results if item["status"] == "failed"]
    report = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "failed" if failed else ("no_op" if not selected else "ok"),
        "startedAt": started_at,
        "finishedAt": utc_now(),
        "inventory": str(args.inventory),
        "outputRoot": str(args.output_root),
        "captionLanguage": CAPTION_LANGUAGE,
        "captionKind": "youtube_automatic",
        "eligibleInventoryCount": len(candidates),
        "batchSize": args.batch_size,
        "selectedIds": [row["id"] for row in selected],
        "completedIds": completed,
        "reusedIds": reused,
        "failed": failed,
        "alreadyCompleteBeforeBatchCount": len(already_complete),
        "remainingEligibleEstimate": max(
            0,
            len(candidates)
            - len(already_complete)
            - len(completed)
            - len(reused),
        ),
        "mediaDownloaded": False,
        "authenticatedSessionUsed": False,
        "results": results,
    }
    report_path = write_batch_report(args.report_dir, report)
    report["reportPath"] = str(report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--yt-dlp", default="yt-dlp")
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if not args.inventory.is_file():
        parser.error(f"inventory does not exist: {args.inventory}")
    return args


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise SystemExit(f"Expected object at {path}:{line_number}")
        rows.append(row)
    return rows


def eligible_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    seen: set[str] = set()
    for row in rows:
        asset_id = str(row.get("id") or "")
        if not asset_id or asset_id in seen:
            continue
        tracks = row.get("automaticEnglishCaptionTracks") or []
        if row.get("englishCaptionStatus") != "automatic_english":
            continue
        if CAPTION_LANGUAGE not in tracks:
            continue
        if not str(row.get("webpage_url") or "").startswith("https://www.youtube.com/"):
            continue
        seen.add(asset_id)
        candidates.append(row)
    return sorted(
        candidates,
        key=lambda item: (str(item.get("upload_date") or ""), str(item.get("id") or "")),
        reverse=True,
    )


def select_candidates(
    candidates: list[dict[str, Any]],
    *,
    output_root: Path,
    batch_size: int,
    requested_ids: list[str],
    force: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    by_id = {str(row["id"]): row for row in candidates}
    if requested_ids:
        missing = [asset_id for asset_id in requested_ids if asset_id not in by_id]
        if missing:
            raise SystemExit(
                "Requested IDs are absent from the eligible automatic-English inventory: "
                + ", ".join(missing)
            )
        unique_requested = list(dict.fromkeys(requested_ids))
        if len(unique_requested) > batch_size:
            raise SystemExit("Requested video IDs exceed --batch-size")
        return [by_id[asset_id] for asset_id in unique_requested], []

    selected: list[dict[str, Any]] = []
    already_complete: list[str] = []
    for row in candidates:
        asset_id = str(row["id"])
        if not force and verify_completed_asset(output_root / asset_id):
            already_complete.append(asset_id)
            continue
        selected.append(row)
        if len(selected) >= batch_size:
            break
    return selected, already_complete


def extract_asset(
    row: dict[str, Any],
    *,
    inventory: Path,
    output_root: Path,
    yt_dlp: str,
    force: bool,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    asset_id = str(row["id"])
    asset_dir = output_root / asset_id
    if not force and verify_completed_asset(asset_dir):
        return {"assetId": asset_id, "status": "already_complete"}

    source_dir = asset_dir / "source"
    normalized_dir = asset_dir / "normalized"
    source_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)
    vtt_path = source_dir / f"{asset_id}.{CAPTION_LANGUAGE}.vtt"

    try:
        reused_vtt = is_usable_vtt(vtt_path)
        if not reused_vtt:
            download_caption(row, source_dir=source_dir, yt_dlp=yt_dlp, runner=runner)
        if not is_usable_vtt(vtt_path):
            raise RuntimeError(f"yt-dlp did not create a usable {CAPTION_LANGUAGE} VTT")

        vtt_text = vtt_path.read_text(encoding="utf-8", errors="replace")
        raw_cues = parse_vtt(vtt_text)
        normalized_cues = extract_incremental_cues(raw_cues)
        transcript = normalize_whitespace(" ".join(cue.text for cue in normalized_cues))
        checks = quality_checks(
            raw_cues,
            normalized_cues,
            transcript,
            duration_seconds=float(row.get("duration") or 0),
        )
        failed_checks = [item["name"] for item in checks if item["state"] != "pass"]
        if failed_checks:
            raise RuntimeError("quality checks failed: " + ", ".join(failed_checks))

        raw_jsonl = normalized_dir / "cues.youtube-auto-raw.jsonl"
        normalized_jsonl = normalized_dir / "cues.youtube-auto.jsonl"
        transcript_path = normalized_dir / "transcript.youtube-auto.txt"
        write_cues(raw_jsonl, raw_cues, origin="youtube_automatic_raw")
        write_cues(normalized_jsonl, normalized_cues, origin="youtube_automatic_increment")
        atomic_write_text(transcript_path, transcript + "\n")

        files = file_receipts(asset_dir, [vtt_path, raw_jsonl, normalized_jsonl, transcript_path])
        manifest = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "ok",
            "extractedAt": utc_now(),
            "asset": {
                "id": asset_id,
                "title": row.get("title"),
                "url": row.get("webpage_url"),
                "uploadDate": row.get("upload_date"),
                "durationSeconds": row.get("duration"),
                "visibility": "public",
            },
            "caption": {
                "kind": "youtube_automatic",
                "language": CAPTION_LANGUAGE,
                "reviewState": "unreviewed_raw",
                "rawCueCount": len(raw_cues),
                "normalizedCueCount": len(normalized_cues),
                "transcriptCharacters": len(transcript),
                "timelineStartMs": raw_cues[0].start_ms,
                "timelineEndMs": raw_cues[-1].end_ms,
                "sourceVttReused": reused_vtt,
            },
            "provenance": {
                "inventory": str(inventory),
                "inventoryObservedAt": row.get("observedAt"),
                "accessObservation": "anonymous_public_metadata_and_caption_request",
                "ytDlpVersion": executable_version(yt_dlp, runner=runner),
                "authenticatedSessionUsed": False,
                "audioDownloaded": False,
                "videoDownloaded": False,
            },
            "qualityChecks": checks,
            "files": files,
        }
        atomic_write_json(asset_dir / "manifest.json", manifest)
        return {
            "assetId": asset_id,
            "status": "ok",
            "sourceVttReused": reused_vtt,
            "rawCueCount": len(raw_cues),
            "normalizedCueCount": len(normalized_cues),
            "transcriptCharacters": len(transcript),
            "timelineCoverage": next(
                item["observed"] for item in checks if item["name"] == "timeline_coverage"
            ),
        }
    except Exception as exc:
        failure = {
            "schemaVersion": SCHEMA_VERSION,
            "status": "failed",
            "assetId": asset_id,
            "failedAt": utc_now(),
            "resumeStage": "caption_download_or_normalization",
            "error": sanitize_error(str(exc)),
            "audioDownloaded": False,
            "videoDownloaded": False,
        }
        atomic_write_json(asset_dir / "failure.json", failure)
        return {"assetId": asset_id, "status": "failed", **failure}


def download_caption(
    row: dict[str, Any],
    *,
    source_dir: Path,
    yt_dlp: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    command = [
        yt_dlp,
        "--ignore-config",
        "--no-cache-dir",
        "--no-playlist",
        "--skip-download",
        "--write-auto-subs",
        "--sub-langs",
        CAPTION_LANGUAGE,
        "--sub-format",
        "vtt",
        "--output",
        str(source_dir / "%(id)s.%(ext)s"),
        str(row["webpage_url"]),
    ]
    proc = runner(command, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(last_nonempty_line(proc.stderr) or "yt-dlp caption request failed")


def parse_vtt(text: str) -> list[Cue]:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    cues: list[Cue] = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        identifier = None
        timing_index = 0
        if "-->" not in lines[0] and len(lines) > 1:
            identifier = lines[0]
            timing_index = 1
        if timing_index >= len(lines):
            continue
        match = TIMESTAMP_RE.search(lines[timing_index])
        if not match:
            continue
        cue_text = "\n".join(lines[timing_index + 1 :]).strip()
        if not cue_text:
            continue
        cleaned = clean_vtt_text(cue_text)
        if not cleaned:
            continue
        cues.append(
            Cue(
                start_ms=parse_time_to_ms(match.group("start")),
                end_ms=parse_time_to_ms(match.group("end")),
                text=cleaned,
                settings=match.group("settings").strip(),
                identifier=identifier,
            )
        )
    return cues


def extract_incremental_cues(cues: list[Cue]) -> list[Cue]:
    increments: list[Cue] = []
    previous_text = ""
    for cue in cues:
        lines = [normalize_whitespace(line) for line in cue.text.splitlines() if line.strip()]
        if not lines:
            continue
        newest = lines[-1]
        if not newest or newest == previous_text:
            continue
        increments.append(Cue(cue.start_ms, cue.end_ms, newest))
        previous_text = newest
    return increments


def clean_vtt_text(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", text)
    return "\n".join(
        normalize_whitespace(html.unescape(line))
        for line in without_tags.splitlines()
        if normalize_whitespace(html.unescape(line))
    )


def quality_checks(
    raw_cues: list[Cue],
    normalized_cues: list[Cue],
    transcript: str,
    *,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    timeline_end_ms = raw_cues[-1].end_ms if raw_cues else 0
    duration_ms = max(0, int(duration_seconds * 1000))
    coverage = timeline_end_ms / duration_ms if duration_ms else 0.0
    words = re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)?", transcript)
    visible_tokens = re.findall(r"\S+", transcript)
    english_ratio = len(words) / len(visible_tokens) if visible_tokens else 0.0
    return [
        check("raw_cues_nonempty", bool(raw_cues), len(raw_cues)),
        check("normalized_cues_nonempty", bool(normalized_cues), len(normalized_cues)),
        check("transcript_minimum_length", len(transcript) >= 1000, len(transcript)),
        check("english_word_ratio", english_ratio >= 0.65, round(english_ratio, 4)),
        check("timeline_coverage", coverage >= 0.70, round(coverage, 4)),
        check(
            "monotonic_raw_timeline",
            all(cue.end_ms > cue.start_ms for cue in raw_cues)
            and all(a.start_ms <= b.start_ms for a, b in zip(raw_cues, raw_cues[1:])),
            {"firstMs": raw_cues[0].start_ms if raw_cues else None, "lastMs": timeline_end_ms},
        ),
    ]


def check(name: str, passed: bool, observed: Any) -> dict[str, Any]:
    return {"name": name, "state": "pass" if passed else "fail", "observed": observed}


def write_cues(path: Path, cues: list[Cue], *, origin: str) -> None:
    rows = []
    for index, cue in enumerate(cues, 1):
        rows.append(
            json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "cueId": f"cue_{index:05d}",
                    "startMs": cue.start_ms,
                    "endMs": cue.end_ms,
                    "text": cue.text,
                    "origin": origin,
                    "reviewState": "unreviewed_raw",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    atomic_write_text(path, "\n".join(rows) + ("\n" if rows else ""))


def file_receipts(root: Path, paths: list[Path]) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in paths
    ]


def verify_completed_asset(asset_dir: Path) -> bool:
    manifest_path = asset_dir / "manifest.json"
    if not manifest_path.is_file():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if manifest.get("status") != "ok" or manifest.get("schemaVersion") != SCHEMA_VERSION:
        return False
    files = manifest.get("files") or []
    if not files:
        return False
    for receipt in files:
        path = asset_dir / str(receipt.get("path") or "")
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        if sha256_file(path) != receipt.get("sha256"):
            return False
    return True


def write_batch_report(report_dir: Path, report: dict[str, Any]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = report_dir / f"batch-{stamp}.json"
    suffix = 1
    while path.exists():
        path = report_dir / f"batch-{stamp}-{suffix}.json"
        suffix += 1
    atomic_write_json(path, report)
    return path


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def is_usable_vtt(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        prefix = path.read_text(encoding="utf-8", errors="replace")[:2048]
    except OSError:
        return False
    return prefix.lstrip("\ufeff").startswith("WEBVTT") and "-->" in prefix


def require_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise SystemExit(f"Executable not found: {name}")
    return executable


def executable_version(
    executable: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str | None:
    proc = runner([executable, "--version"], text=True, capture_output=True, check=False)
    return proc.stdout.strip().splitlines()[0] if proc.returncode == 0 and proc.stdout.strip() else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_time_to_ms(value: str) -> int:
    parts = value.strip().replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    else:
        raise ValueError(f"Unsupported VTT time: {value}")
    return int(((hours * 3600) + (minutes * 60) + seconds) * 1000)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def last_nonempty_line(value: str) -> str:
    for line in reversed(value.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def sanitize_error(value: str) -> str:
    value = re.sub(r"https?://[^\s]+", "[url]", value)
    return value[:600]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
