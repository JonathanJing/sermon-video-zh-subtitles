#!/usr/bin/env python3
"""Bind each committed Dev demo release to its content bytes and catalog entry."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_release_hash(path: Path, key: str, value: str) -> None:
    """Update one top-level hash without reformatting reviewed cue arrays."""
    raw = path.read_text(encoding="utf-8")
    pattern = re.compile(rf'(?m)^  "{re.escape(key)}": "[a-f0-9]{{64}}"(?=,?$)')
    replacement = f'  "{key}": "{value}"'
    if pattern.search(raw):
        updated = pattern.sub(replacement, raw, count=1)
    else:
        if not raw.endswith("\n}\n"):
            raise ValueError(f"Unexpected release JSON ending: {path}")
        updated = raw[:-3] + f',\n{replacement}\n}}\n'
    parsed = json.loads(updated)
    if parsed[key] != value:
        raise ValueError(f"Could not update release hash: {path}")
    path.write_text(updated, encoding="utf-8")


def seal(public: Path, *, check: bool = False) -> None:
    catalog_path = public / "multilingual.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("schemaVersion") != "sermon-multilingual-demo-catalog-v1":
        raise ValueError("Only the Dev demo catalog may be sealed")
    weekly = json.loads((public / "weekly.json").read_text(encoding="utf-8"))
    weeks = {week["id"]: week for week in weekly["weeks"]}
    changed = False
    for page in catalog["pages"]:
        tracks = {track["locale"]: track for track in weeks[page["id"]]["tracks"]}
        for locale, target in page["targets"].items():
            expected = f"/releases/{page['id']}/{locale}.json"
            if target["releasePackageUrl"] != expected:
                raise ValueError(f"Release path mismatch: {page['id']}/{locale}")
            release_path = public / expected.removeprefix("/")
            release = json.loads(release_path.read_text(encoding="utf-8"))
            expected_content = f"/content/{page['id']}/{locale}.json"
            if (release.get("pageId"), release.get("targetLocale"), release.get("contentUrl")) != (
                page["id"], locale, expected_content
            ):
                raise ValueError(f"Release identity mismatch: {page['id']}/{locale}")
            content_path = public / expected_content.removeprefix("/")
            content = json.loads(content_path.read_text(encoding="utf-8"))
            if content.get("locale") != locale or content.get("translationStatus") != release.get("contentStatus"):
                raise ValueError(f"Content identity mismatch: {page['id']}/{locale}")
            track = tracks[locale]
            if release.get("audioUrl") != f"/media/{page['id']}/{locale}.mp3":
                raise ValueError(f"Audio path mismatch: {page['id']}/{locale}")
            if locale != "en":
                layer3 = json.loads((public / "packages/layer3" / f"{page['id']}-{locale}.json").read_text(encoding="utf-8"))
                if layer3["track"]["sha256"] != track["sha256"]:
                    raise ValueError(f"Layer 3 audio hash mismatch: {page['id']}/{locale}")
            if release.get("audioSha256") != track["sha256"]:
                if check:
                    raise ValueError(f"Audio hash mismatch: {page['id']}/{locale}")
                release["audioSha256"] = track["sha256"]
                set_release_hash(release_path, "audioSha256", track["sha256"])
                changed = True
            if target.get("audioStatus") != release.get("audioStatus"):
                if check:
                    raise ValueError(f"Audio status mismatch: {page['id']}/{locale}")
                target["audioStatus"] = release["audioStatus"]
                changed = True
            content_sha = digest(content_path)
            if release.get("contentSha256") != content_sha:
                if check:
                    raise ValueError(f"Content hash mismatch: {page['id']}/{locale}")
                release["contentSha256"] = content_sha
                set_release_hash(release_path, "contentSha256", content_sha)
                changed = True
            release_sha = digest(release_path)
            if target.get("releasePackageJsonSha256") != release_sha:
                if check:
                    raise ValueError(f"Release hash mismatch: {page['id']}/{locale}")
                target["releasePackageJsonSha256"] = release_sha
                changed = True
    if changed:
        write_json(catalog_path, catalog)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, default=Path("firebase/dev/public"))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    seal(args.public, check=args.check)


if __name__ == "__main__":
    main()
