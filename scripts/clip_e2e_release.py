#!/usr/bin/env python3
"""Prepare the machine-checked release of a real-model clip E2E for an isolated Dev page.

Inputs per locale are the run's real candidate, text waiver, audio package, audio waiver and
ASR screening receipt; the output is the frozen ``sermon_unified_delivery`` plan and its prepared
release (catalog v4 with a ``machine_checked`` disclosure per locale), ready for
``run_dev_simulated_delivery.py --machine-checked``.

Two human gates of the delivery contract have no machine replacement in this path: the page
metadata approval and the outline/meditation study reviews. For an isolated test page they are
filled from the run specification's explicit authorization statement, and every such record
says it is a default pass, not a human review. The study products are deterministic test
sections built from the candidate, not model output. Display texts come from the run
specification and must label the page as a test. See docs/clip-real-e2e.zh.md.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMPLATE = ROOT / "artifacts/unified-cli-acceptance/native-four-product-fixture-v2"
DEV_ROUTE = {"channel": "dev", "project": "ai-for-god-sermon-audio-dev", "site": "ai-for-god-sermon-audio-dev",
             "origin": "https://ai-for-god-sermon-audio-dev.web.app"}
DISPLAY_FIELDS = ("series", "title", "speaker", "scripture", "summary")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def one(directory: Path, prefix: str) -> Path:
    found = [p for p in Path(directory).glob(prefix + "*.json") if not p.name.endswith(".inputs.json")]
    require(len(found) == 1, f"expected exactly one {prefix}*.json in {directory}, found {len(found)}")
    return found[0]


def validate_display(display: dict, locales: list[str]) -> None:
    require(isinstance(display, dict) and set(locales) <= set(display), "display texts missing for a locale")
    for locale in locales:
        row = display[locale]
        require(isinstance(row, dict) and set(DISPLAY_FIELDS) <= set(row)
                and all(isinstance(row[k], str) and row[k].strip() for k in DISPLAY_FIELDS),
                f"display texts incomplete for {locale}")


def prepare(out: Path, *, page_id: str, date: str, locales: list[str], source_path: Path, anchor_path: Path,
            lanes: dict, display: dict, default_pass: str, template: Path = TEMPLATE) -> dict:
    """Write and execute the frozen delivery plan; ``lanes[locale]`` has candidate, textQcOut, audioPackage, audioQcOut."""
    from scripts import build_full_video_app_release as release
    from scripts import machine_quality_release_basis as basis
    from scripts import sermon_unified_delivery as delivery
    from scripts import study_artifacts
    from scripts.build_dev_180s_simulated_inputs import read, save, ref
    from scripts.delivery_contract import sha as json_sha
    require(page_id.startswith(("mockup-", "dev-")), "clip E2E pages must use an isolated mockup-/dev- page ID")
    require(isinstance(default_pass, str) and "not a human review" in default_pass,
            "the default-pass statement must say it is not a human review")
    validate_display(display, locales)
    out = Path(out)
    require(not out.exists() or not any(out.iterdir()), "Layer 4 output directory must be new or empty")
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    shown = {locale: dict(display[locale], outline=["[test] see the outline study product"]) for locale in locales}
    source, anchor = read(source_path), read(anchor_path)
    source_sha = json_sha(source)
    units = {u["sourceUnitId"]: u for u in anchor["sourceUnits"]}
    window = source["source"]["approvedWindow"]
    config = copy.deepcopy(read(template / "config.json"))
    config.update(pageId=page_id, date=date, locales=locales, workRoot=str(out / "work"), action="prepare",
                  requiredEndpoints=["dev", "beta", "production_ios", "production_web"],
                  intent=dict(DEV_ROUTE, schemaVersion="sermon-release-intent-v1", environment="dev"),
                  routes={"dev": DEV_ROUTE})
    config["inputs"] = {"source": ref(source_path), **{name: {} for name in delivery.MAPS}}
    proposal_path = save(out / "metadata-proposal.json", {
        "schemaVersion": "sermon-formal-metadata-proposal-draft-v1", "pageId": page_id, "date": date,
        "note": "Dev real-model clip E2E test page; display fields label the page as a test.",
        "locales": {k: shown[k] for k in locales}})
    for locale in locales:
        lane, loc = lanes[locale], out / locale
        candidate_path = Path(lane["candidate"])
        candidate = read(candidate_path)
        package_path = Path(lane["audioPackage"])
        package = read(package_path)
        text_waiver = one(Path(lane["textQcOut"]), "text-waiver-")
        audio_waiver = one(Path(lane["audioQcOut"]), "audio-waiver-")
        screening = Path(read(Path(lane["audioQcOut"]) / "preflight.json")["paths"]["screening"])
        require(package["targetLanguageCandidateJsonSha256"] == json_sha(candidate)
                and package["englishSourcePackageJsonSha256"] == source_sha,
                f"{locale}: audio package is not built from this candidate and source")
        cues = [{"textGroupId": g["translationGroupId"], "sourceUnitIds": g["sourceUnitIds"],
                 "start": round(min(float(units[i]["start"]) for i in g["sourceUnitIds"]), 3),
                 "end": round(max(float(units[i]["end"]) for i in g["sourceUnitIds"]), 3), "text": g["targetText"]}
                for g in candidate["groups"]]
        track = Path(package["track"]["path"])
        content = dict(shown[locale], schemaVersion="sermon-full-video-text-content-v3", pageId=page_id, targetLocale=locale,
                       sourceLocale="en", status="machine_checked", englishSourcePackageJsonSha256=source_sha,
                       targetLanguageCandidateJsonSha256=json_sha(candidate),
                       sourceMediaSha256=source["source"]["media"]["sha256"],
                       durationSeconds=window["endSeconds"] - window["startSeconds"],
                       audioDurationSeconds=release.stage.decode_audio(track, locale + " measured audio clock"),
                       reviewMode="formal", cues=cues, disclosure=basis.disclosure(locale),
                       sourceWindow={"schemaVersion": "sermon-original-recording-window-v1",
                                     "mediaSha256": source["source"]["media"]["sha256"],
                                     "startSeconds": window["startSeconds"], "endSeconds": window["endSeconds"]})
        release.validate(content, "sermon-full-video-text-content-v3.schema.json")
        names = {"full_candidate": candidate_path, "spoken_candidate": candidate_path, "full_review_receipt": text_waiver,
                 "spoken_review_receipt": text_waiver, "audio_package": package_path, "audio_review_receipt": audio_waiver,
                 "audio_screening_receipt": screening, "full_content": save(loc / "full-content.json", content)}
        for kind in ("outline", "meditation"):
            sections = [{"title": f"[test] {kind} {i + 1}", "body": g["targetText"], "sourceUnitIds": g["sourceUnitIds"]}
                        for i, g in enumerate(candidate["groups"])]
            artifact = study_artifacts.produce(kind, sections, page_id=page_id, locale=locale, source_sha=source_sha,
                                               text_sha=json_sha(candidate),
                                               producer_identity="deterministic test sections from the candidate (no model)")
            artifact_path = save(loc / f"{kind}.json", artifact)
            review = read(template / "outline_review.json")
            review.update(kind=kind, pageId=page_id, locale=locale, sourcePackageSha256=source_sha,
                          textCandidateSha256=json_sha(candidate), artifactSha256=json_sha(artifact),
                          reviewedBy=default_pass, reviewedAt=recorded_at)
            study_artifacts.ingest_review(artifact, review)
            names[kind] = artifact_path
            names[kind + "_review"] = save(loc / f"{kind}-review.json", review)
        for name, path in names.items():
            config["inputs"][name][locale] = ref(path)
    metadata = {"schemaVersion": "sermon-formal-dev-metadata-approval-v2", "pageId": page_id, "date": date,
                "proposalFileSha256": hashlib.sha256(proposal_path.read_bytes()).hexdigest(),
                "decision": "approved_selected_locales", "approvalText": "所列语言页面信息已批准", "reviewer": "user",
                "recordedAt": recorded_at, "approvedLocales": locales, "locales": {k: shown[k] for k in locales}}
    (out / "metadata-approval.evidence.txt").write_text("Metadata approval for this Dev test page: " + default_pass + "\n")
    config["inputs"]["metadata_approval"] = ref(save(out / "metadata-approval.json", metadata))
    config["inputs"]["metadata_proposal"] = ref(proposal_path)
    frozen = out / "delivery.json"
    plan = delivery.freeze(save(out / "delivery-draft.json", config), frozen)
    result = delivery.execute(frozen, plan["planHash"])
    save(out / "prepare-result.json", result)
    return {"status": result.get("status"), "pageId": page_id, "fourProducts": result.get("fourProducts"),
            "prepared": str(out / "work/prepared")}


if __name__ == "__main__":
    raise SystemExit("Run through tools/development/run_clip_real_e2e.py (stage layer4); see docs/clip-real-e2e.zh.md")
