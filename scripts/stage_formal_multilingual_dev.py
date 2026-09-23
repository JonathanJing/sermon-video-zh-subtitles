#!/usr/bin/env python3
"""Preflight and stage one complete, reviewed three-locale formal Dev page.

The output is a new directory. It never edits the existing POC catalog, uploads
files, or upgrades a Layer 4 candidate into an HTTP-verified release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
LOCALES = ("zh-Hans", "ko", "es")
PAGE_ID = re.compile(r"^[A-Za-z0-9_-]{1,160}$")


class StageError(ValueError):
    pass


def canonical_sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_package(path: Path, schema_name: str) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value))
    if errors:
        raise StageError(f"{path}: {errors[0].message}")
    return value


def assignment_map(values: list[str], option: str) -> dict[str, Path]:
    result = {}
    for value in values:
        locale, separator, path = value.partition("=")
        if not separator or locale not in LOCALES or locale in result or not path:
            raise StageError(f"{option}: expected one unique LOCALE=PATH per {', '.join(LOCALES)}")
        result[locale] = Path(path)
    if set(result) != set(LOCALES):
        raise StageError(f"{option}: all three locales are required: {', '.join(LOCALES)}")
    return result


def reviewed_candidate(candidate: dict) -> bool:
    groups = candidate["groups"]
    group_ids = [group["translationGroupId"] for group in groups]
    return (
        len(group_ids) == len(set(group_ids))
        and candidate["status"] == "human_translation_approved"
        and candidate["modelReview"]["status"] == "pass"
        and set(candidate["modelReview"]["reviewedGroupIds"]) == set(group_ids)
        and candidate["humanReview"]["translation"] == "approved"
        and bool(candidate["humanReview"]["reviewer"])
        and set(candidate["humanReview"]["reviewedGroupIds"]) == set(group_ids)
        and all(group["semanticReview"]["status"] == "pass"
                and group["languageReview"]["status"] == "pass"
                and all(check["status"] == "pass" for check in group["languageReview"]["checks"])
                for group in groups)
    )


def checked_file(path: Path, expected: str, label: str) -> Path:
    if not path.is_file() or file_sha(path) != expected:
        raise StageError(f"{label}: file absent or SHA-256 mismatch: {path}")
    return path


def local_artifact(package_path: Path, artifact: dict, label: str) -> Path:
    raw = Path(artifact["path"])
    path = raw if raw.is_absolute() else package_path.parent / raw
    checked_file(path, artifact["sha256"], label)
    if "jsonSha256" in artifact and canonical_sha(json.loads(path.read_text(encoding="utf-8"))) != artifact["jsonSha256"]:
        raise StageError(f"{label}: canonical JSON hash differs")
    return path


def decode_audio(path: Path, label: str) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    metadata = json.loads(probe.stdout or "{}")
    try:
        duration = float(metadata.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = float("nan")
    if (probe.returncode or len(metadata.get("streams", [])) != 1
            or not math.isfinite(duration) or duration <= 0):
        raise StageError(f"{label}: expected exactly one readable audio stream")
    decoded = subprocess.run(
        ["ffmpeg", "-nostdin", "-xerror", "-v", "error", "-i", str(path),
         "-map", "0:a:0", "-f", "null", "-"], capture_output=True, text=True, check=False,
    )
    if decoded.returncode:
        raise StageError(f"{label}: full audio decode failed: {decoded.stderr.strip()[:400]}")
    return duration


def asset_source(root: Path, path: str) -> Path:
    parsed = PurePosixPath(path)
    if (not path.startswith("/") or path.startswith("//") or ".." in parsed.parts
            or "\\" in path or "?" in path or "#" in path or "%" in path):
        raise StageError(f"unsafe public asset path: {path}")
    source = root.joinpath(*parsed.parts[1:])
    if not source.resolve().is_relative_to(root.resolve()):
        raise StageError(f"asset escapes --asset-root: {path}")
    return source


def preflight(args: argparse.Namespace) -> tuple[dict, dict[str, tuple[Path, str]], dict[str, dict]]:
    if not PAGE_ID.fullmatch(args.page_id):
        raise StageError("unsafe page ID")
    if args.default_target not in LOCALES:
        raise StageError("default target must be one of the three requested locales")
    source = read_package(args.source, "sermon-english-source-package-v1.schema.json")
    if (source["status"] != "ready_for_translation" or source["translationEligible"] is not True
            or source["source"]["approvedWindow"]["humanApproval"] is not True
            or source["review"]["humanApproval"] is not True or source["issues"]):
        raise StageError("Layer 1 source is not approved and ready for translation")
    if source["source"]["serviceDate"] != args.page_date:
        raise StageError("page date differs from Layer 1 service date")
    source_hash = canonical_sha(source)
    anchor_path = local_artifact(args.source, source["anchors"]["artifact"], "Layer 1 anchors")
    anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    source_ids = [unit["sourceUnitId"] for unit in anchor["sourceUnits"]]
    if not source_ids or len(source_ids) != len(set(source_ids)):
        raise StageError("Layer 1 anchor source units are missing or duplicated")
    candidate_paths = assignment_map(args.candidate, "--candidate")
    review_paths = assignment_map(args.human_review_receipt, "--human-review-receipt")
    content_review_paths = assignment_map(args.content_review_receipt, "--content-review-receipt")
    audio_paths = assignment_map(args.audio_package, "--audio-package")
    audio_review_paths = assignment_map(args.audio_human_review_receipt, "--audio-human-review-receipt")
    release_paths = assignment_map(args.release, "--release")
    files: dict[str, tuple[Path, str]] = {}
    targets = {}
    for locale in LOCALES:
        candidate = read_package(candidate_paths[locale], "sermon-target-language-candidate-v2.schema.json")
        human_receipt = read_package(review_paths[locale], "sermon-target-language-human-review-receipt-v1.schema.json")
        audio = read_package(audio_paths[locale], "sermon-target-language-audio-package-v1.schema.json")
        audio_receipt = read_package(
            audio_review_paths[locale], "sermon-target-language-audio-human-review-receipt-v1.schema.json")
        release = read_package(release_paths[locale], "sermon-target-language-release-package-v1.schema.json")
        candidate_hash = canonical_sha(candidate)
        audio_hash = canonical_sha(audio)
        if (candidate["targetLocale"] != locale or candidate["englishSourcePackageJsonSha256"] != source_hash
                or candidate["anchorManifestSha256"] != source["anchors"]["artifact"]["jsonSha256"]
                or not reviewed_candidate(candidate)):
            raise StageError(f"{locale}: Layer 2 locale, source, anchor, or human review is invalid")
        group_ids = [group["translationGroupId"] for group in candidate["groups"]]
        translated_source_ids = [source_id for group in candidate["groups"] for source_id in group["sourceUnitIds"]]
        if translated_source_ids != source_ids:
            raise StageError(f"{locale}: Layer 2 groups do not cover Layer 1 source units in order")
        if (human_receipt["decision"] != "approved" or human_receipt["targetLocale"] != locale
                or human_receipt["englishSourcePackageJsonSha256"] != source_hash
                or human_receipt["anchorManifestJsonSha256"] != source["anchors"]["artifact"]["jsonSha256"]
                or human_receipt["translationPolicySha256"] != candidate["translationPolicySha256"]
                or human_receipt["candidateJsonSha256"] != candidate_hash
                or human_receipt["reviewer"] != candidate["humanReview"]["reviewer"]
                or human_receipt["reviewedAt"] != candidate["humanReview"]["reviewedAt"]
                or human_receipt["reviewedGroupIds"] != group_ids
                or [row["translationGroupId"] for row in human_receipt["groupReviews"]] != group_ids
                or any(row["decision"] != "approved" for row in human_receipt["groupReviews"])):
            raise StageError(f"{locale}: independent Layer 2 human review receipt is invalid")
        if (audio["targetLocale"] != locale or audio["englishSourcePackageJsonSha256"] != source_hash
                or audio["targetLanguageCandidateJsonSha256"] != candidate_hash
                or audio["status"] != "human_reviewed" or audio["machineScreening"]["status"] != "pass"
                or audio["humanReview"]["status"] != "approved"
                or audio["humanReview"]["humanApproval"] is not True
                or audio["humanReview"]["fullPlayback"] != "approved"
                or audio["voice"] is None or audio["voice"]["authorizationStatus"] != "authorized"
                or audio["voice"]["targetLocaleCapability"] != "reviewed" or audio["issues"]
                or audio["track"] is None):
            raise StageError(f"{locale}: Layer 3 package is not fully reviewed and bound")
        if (audio_receipt["targetLocale"] != locale
                or audio_receipt["englishSourcePackageJsonSha256"] != source_hash
                or audio_receipt["targetLanguageCandidateJsonSha256"] != candidate_hash
                or audio_receipt["targetLanguageAudioPackageJsonSha256"] != audio_hash
                or audio_receipt["trackSha256"] != audio["track"]["sha256"]
                or audio_receipt["reviewedBy"] != audio["humanReview"]["reviewedBy"]
                or audio_receipt["reviewedAt"] != audio["humanReview"]["reviewedAt"]
                or audio_receipt["reviewedUnitIds"] != group_ids):
            raise StageError(f"{locale}: independent full-playback and 1x video-sync receipt is invalid")
        expected_units = {group["translationGroupId"]: hashlib.sha256(group["targetText"].encode()).hexdigest()
                          for group in candidate["groups"]}
        observed_units = {unit["textGroupId"]: unit["targetTextSha256"] for unit in audio["units"]}
        if (len(observed_units) != len(audio["units"]) or observed_units != expected_units
                or [unit["textGroupId"] for unit in audio["units"]] != group_ids):
            raise StageError(f"{locale}: Layer 3 units differ from reviewed Layer 2 text groups")
        if (release["pageId"] != args.page_id or release["targetLocale"] != locale
                or release["sourceLocale"] != "en"
                or release["targetLanguageCandidateJsonSha256"] != candidate_hash
                or release["targetLanguageAudioPackageJsonSha256"] != audio_hash
                or release["status"] != "candidate" or release["contentStatus"] != "human_reviewed"
                or release["audioStatus"] != "human_reviewed"
                or release["interfaceLocale"] != locale or release["contentLocale"] != locale
                or release["audioLocale"] != locale or release["issues"]
                or any(release[gate] != {"status": "not_run", "evidenceSha256": None}
                       for gate in ("httpVerification", "deviceAcceptance", "venueAcceptance"))):
            raise StageError(f"{locale}: Layer 4 candidate identity or gate is invalid")
        track = local_artifact(audio_paths[locale], audio["track"], f"{locale} track") if audio["track"] else None
        if track is None or audio["captions"] is None or audio["schedule"] is None or not audio["units"]:
            raise StageError(f"{locale}: measured track, captions, schedule, and units are required")
        track_duration = decode_audio(track, f"{locale} track")
        captions_path = local_artifact(audio_paths[locale], audio["captions"], f"{locale} captions")
        captions = json.loads(captions_path.read_text(encoding="utf-8"))
        schedule_path = local_artifact(audio_paths[locale], audio["schedule"], f"{locale} schedule")
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        if (schedule.get("targetLocale") != locale or schedule.get("timingKind") != "measured_target_audio"
                or schedule.get("status") != "pass" or schedule.get("issues")
                or not isinstance(schedule.get("trackDurationSeconds"), (int, float))
                or not math.isfinite(schedule["trackDurationSeconds"])
                or not isinstance(schedule.get("entries"), list)
                or not isinstance(captions.get("cues"), list)):
            raise StageError(f"{locale}: Layer 3 schedule lacks measured same-locale cues")
        if abs(schedule["trackDurationSeconds"] - track_duration) > 0.2:
            raise StageError(f"{locale}: measured schedule duration differs from decoded Layer 3 track")
        for index, unit in enumerate(audio["units"]):
            unit_file = local_artifact(audio_paths[locale], unit["audio"], f"{locale} unit {index}")
            unit_duration = decode_audio(unit_file, f"{locale} unit {index}")
            if abs(unit_duration - unit["durationSeconds"]) > 0.2:
                raise StageError(f"{locale} unit {index}: measured duration differs from decoded audio")
        seen_roles = set()
        seen_paths = set()
        for asset in release["assets"]:
            role, path = asset["role"], asset["path"]
            expected_paths = {
                "content": f"/content/{args.page_id}/{locale}.json",
                "audio": f"/media/{args.page_id}/{locale}.mp3",
                "captions": f"/captions/{args.page_id}/{locale}.json",
            }
            if role not in expected_paths or path != expected_paths[role]:
                raise StageError(f"{locale}: unexpected {role} asset path: {path}")
            if path in seen_paths or role in seen_roles:
                raise StageError(f"{locale}: duplicate asset path or role: {path}")
            seen_paths.add(path)
            seen_roles.add(role)
            if path.startswith(("/releases/", "/multilingual", "/index.html")):
                raise StageError(f"{locale}: release may not overwrite application/catalog files")
            source_asset = checked_file(asset_source(args.asset_root, path), asset["sha256"], f"{locale} {role}")
            if path in files and files[path] != (source_asset, asset["sha256"]):
                raise StageError(f"asset path shared with a different source: {path}")
            files[path] = (source_asset, asset["sha256"])
            if role == "audio":
                if asset["sha256"] != audio["track"]["sha256"]:
                    raise StageError(f"{locale}: release audio differs from Layer 3 track")
                if abs(decode_audio(source_asset, f"{locale} release audio") - track_duration) > 0.2:
                    raise StageError(f"{locale}: release audio duration differs from Layer 3")
            if role == "captions" and asset["sha256"] != audio["captions"]["sha256"]:
                raise StageError(f"{locale}: release captions differ from Layer 3")
            if role == "content":
                content = read_package(source_asset, "sermon-formal-dev-content-v1.schema.json")
                content_receipt = read_package(
                    content_review_paths[locale], "sermon-formal-dev-content-review-receipt-v1.schema.json")
                if (content["pageId"] != args.page_id or content["locale"] != locale
                        or content["englishSourcePackageJsonSha256"] != source_hash
                        or content["targetLanguageCandidateJsonSha256"] != candidate_hash
                        or content["targetLanguageAudioPackageJsonSha256"] != audio_hash):
                    raise StageError(f"{locale}: formal content identity or upstream hash differs")
                if (content_receipt["pageId"] != args.page_id or content_receipt["targetLocale"] != locale
                        or content_receipt["englishSourcePackageJsonSha256"] != source_hash
                        or content_receipt["targetLanguageCandidateJsonSha256"] != candidate_hash
                        or content_receipt["targetLanguageAudioPackageJsonSha256"] != audio_hash
                        or content_receipt["contentJsonSha256"] != canonical_sha(content)
                        or set(content_receipt["reviewedFields"]) != {
                            "series", "title", "speaker", "scripture", "date", "summary"}):
                    raise StageError(f"{locale}: independent content metadata review is invalid")
                if abs(content["durationSeconds"] - track_duration) > 0.2:
                    raise StageError(f"{locale}: content duration differs from decoded Layer 3 track")
                expected_cues = schedule["entries"]
                caption_cues = captions["cues"]
                actual_cues = content["cues"]
                if len(actual_cues) != len(expected_cues) or len(actual_cues) != len(caption_cues):
                    raise StageError(f"{locale}: content cue count differs from measured schedule")
                previous_end = 0.0
                groups = {group["translationGroupId"]: group for group in candidate["groups"]}
                for content_cue, scheduled_cue, caption_cue in zip(actual_cues, expected_cues, caption_cues):
                    group = groups.get(content_cue["textGroupId"])
                    if (group is None or content_cue["textGroupId"] != scheduled_cue.get("textGroupId")
                            or content_cue["textGroupId"] != caption_cue.get("textGroupId")
                            or content_cue["sourceUnitIds"] != group["sourceUnitIds"]
                            or content_cue["sourceUnitIds"] != scheduled_cue.get("sourceUnitIds")
                            or content_cue["text"] != group["targetText"]
                            or content_cue["text"] != caption_cue.get("text")
                            or content_cue["start"] != scheduled_cue.get("plannedStart")
                            or content_cue["end"] != scheduled_cue.get("plannedEnd")
                            or content_cue["start"] != caption_cue.get("start")
                            or content_cue["end"] != caption_cue.get("end")
                            or not math.isfinite(content_cue["start"]) or not math.isfinite(content_cue["end"])
                            or content_cue["start"] < previous_end - 0.02
                            or content_cue["end"] <= content_cue["start"]
                            or content_cue["end"] > content["durationSeconds"] + 0.1):
                        raise StageError(f"{locale}: content cues differ from measured schedule")
                    previous_end = content_cue["end"]
                if [cue["textGroupId"] for cue in actual_cues] != group_ids:
                    raise StageError(f"{locale}: content does not cover reviewed text groups in order")
        if not {"content", "audio", "captions"}.issubset(seen_roles):
            raise StageError(f"{locale}: content, audio, and captions assets are required")
        release_url = f"/releases/{args.page_id}/{locale}.json"
        files[release_url] = (release_paths[locale], file_sha(release_paths[locale]))
        targets[locale] = {
            "releasePackageUrl": release_url,
            "releasePackageJsonSha256": file_sha(release_paths[locale]),
            "contentStatus": "human_reviewed",
            "audioStatus": "human_reviewed",
            "capabilities": ["text", "captions", "audio"],
        }
    catalog = {
        "schemaVersion": "sermon-multilingual-catalog-v2",
        "generatedAt": args.generated_at,
        "defaultPageId": args.page_id,
        "pages": [{"id": args.page_id, "date": args.page_date, "sourceLocale": "en",
                   "sourceIdentitySha256": source_hash, "defaultTargetLocale": args.default_target,
                   "targets": targets}],
    }
    schema = json.loads((ROOT / "schemas/sermon-multilingual-catalog-v2.schema.json").read_text())
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(catalog))
    if errors:
        raise StageError(f"catalog: {errors[0].message}")
    return catalog, files, targets


def stage(args: argparse.Namespace) -> dict:
    catalog, files, targets = preflight(args)
    if args.out.exists():
        raise StageError(f"output already exists: {args.out}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{args.out.name}-", dir=args.out.parent))
    try:
        for public_path, (source, expected_hash) in files.items():
            destination = temporary.joinpath(*PurePosixPath(public_path).parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if file_sha(destination) != expected_hash:
                raise StageError(f"staged file differs: {public_path}")
        catalog_path = temporary / "multilingual-v2.json"
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
        receipt = {"schemaVersion": "sermon-formal-dev-stage-receipt-v1", "pageId": args.page_id,
                   "catalogPath": "/multilingual-v2.json", "catalogSha256": file_sha(catalog_path),
                   "sourceIdentitySha256": catalog["pages"][0]["sourceIdentitySha256"],
                   "targetLocales": list(LOCALES), "releasePackageSha256": {
                       locale: targets[locale]["releasePackageJsonSha256"] for locale in LOCALES},
                   "assetCount": len(files), "deploymentStatus": "not_deployed",
                   "httpVerification": "not_run", "deviceAcceptance": "not_run"}
        (temporary / "stage-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        os.rename(temporary, args.out)
        return receipt
    except Exception:
        shutil.rmtree(temporary)
        raise


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--human-review-receipt", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--content-review-receipt", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--audio-package", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--audio-human-review-receipt", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--release", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--page-date", required=True)
    parser.add_argument("--default-target", default="zh-Hans")
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        receipt = stage(parse_args(argv if argv is not None else sys.argv[1:]))
    except (StageError, OSError, json.JSONDecodeError, subprocess.SubprocessError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
