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
DERIVED_CLIP_SCHEMA = "sermon-clip-timeline-map-v3"
EPSILON = 0.025
MAX_TRAILING_SILENCE_SECONDS = 0.25
AAC_FRAME_SAMPLES = 1024
AAC_PADDING_BUDGET_FRAMES = 4
WINDOW_SAMPLE_TOLERANCE = 1


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


def probe_derived_audio(path: Path) -> dict[str, Any]:
    """Probe and decode only the derived clip; preserve measured AAC padding."""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "a:0",
            "-show_entries",
            "format=duration,size:stream=codec_name,start_time,duration,sample_rate,channels:frame=nb_samples",
            "-show_frames", "-of", "json", str(path),
        ], capture_output=True, text=True, check=True, timeout=300)
        probe = json.loads(result.stdout)
        streams = probe.get("streams", [])
        require(len(streams) == 1, "Derived clip must contain exactly one audio stream")
        stream = streams[0]
        fmt = probe.get("format", {})
        codec = stream.get("codec_name")
        sample_rate, channels = int(stream["sample_rate"]), int(stream["channels"])
        format_duration = float(fmt["duration"])
        stream_start = float(stream["start_time"])
        stream_duration = float(stream["duration"])
        samples = sum(int(frame["nb_samples"]) for frame in probe.get("frames", []))
        require(codec == "aac" and sample_rate == 44100 and channels == 1,
                "Derived clip audio must match the recorded AAC 44.1 kHz mono extraction")
        require(all(math.isfinite(value) and value > 0
                     for value in (format_duration, stream_duration))
                and math.isfinite(stream_start) and stream_start >= 0 and samples > 0,
                "Derived clip has invalid measured audio timing")
        container_samples = round(format_duration * sample_rate)
        padding_samples = container_samples - samples
        stream_samples = round(stream_duration * sample_rate)
        stream_padding_samples = stream_samples - samples
        padding_budget = AAC_FRAME_SAMPLES * AAC_PADDING_BUDGET_FRAMES
        require(0 <= padding_samples <= padding_budget
                and 0 <= stream_padding_samples <= padding_budget,
                "Derived clip container padding exceeds the AAC codec-specific budget")
        return {
            "codec": codec,
            "sampleRate": sample_rate,
            "channels": channels,
            "formatDurationSeconds": format_duration,
            "streamStartTimeSeconds": stream_start,
            "streamDurationSeconds": stream_duration,
            "decodedAudioSamples": samples,
            "decodedAudioDurationSeconds": samples / sample_rate,
            "containerPaddingSamples": padding_samples,
            "paddingBudgetSamples": padding_budget,
        }
    except FileNotFoundError as exc:
        raise ValueError("ffprobe is required to validate derived AAC clip evidence") from exc
    except (OSError, KeyError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Derived clip"):
            raise
        raise ValueError(f"Cannot probe derived clip audio: {path}: {exc}") from exc


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


def validate(value: dict[str, Any], source: dict[str, Any], anchor: dict[str, Any]) -> float:
    version = value.get("schemaVersion")
    require(version in {CLIP_SCHEMA, COMPLETE_MEDIA_SCHEMA, DERIVED_CLIP_SCHEMA},
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
    if version == DERIVED_CLIP_SCHEMA:
        return validate_derived_clip(value, source, anchor)
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


def validate_derived_clip(value: dict[str, Any], source: dict[str, Any],
                          anchor: dict[str, Any]) -> float:
    """Validate clip-relative anchors against an independently bound extracted clip."""
    media = source.get("source", {}).get("media", {})
    full = value["sourceMedia"]
    source_path = Path(full["path"])
    require(source_path.is_file()
            and interpretation.sha256(source_path) == full["sha256"] == media.get("sha256")
            and source_path.stat().st_size == full["sizeBytes"] == media.get("sizeBytes"),
            "Derived clip full source media identity mismatch")
    full_duration = media_duration(source_path)
    require(abs(full_duration - media.get("durationSeconds", -1)) <= 1e-6
            and full["durationSeconds"] == media["durationSeconds"],
            "Derived clip full source media duration mismatch")

    window = source.get("source", {}).get("approvedWindow", {})
    evidence = window.get("evidence", {})
    approval_path = Path(value["windowApproval"]["path"])
    require(window.get("status") == "approved" and window.get("humanApproval") is True
            and approval_path.is_file()
            and interpretation.sha256(approval_path) == value["windowApproval"]["sha256"]
            == evidence.get("sha256"),
            "Derived clip approval evidence hash mismatch")
    approval = read_object(approval_path)
    require(interpretation.json_sha256(approval) == value["windowApproval"]["jsonSha256"]
            == evidence.get("jsonSha256")
            and approval.get("schemaVersion") == "sermon-clip-window-approval-v1"
            and approval.get("sourceId") == source.get("source", {}).get("sourceId")
            and approval.get("sourceMediaSha256") == media.get("sha256")
            and approval.get("humanApproval") is True and approval.get("status") == "approved",
            "Derived clip approval identity mismatch")
    start, end = window.get("startSeconds"), window.get("endSeconds")
    require(type(start) in (int, float) and type(end) in (int, float)
            and math.isfinite(start) and math.isfinite(end)
            and 0 <= start < end <= full_duration
            and seconds(approval["startTime"]) == start
            and seconds(approval["endTime"]) == end
            and value["approvedWindow"] == {"startSeconds": start, "endSeconds": end}
            and value["approvedWindowSeconds"] == end - start,
            "Derived clip approved window is invalid or differs from approval")

    receipt_binding = value["extractionReceipt"]
    receipt_path = Path(receipt_binding["path"])
    require(receipt_path.is_file()
            and interpretation.sha256(receipt_path) == receipt_binding["sha256"],
            "Derived clip extraction receipt file hash mismatch")
    receipt = read_object(receipt_path)
    require(interpretation.json_sha256(receipt) == receipt_binding["jsonSha256"]
            and receipt.get("schemaVersion") == 1
            and receipt.get("operation") == "clip_and_normalize",
            "Derived clip extraction receipt identity mismatch")
    source_stat = source_path.stat()
    source_identity = receipt.get("source", {})
    require(source_identity.get("sha256") == full["sha256"]
            and source_identity.get("sizeBytes") == source_stat.st_size == full["sizeBytes"]
            and receipt.get("startSeconds") == start and receipt.get("endSeconds") == end
            and receipt.get("audioFilter") == "loudnorm=I=-16:TP=-1.5:LRA=11"
            and receipt.get("codec") == "aac" and receipt.get("sampleRate") == 44100
            and receipt.get("channels") == 1 and receipt.get("bitrate") == "64k",
            "Derived clip extraction receipt does not match source/window/configuration")

    clip = value["clipMedia"]
    clip_path = Path(clip["path"])
    require(clip_path.is_file()
            and interpretation.sha256(clip_path) == clip["sha256"]
            and clip_path.stat().st_size == clip["sizeBytes"],
            "Derived clip media hash or byte length mismatch")
    measured = probe_derived_audio(clip_path)
    require(measured == value["clipMediaProbe"]
            and value["clipDurationSeconds"] == measured["decodedAudioDurationSeconds"],
            "Derived clip measured audio duration or codec-padding evidence mismatch")
    expected_samples = (end - start) * measured["sampleRate"]
    require(abs(measured["decodedAudioSamples"] - expected_samples) <= WINDOW_SAMPLE_TOLERANCE,
            "Decoded derived clip duration differs from the exact approved-window sample count")
    require(measured["containerPaddingSamples"] <= AAC_FRAME_SAMPLES * AAC_PADDING_BUDGET_FRAMES
            and measured["paddingBudgetSamples"] == AAC_FRAME_SAMPLES * AAC_PADDING_BUDGET_FRAMES,
            "Derived clip AAC container-padding budget is invalid")

    origin = value["anchorOrigin"]
    require(origin["kind"] == "derived_clip_zero_equals_approved_window_start"
            and origin["absoluteSourceStartSeconds"] == start
            and value["timebase"] == "anchor_clip_relative_to_derived_window_audio"
            and value["anchorOffsetSeconds"] == 0,
            "Derived clip anchor origin does not match the approved extraction start")
    units = anchor.get("sourceUnits", [])
    require(isinstance(units, list) and bool(units), "Clip timeline map has no source units")
    require(value["anchorFirstStartSeconds"] == units[0]["start"]
            and value["anchorLastEndSeconds"] == units[-1]["end"],
            "Derived clip anchor endpoints differ from approved anchors")
    previous = 0.0
    for unit in units:
        unit_start, unit_end = unit.get("start"), unit.get("end")
        require(type(unit_start) in (int, float) and type(unit_end) in (int, float)
                and math.isfinite(unit_start) and math.isfinite(unit_end)
                and 0 <= unit_start < unit_end <= end - start
                and unit_start >= previous,
                "Derived clip source units are outside or disordered within the approved window")
        previous = unit_end
    return 0.0


def prepare(source_path: Path, anchor_path: Path, clip_path: Path,
            anchor_offset_seconds: float | None, out: Path, *,
            source_media_path: Path | None = None,
            extraction_receipt_path: Path | None = None) -> dict[str, Any]:
    require(not out.exists(), "Clip timeline map is immutable; choose a new path")
    source, anchor = read_object(source_path), read_object(anchor_path)
    evidence = source["source"]["approvedWindow"]["evidence"]
    approval = read_object(Path(evidence["path"]))
    window = source["source"]["approvedWindow"]
    if source_media_path is not None or extraction_receipt_path is not None:
        require(source_media_path is not None and extraction_receipt_path is not None,
                "Derived clip preparation requires both --source-media and --extraction-receipt")
        require(anchor_offset_seconds is None or anchor_offset_seconds == 0,
                "Derived clip anchor offset is always zero")
        full = read_object(source_path)["source"]["media"]
        source_stat = source_media_path.stat()
        full_identity = {
            "path": str(source_media_path.resolve()),
            "sha256": interpretation.sha256(source_media_path),
            "sizeBytes": source_stat.st_size,
            "durationSeconds": full["durationSeconds"],
        }
        require(full_identity["sha256"] == full["sha256"]
                and full_identity["sizeBytes"] == full["sizeBytes"]
                and abs(media_duration(source_media_path) - full["durationSeconds"]) <= 1e-6,
                "Full source media differs from the English Source Package")
        receipt_path = extraction_receipt_path.resolve()
        receipt = read_object(receipt_path)
        approval_window = {"path": evidence["path"], "sha256": evidence["sha256"],
                           "jsonSha256": evidence["jsonSha256"]}
        window_length = window["endSeconds"] - window["startSeconds"]
        measured = probe_derived_audio(clip_path)
        clip_samples_expected = window_length * measured["sampleRate"]
        require(abs(measured["decodedAudioSamples"] - clip_samples_expected)
                <= WINDOW_SAMPLE_TOLERANCE,
                "Decoded derived clip duration differs from the approved window")
        value = {
            "schemaVersion": DERIVED_CLIP_SCHEMA,
            "timebase": "anchor_clip_relative_to_derived_window_audio",
            "englishSourcePackageJsonSha256": interpretation.json_sha256(source),
            "anchorManifestJsonSha256": interpretation.json_sha256(anchor),
            "sourceMedia": full_identity,
            "approvedWindow": {"startSeconds": window["startSeconds"],
                               "endSeconds": window["endSeconds"]},
            "approvedWindowSeconds": window_length,
            "windowApproval": approval_window,
            "extractionReceipt": {
                "path": str(receipt_path),
                "sha256": interpretation.sha256(receipt_path),
                "jsonSha256": interpretation.json_sha256(receipt),
            },
            "clipMedia": {"path": str(clip_path.resolve()),
                          "sha256": interpretation.sha256(clip_path),
                          "sizeBytes": clip_path.stat().st_size},
            "clipMediaProbe": measured,
            "clipDurationSeconds": measured["decodedAudioDurationSeconds"],
            "anchorOrigin": {
                "kind": "derived_clip_zero_equals_approved_window_start",
                "absoluteSourceStartSeconds": window["startSeconds"],
            },
            "anchorOffsetSeconds": 0,
            "anchorFirstStartSeconds": anchor["sourceUnits"][0]["start"],
            "anchorLastEndSeconds": anchor["sourceUnits"][-1]["end"],
        }
        validate(value, source, anchor)
        out.parent.mkdir(parents=True, exist_ok=True)
        interpretation.write_json(out, value)
        return value
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
    parser.add_argument("--source-media", type=Path,
                        help="Full source media file to hash for a v3 derived-clip map")
    parser.add_argument("--extraction-receipt", type=Path,
                        help="clip_and_normalize cache receipt for a v3 derived-clip map")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    value = prepare(args.source, args.anchor, args.clip_media, args.anchor_offset_seconds, args.out,
                    source_media_path=args.source_media,
                    extraction_receipt_path=args.extraction_receipt)
    print(json.dumps({"status": "clip_timebase_bound", "anchorOffsetSeconds": value["anchorOffsetSeconds"],
                      "map": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
