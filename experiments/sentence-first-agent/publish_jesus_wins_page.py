#!/usr/bin/env python3
"""Publish the 2026-10-23 sentence-first clip to the Dev Hosting site (experiment only).

Copy of publish_podcast_page.py for one clip page, per the runbook's "copy the driver and
change the top constants" step. Two differences from the published podcast driver:

  * ENVIRONMENT = "dev": every baseline/stage step targets the Dev project, not Production.
  * the page is a 10-minute clip; the Layer 2 candidates are clip packages built from the
    reviewed sentence table (zh reuses the formal approved candidate's targets, ko is the
    agent translation). No Production catalog or release is touched.

Sequence (each its own subcommand): assets -> baseline -> stage1 -> publish -> verify ->
stage2 -> publish -> readback -> baseline -> stage-english-reference -> publish.

Run from the sfa-main worktree with its packages first on PYTHONPATH and the main checkout's
venv. Example:

  PYTHONPATH="packages/production/src:." GOOGLE_APPLICATION_CREDENTIALS=... \
  XDG_CONFIG_HOME=<writable firebase configstore copy> python publish_clip_page_dev.py assets --out ...
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen

WT = Path(__file__).resolve().parents[2]
for entry in (str(WT), str(WT / "packages/production/src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.delivery import baseline as bl, contract, publication as pub  # noqa: E402
from tongxing_production.delivery import published_english_reference as english_reference  # noqa: E402

ENVIRONMENT = "production"
PAGE_ID = "if-i-had-more-time-jesus-wins"
LOCALES = ("zh-Hans", "ko", "es")
RUN_DIR = {"zh-Hans": "20261026-jesus-wins-podcast-zh", "ko": "20261026-jesus-wins-podcast-ko", "es": "20261026-jesus-wins-podcast-es"}
RUNS = Path("/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/sentence-first-agent")
PODCAST = Path("/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts/if-i-had-more-time-jesus-wins")
SOURCE_URL = "https://www.youtube.com/watch?v=7KRsow9aqBo"
DATE = "2026-10-25"
WINDOW_START, WINDOW_END = 0.0, 3297.466
SENTENCES = 890
SPEAKERS = "Eric Geiger · Steve Bang Lee"
CATEGORY = {"schemaVersion": "sermon-page-display-category-v1",
            "labels": {"zh-Hans": "播客", "en": "Podcast", "ko": "팟캐스트", "es": "Pódcast"}}
PAGE_TITLE = "如果我有更多时间 · 耶稣得胜"
META = {
    "zh-Hans": {"title": PAGE_TITLE, "series": "如果我有更多时间（播客系列）", "scripture": "启示录 12–13 章",
                "badge": "证道播客 · AI 合成配音 · 已人工审核",
                "source": "英文来源 / English source",
                "note": "自然语速配音，非原视频同步。本项目与 Mariners Church 无隶属关系。"},
    "ko": {"title": "If I Had More Time · 예수님은 승리하십니다",
           "series": "If I Had More Time", "scripture": "요한계시록 12–13장",
           "badge": "설교 팟캐스트 · AI 합성 음성 · 검토 완료",
           "source": "영어 원본 / English source",
           "note": "자연스러운 속도의 더빙으로, 원본 영상과 동기화되지 않습니다. 이 프로젝트는 Mariners Church와 관련이 없습니다."},
    "es": {"title": "If I Had More Time · Jesús vence",
           "series": "If I Had More Time", "scripture": "Apocalipsis 12–13",
           "badge": "Pódcast del sermón · Voz sintetizada por IA · Revisado",
           "source": "Fuente en inglés / English source",
           "note": "Doblaje a ritmo natural, no sincronizado con el video original. Este proyecto no está afiliado a Mariners Church."},
}
VERDICT = RUNS / "20261026-jesus-wins-podcast-review" / "human-review-verdict.json"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def json_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def reader(url):
    with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=120) as response:
        return response.status, response.read()


def english_source() -> tuple[dict, str]:
    value = json.loads((PODCAST / "layer1-srt/english-source.json").read_text(encoding="utf-8"))
    return value, json_sha(value)


def ios_cue_check(cues, duration, requires_units):
    """The iOS reader's validateCues (PublishedTranscript.swift), so a bad file never ships again."""
    contract.require(0 < len(cues) <= 10_000, "cue count")
    previous, ids = 0.0, set()
    for cue in cues:
        contract.require(cue["start"] >= previous and cue["start"] < cue["end"] and cue["end"] <= duration + 0.001
                         and cue["text"].strip() and cue["textGroupId"] not in ids,
                         f"iOS would reject cue {cue['textGroupId']} ({cue['start']}–{cue['end']} vs {duration})")
        contract.require(not requires_units or bool(cue.get("sourceUnitIds")), "missing sourceUnitIds")
        ids.add(cue["textGroupId"])
        previous = cue["end"]


def cmd_assets(out: Path) -> dict:
    contract.require(not out.exists(), "Use a new assets directory")
    esp, esp_sha = english_source()
    media = esp["source"]["media"]["sha256"]
    contract.require(hashlib.sha256(SOURCE_URL.encode()).hexdigest() == esp["source"]["sourceUrlHash"],
                     "Source URL differs from the source package")
    verdict = VERDICT
    contract.require(verdict.exists(), f"Human review verdict missing: {verdict}")
    contract.require(json.loads(verdict.read_text())["verdict"] == "approved", "Human review verdict is not approved")
    summary = {}
    for loc in LOCALES:
        run = RUNS / RUN_DIR[loc]
        sent = rows(run / "sentences.jsonl")
        tr = {r["id"]: r for r in rows(run / "translations.jsonl")}
        sp = {r["id"]: r for r in rows(run / "speech.jsonl")}
        sched = {r["id"]: r for r in json.loads((run / "schedule.json").read_text())["sentences"]}
        contract.require(len(sent) == SENTENCES and all(sched.get(s["id"], {}).get("actualStart") is not None for s in sent),
                         f"{loc}: sentence table or schedule incomplete")
        candidate = {"schemaVersion": "sentence-first-episode-candidate-v1", "pageId": PAGE_ID, "targetLocale": loc,
                     "englishSourcePackageJsonSha256": esp_sha,
                     "translationBasis": f"{loc}: agent translation with independent second-pass review",
                     "humanReview": {"verdictSha256": sha_file(verdict), "status": "approved"},
                     "groups": [{"id": s["id"], "sourceUnitId": s["sourceUnitId"], "speakerId": s["speakerId"],
                                 "english": s["english"], "targetText": tr[s["id"]]["target"],
                                 "spokenText": sp[s["id"]]["spokenText"]} for s in sent]}
        write_json(out / f"packages/{loc}-candidate.json", candidate)
        candidate_sha = json_sha(candidate)
        mp3 = out / f"public/media/{PAGE_ID}/{loc}.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(run / "track.wav"),
                        "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
        audio_seconds = round(float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(mp3)],
            capture_output=True, text=True, check=True).stdout.strip()), 3)
        audio_package = {"schemaVersion": "sentence-first-episode-audio-package-v1", "pageId": PAGE_ID, "targetLocale": loc,
                         "targetLanguageCandidateJsonSha256": candidate_sha,
                         "voices": sorted({s["speakerId"] for s in sent}),
                         "track": {"wavSha256": sha_file(run / "track.wav"), "mp3Sha256": sha_file(mp3),
                                   "mp3DurationSeconds": audio_seconds},
                         "synchronization": "not on the source video clock; natural-rate dub of a 10-minute clip",
                         "humanReview": {"verdictSha256": sha_file(verdict), "status": "approved"},
                         "units": [{"id": s["id"], "sourceUnitId": s["sourceUnitId"], "speakerId": s["speakerId"],
                                    "wavSha256": sha_file(run / f"tts/{s['id']}.wav"),
                                    "plannedStart": sched[s["id"]]["actualStart"], "seconds": sched[s["id"]]["dubSeconds"]}
                                   for s in sent]}
        write_json(out / f"packages/{loc}-audio-package.json", audio_package)
        audio_sha = json_sha(audio_package)
        captions = {"schemaVersion": "sermon-target-language-captions-v1", "pageId": PAGE_ID, "locale": loc,
                    "audioPackageJsonSha256": audio_sha,
                    "timingBasis": "concatenated target audio; natural unit durations; no source-video synchronization",
                    "cues": [{"start": round(sched[s["id"]]["actualStart"], 3),
                              "end": round(sched[s["id"]]["actualStart"] + sched[s["id"]]["dubSeconds"], 3),
                              "sourceUnitIds": [s["sourceUnitId"]], "text": tr[s["id"]]["target"],
                              "textGroupId": "translation-" + s["sourceUnitId"]} for s in sent]}
        write_json(out / f"public/captions/{PAGE_ID}/{loc}.json", captions)
        m = META[loc]
        content = {"schemaVersion": "sermon-full-video-text-content-v2", "pageId": PAGE_ID, "locale": loc, "targetLocale": loc,
                   "sourceLocale": "en", "status": "human_reviewed", "contentStatus": "human_reviewed",
                   "audioStatus": "human_reviewed", "reviewMode": "formal", "date": DATE, "title": m["title"],
                   "series": m["series"], "scripture": m["scripture"], "speaker": SPEAKERS,
                   "durationSeconds": WINDOW_END, "audioDurationSeconds": audio_seconds,
                   "englishSourcePackageJsonSha256": esp_sha, "sourceMediaSha256": media,
                   "targetLanguageCandidateJsonSha256": candidate_sha, "targetLanguageAudioPackageJsonSha256": audio_sha,
                   "cues": [{"start": round(WINDOW_START + s["start"], 3), "end": round(WINDOW_START + s["end"], 3),
                             "sourceUnitIds": [s["sourceUnitId"]], "text": tr[s["id"]]["target"],
                             "textGroupId": "translation-" + s["sourceUnitId"]} for s in sent]}
        ios_cue_check(content["cues"], content["durationSeconds"], True)
        ios_cue_check(captions["cues"], audio_seconds, False)
        write_json(out / f"public/content/{PAGE_ID}/{loc}.json", content)
        body = "".join(f"<p>{html.escape(tr[s['id']]['target'])}</p>" for s in sent)
        page = (f'<!doctype html><html lang="{loc}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(m["title"])}</title>'
                '<style>body{max-width:48rem;margin:auto;padding:1.2rem;font:1.1rem/1.7 system-ui}audio{width:100%}</style></head>'
                f'<body><h1>{html.escape(m["title"])}</h1><p>{DATE} · {html.escape(SPEAKERS)}</p><p>{html.escape(m["badge"])}</p>'
                f'<audio controls preload="none" src="/media/{PAGE_ID}/{loc}.mp3"></audio>'
                f'<p><a href="{SOURCE_URL}">{html.escape(m["source"])}</a></p><p>{html.escape(m["note"])}</p>{body}</body></html>')
        page_path = out / f"public/pages/{PAGE_ID}/{loc}/index.html"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(page, encoding="utf-8")
        release = {"schemaVersion": "sermon-target-language-release-package-v2", "packageId": f"{PAGE_ID}-{loc}-{ENVIRONMENT}-v1",
                   "pageId": PAGE_ID, "sourceLocale": "en", "targetLocale": loc, "interfaceLocale": loc,
                   "contentLocale": loc, "audioLocale": loc,
                   "targetLanguageCandidateJsonSha256": candidate_sha, "spokenTargetLanguageCandidateJsonSha256": candidate_sha,
                   "targetLanguageAudioPackageJsonSha256": audio_sha, "status": "candidate",
                   "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                   "assets": [{"role": role, "path": path, "sha256": sha_file(out / "public" / path.lstrip("/"))}
                              for role, path in (("page", f"/pages/{PAGE_ID}/{loc}/index.html"),
                                                 ("content", f"/content/{PAGE_ID}/{loc}.json"),
                                                 ("audio", f"/media/{PAGE_ID}/{loc}.mp3"),
                                                 ("captions", f"/captions/{PAGE_ID}/{loc}.json"))],
                   "httpVerification": {"status": "not_run", "evidenceSha256": None},
                   "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
                   "venueAcceptance": {"status": "not_run", "evidenceSha256": None}, "issues": []}
        contract.validate_release_schema(release)
        write_json(out / f"releases/{loc}.json", release)
        summary[loc] = {"cues": len(sent), "audioSeconds": audio_seconds, "mp3Bytes": mp3.stat().st_size}
    write_json(out / "assets-summary.json", {"pageId": PAGE_ID, "environment": ENVIRONMENT,
                                             "englishSourcePackageJsonSha256": esp_sha,
                                             "sourceMediaSha256": media, "locales": summary})
    return summary


def stage(base: Path, out: Path, add_public: Path | None, files: dict[str, bytes] | None = None,
          replace: frozenset[str] = frozenset()) -> None:
    contract.require(not out.exists(), "Use a new snapshot directory")
    out.mkdir(parents=True)
    shutil.copytree(base / "public", out / "public")
    shutil.copyfile(base / "firebase.json", out / "firebase.json")
    shutil.copyfile(base / "baseline-receipt.json", out / "baseline-receipt.json")
    added = []
    if add_public is not None:
        for src in sorted(add_public.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(add_public)
            target = out / "public" / rel
            contract.require(not target.exists(), "Refusing to overwrite an existing published file: " + str(rel))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            added.append("/" + str(rel))
    for rel, data in (files or {}).items():
        target = out / "public" / rel
        contract.require(not target.exists() or rel in contract.CATALOG_FILES.values() or rel in replace,
                         "Refusing to overwrite: " + rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        added.append("/" + rel)
    report = {**bl.catalog_report(out / "public"), "files": bl.files_report(out / "public")}
    bl.write(out / "seal-report.json", report)
    contract.validate_catalog_snapshot(out)
    bl.write(out / "publish-config.json", bl.publication_config(base, out, environment=ENVIRONMENT))
    write_json(out / "staged-changes.json", {"pageId": PAGE_ID, "environment": ENVIRONMENT,
                                             "changedPaths": added, "base": str(base)})


def cmd_stage1(baseline_dir: Path, assets: Path, out: Path) -> dict:
    public = baseline_dir / "public"
    read = lambda name: json.loads((public / contract.CATALOG_FILES[name]).read_text())
    v4, v3, changes = contract.repair_projected_defaults(read(contract.CATALOG_V5), read(contract.CATALOG_V4), read(contract.CATALOG_V3))
    files = {}
    if changes:
        for name, value in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
            files[contract.CATALOG_FILES[name]] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stage(baseline_dir, out, assets / "public", files)
    write_json(out / "catalog-default-locale-repair.json",
               {"reason": "live v4/v3 default locales re-projected from live v5 (dev site)", "changes": changes})
    return {"staged": str(out), "files": len(json.loads((out / "staged-changes.json").read_text())["changedPaths"]),
            "defaultLocaleChanges": len(changes)}


def cmd_publish(snapshot: Path) -> dict:
    config = bl.read(snapshot / "publish-config.json")
    contract.require(not (snapshot / "deployment-attempt-v2.json").exists(),
                     "This snapshot already has a deployment attempt; reconcile it, never retry")
    result = pub.publish(**config, request=pub.authenticated_transport(), reader=reader)
    return {k: result.get(k) for k in ("status", "newVersion", "baselineVersion", "catalogSha256")}


def cmd_verify(assets: Path, out: Path) -> dict:
    origin = bl.hosting_target(ENVIRONMENT)["origin"]
    checks = []
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        for asset in release["assets"]:
            status, data = reader(origin + asset["path"])
            digest = hashlib.sha256(data).hexdigest()
            row = {"path": asset["path"], "status": status, "sha256": digest, "pass": status == 200 and digest == asset["sha256"]}
            if asset["role"] == "audio":
                with urlopen(Request(origin + asset["path"], headers={"Range": "bytes=0-1023", "Cache-Control": "no-cache"}),
                             timeout=120) as r:
                    part = r.read()
                    row.update(rangeStatus=r.status, contentRange=r.headers.get("Content-Range"),
                               contentType=r.headers.get("Content-Type"))
                row["pass"] = (row["pass"] and row["rangeStatus"] == 206 and len(part) == 1024
                               and row["contentRange"] == f"bytes 0-1023/{len(data)}")
            checks.append(row)
    evidence = {"schemaVersion": "sentence-first-episode-http-verification-v1", "origin": origin, "pageId": PAGE_ID,
                "checks": checks, "status": "pass" if all(c["pass"] for c in checks) else "fail"}
    write_json(out, evidence)
    return {"status": evidence["status"], "checks": len(checks), "failed": [c["path"] for c in checks if not c["pass"]]}


def cmd_stage2(stage1: Path, assets: Path, evidence_path: Path, out: Path, with_english: bool = False) -> dict:
    evidence = json.loads(evidence_path.read_text())
    contract.require(evidence["status"] == "pass", "HTTP verification did not pass")
    attempt = json.loads((stage1 / "deployment-attempt-v2.json").read_text())
    contract.require(attempt.get("status") == "deployed", "Stage 1 is not deployed")
    evidence_sha = sha_file(evidence_path)
    esp, esp_sha = english_source()
    files, targets = {}, {}
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        release.update(status="published_http_verified", httpVerification={"status": "pass", "evidenceSha256": evidence_sha})
        contract.validate_release_schema(release)
        data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        files[f"releases-v2/{PAGE_ID}/{loc}.json"] = data
        targets[loc] = {"audioStatus": "human_reviewed", "capabilities": ["text", "captions", "audio"],
                        "contentStatus": "human_reviewed", "releasePackageJsonSha256": hashlib.sha256(data).hexdigest(),
                        "releasePackageUrl": f"/releases-v2/{PAGE_ID}/{loc}.json"}
    public = stage1 / "public"
    old = {name: json.loads((public / contract.CATALOG_FILES[name]).read_text()) for name in contract.CATALOG_FILES}
    contract.require(all(p["id"] != PAGE_ID for v in old.values() for p in v["pages"]), "Page already in a live catalog")
    page = {"id": PAGE_ID, "date": DATE, "title": PAGE_TITLE, "defaultTargetLocale": "zh-Hans", "displayCategory": CATEGORY,
            "mediaType": "podcast", "sourceLocale": "en", "sourceIdentitySha256": esp_sha,
            "sourceMediaSha256": esp["source"]["media"]["sha256"], "sourceMode": "single_source",
            "sourceUrl": SOURCE_URL, "targets": targets}
    v5 = copy.deepcopy(old[contract.CATALOG_V5])
    v5["pages"].append(page)
    contract.validate_catalog_schema(v5)
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    for name, new in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        contract.require(sum(p["id"] == PAGE_ID for p in new["pages"]) == 1, name + ": page missing from projection")
        contract.require({**new, "pages": [p for p in new["pages"] if p["id"] != PAGE_ID]} == old[name],
                         name + ": projection changed other pages")
    for loc in LOCALES:
        release = json.loads(files[f"releases-v2/{PAGE_ID}/{loc}.json"])
        contract.validate_v2_release_target(release, page, loc)
        contract.validate_content_target(json.loads((public / f"content/{PAGE_ID}/{loc}.json").read_text()), page, loc)
    for name, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        files[contract.CATALOG_FILES[name]] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stage(stage1, out, None, files)
    result = {"staged": str(out), "changed": sorted(files), "defaultPageId": v3["defaultPageId"]}
    if with_english:
        reference = english_reference.build_reference(out / "public", PAGE_ID, PODCAST / "layer1-srt/english-source.json")
        target = out / "public" / "english-reference" / f"{PAGE_ID}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(reference, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        result["englishReference"] = {"path": f"/english-reference/{PAGE_ID}.json", "sha256": sha_file(target),
                                      "blocks": {loc: len(reference["targets"][loc]["blocks"]) for loc in LOCALES}}
    return result


def build_clip_reference(public: Path, page_id: str, source_path: Path) -> dict:
    """The published English comparison for a clip page.

    Same approval and hash checks as published_english_reference.build_reference, except that the
    page's cues must cover a *contiguous ordered subset* of the approved source units instead of
    every unit. A 10-minute clip of a 40-minute episode is exactly that case; the canonical builder
    requires the page to cover all 746 units and would refuse it (2026-10-23 finding).
    """
    er = english_reference
    source = er.read_json(source_path)
    er.require(source.get("schemaVersion") == "sermon-english-source-package-v1", "Unsupported source package")
    er.require(source.get("status") == "ready_for_translation" and source.get("translationEligible") is True,
               "English source is not approved for translation")
    review = source.get("review", {})
    er.require(review.get("humanApproval") is True, "English source needs human approval")
    checks = ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries")
    er.require(all(review.get("checks", {}).get(k) == "approved" for k in checks), "Incomplete source approval")
    window = source["source"]["approvedWindow"]
    er.require(window.get("humanApproval") is True and window.get("status") == "approved", "Unapproved source window")
    er.read_evidence(window["evidence"])
    er.read_evidence(source["transcript"]["artifact"])
    anchors = er.read_evidence(source["anchors"]["artifact"])
    receipt = er.read_evidence(review["evidence"])
    er.require(receipt.get("humanApproval") is True and all(receipt.get("checks", {}).get(k) == "approved" for k in checks),
               "Incomplete approval receipt")
    er.require(receipt.get("anchorManifestJsonSha256") == source["anchors"]["artifact"]["jsonSha256"],
               "Approval receipt does not cover these anchors")
    er.require(receipt.get("alignedSegmentsSha256") == source["transcript"]["artifact"]["sha256"]
               == anchors.get("input", {}).get("mfaSegmentsSha256"), "Transcript binding mismatch")
    units = anchors["sourceUnits"]
    unit_ids = [unit["sourceUnitId"] for unit in units]
    er.require(unit_ids and len(set(unit_ids)) == len(unit_ids), "Duplicate or absent source units")
    er.require(len(unit_ids) == source["anchors"]["sourceUnitCount"], "Source unit count mismatch")
    er.require(review.get("reviewedSourceUnitIds") == unit_ids, "Source review does not cover all ordered units")
    er.require(receipt.get("reviewedSourceUnitIds") == unit_ids, "Receipt does not cover all ordered units")
    english = {unit["sourceUnitId"]: unit["english"] for unit in units}
    er.require(all(isinstance(text, str) and text.strip() for text in english.values()), "Empty English unit")
    source_sha = er.canonical_sha(source)
    media_sha = source["source"]["media"]["sha256"]
    catalog = er.published_catalog(public)
    allowed = er.PUBLISHED_CONTENT[catalog["schemaVersion"]]
    pages = [page for page in catalog["pages"] if page["id"] == page_id]
    er.require(len(pages) == 1, "Page must occur exactly once in catalog")
    page = pages[0]
    er.require(page["sourceIdentitySha256"] == source_sha, "Catalog source identity mismatch")
    targets = {}
    for locale, target in page["targets"].items():
        release = er.read_json(er.public_path(public, target["releasePackageUrl"]),
                               sha256=target["releasePackageJsonSha256"])
        er.require(release.get("status") == "published_http_verified" and release.get("contentStatus") in allowed,
                   f"Unpublished or unreviewed release: {locale}")
        er.require(release.get("pageId") == page_id and release.get("targetLocale") == locale
                   and release.get("contentLocale") == locale, f"Release identity mismatch: {locale}")
        assets = {}
        for role in ("content", "captions"):
            matches = [asset for asset in release["assets"] if asset["role"] == role]
            er.require(len(matches) == 1, f"Expected one {role} asset: {locale}")
            asset = matches[0]
            assets[role] = (er.read_json(er.public_path(public, asset["path"]), sha256=asset["sha256"]), asset["sha256"])
        content, content_sha = assets["content"]
        captions, captions_sha = assets["captions"]
        er.require(content.get("pageId") == page_id and content.get("targetLocale") == locale
                   and content.get("status") == release["contentStatus"], f"Content identity/status mismatch: {locale}")
        er.require(content.get("englishSourcePackageJsonSha256") == source_sha
                   and content.get("sourceMediaSha256") == media_sha, f"Content source mismatch: {locale}")
        er.require(content.get("targetLanguageCandidateJsonSha256") == release.get("targetLanguageCandidateJsonSha256"),
                   f"Content candidate mismatch: {locale}")
        groups = content["cues"]
        group_ids = [group["textGroupId"] for group in groups]
        er.require(len(set(group_ids)) == len(group_ids), f"Duplicate translation groups: {locale}")
        er.require([cue["textGroupId"] for cue in captions["cues"]] == group_ids,
                   f"Spoken captions do not match translation group order: {locale}")
        mapped_ids = [unit_id for group in groups for unit_id in group["sourceUnitIds"]]
        er.require(all(group["sourceUnitIds"] for group in groups), f"Empty source mapping: {locale}")
        er.require(mapped_ids and all(unit_id in english for unit_id in mapped_ids),
                   f"Page maps an unapproved source unit: {locale}")
        lo = unit_ids.index(mapped_ids[0])
        er.require(mapped_ids == unit_ids[lo:lo + len(mapped_ids)],
                   f"Page cues are not a contiguous ordered subset of the approved units: {locale}")
        blocks = [{"textGroupId": group["textGroupId"], "sourceUnitIds": group["sourceUnitIds"],
                   "english": " ".join(english[unit_id] for unit_id in group["sourceUnitIds"])} for group in groups]
        targets[locale] = {"contentSha256": content_sha, "captionsSha256": captions_sha,
                           "releasePackageJsonSha256": target["releasePackageJsonSha256"], "blocks": blocks}
    er.require(targets, "Page has no published targets")
    return {"schemaVersion": "sermon-published-english-reference-v1", "pageId": page_id,
            "sourceIdentitySha256": source_sha, "sourceMediaSha256": media_sha,
            "reviewState": "human_approved", "targets": targets}


def cmd_stage_english_reference(base: Path, out: Path) -> dict:
    reference = english_reference.build_reference(base / "public", PAGE_ID, PODCAST / "layer1-srt/english-source.json")
    rel = f"english-reference/{PAGE_ID}.json"
    data = (json.dumps(reference, ensure_ascii=False, indent=2) + "\n").encode()
    stage(base, out, None, {rel: data}, replace=frozenset([rel]))
    return {"staged": str(out), "path": "/" + rel, "sha256": hashlib.sha256(data).hexdigest(),
            "blocks": {loc: len(t["blocks"]) for loc, t in reference["targets"].items()}}


def cmd_readback(stage2: Path) -> dict:
    origin = bl.hosting_target(ENVIRONMENT)["origin"]
    results = {}
    for rel in [*contract.CATALOG_FILES.values(), *(f"releases-v2/{PAGE_ID}/{loc}.json" for loc in LOCALES)]:
        status, data = reader(origin + "/" + rel)
        results[rel] = status == 200 and hashlib.sha256(data).hexdigest() == sha_file(stage2 / "public" / rel)
    extra = stage2 / "public" / "english-reference" / f"{PAGE_ID}.json"
    if extra.exists():
        status, data = reader(origin + f"/english-reference/{PAGE_ID}.json")
        results[f"english-reference/{PAGE_ID}.json"] = status == 200 and hashlib.sha256(data).hexdigest() == sha_file(extra)
    return {"pass": all(results.values()), "checks": results}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assets"); a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("baseline"); b.add_argument("--out", type=Path, required=True)
    b.add_argument("--cache-public", type=Path); b.add_argument("--cache-receipt", type=Path)
    s1 = sub.add_parser("stage1")
    s1.add_argument("--baseline", type=Path, required=True); s1.add_argument("--assets", type=Path, required=True)
    s1.add_argument("--out", type=Path, required=True)
    pb = sub.add_parser("publish"); pb.add_argument("--snapshot", type=Path, required=True)
    v = sub.add_parser("verify"); v.add_argument("--assets", type=Path, required=True); v.add_argument("--out", type=Path, required=True)
    s2 = sub.add_parser("stage2")
    s2.add_argument("--stage1", type=Path, required=True); s2.add_argument("--assets", type=Path, required=True)
    s2.add_argument("--evidence", type=Path, required=True); s2.add_argument("--out", type=Path, required=True)
    s2.add_argument("--with-english", action="store_true", help="build and stage the English reference in this same deploy (two-deploy path)")
    rb = sub.add_parser("readback"); rb.add_argument("--stage2", type=Path, required=True)
    se = sub.add_parser("stage-english-reference"); se.add_argument("--base", type=Path, required=True)
    se.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.cmd == "stage-english-reference":
        print(json.dumps(cmd_stage_english_reference(args.base, args.out), ensure_ascii=False)); return 0
    if args.cmd == "assets":
        result = cmd_assets(args.out)
    elif args.cmd == "baseline":
        result = bl.baseline(args.out, cache_public=args.cache_public, cache_receipt=args.cache_receipt,
                             environment=ENVIRONMENT, allow_default_locale_drift=True)
    elif args.cmd == "stage1":
        result = cmd_stage1(args.baseline, args.assets, args.out)
    elif args.cmd == "publish":
        result = cmd_publish(args.snapshot)
    elif args.cmd == "verify":
        result = cmd_verify(args.assets, args.out)
    elif args.cmd == "stage2":
        result = cmd_stage2(args.stage1, args.assets, args.evidence, args.out, args.with_english)
    else:
        result = cmd_readback(args.stage2)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
