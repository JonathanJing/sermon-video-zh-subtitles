#!/usr/bin/env python3
"""Stage reviewed dubbing beside the published Sep 27 full-text video page.

This is a separate Layer 4 page extension. It does not convert the existing
single-candidate text-only Release Package into a formal audio Release Package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from jsonschema import Draft202012Validator

try:
    from scripts import stage_formal_multilingual_dev as stage
except ImportError:
    import stage_formal_multilingual_dev as stage


ROOT = Path(__file__).resolve().parents[1]
PAGE_ID = "2026-09-27-weekend-sermon-drive-530"
PAGE_DATA_SHA256 = "fa071d1b7678eeaad7c5ae4c1539d2b6f8b908322b2e12283881b0be304362f3"
LOCALES = ("zh-Hans", "ko", "es")
SCHEMA = "sermon-full-video-audio-extension-v1.schema.json"
SCRIPT = ROOT / "firebase/dev/public/sep27-page-audio-extension.mjs"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(result, dict), f"Expected JSON object: {path}")
    return result


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def assignment_map(values: list[str], option: str) -> dict[str, Path]:
    result = stage.assignment_map(values, option)
    require(set(result) == set(LOCALES), f"{option}: require exactly zh-Hans, ko, es")
    return result


def content_cues(content: dict, candidate: dict, source_hash: str, locale: str) -> list[str]:
    require(content.get("schemaVersion") == "sermon-full-video-text-content-v1"
            and content.get("pageId") == PAGE_ID
            and content.get("targetLocale") == locale
            and content.get("status") == "human_reviewed"
            and content.get("englishSourcePackageJsonSha256") == source_hash
            and content.get("targetLanguageCandidateJsonSha256") == stage.canonical_sha(candidate)
            and candidate.get("targetLocale") == locale
            and candidate.get("englishSourcePackageJsonSha256") == source_hash
            and stage.reviewed_candidate(candidate),
            f"{locale}: published full display text is not bound to the approved candidate")
    cues = content.get("cues", [])
    groups = candidate["groups"]
    require(len(cues) == len(groups)
            and all(cue["textGroupId"] == group["translationGroupId"]
                    and cue["sourceUnitIds"] == group["sourceUnitIds"]
                    and cue["text"] == group["targetText"]
                    for cue, group in zip(cues, groups)),
            f"{locale}: published cues differ from full approved text")
    return [unit for group in groups for unit in group["sourceUnitIds"]]


def checked_locale(*, locale: str, source_hash: str, source_duration: float,
                   content: dict, display: dict, spoken: dict, audio: dict,
                   review: dict, screening: dict, audio_path: Path,
                   audio_package_path: Path) -> tuple[dict, Path, Path]:
    full_ids = content_cues(content, display, source_hash, locale)
    spoken_ids = [unit for group in spoken["groups"] for unit in group["sourceUnitIds"]]
    require(spoken.get("targetLocale") == locale
            and spoken.get("englishSourcePackageJsonSha256") == source_hash
            and stage.reviewed_candidate(spoken)
            and spoken_ids == full_ids,
            f"{locale}: reviewed spoken script does not cover the same complete source")
    spoken_hash = stage.canonical_sha(spoken)
    audio_hash = stage.canonical_sha(audio)
    group_ids = [group["translationGroupId"] for group in spoken["groups"]]
    require(audio.get("status") == "human_reviewed"
            and audio.get("targetLocale") == locale
            and audio.get("englishSourcePackageJsonSha256") == source_hash
            and audio.get("targetLanguageCandidateJsonSha256") == spoken_hash
            and audio.get("humanReview", {}).get("humanApproval") is True
            and audio.get("humanReview", {}).get("fullPlayback") == "approved"
            and audio.get("track") is not None
            and audio.get("captions") is not None
            and audio.get("schedule") is not None
            and [unit["textGroupId"] for unit in audio.get("units", [])] == group_ids,
            f"{locale}: audio does not belong to the human-reviewed spoken script")
    require(all(unit["targetTextSha256"] == hashlib.sha256(
                group["targetText"].encode("utf-8")).hexdigest()
                for unit, group in zip(audio["units"], spoken["groups"])),
            f"{locale}: audio units differ from the spoken text")
    require(review.get("schemaVersion") == "sermon-target-language-audio-human-review-receipt-v2"
            and review.get("targetLocale") == locale
            and review.get("englishSourcePackageJsonSha256") == source_hash
            and review.get("targetLanguageCandidateJsonSha256") == spoken_hash
            and review.get("targetLanguageAudioPackageJsonSha256") == audio_hash
            and review.get("trackSha256") == audio["track"]["sha256"]
            and review.get("decision") == "approved"
            and review.get("fullPlayback") == "approved"
            and review.get("videoSync1x") == "approved"
            and review.get("reviewedUnitIds") == group_ids
            and review.get("reviewedBy") == audio["humanReview"]["reviewedBy"]
            and review.get("reviewedAt") == audio["humanReview"]["reviewedAt"]
            and review.get("checks") == {name: "approved" for name in (
                "pronunciation", "naturalness", "completeness", "scripture",
                "voiceIdentity", "synchronization")}
            and review.get("issues") == [],
            f"{locale}: full listening and 1x sync review differs from the audio")
    stage.validate_audio_screening_review(audio, review, screening)
    track = stage.local_artifact(audio_package_path, audio["track"], f"{locale} track")
    caption_path = stage.local_artifact(audio_package_path, audio["captions"], f"{locale} captions")
    schedule_path = stage.local_artifact(audio_package_path, audio["schedule"], f"{locale} schedule")
    require(track.suffix == ".mp3", f"{locale}: web dubbing must be an MP3")
    duration = stage.decode_audio(track, f"{locale} track")
    require(abs(duration - source_duration) <= 0.2,
            f"{locale}: dubbed track does not span the complete video")
    captions, schedule = read(caption_path), read(schedule_path)
    require(schedule.get("status") == "pass" and schedule.get("issues") == []
            and schedule.get("targetLocale") == locale
            and len(captions.get("cues", [])) == len(group_ids)
            and len(schedule.get("entries", [])) == len(group_ids),
            f"{locale}: reviewed spoken captions or measured schedule is incomplete")
    for group, cue, entry in zip(spoken["groups"], captions["cues"], schedule["entries"]):
        require(group["translationGroupId"] == cue["textGroupId"] == entry["textGroupId"]
                and cue["text"] == group["targetText"]
                and entry["sourceUnitIds"] == group["sourceUnitIds"]
                and cue["start"] == entry["plannedStart"]
                and cue["end"] == entry["plannedEnd"],
                f"{locale}: captions do not follow the reviewed spoken script")
    require(stage.file_sha(audio_path) == audio["track"]["sha256"],
            f"{locale}: supplied audio file differs from the Layer 3 package")
    return ({
        "displayCandidateJsonSha256": stage.canonical_sha(display),
        "spokenCandidateJsonSha256": spoken_hash,
        "audioPackageJsonSha256": audio_hash,
        "audioHumanReviewReceiptJsonSha256": stage.canonical_sha(review),
        "machineScreeningReceiptJsonSha256": stage.canonical_sha(screening),
        "durationSeconds": duration,
        "spokenCueCount": len(group_ids),
    }, track, caption_path)


def build(args: argparse.Namespace) -> Path:
    require(not args.out.exists(), "Choose a new immutable output directory")
    base = args.base_public
    page = base / "pages" / PAGE_ID
    data_file = page / "page-data.js"
    require(stage.file_sha(data_file) == PAGE_DATA_SHA256,
            "Published full-text page-data.js differs; do not replace approved display text")
    source = stage.read_package(args.source, "sermon-english-source-package-v1.schema.json")
    source_hash = stage.canonical_sha(source)
    duration = source["source"]["media"]["durationSeconds"]
    anchor_ref = source["anchors"]["artifact"]
    anchor_path = stage.checked_file(Path(anchor_ref["path"]), anchor_ref["sha256"],
                                     "approved English anchors")
    anchor = read(anchor_path)
    require(stage.canonical_sha(anchor) == anchor_ref["jsonSha256"],
            "English anchor JSON identity changed")
    source_ids = [unit["sourceUnitId"] for unit in anchor["sourceUnits"]]
    require(source["status"] == "ready_for_translation"
            and source["source"]["approvedWindow"]["startSeconds"] == 0
            and source["source"]["approvedWindow"]["endSeconds"] == duration,
            "This extension requires the approved complete source video")
    assignments = {name: assignment_map(getattr(args, name), f"--{name.replace('_', '-')}")
                   for name in ("display_candidate", "spoken_candidate", "audio_package",
                                "audio_review_receipt", "screening_receipt")}
    checked = {}
    for locale in LOCALES:
        content_path = base / "content" / PAGE_ID / f"{locale}.json"
        release_path = base / "releases" / PAGE_ID / f"{locale}.json"
        content, release = read(content_path), read(release_path)
        display = stage.read_package(assignments["display_candidate"][locale],
                                     "sermon-target-language-candidate-v2.schema.json")
        spoken = stage.read_package(assignments["spoken_candidate"][locale],
                                    "sermon-target-language-candidate-v2.schema.json")
        audio_file = assignments["audio_package"][locale]
        audio = stage.read_package(audio_file, "sermon-target-language-audio-package-v1.schema.json")
        review_file = assignments["audio_review_receipt"][locale]
        review_raw = read(review_file)
        require(review_raw.get("schemaVersion") ==
                "sermon-target-language-audio-human-review-receipt-v2",
                f"{locale}: require independent v2 full-audio review receipt")
        review = stage.read_package(
            review_file, "sermon-target-language-audio-human-review-receipt-v2.schema.json")
        screening = stage.read_audio_screening(assignments["screening_receipt"][locale])
        require(release.get("schemaVersion") == "sermon-target-language-release-package-v1"
                and release.get("status") == "published_http_verified"
                and release.get("audioStatus") == "unavailable"
                and release.get("targetLanguageCandidateJsonSha256") == stage.canonical_sha(display)
                and next((asset["sha256"] for asset in release["assets"]
                          if asset["role"] == "content"), None) == stage.file_sha(content_path),
                f"{locale}: published display-only release changed")
        require(content.get("sourceMediaSha256") == source["source"]["media"]["sha256"]
                and [unit for cue in content["cues"] for unit in cue["sourceUnitIds"]]
                == source_ids,
                f"{locale}: full display text does not cover this exact media")
        row, track, captions = checked_locale(
            locale=locale, source_hash=source_hash, source_duration=duration,
            content=content, display=display, spoken=spoken, audio=audio,
            review=review, screening=screening, audio_path=stage.local_artifact(
                audio_file, audio["track"], f"{locale} track"), audio_package_path=audio_file)
        row["displayContentSha256"] = stage.file_sha(content_path)
        checked[locale] = (row, track, captions)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{args.out.name}-", dir=args.out.parent))
    try:
        shutil.copytree(base, temporary, dirs_exist_ok=True)
        target_page = temporary / "pages" / PAGE_ID
        rows = {}
        for locale, (row, track, captions) in checked.items():
            audio_url = f"/media/{PAGE_ID}/spoken/{locale}-{stage.file_sha(track)[:16]}.mp3"
            caption_url = f"/captions/{PAGE_ID}/spoken/{locale}-{stage.file_sha(captions)[:16]}.json"
            for url, original in ((audio_url, track), (caption_url, captions)):
                destination = temporary / url.lstrip("/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(original, destination)
                require(stage.file_sha(destination) == stage.file_sha(original),
                        f"Copied asset hash mismatch: {url}")
            rows[locale] = {**row,
                            "audio": {"path": audio_url, "sha256": stage.file_sha(track)},
                            "captions": {"path": caption_url,
                                         "sha256": stage.file_sha(captions)}}
        manifest = {"schemaVersion": "sermon-full-video-audio-extension-v1",
                    "pageId": PAGE_ID,
                    "englishSourcePackageJsonSha256": source_hash,
                    "sourceMediaSha256": source["source"]["media"]["sha256"],
                    "pageDataSha256": PAGE_DATA_SHA256,
                    "status": "three_locale_audio_human_reviewed_candidate",
                    "locales": rows}
        schema = read(ROOT / "schemas" / SCHEMA)
        problems = list(Draft202012Validator(schema).iter_errors(manifest))
        require(not problems, f"Audio extension schema: {problems[0].message if problems else ''}")
        manifest_file = target_page / "audio-extension.json"
        write(manifest_file, manifest)
        shutil.copyfile(SCRIPT, target_page / SCRIPT.name)
        html_path = target_page / "index.html"
        html = html_path.read_text(encoding="utf-8")
        require(html.count("</body>") == 1 and "data-audio-extension" not in html,
                "Unexpected or already extended page HTML")
        old_notice = "三语正式配音尚在制作和同步审核中"
        old_footer = "三语配音完成同步和听审后另行补充"
        require(old_notice in html and old_footer in html,
                "Full-video page status copy differs from the approved text-only edition")
        html = html.replace(old_notice, "三语配音已完成全文听审；完整译文仍按原视频显示")
        html = html.replace(old_footer, "配音使用另行人审的精简口播稿，字幕与完整译文分开显示")
        html = html.replace("</body>",
                            f'<script type="module" '
                            f'src="{SCRIPT.name}" data-audio-extension '
                            f'data-manifest-sha256="{stage.file_sha(manifest_file)}"></script></body>')
        html_path.write_text(html, encoding="utf-8")
        # Keep the existing single-candidate package explicitly display-only.
        # Its page asset hash and HTTP gate must reflect the new page bytes.
        for locale in LOCALES:
            release_path = temporary / "releases" / PAGE_ID / f"{locale}.json"
            release = read(release_path)
            for asset in release["assets"]:
                if asset["role"] == "page":
                    asset["sha256"] = stage.file_sha(html_path)
            release["status"] = "candidate"
            release["httpVerification"] = {"status": "not_run", "evidenceSha256": None}
            write(release_path, release)
            stage.read_package(release_path, "sermon-target-language-release-package-v1.schema.json")
        require(stage.file_sha(target_page / "page-data.js") == PAGE_DATA_SHA256,
                "Full translation page data changed during staging")
        for locale in LOCALES:
            original = base / "content" / PAGE_ID / f"{locale}.json"
            copied = temporary / "content" / PAGE_ID / f"{locale}.json"
            require(stage.file_sha(original) == stage.file_sha(copied),
                    f"{locale}: full approved content changed during staging")
        write(temporary / "audio-extension-preparation-receipt.json", {
            "schemaVersion": "sermon-full-video-audio-extension-preparation-v1",
            "status": "candidate_not_deployed", "pageId": PAGE_ID,
            "audioExtensionJsonSha256": stage.canonical_sha(manifest),
            "pageSha256": stage.file_sha(html_path),
            "pageDataSha256": PAGE_DATA_SHA256})
        os.rename(temporary, args.out)
    except Exception:
        shutil.rmtree(temporary)
        raise
    return args.out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-public", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    for name in ("display-candidate", "spoken-candidate", "audio-package",
                 "audio-review-receipt", "screening-receipt"):
        parser.add_argument(f"--{name}", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args)
    except (ValueError, OSError, json.JSONDecodeError, stage.StageError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps({"status": "candidate_not_deployed", "public": str(result)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
