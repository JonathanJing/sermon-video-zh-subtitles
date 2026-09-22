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


def media_name(audio_url: str, page_id: str) -> str:
    prefix = f"/media/{page_id}/"
    if not isinstance(audio_url, str) or not audio_url.startswith(prefix):
        raise SystemExit(f"Release audio URL is outside this page: {audio_url}")
    name = audio_url[len(prefix):]
    if not name or name in (".", "..") or "/" in name or "?" in name or "#" in name or not name.endswith(".mp3"):
        raise SystemExit(f"Invalid release audio filename: {audio_url}")
    return name


def release_audio_sources(release: dict, page_id: str, locale: str, canonical_source: Path,
                          canonical_hash: str, variant_media_dir: Path | None) -> list[tuple[Path, str, str]]:
    """Preflight every advertised file, including the selected default variant."""
    if release.get("pageId") != page_id or release.get("targetLocale") != locale:
        raise SystemExit(f"Release identity differs: {locale}")
    base_name = f"{locale}.mp3"
    if media_name(release.get("audioUrl"), page_id) != base_name or release.get("audioSha256") != canonical_hash:
        raise SystemExit(f"Release base audio differs from Layer 3: {locale}")
    sources = {base_name: (canonical_source, canonical_hash)}
    variants = release.get("audioVariants", [])
    if not isinstance(variants, list):
        raise SystemExit(f"Invalid audio variants: {locale}")
    ids = set()
    for variant in variants:
        if not isinstance(variant, dict) or not isinstance(variant.get("id"), str) or variant["id"] in ids:
            raise SystemExit(f"Invalid or duplicate audio variant ID: {locale}")
        ids.add(variant["id"])
        name = media_name(variant.get("audioUrl"), page_id)
        expected = variant.get("audioSha256")
        if not isinstance(expected, str) or len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
            raise SystemExit(f"Invalid audio variant hash: {locale}/{name}")
        if name == base_name:
            if expected != canonical_hash:
                raise SystemExit(f"Release base variant hash differs: {locale}")
            continue
        if name in sources and sources[name][1] != expected:
            raise SystemExit(f"Conflicting audio variant hashes: {locale}/{name}")
        if variant_media_dir is None:
            raise SystemExit(f"Variant audio requires --variant-media-dir: {locale}/{name}")
        sources[name] = (variant_media_dir / name, expected)
    default_id = release.get("defaultAudioVariantId")
    if default_id is not None and default_id not in ids:
        raise SystemExit(f"Default audio variant is not advertised: {locale}/{default_id}")
    result = []
    for name, (source, expected) in sources.items():
        if not source.is_file() or file_sha(source) != expected:
            raise SystemExit(f"Missing or mismatched release audio: {locale}/{name}")
        result.append((source, name, expected))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer2", type=Path, required=True)
    parser.add_argument("--layer3", type=Path, required=True)
    parser.add_argument("--source-media", type=Path, help="Authorized Layer 1 media used to recreate the English reference audio")
    parser.add_argument("--variant-media-dir", type=Path, help="Reviewed local MP3 artifacts for every noncanonical audio variant advertised by the Dev release")
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
    layer2_public = args.public / "packages" / "layer2"
    layer3_public = args.public / "packages" / "layer3"
    staged = []
    staged_sources = []
    advertised_files = {}
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
        release_path = args.public / "releases" / args.page_id / f"{locale}.json"
        release = json.loads(release_path.read_text(encoding="utf-8"))
        media_sources = release_audio_sources(release, args.page_id, locale, source, expected, args.variant_media_dir)
        for _, name, audio_hash in media_sources:
            if name in advertised_files and advertised_files[name] != audio_hash:
                raise SystemExit(f"Different locales advertise conflicting audio: {name}")
            advertised_files[name] = audio_hash
        staged_sources.append((locale, candidate_path, package_path, media_sources))
    # No staged package or MP3 is changed until every locale and variant passes.
    destination.mkdir(parents=True, exist_ok=True)
    layer2_public.mkdir(parents=True, exist_ok=True)
    layer3_public.mkdir(parents=True, exist_ok=True)
    for locale, candidate_path, package_path, media_sources in staged_sources:
        for source, name, expected in media_sources:
            target = destination / name
            if source.resolve() != target.resolve():
                shutil.copyfile(source, target)
            if file_sha(target) != expected:
                raise SystemExit(f"Staged media hash mismatch: {locale}/{name}")
        candidate_target = layer2_public / f"{args.page_id}-{locale}.json"
        package_target = layer3_public / f"{args.page_id}-{locale}.json"
        shutil.copyfile(candidate_path, candidate_target)
        shutil.copyfile(package_path, package_target)
        staged.append({
            "targetLocale": locale,
            "audioPath": str(destination / f"{locale}.mp3"),
            "audioSha256": tracks[locale]["sha256"],
            "variantAudioPaths": [str(destination / name) for _, name, _ in media_sources],
            "layer2JsonSha256": canonical_sha(json.loads(candidate_path.read_text(encoding="utf-8"))),
            "layer3JsonSha256": canonical_sha(json.loads(package_path.read_text(encoding="utf-8"))),
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
