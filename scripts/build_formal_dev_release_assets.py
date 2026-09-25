#!/usr/bin/env python3
"""Build three locale-bound Dev content and release candidates from reviewed audio.

The reviewed metadata document records the operator's approval of display
fields. Cues come only from the approved text and measured Layer 3 schedule.
The resulting release packages remain candidates until separate HTTP checks.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

try:
    from scripts import stage_formal_multilingual_dev as stage
except ImportError:
    import stage_formal_multilingual_dev as stage


FIELDS = ("series", "title", "speaker", "scripture", "summary", "outline")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8")


def checked_metadata(path: Path, proposal: Path, page_id: str, date: str) -> dict:
    metadata = json.loads(path.read_text(encoding="utf-8"))
    require(metadata.get("schemaVersion") == "sermon-formal-dev-metadata-approval-v1"
            and metadata.get("pageId") == page_id
            and metadata.get("date") == date
            and metadata.get("decision") == "approved_all_three_locales"
            and metadata.get("approvalText") in {"三语全部批准", "三语页面信息全部批准"}
            and metadata.get("reviewer") == "user"
            and metadata.get("proposalFileSha256") == stage.file_sha(proposal)
            and set(metadata.get("locales", {})) == set(stage.LOCALES),
            "Display metadata approval or proposal binding differs")
    recorded_at = metadata.get("recordedAt")
    require(isinstance(recorded_at, str)
            and datetime.fromisoformat(recorded_at.replace("Z", "+00:00")).tzinfo is not None,
            "Display metadata approval needs a timezone-bearing recording time")
    proposal_text = proposal.read_text(encoding="utf-8")
    for locale, fields in metadata["locales"].items():
        require(set(fields) == set(FIELDS)
                and all(isinstance(fields[name], str) and fields[name] in proposal_text
                        for name in FIELDS if name != "outline")
                and isinstance(fields["outline"], list)
                and all(isinstance(line, str) and line in proposal_text
                        for line in fields["outline"]),
                f"{locale}: approved display fields differ from the proposal")
    return metadata


def build(args: argparse.Namespace) -> dict:
    require(stage.PAGE_ID.fullmatch(args.page_id) is not None, "Unsafe page ID")
    require(not args.out.exists(), "Release asset output is immutable")
    source = stage.read_package(args.source, "sermon-english-source-package-v1.schema.json")
    source_hash = stage.canonical_sha(source)
    require(source["status"] == "ready_for_translation"
            and source["source"]["serviceDate"] == args.date,
            "Source package or service date differs")
    metadata = checked_metadata(args.metadata, args.metadata_proposal, args.page_id, args.date)
    candidate_paths = stage.assignment_map(args.candidate, "--candidate")
    audio_paths = stage.assignment_map(args.audio_package, "--audio-package")
    rows: dict[str, tuple[dict, dict, dict, Path, Path, Path]] = {}
    for locale in stage.LOCALES:
        candidate = stage.read_package(candidate_paths[locale],
                                       "sermon-target-language-candidate-v2.schema.json")
        audio = stage.read_package(audio_paths[locale],
                                   "sermon-target-language-audio-package-v1.schema.json")
        candidate_hash = stage.canonical_sha(candidate)
        audio_hash = stage.canonical_sha(audio)
        require(stage.reviewed_candidate(candidate)
                and candidate["targetLocale"] == locale
                and candidate["englishSourcePackageJsonSha256"] == source_hash
                and audio["status"] == "human_reviewed"
                and audio["humanReview"]["humanApproval"] is True
                and audio["targetLocale"] == locale
                and audio["englishSourcePackageJsonSha256"] == source_hash
                and audio["targetLanguageCandidateJsonSha256"] == candidate_hash
                and audio["track"] is not None
                and audio["schedule"] is not None
                and audio["captions"] is not None,
                f"{locale}: upstream text or audio has not passed human review")
        track = stage.local_artifact(audio_paths[locale], audio["track"], f"{locale} track")
        require(track.suffix in {".wav", ".mp3"}, f"{locale}: unsupported release track format")
        schedule = stage.local_artifact(audio_paths[locale], audio["schedule"], f"{locale} schedule")
        captions = stage.local_artifact(audio_paths[locale], audio["captions"], f"{locale} captions")
        rows[locale] = (candidate, audio, {"candidate": candidate_hash, "audio": audio_hash},
                        track, schedule, captions)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    output_root = Path(tempfile.mkdtemp(prefix=f".{args.out.name}-", dir=args.out.parent))
    for locale, (candidate, audio, hashes, track, schedule_path, captions_path) in rows.items():
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        captions = json.loads(captions_path.read_text(encoding="utf-8"))
        groups = candidate["groups"]
        entries = schedule["entries"]
        require(len(entries) == len(groups) == len(captions["cues"]),
                f"{locale}: schedule, captions, and approved text coverage differ")
        cues = []
        for group, entry, caption in zip(groups, entries, captions["cues"]):
            require(group["translationGroupId"] == entry["textGroupId"] == caption["textGroupId"]
                    and group["sourceUnitIds"] == entry["sourceUnitIds"]
                    and group["targetText"] == caption["text"]
                    and entry["plannedStart"] == caption["start"]
                    and entry["plannedEnd"] == caption["end"],
                    f"{locale}: measured cue differs from approved text")
            cues.append({"textGroupId": group["translationGroupId"],
                         "sourceUnitIds": group["sourceUnitIds"],
                         "start": entry["plannedStart"], "end": entry["plannedEnd"],
                         "text": group["targetText"]})
        display = metadata["locales"][locale]
        content = {
            "schemaVersion": "sermon-formal-dev-content-v1", "pageId": args.page_id,
            "sourceLocale": "en", "locale": locale,
            "englishSourcePackageJsonSha256": source_hash,
            "targetLanguageCandidateJsonSha256": hashes["candidate"],
            "targetLanguageAudioPackageJsonSha256": hashes["audio"],
            "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
            **{name: display[name] for name in FIELDS if name != "outline"},
            "date": args.date, "durationSeconds": stage.decode_audio(track, f"{locale} track"),
            "cues": cues,
            "outline": [{"title": str(index), "body": text}
                        for index, text in enumerate(display["outline"], 1)],
        }
        content_path = output_root / "assets/content" / args.page_id / f"{locale}.json"
        write_json(content_path, content)
        stage.read_package(content_path, "sermon-formal-dev-content-v1.schema.json")
        content_receipt = {
            "schemaVersion": "sermon-formal-dev-content-review-receipt-v1",
            "pageId": args.page_id, "targetLocale": locale,
            "englishSourcePackageJsonSha256": source_hash,
            "targetLanguageCandidateJsonSha256": hashes["candidate"],
            "targetLanguageAudioPackageJsonSha256": hashes["audio"],
            "contentJsonSha256": stage.canonical_sha(content),
            "decision": "approved", "reviewer": metadata["reviewer"],
            "reviewedAt": metadata["recordedAt"],
            "reviewedFields": ["series", "title", "speaker", "scripture", "date", "summary", "outline"],
        }
        write_json(output_root / "review/content" / f"{locale}.json", content_receipt)
        media_path = output_root / "assets/media" / args.page_id / f"{locale}{track.suffix}"
        caption_path = output_root / "assets/captions" / args.page_id / f"{locale}.json"
        media_path.parent.mkdir(parents=True, exist_ok=True)
        caption_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(track, media_path)
        shutil.copyfile(captions_path, caption_path)
        require(stage.file_sha(media_path) == audio["track"]["sha256"]
                and stage.file_sha(caption_path) == audio["captions"]["sha256"],
                f"{locale}: copied release media differs")
        release = {
            "schemaVersion": "sermon-target-language-release-package-v1",
            "packageId": f"{args.page_id}-{locale}", "pageId": args.page_id,
            "sourceLocale": "en", "targetLocale": locale,
            "targetLanguageCandidateJsonSha256": hashes["candidate"],
            "targetLanguageAudioPackageJsonSha256": hashes["audio"],
            "status": "candidate", "contentStatus": "human_reviewed",
            "audioStatus": "human_reviewed", "interfaceLocale": locale,
            "contentLocale": locale, "audioLocale": locale,
            "assets": [{"role": role, "path": f"/{directory}/{args.page_id}/{locale}.{suffix}",
                        "sha256": stage.file_sha(path)}
                       for role, directory, suffix, path in (
                           ("content", "content", "json", content_path),
                           ("audio", "media", track.suffix.lstrip("."), media_path),
                           ("captions", "captions", "json", caption_path))],
            "httpVerification": {"status": "not_run", "evidenceSha256": None},
            "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
            "venueAcceptance": {"status": "not_run", "evidenceSha256": None},
            "issues": [],
        }
        release_path = output_root / "releases" / f"{locale}.json"
        write_json(release_path, release)
        stage.read_package(release_path, "sermon-target-language-release-package-v1.schema.json")
    receipt = {"schemaVersion": "sermon-formal-dev-release-asset-preparation-v1",
               "pageId": args.page_id, "metadataApprovalJsonSha256": stage.canonical_sha(metadata),
               "targetLocales": list(stage.LOCALES), "status": "candidate_not_deployed"}
    write_json(output_root / "preparation-receipt.json", receipt)
    os.rename(output_root, args.out)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--audio-package", action="append", default=[], metavar="LOCALE=PATH")
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--metadata-proposal", type=Path, required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = build(args)
    except (ValueError, OSError, json.JSONDecodeError, stage.StageError) as error:
        parser.exit(2, f"error: {error}\n")
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
