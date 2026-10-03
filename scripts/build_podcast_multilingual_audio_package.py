#!/usr/bin/env python3
"""Assemble natural-rate ES/KO podcast renders into a review-pending Layer 3 package."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import wave
try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:  # The producer remains runnable in the standard Python runtime.
    Draft202012Validator = None
    FormatChecker = None


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sermon-target-language-audio-package-v3-multilingual-podcast.schema.json"
GAP_SECONDS = 0.1


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_sha(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Refusing to replace immutable artifact: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def vtt_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    hours, rem = divmod(millis, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", choices=("es", "ko"), required=True)
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--waiver", type=Path, required=True)
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--workers", type=Path, required=True)
    parser.add_argument("--voice-extension-dir", type=Path, required=True)
    parser.add_argument("--render-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    job, source, candidate, waiver, route, worker_data = map(
        load, (args.job, args.source, args.candidate, args.waiver, args.route, args.workers))
    rendered = load(args.render_root / "rendered-units.json")
    require = lambda condition, message: (_ for _ in ()).throw(ValueError(message)) if not condition else None
    require(job.get("targetLocale") == args.locale == candidate.get("targetLocale"),
            "Locale does not match the frozen speech job and candidate")
    require(candidate.get("status") == "machine_review_pass_human_review_pending"
            and candidate.get("releaseEligible") is False
            and waiver.get("humanApproval") is False
            and waiver.get("releaseEligible") is False
            and waiver.get("audioHumanReviewRequired") is True,
            "Expected a review-waived, machine-passed, unreleased candidate")
    require(route.get("status") == "approved" and len(job.get("units", [])) == 839
            and len(candidate.get("groups", [])) == 839 and len(route.get("groups", [])) == 839,
            "Source, candidate, route, and speech job must cover all 839 groups")
    require(rendered.get("jobJsonSha256") == json_sha(job)
            and rendered.get("candidateJsonSha256") == json_sha(candidate)
            and rendered.get("sourceJsonSha256") == json_sha(source)
            and rendered.get("routeJsonSha256") == json_sha(route)
            and rendered.get("reviewWaiverJsonSha256") == json_sha(waiver)
            and len(rendered.get("units", [])) == 839,
            "Rendered output is incomplete or bound to different inputs")

    groups = {row["translationGroupId"]: row for row in candidate["groups"]}
    route_rows = {row["translationGroupId"]: row for row in route["groups"]}
    render_rows = {row["groupId"]: row for row in rendered["units"]}
    require(len(render_rows) == 839 and set(groups) == set(route_rows) == set(render_rows),
            "Rendered groups differ from the frozen candidate or speaker route")
    workers = {row["workerId"]: row for row in worker_data["workers"]}
    job_workers = {row["workerId"]: row for row in job["workers"]}
    require(set(workers) == set(job_workers) and len(workers) == 2,
            "Runtime and job worker identities differ")
    adapters: dict[str, dict[str, Any]] = {}
    authorizations: dict[str, dict[str, Any]] = {}
    for worker in worker_data["workers"]:
        adapter_path = args.voice_extension_dir / f"speech-adapter-{worker['speakerId']}.json"
        adapters[worker["speakerId"]] = load(adapter_path)
        authorization_path = args.voice_extension_dir / f"voice-authority-{worker['speakerId']}.json"
        authorizations[worker["speakerId"]] = load(authorization_path)
        bound = job_workers[worker["workerId"]]
        require(json_sha(adapters[worker["speakerId"]]) == bound["adapterJsonSha256"]
                and file_sha(authorization_path) == bound["authorizationJsonSha256"],
                f"Voice route evidence changed for {worker['speakerId']}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    track_path = args.out_dir / f"{args.locale}-track.wav"
    captions_path = args.out_dir / "captions.vtt"
    schedule_path = args.out_dir / "schedule.json"
    package_path = args.out_dir / "audio-package.candidate.json"
    for path in (track_path, captions_path, schedule_path, package_path):
        require(not path.exists(), f"Refusing to replace existing artifact: {path}")

    ordered = sorted(job["units"], key=lambda row: row["unitIndex"])
    schedule_units = []
    package_units = []
    vtt = ["WEBVTT", ""]
    cursor = 0.0
    audio_params: tuple[int, int, int, str, str] | None = None
    with wave.open(str(track_path), "wb") as track:
        for index, unit in enumerate(ordered):
            group_id = unit["translationGroupId"]
            group = groups[group_id]
            row = render_rows[group_id]
            route_row = route_rows[group_id]
            worker = workers[unit["workerId"]]
            require(group.get("targetText") == unit["text"]
                    and row.get("textSha256") == hashlib.sha256(unit["text"].encode()).hexdigest()
                    and row.get("speakerId") == unit["speakerId"] == route_row.get("speakerId")
                    and row.get("checkpointSha256") == worker["checkpointSha256"]
                    and row.get("workerId") == worker["workerId"],
                    f"Rendered identity mismatch: {group_id}")
            rel = Path(unit["outputRelativePath"])
            audio_path = (args.render_root / rel).resolve()
            require(audio_path.is_relative_to(args.render_root.resolve()) and audio_path.is_file(),
                    f"Missing or escaped audio path: {group_id}")
            render_receipt_path = audio_path.with_suffix(".render.json")
            require(render_receipt_path.is_file(), f"Missing render receipt: {group_id}")
            render_receipt = load(render_receipt_path)
            actual_sha = file_sha(audio_path)
            with wave.open(str(audio_path), "rb") as clip:
                params = clip.getparams()
                frames = clip.readframes(params.nframes)
            require(actual_sha == row.get("audioSha256") == render_receipt.get("audioSha256")
                    and params.nframes > 0 and params.framerate > 0 and params.nchannels == 1
                    and params.comptype == "NONE",
                    f"Audio bytes or format do not match the render receipt: {group_id}")
            current_params = (params.nchannels, params.sampwidth, params.framerate,
                              params.comptype, params.compname)
            if audio_params is None:
                audio_params = current_params
                track.setnchannels(params.nchannels)
                track.setsampwidth(params.sampwidth)
                track.setframerate(params.framerate)
                gap_frames = round(GAP_SECONDS * params.framerate)
                gap = b"\0" * (gap_frames * params.nchannels * params.sampwidth)
            require(current_params == audio_params,
                    f"Sample rate or channel count changed at {group_id}")
            start = cursor
            track.writeframesraw(frames)
            duration = params.nframes / params.framerate
            cursor += duration
            end = cursor
            vtt.extend([str(index + 1), f"{vtt_time(start)} --> {vtt_time(end)}",
                        unit["text"], ""])
            schedule_units.append({"index": index, "textGroupId": group_id,
                                   "sourceUnitIds": unit["sourceUnitIds"],
                                   "speakerId": unit["speakerId"], "workerId": unit["workerId"],
                                   "targetText": unit["text"], "audioPath": str(audio_path),
                                   "audioSha256": actual_sha, "startSeconds": round(start, 6),
                                   "endSeconds": round(end, 6), "durationSeconds": round(duration, 6),
                                   "sourceTimebase": "source audio order only; no duration fit or video sync"})
            package_units.append({"textGroupId": group_id,
                                  "targetTextSha256": hashlib.sha256(unit["text"].encode()).hexdigest(),
                                  "speakerId": unit["speakerId"],
                                  "checkpointSha256": worker["checkpointSha256"],
                                  "workerId": unit["workerId"],
                                  "audio": {"path": str(audio_path), "sha256": actual_sha},
                                  "durationSeconds": round(duration, 6),
                                  "receipt": {"path": str(render_receipt_path),
                                              "sha256": file_sha(render_receipt_path),
                                              "jsonSha256": json_sha(render_receipt)}})
            if index + 1 < len(ordered):
                track.writeframesraw(gap)
                cursor += GAP_SECONDS

    captions_path.write_text("\n".join(vtt), encoding="utf-8")
    schedule = {"schemaVersion": "podcast-audio-schedule-v1", "locale": args.locale,
                "timingBasis": "concatenated target audio, measured natural unit durations",
                "interUnitGapSeconds": GAP_SECONDS, "totalDurationSeconds": round(cursor, 3),
                "videoSync": "not_applicable_audio_only", "units": schedule_units}
    write_json(schedule_path, schedule)

    voices = []
    for worker in worker_data["workers"]:
        adapter = adapters[worker["speakerId"]]
        bound = job_workers[worker["workerId"]]
        voices.append({"speakerId": worker["speakerId"], "provider": adapter["provider"],
                       "model": adapter["model"], "checkpointSha256": worker["checkpointSha256"],
                       "targetLocaleCapability": adapter["capabilityStatus"],
                       "authorizationStatus": "authorized",
                       "authorizationJsonSha256": bound["authorizationJsonSha256"]})
    downstream = json_sha({"candidate": json_sha(candidate), "job": json_sha(job),
                           "route": json_sha(route), "waiver": json_sha(waiver),
                           "track": file_sha(track_path), "units": [row["audio"]["sha256"]
                                                                      for row in package_units]})
    package = {"schemaVersion": "sermon-target-language-audio-package-v3-multilingual-podcast",
               "packageId": f"podcast-{args.locale}-{downstream[:16]}",
               "englishSourcePackageJsonSha256": json_sha(source),
               "targetLanguageCandidateJsonSha256": json_sha(candidate),
               "targetLanguageSpeechJobJsonSha256": json_sha(job),
               "speakerRouteJsonSha256": json_sha(route),
               "contentReviewWaiverJsonSha256": json_sha(waiver),
               "targetLocale": args.locale, "status": "candidate",
               "ratePolicy": "natural_no_time_stretch",
               "videoSyncPolicy": "not_applicable_audio_only", "voices": voices,
               "units": package_units,
               "track": {"path": str(track_path), "sha256": file_sha(track_path)},
               "captions": {"path": str(captions_path), "sha256": file_sha(captions_path)},
               "schedule": {"path": str(schedule_path), "sha256": file_sha(schedule_path),
                            "jsonSha256": json_sha(schedule)},
               "machineScreening": {"status": "not_run", "model": None, "coverage": 0.0},
               "humanReview": {"status": "pending", "humanApproval": False,
                               "reviewedBy": None, "reviewedAt": None,
                               "fullPlayback": "pending", "audioTimelineReview": "pending",
                               "videoSync": "not_applicable",
                               "contentReview": "waived_by_user_not_approved"},
               "issues": [], "releaseEligible": False,
               "downstreamInvalidationKey": downstream}
    if Draft202012Validator is not None:
        schema = json.loads((ROOT / "schemas" / SCHEMA).read_text(encoding="utf-8"))
        errors = sorted(Draft202012Validator(
            schema, format_checker=FormatChecker()).iter_errors(package),
            key=lambda err: list(err.absolute_path))
        if errors:
            raise ValueError("Package schema errors: " + "; ".join(
                f"/{'/'.join(map(str, err.absolute_path))}: {err.message}" for err in errors))
    else:
        require(set(package) == {"schemaVersion", "packageId", "englishSourcePackageJsonSha256",
                                "targetLanguageCandidateJsonSha256", "targetLanguageSpeechJobJsonSha256",
                                "speakerRouteJsonSha256", "contentReviewWaiverJsonSha256", "targetLocale",
                                "status", "ratePolicy", "videoSyncPolicy", "voices", "units", "track",
                                "captions", "schedule", "machineScreening", "humanReview", "issues",
                                "releaseEligible", "downstreamInvalidationKey"},
                "Package fields differ from the versioned v3 schema")
        require(package["schemaVersion"] == "sermon-target-language-audio-package-v3-multilingual-podcast"
                and package["targetLocale"] in {"es", "ko"}
                and package["status"] == "candidate" and package["releaseEligible"] is False
                and package["humanReview"]["humanApproval"] is False
                and package["humanReview"]["audioTimelineReview"] == "pending"
                and len(package["units"]) == 839 and len(package["voices"]) == 2,
                "Package fails structural v3 schema checks")
    write_json(package_path, package)
    print(json.dumps({"targetLocale": args.locale, "units": len(package_units),
                      "track": str(track_path), "durationSeconds": round(cursor, 3),
                      "package": str(package_path), "releaseEligible": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
