#!/usr/bin/env python3
"""Bind sermon-relative English anchors to an approved clip's media timebase."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import subprocess
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

try:
    from scripts import sermon_sentence_interpretation as interpretation
except ImportError:
    import sermon_sentence_interpretation as interpretation


SCHEMA = "sermon-clip-timeline-map-v1"
EPSILON = 0.025
MAX_TRAILING_SILENCE_SECONDS = 0.25


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def seconds(value: str) -> float:
    parts = value.split(":")
    require(len(parts) in {2, 3}, f"Invalid time notation: {value}")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError(f"Invalid time notation: {value}") from exc
    require(all(math.isfinite(number) and number >= 0 for number in numbers),
            f"Invalid time notation: {value}")
    if len(parts) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def media_duration(path: Path) -> float:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ], capture_output=True, text=True, check=True, timeout=90)
        duration = float(result.stdout.strip())
        require(math.isfinite(duration) and duration > 0, "Invalid clip media duration")
        return duration
    except FileNotFoundError:
        # GPU containers may have no ffprobe. The MP4 movie header gives the
        # declared media timebase without trusting a job-supplied duration.
        return mp4_movie_duration(path)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"Cannot probe clip media duration: {path}: {exc}") from exc


def mp4_movie_duration(path: Path) -> float:
    try:
        with path.open("rb") as handle:
            end = path.stat().st_size

            def boxes(limit: int):
                while handle.tell() + 8 <= limit:
                    start = handle.tell()
                    header = handle.read(8)
                    size = int.from_bytes(header[:4], "big")
                    kind = header[4:]
                    if size == 1:
                        size = int.from_bytes(handle.read(8), "big")
                        header_size = 16
                    else:
                        header_size = 8
                        if size == 0:
                            size = limit - start
                    require(size >= header_size and start + size <= limit,
                            "Malformed MP4 box length")
                    yield kind, start + size
                    handle.seek(start + size)

            for kind, box_end in boxes(end):
                if kind != b"moov":
                    continue
                # `boxes` yields after reading the header and before seeking.
                for child_kind, child_end in boxes(box_end):
                    if child_kind != b"mvhd":
                        continue
                    version = handle.read(1)[0]
                    require(version in {0, 1}, "Unsupported MP4 movie header")
                    handle.seek(3 + (16 if version else 8), 1)
                    timescale = int.from_bytes(handle.read(4), "big")
                    ticks = int.from_bytes(handle.read(8 if version else 4), "big")
                    require(timescale > 0 and ticks > 0
                            and ticks != ((2**64 - 1) if version else (2**32 - 1)),
                            "Invalid MP4 movie timebase")
                    duration = ticks / timescale
                    require(math.isfinite(duration) and duration > 0,
                            "Invalid MP4 movie duration")
                    return duration
                break
        raise ValueError("MP4 movie duration header not found")
    except (OSError, IndexError) as exc:
        raise ValueError(f"Cannot probe clip media duration: {path}: {exc}") from exc


def validate(value: dict[str, Any], source: dict[str, Any], anchor: dict[str, Any]) -> float:
    schema = read_object(Path(__file__).parents[1] / "schemas" /
                         "sermon-clip-timeline-map-v1.schema.json")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    require(not errors, f"Clip timeline map schema error: {errors[0].message if errors else ''}")
    require(value["englishSourcePackageJsonSha256"] == interpretation.json_sha256(source)
            and value["anchorManifestJsonSha256"] == interpretation.json_sha256(anchor)
            and source.get("anchors", {}).get("artifact", {}).get("jsonSha256")
            == interpretation.json_sha256(anchor),
            "Clip timeline map differs from English source or anchor")
    media = source.get("source", {}).get("media", {})
    clip_path = Path(value["clipMedia"]["path"])
    require(clip_path.is_file()
            and interpretation.sha256(clip_path) == value["clipMedia"]["sha256"]
            == media.get("sha256"),
            "Clip timeline map media SHA-256 mismatch")
    actual_duration = media_duration(clip_path)
    require(abs(actual_duration - value["clipDurationSeconds"]) <= EPSILON
            and abs(actual_duration - media.get("durationSeconds", -1)) <= EPSILON,
            "Clip timeline map media duration mismatch")
    window = source.get("source", {}).get("approvedWindow", {})
    evidence = window.get("evidence", {})
    approval_path = Path(value["windowApproval"]["path"])
    require(window.get("status") == "approved" and window.get("humanApproval") is True
            and approval_path.is_file()
            and interpretation.sha256(approval_path) == value["windowApproval"]["sha256"]
            == evidence.get("sha256"),
            "Clip timeline map approval evidence hash mismatch")
    approval = read_object(approval_path)
    require(interpretation.json_sha256(approval) == value["windowApproval"]["jsonSha256"]
            == evidence.get("jsonSha256")
            and approval.get("humanApproval") is True
            and approval.get("status") == "approved"
            and approval.get("sourceMediaSha256") == media.get("sha256"),
            "Clip timeline map approval identity mismatch")
    start, end = window.get("startSeconds"), window.get("endSeconds")
    require(isinstance(start, (int, float)) and isinstance(end, (int, float))
            and 0 <= start < end <= actual_duration + EPSILON,
            "Clip timeline map approved window is invalid")
    require(abs(seconds(approval["startTime"]) - start) <= EPSILON
            and abs(seconds(approval["endTime"]) - end) <= EPSILON,
            "Clip timeline map approval time differs from source")
    original = approval.get("originalRecordingWindow", "")
    parts = original.split("-")
    require(len(parts) == 2, "Clip timeline map lacks original recording window")
    original_start, original_end = seconds(parts[0]), seconds(parts[1])
    require(abs(original_start - value["originalRecordingStartSeconds"]) <= EPSILON
            and abs(original_end - value["originalRecordingEndSeconds"]) <= EPSILON
            and abs((original_end - original_start) - (end - start)) <= EPSILON,
            "Clip timeline map original recording window mismatch")
    units = anchor.get("sourceUnits", [])
    require(isinstance(units, list) and bool(units), "Clip timeline map has no source units")
    offset = value["anchorOffsetSeconds"]
    require(abs(units[0]["start"] - value["anchorFirstStartSeconds"]) <= EPSILON
            and abs(units[-1]["end"] - value["anchorLastEndSeconds"]) <= EPSILON
            and abs(units[0]["start"] - offset - start) <= EPSILON
            and -EPSILON <= end - (units[-1]["end"] - offset)
            <= MAX_TRAILING_SILENCE_SECONDS + EPSILON,
            "Clip timeline map anchor offset does not align approved clip edges")
    previous = start
    for unit in units:
        unit_start, unit_end = unit["start"] - offset, unit["end"] - offset
        require(start - EPSILON <= unit_start < unit_end <= end + EPSILON
                and unit_start + EPSILON >= previous,
                "Clip timeline map source unit is outside or disordered within clip")
        previous = unit_end
    return offset


def prepare(source_path: Path, anchor_path: Path, clip_path: Path,
            anchor_offset_seconds: float, out: Path) -> dict[str, Any]:
    require(not out.exists(), "Clip timeline map is immutable; choose a new path")
    source, anchor = read_object(source_path), read_object(anchor_path)
    evidence = source["source"]["approvedWindow"]["evidence"]
    approval = read_object(Path(evidence["path"]))
    original_start, original_end = (seconds(part) for part in approval["originalRecordingWindow"].split("-"))
    value = {
        "schemaVersion": SCHEMA,
        "timebase": "anchor_sermon_relative_to_clip_media",
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "anchorManifestJsonSha256": interpretation.json_sha256(anchor),
        "clipMedia": {"path": str(clip_path.resolve()), "sha256": interpretation.sha256(clip_path)},
        "clipDurationSeconds": media_duration(clip_path),
        "windowApproval": evidence,
        "anchorOffsetSeconds": anchor_offset_seconds,
        "anchorFirstStartSeconds": anchor["sourceUnits"][0]["start"],
        "anchorLastEndSeconds": anchor["sourceUnits"][-1]["end"],
        "originalRecordingStartSeconds": original_start,
        "originalRecordingEndSeconds": original_end,
    }
    validate(value, source, anchor)
    out.parent.mkdir(parents=True, exist_ok=True)
    interpretation.write_json(out, value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--clip-media", type=Path, required=True)
    parser.add_argument("--anchor-offset-seconds", type=float, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = prepare(args.source, args.anchor, args.clip_media, args.anchor_offset_seconds, args.out)
    print(json.dumps({"status": "clip_timebase_bound", "anchorOffsetSeconds": value["anchorOffsetSeconds"],
                      "map": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
