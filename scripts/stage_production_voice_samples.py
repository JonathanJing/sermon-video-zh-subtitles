#!/usr/bin/env python3
"""Stage and verify Korean/Spanish voice auditions over an exact Production snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

try:
    from scripts import assemble_multilingual_hosting as hosting
    from scripts import stage_voice_demo_dev as dev_demo
    from scripts import verify_multilingual_hosting as http
except ImportError:
    import assemble_multilingual_hosting as hosting
    import stage_voice_demo_dev as dev_demo
    import verify_multilingual_hosting as http


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://ai-for-god-sermon-audio.web.app"
PROJECT = "ai-for-god-caption-dev"
SITE = "ai-for-god-sermon-audio"
PREFIX = dev_demo.PREFIX
CATALOG_NAME = f"{PREFIX}/production-ko-es.json"
SOURCE_UI = ROOT / "experiments/sermon-dubbing-poc/web"
SCHEMA = "sermon-production-voice-overlay-v1"


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def inventory(public: Path) -> list[dict]:
    return [{"path": name, "sha256": hosting.digest(path), "bytes": path.stat().st_size}
            for name, path in sorted(hosting.regular_files(public).items())]


def validate_config(config: dict) -> None:
    site = config.get("hosting", {})
    require(site.get("public") == "public"
            and site.get("site") == SITE
            and {"source": "/api/**", "function": {
                "functionId": "sermon-feedback-api", "region": "us-west1"}}
            in site.get("rewrites", []), "Production Hosting configuration changed")


def stage(base: Path, dev_public: Path, out: Path) -> dict:
    require(not out.exists() and not out.is_symlink(), "Use a new candidate directory")
    source = dev_demo.public_catalog(dev_public)
    base_public = base / "public"
    before = inventory(base_public)
    base_names = {item["path"] for item in before}
    require(CATALOG_NAME not in base_names and "voice-samples.mjs" not in base_names,
            "Production voice overlay already exists")
    validate_config(hosting.load(base / "firebase.json"))
    weekly = hosting.load(base_public / "weekly.json")
    bank = {speaker["id"]: speaker["name"] for speaker in weekly["voiceBank"]["speakers"]}
    require(len(bank) == 6 and set(bank) == {speaker["speakerId"] for speaker in source["speakers"]},
            "Production speaker bank differs from Dev demo")
    formal_catalog = base_public / "multilingual-v2.json"
    if formal_catalog.is_file():
        hosting.verify_catalog_assets(base_public, hosting.load(formal_catalog))

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(base_public, public, copy_function=os.link)
        speakers = []
        for speaker in source["speakers"]:
            speaker_id = speaker["speakerId"]
            require(bank[speaker_id] == speaker["displayName"], "Speaker name changed")
            samples = []
            for locale in ("ko", "es"):
                sample = next(item for item in speaker["samples"] if item["locale"] == locale)
                path = hosting.checked_public_path(dev_public, sample["path"])
                require(path.is_file() and not path.is_symlink()
                        and path.stat().st_size == sample["bytes"]
                        and hosting.digest(path) == sample["sha256"]
                        and sample["humanListeningStatus"] == "pending", "Demo source changed")
                target = hosting.checked_public_path(public, sample["path"])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                samples.append(sample)
            speakers.append({"speakerId": speaker_id, "displayName": bank[speaker_id],
                             "samples": samples})
        catalog = {"schemaVersion": "sermon-production-voice-auditions-v1",
                   "status": "audition_demo", "sourceScope": source["sourceScope"],
                   "humanListeningStatus": "pending", "speakerCount": 6,
                   "sampleCount": 12, "speakers": speakers}
        (public / CATALOG_NAME).write_text(
            json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        index = public / "index.html"
        html = index.read_text(encoding="utf-8")
        marker = '  <script type="module" src="/app.mjs"></script>'
        require(html.count(marker) == 1 and "voice-samples.mjs" not in html,
                "Production entry point changed")
        index.unlink()  # copytree uses hard links; never mutate the base snapshot.
        index.write_text(html.replace(marker, marker +
                            '\n  <script type="module" src="/voice-samples.mjs"></script>', 1),
                         encoding="utf-8")
        style = public / "style.css"
        style.unlink()
        shutil.copyfile(SOURCE_UI / "style.css", style)
        shutil.copyfile(SOURCE_UI / "voice-samples.mjs", public / "voice-samples.mjs")
        shutil.copyfile(base / "firebase.json", temporary / "firebase.json")
        after = inventory(public)
        before_map, after_map = ({item["path"]: item for item in items} for items in (before, after))
        modified = sorted(name for name in before_map if before_map[name] != after_map.get(name))
        added = sorted(set(after_map) - set(before_map))
        require(modified == ["index.html", "style.css"]
                and set(added) == {"voice-samples.mjs", CATALOG_NAME,
                                   *(f"{PREFIX}/{speaker['speakerId']}/{locale}.mp3"
                                     for speaker in speakers for locale in ("ko", "es"))},
                "Unexpected Production file change")
        report = {"schemaVersion": SCHEMA, "status": "validated_not_deployed",
                  "siteId": SITE, "projectId": PROJECT, "origin": ORIGIN,
                  "baseBuildReportSha256": hosting.digest(base / "build-report.json"),
                  "devCatalogSha256": hosting.digest(dev_public / dev_demo.PREFIX / "catalog.json"),
                  "voiceCatalogSha256": hosting.digest(public / CATALOG_NAME),
                  "oldFormalCatalogSha256": hosting.digest(formal_catalog) if formal_catalog.is_file() else None,
                  "oldWeeklyCatalogSha256": hosting.digest(base_public / "weekly.json"),
                  "baseFiles": before, "files": after, "modifiedFiles": modified,
                  "addedFiles": added,
                  "firebaseConfigSha256": hosting.digest(temporary / "firebase.json")}
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        verify_candidate(temporary)
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def verify_candidate(candidate: Path) -> dict:
    report = hosting.load(candidate / "build-report.json")
    require(report.get("schemaVersion") == SCHEMA and report.get("status") == "validated_not_deployed"
            and report.get("projectId") == PROJECT and report.get("siteId") == SITE
            and report.get("origin") == ORIGIN, "Invalid Production voice candidate")
    public = candidate / "public"
    require(inventory(public) == report["files"]
            and hosting.digest(candidate / "firebase.json") == report["firebaseConfigSha256"]
            and hosting.digest(public / "weekly.json") == report["oldWeeklyCatalogSha256"]
            and ((hosting.digest(public / "multilingual-v2.json") if
                  (public / "multilingual-v2.json").is_file() else None)
                 == report["oldFormalCatalogSha256"]),
            "Candidate files changed")
    require(hosting.digest(public / "voice-samples.mjs") ==
            hosting.digest(SOURCE_UI / "voice-samples.mjs")
            and hosting.digest(public / "style.css") == hosting.digest(SOURCE_UI / "style.css"),
            "Voice audition UI differs from checked-in code")
    validate_config(hosting.load(candidate / "firebase.json"))
    if report["oldFormalCatalogSha256"] is not None:
        hosting.verify_catalog_assets(public, hosting.load(public / "multilingual-v2.json"))
    catalog = hosting.load(public / CATALOG_NAME)
    require(catalog.get("schemaVersion") == "sermon-production-voice-auditions-v1"
            and catalog.get("status") == "audition_demo"
            and catalog.get("humanListeningStatus") == "pending"
            and catalog.get("speakerCount") == 6 and catalog.get("sampleCount") == 12
            and len(catalog.get("speakers", [])) == 6
            and hosting.digest(public / CATALOG_NAME) == report["voiceCatalogSha256"],
            "Voice demo catalog changed")
    names = {speaker["id"]: speaker["name"] for speaker in hosting.load(public / "weekly.json")
             ["voiceBank"]["speakers"]}
    require(set(names) == {speaker["speakerId"] for speaker in catalog["speakers"]},
            "Voice demo speakers differ from published bank")
    for speaker in catalog["speakers"]:
        require(speaker["displayName"] == names[speaker["speakerId"]]
                and {item["locale"] for item in speaker["samples"]} == {"ko", "es"},
                "Voice demo speaker incomplete")
        for sample in speaker["samples"]:
            require(sample["path"] == f"/{PREFIX}/{speaker['speakerId']}/{sample['locale']}.mp3"
                    and sample["humanListeningStatus"] == "pending"
                    and hosting.digest(hosting.checked_public_path(public, sample["path"])) == sample["sha256"]
                    and hosting.checked_public_path(public, sample["path"]).stat().st_size == sample["bytes"],
                    "Voice demo asset changed")
    return report


def check_http(candidate: Path, *, baseline: bool, workers: int = 4) -> dict:
    report = verify_candidate(candidate)
    expected = report["baseFiles"] if baseline else report["files"]
    def check(item: dict) -> dict:
        path = "/" + item["path"]
        status, headers, size, digest = http.request_file(ORIGIN, path)
        require(status == 200 and size == item["bytes"] and digest == item["sha256"],
                f"Production file changed: {path}")
        return {"path": path, "sha256": digest, "bytes": size}
    results = http.ordered_checks(expected, check, workers)
    if baseline:
        from urllib.error import HTTPError
        from urllib.request import urlopen
        try:
            urlopen(ORIGIN + "/" + CATALOG_NAME, timeout=30)
        except HTTPError as error:
            require(error.code == 404, "Voice catalog already exists online")
        else:
            raise ValueError("Voice catalog already exists online")
    return {"schemaVersion": "sermon-production-voice-http-v1",
            "status": "pass", "origin": ORIGIN, "phase": "baseline" if baseline else "published",
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "buildReportSha256": hosting.digest(candidate / "build-report.json"),
            "checkedFiles": len(expected), "results": results,
            "deviceAcceptance": "not_run", "venueAcceptance": "not_run"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("stage")
    build.add_argument("--base", type=Path, required=True)
    build.add_argument("--dev-public", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    for name in ("preflight", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--candidate", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--http-workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "stage":
        report = stage(args.base, args.dev_public, args.out)
        print(json.dumps({"status": report["status"], "addedFiles": len(report["addedFiles"])}))
    else:
        require(not args.out.exists(), "Use a new verification receipt")
        receipt = check_http(args.candidate, baseline=args.command == "preflight",
                             workers=args.http_workers)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                                       indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": receipt["status"], "checkedFiles": receipt["checkedFiles"]}))


if __name__ == "__main__":
    main()
