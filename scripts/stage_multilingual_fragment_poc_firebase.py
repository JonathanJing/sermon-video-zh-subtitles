#!/usr/bin/env python3
"""Stage canonical Layer 2/3 POC packages and ignored audio for Dev Firebase."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


TARGET_LOCALES = ("zh-Hans", "ko", "es", "vi")


def canonical_sha(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer2", type=Path, required=True)
    parser.add_argument("--layer3", type=Path, required=True)
    parser.add_argument("--source-media", type=Path, help="Authorized Layer 1 media used to recreate the English reference audio")
    parser.add_argument("--public", type=Path, default=Path("firebase/dev/public"))
    parser.add_argument("--page-id", default="2026-09-20-lion-of-judah-poc")
    args = parser.parse_args()

    weekly = json.loads((args.public / "weekly.json").read_text(encoding="utf-8"))
    week = next((item for item in weekly["weeks"] if item["id"] == args.page_id), None)
    if not week:
        raise SystemExit(f"Page is absent from weekly.json: {args.page_id}")
    tracks = {item["locale"]: item for item in week["tracks"]}
    if not set(TARGET_LOCALES).issubset(tracks):
        raise SystemExit("Committed weekly manifest does not cover all target-language POC locales")

    destination = args.public / "media" / args.page_id
    destination.mkdir(parents=True, exist_ok=True)
    layer2_public = args.public / "packages" / "layer2"
    layer3_public = args.public / "packages" / "layer3"
    layer2_public.mkdir(parents=True, exist_ok=True)
    layer3_public.mkdir(parents=True, exist_ok=True)
    staged = []
    for locale in TARGET_LOCALES:
        candidate_path = args.layer2 / locale / "target-language-candidate.json"
        package_path = args.layer3 / locale / "target-language-audio-package.json"
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        package = json.loads(package_path.read_text(encoding="utf-8"))
        if package["targetLanguageCandidateJsonSha256"] != canonical_sha(candidate):
            raise SystemExit(f"Layer 3 package is not bound to Layer 2 candidate: {locale}")
        source = args.layer3 / locale / "audio.mp3"
        expected = tracks[locale]["sha256"]
        actual = file_sha(source)
        if actual != expected or package["track"]["sha256"] != expected:
            raise SystemExit(f"Layer 3, weekly manifest, and audio hash differ: {locale}")
        target = destination / f"{locale}.mp3"
        shutil.copyfile(source, target)
        if file_sha(target) != expected:
            raise SystemExit(f"Staged media hash mismatch: {locale}")
        candidate_target = layer2_public / f"{args.page_id}-{locale}.json"
        package_target = layer3_public / f"{args.page_id}-{locale}.json"
        shutil.copyfile(candidate_path, candidate_target)
        shutil.copyfile(package_path, package_target)
        staged.append({
            "targetLocale": locale,
            "audioPath": str(target),
            "audioSha256": expected,
            "layer2JsonSha256": canonical_sha(candidate),
            "layer3JsonSha256": canonical_sha(package),
        })

    if "en" in tracks:
        english_track = tracks["en"]
        english_target = destination / "en.mp3"
        if args.source_media:
            catalog = json.loads((args.public / "multilingual.json").read_text(encoding="utf-8"))
            page = next((item for item in catalog["pages"] if item["id"] == args.page_id), None)
            if not page:
                raise SystemExit(f"Page is absent from multilingual.json: {args.page_id}")
            window = page["sourceWindow"]
            if window.get("timebase") != "sermon_relative_seconds":
                raise SystemExit("English source window must declare sermon_relative_seconds timebase")
            try:
                source_media_offset = float(window["sourceMediaOffsetSeconds"])
            except (KeyError, TypeError, ValueError) as exc:
                raise SystemExit("English source window lacks a valid source media offset") from exc
            length = float(window["endSeconds"]) - float(window["startSeconds"])
            source_media_start = source_media_offset + float(window["startSeconds"])
            temporary = english_target.with_name(english_target.stem + ".tmp.mp3")
            subprocess.run([
                "ffmpeg", "-nostdin", "-v", "error", "-ss", str(source_media_start),
                "-i", str(args.source_media), "-t", str(length), "-map", "0:a:0", "-ac", "1",
                "-ar", "44100", "-b:a", "128k", "-map_metadata", "-1", "-write_xing", "0",
                "-y", str(temporary),
            ], check=True)
            temporary.replace(english_target)
        if not english_target.exists():
            raise SystemExit("English source audio is absent; pass --source-media to recreate it")
        subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-i", str(english_target),
            "-map", "0:a:0", "-f", "null", "-",
        ], check=True)
        english_hash = file_sha(english_target)
        if english_hash != english_track["sha256"]:
            raise SystemExit("English source audio hash differs from weekly.json")
        staged.insert(0, {
            "targetLocale": "en",
            "audioPath": str(english_target),
            "audioSha256": english_hash,
            "sourceKind": "original_speaker_audio",
        })
    print(json.dumps({"pageId": args.page_id, "staged": staged}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
