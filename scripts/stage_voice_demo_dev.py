#!/usr/bin/env python3
"""Add a hash-bound, demo-only speaker comparison to the current Dev snapshot.

The result is an immutable Dev Hosting candidate. No AI service is called and
this command never deploys or changes four-layer release approval evidence.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
from urllib.parse import urlparse

try:
    from scripts import assemble_multilingual_hosting as hosting
    from scripts import multilingual_dev_preview as preview
except ImportError:
    import assemble_multilingual_hosting as hosting
    import multilingual_dev_preview as preview


ROOT = Path(__file__).resolve().parents[1]
UI_SOURCE = ROOT / "firebase/dev/public"
VERSION = "2026-09-21-v2"
PREFIX = f"voice-demos/{VERSION}"
PAGES = ("index.html", "multilingual-reader.html", "dev-poc.html")
LOCALES = frozenset({"zh-Hans", "ko", "es", "vi"})
LOCALE_ORDER = ("zh-Hans", "ko", "es", "vi")
SCHEMA = "sermon-multilingual-voice-demo-public-v1"


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise ValueError(reason)


def file_record(path: Path, public: Path) -> dict:
    return {"path": "/" + str(path.relative_to(public)),
            "sha256": hosting.digest(path), "bytes": path.stat().st_size}


def reference_source(base_public: Path, item: dict, explicit: dict[str, Path]) -> Path:
    speaker = item["speakerId"]
    if speaker in explicit:
        path = explicit[speaker]
        require(path.is_file() and not path.is_symlink()
                and hosting.digest(path) == item["sha256"],
                f"Original English reference differs: {speaker}")
        return path
    media = base_public / "media"
    matches = [path for path in media.glob(item["sha256"][:16] + "-*")
               if path.is_file() and not path.is_symlink()
               and hosting.digest(path) == item["sha256"]]
    require(len(matches) == 1, f"Supply one verified --reference for {speaker}")
    return matches[0]


def patch_page(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    require(text.count('id="moreOptions"') == 1
            and text.count("</head>") == 1 and text.count("</body>") == 1
            and "/voice-demo.mjs" not in text and "/voice-demo.css" not in text,
            f"Dev More panel changed or already includes voice demos: {path.name}")
    text = text.replace("</head>", '  <link rel="stylesheet" href="/voice-demo.css">\n</head>', 1)
    text = text.replace("</body>", '  <script type="module" src="/voice-demo.mjs"></script>\n</body>', 1)
    path.write_text(text, encoding="utf-8")


def public_catalog(public: Path) -> dict:
    catalog = hosting.load(public / PREFIX / "catalog.json")
    require(catalog.get("schemaVersion") == SCHEMA
            and catalog.get("status") == "audition_demo"
            and catalog.get("sourceScope") == "voice_capability_audition_not_sermon_translation"
            and catalog.get("humanListeningStatus") == "pending"
            and isinstance(catalog.get("speakers"), list)
            and len(catalog["speakers"]) == 6,
            "Voice demo catalog cannot be represented as approved sermon content")
    speaker_ids = set()
    paths = set()
    for speaker in catalog["speakers"]:
        speaker_id = speaker.get("speakerId")
        require(isinstance(speaker_id, str) and speaker_id not in speaker_ids
                and isinstance(speaker.get("displayName"), str),
                "Duplicate or unnamed voice demo speaker")
        speaker_ids.add(speaker_id)
        original = speaker.get("original", {})
        require(original.get("transcriptStatus") == "machine_screening_only"
                and isinstance(original.get("text"), str)
                and original["text"].strip(),
                f"Original English transcript provenance missing: {speaker_id}")
        source_url = original.get("sourceUrl")
        parsed = urlparse(source_url or "")
        require(parsed.scheme == "https" and parsed.hostname and not parsed.username
                and not parsed.password, f"Original source URL missing: {speaker_id}")
        samples = speaker.get("samples")
        require(isinstance(samples, list) and len(samples) == 4
                and {item.get("locale") for item in samples} == LOCALES,
                f"Four target locales required for demo speaker: {speaker_id}")
        for item in [original, *samples]:
            path = item.get("path")
            require(isinstance(path, str) and path.startswith("/" + PREFIX + "/")
                    and ".." not in path and path not in paths,
                    f"Unsafe or duplicate voice demo path: {path}")
            paths.add(path)
            actual = hosting.checked_public_path(public, path)
            require(actual.is_file() and not actual.is_symlink()
                    and hosting.digest(actual) == item.get("sha256")
                    and actual.stat().st_size == item.get("bytes")
                    and actual.stat().st_size > 0,
                    f"Voice demo audio differs: {path}")
            if item is not original:
                require(item.get("humanListeningStatus") == "pending"
                        and isinstance(item.get("text"), str) and item["text"].strip(),
                        f"AI sample review status changed: {path}")
    require(len(paths) == 30, "Voice demo requires six originals and 24 AI samples")
    return catalog


def verify_candidate_overlay(candidate: Path, report: dict) -> dict:
    base = hosting.load(candidate / "dev-base-build-report.json")
    prior = hosting.load(candidate / "prior-http-verification.json")
    public = candidate / "public"
    catalog = public_catalog(public)
    require(report.get("schemaVersion") == "sermon-multilingual-dev-preview-v3"
            and report.get("demoOnly") is True
            and report.get("baseBuildReportSha256")
            == hosting.digest(candidate / "dev-base-build-report.json")
            and report.get("priorHttpVerificationSha256")
            == hosting.digest(candidate / "prior-http-verification.json")
            and base.get("files") == report.get("devBaseFiles")
            and base.get("projectId") == preview.DEV_PROJECT
            and base.get("siteId") == preview.DEV_SITE
            and base.get("firebaseConfigSha256") == report.get("firebaseConfigSha256")
            and prior.get("schemaVersion") == "sermon-multilingual-dev-preview-http-v1"
            and prior.get("status") == "pass"
            and prior.get("origin") == preview.DEV_ORIGIN
            and prior.get("buildReportSha256") == report.get("baseBuildReportSha256")
            and prior.get("checkedFiles") == len(report["devBaseFiles"])
            and report.get("voiceDemoCatalogSha256")
            == hosting.digest(public / PREFIX / "catalog.json")
            and report.get("baseCleanUrls") == hosting.load(candidate / "firebase.json")["hosting"].get("cleanUrls")
            and report.get("modifiedFiles") == list(PAGES)
            and report.get("addedFileCount") == 33,
            "Dev voice demo overlay lost its baseline or review boundary")
    base_paths = {item["path"]: item for item in report["devBaseFiles"]}
    current = {item["path"]: item for item in report["files"]}
    require({name for name in base_paths if current.get(name) != base_paths[name]} == set(PAGES)
            and set(current) - set(base_paths) == {
                "voice-demo.mjs", "voice-demo.css", f"{PREFIX}/catalog.json",
                *(asset["path"].lstrip("/") for speaker in catalog["speakers"]
                  for asset in [speaker["original"], *speaker["samples"]])}
            and len(current) - len(base_paths) == 33,
            "Voice demo overlay changed an unrelated Dev file")
    for name in PAGES:
        html = (public / name).read_text(encoding="utf-8")
        require(html.count('href="/voice-demo.css"') == 1
                and html.count('src="/voice-demo.mjs"') == 1,
                f"Voice demo entry missing in {name}")
    for name in ("voice-demo.mjs", "voice-demo.css"):
        require(hosting.digest(public / name) == report.get("voiceDemoUiSha256", {}).get(name),
                f"Voice demo frontend changed: {name}")
    return catalog


def stage(base: Path, delivery: Path, prior_http: Path, out: Path,
          explicit_references: dict[str, Path]) -> dict:
    require(not out.exists() and not out.is_symlink(), "Use a new Dev candidate directory")
    base_report = preview.candidate_report(base)
    prior = hosting.load(prior_http)
    require(prior.get("schemaVersion") == "sermon-multilingual-dev-preview-http-v1"
            and prior.get("status") == "pass"
            and prior.get("origin") == preview.DEV_ORIGIN
            and prior.get("buildReportSha256") == hosting.digest(base / "build-report.json")
            and prior.get("checkedFiles") == len(base_report["files"]),
            "Prior Dev HTTP receipt does not bind the current release")
    source = hosting.load(delivery / "delivery-manifest.json")
    refs = hosting.load(delivery / "references.json")
    script = hosting.load(delivery / "demo-script.json")
    require(source.get("schemaVersion") == "sermon-multilingual-voice-demo-delivery-v1"
            and source.get("status") == "encoded_and_fully_decoded"
            and source.get("scope") == "voice_capability_audition_not_sermon_translation"
            and source.get("speakerCount") == 6
            and source.get("trackCount") == 24
            and source.get("humanListeningStatus") == "pending"
            and refs.get("schemaVersion") == "sermon-multilingual-voice-demo-references-v1"
            and refs.get("textEvidenceStatus") == "machine_screening_only"
            and script.get("schemaVersion") == "sermon-multilingual-voice-demo-script-v1"
            and script.get("scope") == source["scope"]
            and {item.get("targetLocale") for item in script.get("locales", [])} == LOCALES,
            "Voice demo sources are incomplete or misrepresented")
    references = {item["speakerId"]: item for item in refs["references"]}
    tracks = {(item["speakerId"], item["targetLocale"]): item
              for item in source["tracks"]}
    require(len(references) == 6 and len(tracks) == 24
            and len(refs["references"]) == 6 and len(source["tracks"]) == 24,
            "Voice demo speaker or locale duplicated")
    scripts = {item["targetLocale"]: item["text"] for item in script["locales"]}
    base_public = base / "public"
    voice_bank = {item["id"]: item for item in hosting.load(base_public / "weekly.json")
                  .get("voiceBank", {}).get("speakers", [])}
    require(set(references) == set(voice_bank), "Voice demo references differ from published speaker bank")

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(base_public, public)
        speakers = []
        for speaker_id, reference in sorted(references.items()):
            bank = voice_bank[speaker_id]
            source_url = bank.get("referenceSourceUrl")
            parsed = urlparse(source_url or "")
            require(parsed.scheme == "https" and parsed.hostname,
                    f"Original source URL missing: {speaker_id}")
            reference_file = reference_source(base_public, reference, explicit_references)
            extension = reference_file.suffix.lower()
            require(extension in {".wav", ".mp3"}, "English reference must be playable audio")
            target = public / PREFIX / speaker_id / ("en-original" + extension)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(reference_file, target)
            original = {**file_record(target, public), "text": reference["text"],
                        "transcriptStatus": "machine_screening_only",
                        "sourceUrl": source_url}
            samples = []
            for locale in LOCALE_ORDER:
                track = tracks[(speaker_id, locale)]
                audio = track["mp3"]
                path = delivery / audio["path"]
                require(path.resolve().is_relative_to(delivery.resolve())
                        and audio.get("fullDecode") == "pass"
                        and track.get("humanListeningStatus") == "pending"
                        and path.is_file() and not path.is_symlink()
                        and hosting.digest(path) == audio["sha256"],
                        f"AI demo audio differs: {speaker_id}/{locale}")
                target = public / PREFIX / speaker_id / (locale + ".mp3")
                shutil.copyfile(path, target)
                samples.append({**file_record(target, public), "locale": locale,
                                "text": scripts[locale],
                                "humanListeningStatus": "pending",
                                "reviewPriority": bool(track.get("asrScreening", {}).get("reviewPriority"))})
            speakers.append({"speakerId": speaker_id, "displayName": bank["name"],
                             "original": original, "samples": samples})
        catalog = {"schemaVersion": SCHEMA, "status": "audition_demo",
                   "sourceScope": source["scope"], "humanListeningStatus": "pending",
                   "speakerCount": 6, "sampleCount": 24, "speakers": speakers}
        catalog_path = public / PREFIX / "catalog.json"
        catalog_path.write_text(json.dumps(catalog, ensure_ascii=False, sort_keys=True,
                                           indent=2) + "\n", encoding="utf-8")
        for name in ("voice-demo.mjs", "voice-demo.css"):
            require(not (public / name).exists(), f"Voice demo UI already exists: {name}")
            shutil.copyfile(UI_SOURCE / name, public / name)
        for name in PAGES:
            patch_page(public / name)
        shutil.copyfile(base / "firebase.json", temporary / "firebase.json")
        shutil.copyfile(base / "build-report.json", temporary / "dev-base-build-report.json")
        shutil.copyfile(prior_http, temporary / "prior-http-verification.json")
        report = {**base_report,
                  "schemaVersion": "sermon-multilingual-dev-preview-v3",
                  "status": "validated_not_deployed", "demoOnly": True,
                  "files": preview.inventory(public), "devBaseFiles": base_report["files"],
                  "baseCleanUrls": hosting.load(base / "firebase.json")["hosting"]["cleanUrls"],
                  "baseBuildReportSha256": hosting.digest(base / "build-report.json"),
                  "priorHttpVerificationSha256": hosting.digest(prior_http),
                  "voiceDemoCatalogSha256": hosting.digest(catalog_path),
                  "voiceDemoUiSha256": {name: hosting.digest(public / name)
                                         for name in ("voice-demo.mjs", "voice-demo.css")},
                  "sourceDeliveryManifestSha256": hosting.digest(delivery / "delivery-manifest.json"),
                  "sourceReferencesSha256": hosting.digest(delivery / "references.json"),
                  "sourceDemoScriptSha256": hosting.digest(delivery / "demo-script.json"),
                  "modifiedFiles": list(PAGES), "addedFileCount": 33}
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        verify_candidate_overlay(temporary, report)
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def parse_references(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        speaker, separator, path = value.partition("=")
        require(separator and speaker and path and speaker not in result,
                "Use --reference speakerId=/absolute/path/to/original-audio")
        result[speaker] = Path(path).resolve()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-candidate", required=True, type=Path)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--prior-http-verification", required=True, type=Path)
    parser.add_argument("--reference", action="append", default=[],
                        help="speakerId=/absolute/path; needed if the base site lacks that original")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    report = stage(args.base_candidate, args.delivery, args.prior_http_verification,
                   args.out, parse_references(args.reference))
    print(json.dumps({key: report[key] for key in
                      ("schemaVersion", "status", "pageId", "addedFileCount")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
