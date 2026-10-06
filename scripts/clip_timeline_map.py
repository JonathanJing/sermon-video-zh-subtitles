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


CLIP_SCHEMA = "sermon-clip-timeline-map-v1"
COMPLETE_MEDIA_SCHEMA = "sermon-clip-timeline-map-v2"
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


def _complete_media_window(start: float, end: float, duration: float) -> bool:
    return abs(start) <= EPSILON and abs(end - duration) <= EPSILON


def validate_derived_window(value: dict[str, Any], source: dict[str, Any], anchor: dict[str, Any]) -> float:
    schema = read_object(Path(__file__).parents[1] / "schemas/sermon-clip-timeline-map-v3.schema.json")
    errors = list(Draft202012Validator(schema).iter_errors(value))
    require(not errors, f"Derived timeline schema error: {errors[0].message if errors else ''}")
    require(value["englishSourcePackageJsonSha256"] == interpretation.json_sha256(source)
            and value["anchorManifestJsonSha256"] == interpretation.json_sha256(anchor)
            and source.get("anchors", {}).get("artifact", {}).get("jsonSha256") == interpretation.json_sha256(anchor),
            "Derived timeline source/anchor mismatch")
    media = source["source"]["media"]
    source_media = value["sourceMedia"]
    source_path = Path(source_media["path"])
    require(source_path.is_file() and interpretation.sha256(source_path) == source_media["sha256"] == media["sha256"]
            and source_path.stat().st_size == source_media["sizeBytes"]
            and abs(media_duration(source_path) - source_media["durationSeconds"]) <= EPSILON
            and source_media["durationSeconds"] == media["durationSeconds"], "Derived timeline source media mismatch")
    window = source["source"]["approvedWindow"]
    start, end = value["approvedWindow"]["startSeconds"], value["approvedWindow"]["endSeconds"]
    require(window.get("status") == "approved" and window.get("humanApproval") is True
            and start == window["startSeconds"] and end == window["endSeconds"]
            and 0 <= start < end <= source_media["durationSeconds"]
            and abs(end - start - value["approvedWindowSeconds"]) <= EPSILON,
            "Derived timeline approved window mismatch")
    evidence = window["evidence"]
    for key in ("windowApproval", "extractionReceipt"):
        bound = value[key]; path = Path(bound["path"])
        require(path.is_file() and interpretation.sha256(path) == bound["sha256"], f"Derived timeline {key} hash mismatch")
        obj = read_object(path)
        require(interpretation.json_sha256(obj) == bound["jsonSha256"], f"Derived timeline {key} JSON hash mismatch")
        if key == "windowApproval":
            require(bound["sha256"] == evidence["sha256"] and bound["jsonSha256"] == evidence["jsonSha256"]
                    and obj.get("humanApproval") is True and obj.get("status") == "approved"
                    and obj.get("sourceMediaSha256") == media["sha256"]
                    and abs(seconds(obj["startTime"]) - start) <= EPSILON
                    and abs(seconds(obj["endTime"]) - end) <= EPSILON, "Derived timeline approval identity mismatch")
        else:
            require(obj.get("operation") == "clip_and_normalize" and obj.get("source", {}).get("sha256") == media["sha256"]
                    and obj.get("source", {}).get("sizeBytes") == source_media["sizeBytes"]
                    and obj.get("startSeconds") == start and obj.get("endSeconds") == end,
                    "Derived timeline extraction source/window mismatch")
    clip = value["clipMedia"]; path = Path(clip["path"]); probe = value["clipMediaProbe"]
    require(path.is_file() and interpretation.sha256(path) == clip["sha256"] and path.stat().st_size == clip["sizeBytes"],
            "Derived timeline clip hash mismatch")
    actual = media_duration(path)
    rate = probe["sampleRate"]
    require(abs(actual - probe["formatDurationSeconds"]) <= EPSILON
            and probe["streamStartTimeSeconds"] == 0
            and abs(probe["streamDurationSeconds"] - actual) <= EPSILON
            and abs(probe["decodedAudioSamples"] / rate - value["clipDurationSeconds"]) <= 1 / rate
            and abs(probe["decodedAudioDurationSeconds"] - value["clipDurationSeconds"]) <= 1 / rate
            and abs(value["clipDurationSeconds"] - (end - start)) <= 1 / rate
            and abs((actual - value["clipDurationSeconds"]) * rate - probe["containerPaddingSamples"]) <= 1
            and 0 <= probe["containerPaddingSamples"] <= probe["paddingBudgetSamples"] <= 4096,
            "Derived timeline decoded duration or container padding mismatch")
    require(value["anchorOrigin"]["absoluteSourceStartSeconds"] == start and value["anchorOffsetSeconds"] == 0,
            "Derived timeline origin mismatch")
    units = anchor.get("sourceUnits", [])
    require(bool(units) and abs(units[0]["start"] - value["anchorFirstStartSeconds"]) <= EPSILON
            and abs(units[-1]["end"] - value["anchorLastEndSeconds"]) <= EPSILON, "Derived timeline anchor endpoints mismatch")
    previous = 0
    for unit in units:
        require(0 <= unit["start"] < unit["end"] <= value["clipDurationSeconds"] + EPSILON
                and unit["start"] + EPSILON >= previous, "Derived timeline source units outside approved clip")
        previous = unit["end"]
    return 0.0


def validate(value: dict[str, Any], source: dict[str, Any], anchor: dict[str, Any]) -> float:
    version = value.get("schemaVersion")
    if version == "sermon-clip-timeline-map-v3":
        return validate_derived_window(value, source, anchor)
    require(version in {CLIP_SCHEMA, COMPLETE_MEDIA_SCHEMA},
            "Unsupported clip timeline map schema")
    schema = read_object(Path(__file__).parents[1] / "schemas" /
                         f"{version}.schema.json")
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
    units = anchor.get("sourceUnits", [])
    require(isinstance(units, list) and bool(units), "Clip timeline map has no source units")
    offset = value["anchorOffsetSeconds"]
    require(abs(units[0]["start"] - value["anchorFirstStartSeconds"]) <= EPSILON
            and abs(units[-1]["end"] - value["anchorLastEndSeconds"]) <= EPSILON,
            "Clip timeline map anchor endpoints differ from approved anchors")
    if version == CLIP_SCHEMA:
        original = approval.get("originalRecordingWindow", "")
        parts = original.split("-")
        require(len(parts) == 2, "Clip timeline map lacks original recording window")
        original_start, original_end = seconds(parts[0]), seconds(parts[1])
        require(abs(original_start - value["originalRecordingStartSeconds"]) <= EPSILON
                and abs(original_end - value["originalRecordingEndSeconds"]) <= EPSILON
                and abs((original_end - original_start) - (end - start)) <= EPSILON,
                "Clip timeline map original recording window mismatch")
        require(abs(units[0]["start"] - offset - start) <= EPSILON
                and -EPSILON <= end - (units[-1]["end"] - offset)
                <= MAX_TRAILING_SILENCE_SECONDS + EPSILON,
                "Clip timeline map anchor offset does not align approved clip edges")
    else:
        require(_complete_media_window(start, end, actual_duration)
                and not approval.get("originalRecordingWindow")
                and offset == start,
                "Complete-media timebase requires a full-media approval and its source offset")
    previous = start
    for unit in units:
        unit_start, unit_end = unit["start"] - offset, unit["end"] - offset
        require(start - EPSILON <= unit_start < unit_end <= end + EPSILON
                and unit_start + EPSILON >= previous,
                "Clip timeline map source unit is outside or disordered within clip")
        previous = unit_end
    return offset


def prepare(source_path: Path, anchor_path: Path, clip_path: Path,
            anchor_offset_seconds: float | None, out: Path) -> dict[str, Any]:
    require(not out.exists(), "Clip timeline map is immutable; choose a new path")
    source, anchor = read_object(source_path), read_object(anchor_path)
    evidence = source["source"]["approvedWindow"]["evidence"]
    approval = read_object(Path(evidence["path"]))
    window = source["source"]["approvedWindow"]
    duration = media_duration(clip_path)
    complete_media = (_complete_media_window(window["startSeconds"],
                                             window["endSeconds"], duration)
                      and not approval.get("originalRecordingWindow"))
    if complete_media:
        # The approved window is the entire same-hash media, so source and
        # playback coordinates share the media origin. Derive it from the
        # approved start; never infer an offset from the first spoken word.
        offset = window["startSeconds"]
        require(anchor_offset_seconds is None
                or abs(anchor_offset_seconds - offset) <= EPSILON,
                "Complete-media anchor offset differs from the approved media origin")
    else:
        require(anchor_offset_seconds is not None,
                "Clip timeline map requires an explicit anchor offset")
        offset = anchor_offset_seconds
    value = {
        "schemaVersion": COMPLETE_MEDIA_SCHEMA if complete_media else CLIP_SCHEMA,
        "timebase": ("anchor_source_relative_to_complete_media" if complete_media
                     else "anchor_sermon_relative_to_clip_media"),
        "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
        "anchorManifestJsonSha256": interpretation.json_sha256(anchor),
        "clipMedia": {"path": str(clip_path.resolve()), "sha256": interpretation.sha256(clip_path)},
        "clipDurationSeconds": duration,
        "windowApproval": evidence,
        "anchorOffsetSeconds": offset,
        "anchorFirstStartSeconds": anchor["sourceUnits"][0]["start"],
        "anchorLastEndSeconds": anchor["sourceUnits"][-1]["end"],
    }
    if not complete_media:
        original_start, original_end = (seconds(part) for part in
                                        approval["originalRecordingWindow"].split("-"))
        value["originalRecordingStartSeconds"] = original_start
        value["originalRecordingEndSeconds"] = original_end
    validate(value, source, anchor)
    out.parent.mkdir(parents=True, exist_ok=True)
    interpretation.write_json(out, value)
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--clip-media", type=Path, required=True)
    parser.add_argument("--anchor-offset-seconds", type=float,
                        help="Required for extracted clips; complete media derives its source origin")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = prepare(args.source, args.anchor, args.clip_media, args.anchor_offset_seconds, args.out)
    print(json.dumps({"status": "clip_timebase_bound", "anchorOffsetSeconds": value["anchorOffsetSeconds"],
                      "map": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
