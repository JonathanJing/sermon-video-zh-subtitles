#!/usr/bin/env python3
"""Stage and verify Korean/Spanish voice auditions over an exact Production snapshot."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

try:
    from scripts import assemble_multilingual_hosting as hosting
    from scripts import stage_voice_demo_dev as dev_demo
    from scripts import build_multilingual_voice_preview as voice_preview
    from scripts import verify_multilingual_hosting as http
except ImportError:
    import assemble_multilingual_hosting as hosting
    import stage_voice_demo_dev as dev_demo
    import build_multilingual_voice_preview as voice_preview
    import verify_multilingual_hosting as http


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "https://ai-for-god-sermon-audio.web.app"
PROJECT = "ai-for-god-caption-dev"
SITE = "ai-for-god-sermon-audio"
PREFIX = dev_demo.PREFIX
CATALOG_NAME = f"{PREFIX}/production-ko-es.json"
SOURCE_UI = ROOT / "experiments/sermon-dubbing-poc/web"
SCHEMA = "sermon-production-voice-overlay-v1"
LEGACY_CODE = ROOT / "experiments/sermon-dubbing-poc"
if str(LEGACY_CODE) not in sys.path:
    sys.path.insert(0, str(LEGACY_CODE))
import weekly_release  # noqa: E402


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


def validate_delivery(delivery: Path) -> tuple[dict, dict, dict]:
    manifest, script, registry, _, _, _ = voice_preview.validate(delivery, decode=False)
    require(manifest.get("humanListeningStatus") == "pending"
            and manifest.get("machineScreening", {}).get("status") == "machine_screening_only"
            and all(speaker.get("authorization", {}).get("status") == "authorized"
                    and "multilingual_voice_demo" in speaker["authorization"].get("purposes", [])
                    for speaker in registry["speakers"]),
            "Demo delivery lacks authorized audition scope")
    return manifest, script, registry


def stage(base: Path, dev_public: Path, delivery: Path, out: Path) -> dict:
    require(not out.exists() and not out.is_symlink(), "Use a new candidate directory")
    source = dev_demo.public_catalog(dev_public)
    manifest, script, registry = validate_delivery(delivery)
    delivered = {(item["speakerId"], item["targetLocale"]): item
                 for item in manifest["tracks"]}
    script_text = {item["targetLocale"]: item["text"] for item in script["locales"]}
    registered = {item["speakerId"]: item["displayName"] for item in registry["speakers"]}
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
        shutil.copytree(base_public, public)
        speakers = []
        for speaker in source["speakers"]:
            speaker_id = speaker["speakerId"]
            require(bank[speaker_id] == speaker["displayName"] == registered[speaker_id],
                    "Speaker name changed")
            samples = []
            for locale in ("ko", "es"):
                sample = next(item for item in speaker["samples"] if item["locale"] == locale)
                receipt = delivered[(speaker_id, locale)]
                path = hosting.checked_public_path(dev_public, sample["path"])
                require(path.is_file() and not path.is_symlink()
                        and path.stat().st_size == sample["bytes"]
                        and hosting.digest(path) == sample["sha256"]
                        and sample["humanListeningStatus"] == receipt["humanListeningStatus"] == "pending"
                        and sample["sha256"] == receipt["mp3"]["sha256"]
                        and sample["text"] == script_text[locale], "Demo source changed")
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
        index.unlink()
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
                  "sourceDeliveryPath": str(delivery.resolve()),
                  "sourceDeliveryManifestSha256": hosting.digest(delivery / "delivery-manifest.json"),
                  "sourceRegistrySha256": hosting.digest(delivery / "registry.json"),
                  "sourceScriptSha256": hosting.digest(delivery / "demo-script.json"),
                  "voiceCatalogSha256": hosting.digest(public / CATALOG_NAME),
                  "oldFormalCatalogSha256": hosting.digest(formal_catalog) if formal_catalog.is_file() else None,
                  "oldWeeklyCatalogSha256": hosting.digest(base_public / "weekly.json"),
                  "feedbackEnabled": hosting.load(base_public / "engagement.json")["enabled"],
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
    delivery = Path(report["sourceDeliveryPath"])
    require(hosting.digest(delivery / "delivery-manifest.json") == report["sourceDeliveryManifestSha256"]
            and hosting.digest(delivery / "registry.json") == report["sourceRegistrySha256"]
            and hosting.digest(delivery / "demo-script.json") == report["sourceScriptSha256"],
            "Voice source evidence changed")
    manifest, script, registry = validate_delivery(delivery)
    delivered = {(item["speakerId"], item["targetLocale"]): item
                 for item in manifest["tracks"]}
    script_text = {item["targetLocale"]: item["text"] for item in script["locales"]}
    registered = {item["speakerId"]: item["displayName"] for item in registry["speakers"]}
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
                == registered[speaker["speakerId"]]
                and {item["locale"] for item in speaker["samples"]} == {"ko", "es"},
                "Voice demo speaker incomplete")
        for sample in speaker["samples"]:
            receipt = delivered[(speaker["speakerId"], sample["locale"])]
            require(sample["path"] == f"/{PREFIX}/{speaker['speakerId']}/{sample['locale']}.mp3"
                    and sample["humanListeningStatus"] == receipt["humanListeningStatus"] == "pending"
                    and sample["sha256"] == receipt["mp3"]["sha256"]
                    and sample["text"] == script_text[sample["locale"]]
                    and hosting.digest(hosting.checked_public_path(public, sample["path"])) == sample["sha256"]
                    and hosting.checked_public_path(public, sample["path"]).stat().st_size == sample["bytes"],
                    "Voice demo asset changed")
    return report


def check_http(candidate: Path, *, baseline: bool, workers: int = 4) -> dict:
    report = verify_candidate(candidate)
    expected = report["baseFiles"] if baseline else report["files"]
    voice_paths = set()
    if not baseline:
        catalog = hosting.load(candidate / "public" / CATALOG_NAME)
        voice_paths = {sample["path"] for speaker in catalog["speakers"]
                       for sample in speaker["samples"]}
        require(len(voice_paths) == 12, "Voice catalog has incomplete audio samples")
    def check(item: dict) -> dict:
        path = "/" + item["path"]
        status, headers, size, digest = http.request_file(ORIGIN, path)
        require(status == 200 and size == item["bytes"] and digest == item["sha256"],
                f"Production file changed: {path}")
        result = {"path": path, "sha256": digest, "bytes": size}
        if path in voice_paths:
            result.update(check_audio_range(candidate / "public", item))
        return result
    results = http.ordered_checks(expected, check, workers)
    if baseline and CATALOG_NAME not in {item["path"] for item in expected}:
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


def check_audio_range(public: Path, item: dict) -> dict:
    """Verify the one-byte response or Firebase's checked full-body fallback."""
    path = "/" + item["path"]
    status, headers, size, digest = http.request_file(
        ORIGIN, path, request_headers={"Range": "bytes=0-0"})
    with (public / item["path"]).open("rb") as stream:
        first_byte = stream.read(1)
    partial = (status == 206 and size == 1
               and digest == hashlib.sha256(first_byte).hexdigest()
               and headers.get("content-range") == f"bytes 0-0/{item['bytes']}")
    full = (status == 200 and size == item["bytes"]
            and digest == item["sha256"] and "content-range" not in headers)
    require(partial or full, f"Voice audition Range/full-body check failed: {path}")
    return {"range206": partial, "fullBodyFallback": full}


def refresh(base: Path, legacy: Path, prior_http: Path, out: Path) -> dict:
    """Carry the voice overlay into a reviewed legacy weekly release."""
    require(not out.exists() and not out.is_symlink(), "Use a new candidate directory")
    current = verify_candidate(base)
    prior = hosting.load(prior_http)
    require(prior.get("schemaVersion") == "sermon-production-voice-http-v1"
            and prior.get("status") == "pass" and prior.get("phase") == "published"
            and prior.get("origin") == ORIGIN
            and prior.get("buildReportSha256") == hosting.digest(base / "build-report.json")
            and prior.get("checkedFiles") == len(current["files"]),
            "Prior HTTP receipt does not bind the current voice overlay")
    legacy_report, new_weekly = weekly_release.read_release(legacy)
    plan = hosting.load(legacy / "release-plan.json")
    old_weekly = hosting.load(base / "public/weekly.json")
    previous_ids = {page["id"] for page in old_weekly["weeks"]}
    incoming_ids = {page["id"] for page in new_weekly["weeks"]}
    require(plan.get("schemaVersion") == "sermon-weekly-release-plan-v1"
            and plan.get("status") == "prepared_not_deployed"
            and plan.get("origin") == ORIGIN
            and plan.get("buildReportSha256") == hosting.digest(legacy / "build-report.json")
            and plan.get("previousWeekIds") == sorted(previous_ids)
            and plan.get("weekIds") == sorted(incoming_ids)
            and plan.get("changes", {}).get("removed") == []
            and plan.get("uiPolicy") == "reuse_registered_ui_and_settings"
            and previous_ids.issubset(incoming_ids)
            and legacy_report.get("reviewPreview") is False
            and legacy_report.get("feedbackEnabled") == current["feedbackEnabled"],
            "Weekly release does not extend the current catalog and feedback policy")
    old_public = base / "public"
    old_files = hosting.regular_files(old_public)
    new_files = hosting.regular_files(legacy / "public")
    for name, path in new_files.items():
        if name in {"index.html", "style.css", "weekly.json"}:
            continue
        if name in old_files:
            require(hosting.digest(path) == hosting.digest(old_files[name]),
                    f"Weekly release would overwrite a Production file: {name}")
        else:
            require(name.startswith(("media/", "downloads/", "fingerprints/")),
                    f"Weekly release adds unreviewed UI: {name}")
    require({item["id"]: item for item in old_weekly["voiceBank"]["speakers"]}
            == {item["id"]: item for item in new_weekly["voiceBank"]["speakers"]},
            "Weekly release changed speaker auditions")

    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        public = temporary / "public"
        shutil.copytree(old_public, public)
        for name, path in new_files.items():
            if name in old_files or name in {"index.html", "style.css", "weekly.json"}:
                continue
            target = public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
        shutil.copyfile(legacy / "public/weekly.json", public / "weekly.json")
        shutil.copyfile(base / "firebase.json", temporary / "firebase.json")
        if current["feedbackEnabled"]:
            feedback = legacy / "feedback-catalog.json"
            require(feedback.is_file()
                    and hosting.digest(feedback) == legacy_report["feedbackCatalogSha256"],
                    "Reviewed feedback catalog changed")
            shutil.copyfile(feedback, temporary / "feedback-catalog.json")
        report = dict(current)
        report.update(baseFiles=current["files"], files=inventory(public),
                      oldWeeklyCatalogSha256=hosting.digest(public / "weekly.json"),
                      baseBuildReportSha256=hosting.digest(base / "build-report.json"),
                      legacyWeeklyReleaseBuildReportSha256=hosting.digest(legacy / "build-report.json"),
                      legacyWeeklyReleasePlanSha256=hosting.digest(legacy / "release-plan.json"),
                      priorHttpVerificationSha256=hosting.digest(prior_http))
        before = {item["path"]: item for item in current["files"]}
        after = {item["path"]: item for item in report["files"]}
        report["modifiedFiles"] = sorted(name for name in before if before[name] != after.get(name))
        report["addedFiles"] = sorted(set(after) - set(before))
        if current["feedbackEnabled"]:
            report["feedbackCatalogSha256"] = hosting.digest(temporary / "feedback-catalog.json")
        (temporary / "build-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        verify_candidate(temporary)
        os.rename(temporary, out)
        return report
    except Exception:
        shutil.rmtree(temporary)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("stage")
    build.add_argument("--base", type=Path, required=True)
    build.add_argument("--dev-public", type=Path, required=True)
    build.add_argument("--delivery", type=Path, required=True)
    build.add_argument("--out", type=Path, required=True)
    update = sub.add_parser("refresh-weekly")
    update.add_argument("--base-candidate", type=Path, required=True)
    update.add_argument("--legacy-release", type=Path, required=True)
    update.add_argument("--prior-http-verification", type=Path, required=True)
    update.add_argument("--out", type=Path, required=True)
    for name in ("preflight", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--candidate", type=Path, required=True)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--http-workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "stage":
        report = stage(args.base, args.dev_public, args.delivery, args.out)
        print(json.dumps({"status": report["status"], "addedFiles": len(report["addedFiles"])}))
    elif args.command == "refresh-weekly":
        report = refresh(args.base_candidate, args.legacy_release,
                         args.prior_http_verification, args.out)
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
