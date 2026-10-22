#!/usr/bin/env python3
"""Publish the sentence-first podcast dubs as one human-reviewed page on Production Hosting.

User-approved on 2026-10-22 after a full human review of the three dubs. Follows the
2026-10-07 podcast precedent (release v2, human_reviewed, captions on the dub's own
clock, no fingerprint alignment) and the repository's guarded publisher: a complete
live baseline, assets first, HTTP verification, then releases and the v5/v4/v3
catalogs in a second deploy. Each step is its own subcommand:

  assets    build page/content/captions/MP3 per locale and the local package summaries
  baseline  take a complete live Production snapshot (delivery.baseline.baseline)
  stage1    baseline + new assets, catalogs unchanged, publish config
  publish   run the guarded publisher on a staged snapshot (stage1 or stage2)
  verify    GET/SHA every new asset and Range-check each MP3 on the live site
  stage2    stage1 + releases (with the verification evidence) + appended catalogs
  readback  compare the live catalogs and releases with the stage2 snapshot

Run with the main checkout's venv and this worktree first on PYTHONPATH.
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

PAGE_ID = "if-i-had-more-time-jesus-sends-and-resurrects-his-own"
LOCALES = ("zh-Hans", "ko", "es")
RUN_DIR = {"zh-Hans": "zh", "ko": "ko", "es": "es"}
RUNS = WT / "artifacts/sentence-first-agent"
PODCAST = Path("/Users/jonathan_jing/SynologyDrive/GitHub/Active/sermon-video-zh-subtitles/artifacts/podcasts") / PAGE_ID
ORIGIN = "https://ai-for-god-sermon-audio.web.app"
SOURCE_URL = "https://www.youtube.com/watch?v=AKY0k5KiKns"
DATE = "2026-10-18"
WINDOW_START, WINDOW_END = 5.5, 2406.0
SPEAKERS = "Steve Bang Lee · John Thomas"
CATEGORY = {"schemaVersion": "sermon-page-display-category-v1",
            "labels": {"zh-Hans": "证道播客", "en": "Sermon Podcast", "ko": "설교 팟캐스트", "es": "Pódcast del sermón"}}
PAGE_TITLE = "如果我有更多时间 · 耶稣差遣并使属祂的人复活"
META = {
    "zh-Hans": {"title": PAGE_TITLE, "series": "启示录：耶稣带来的安慰与盼望", "scripture": "启示录 10–11 章",
                "badge": "证道播客 · Sermon podcast · AI 合成配音 · 已审核", "source": "英文来源 / English source",
                "note": "自然语速配音，非原视频同步；本项目与 Mariners Church 无隶属关系。"},
    "ko": {"title": "If I Had More Time · 예수님은 자기 백성을 보내시고 다시 살리십니다", "series": "요한계시록: 예수님이 주시는 위로와 소망",
           "scripture": "요한계시록 10–11장", "badge": "설교 팟캐스트 · Sermon podcast · AI 합성 음성 · 검토 완료",
           "source": "영어 원본 / English source",
           "note": "자연스러운 속도의 더빙으로, 원본 영상과 동기화되지 않습니다. 이 프로젝트는 Mariners Church와 관련이 없습니다."},
    "es": {"title": "If I Had More Time · Jesús envía y resucita a los suyos", "series": "Apocalipsis: El consuelo y la esperanza que Jesús trae",
           "scripture": "Apocalipsis 10–11", "badge": "Pódcast del sermón · Sermon podcast · Voz sintetizada por IA · Revisado",
           "source": "Fuente en inglés / English source",
           "note": "Doblaje a ritmo natural, no sincronizado con el video original. Este proyecto no está afiliado a Mariners Church."},
}


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
    value = json.loads((PODCAST / "layer2/zh-Hans/english-source.json").read_text(encoding="utf-8"))
    return value, json_sha(value)


def cmd_assets(out: Path) -> dict:
    contract.require(not out.exists(), "Use a new assets directory")
    esp, esp_sha = english_source()
    media = esp["source"]["media"]["sha256"]
    contract.require(hashlib.sha256(SOURCE_URL.encode()).hexdigest() == esp["source"]["sourceUrlHash"],
                     "Source URL differs from the source package")
    verdict = RUNS / "20261022-podcast-review-sheets/human-review-verdict.json"
    contract.require(json.loads(verdict.read_text())["verdict"] == "approved", "Human review verdict is not approved")
    summary = {}
    for loc in LOCALES:
        run = RUNS / f"20261022-podcast-sends-resurrects-{RUN_DIR[loc]}"
        sent = rows(run / "sentences.jsonl")
        tr = {r["id"]: r for r in rows(run / "translations.jsonl")}
        sp = {r["id"]: r for r in rows(run / "speech.jsonl")}
        sched = {r["id"]: r for r in json.loads((run / "schedule.json").read_text())["sentences"]}
        contract.require(len(sent) == 746 and all(sched.get(s["id"], {}).get("actualStart") is not None for s in sent),
                         f"{loc}: schedule incomplete")
        # Layer 2 identity: the approved formal candidate for zh; the reviewed sentence table for ko/es.
        if loc == "zh-Hans":
            candidate_sha = json_sha(json.loads((PODCAST / "layer2/zh-Hans/candidate-approved.json").read_text(encoding="utf-8")))
        else:
            candidate = {"schemaVersion": "sentence-first-podcast-candidate-v1", "pageId": PAGE_ID, "targetLocale": loc,
                         "englishSourcePackageJsonSha256": esp_sha,
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
        audio_package = {"schemaVersion": "sentence-first-podcast-audio-package-v1", "pageId": PAGE_ID, "targetLocale": loc,
                         "targetLanguageCandidateJsonSha256": candidate_sha, "voices": ["steve_bang_lee", "john_thomas"],
                         "track": {"wavSha256": sha_file(run / "track.wav"), "mp3Sha256": sha_file(mp3),
                                   "mp3DurationSeconds": audio_seconds},
                         "synchronization": "not on the source video clock; natural-rate dub about 25% longer than the source speech",
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
                   "durationSeconds": round(WINDOW_END - WINDOW_START, 3), "audioDurationSeconds": audio_seconds,
                   "englishSourcePackageJsonSha256": esp_sha, "sourceMediaSha256": media,
                   "targetLanguageCandidateJsonSha256": candidate_sha, "targetLanguageAudioPackageJsonSha256": audio_sha,
                   "cues": [{"start": round(WINDOW_START + s["start"], 3), "end": round(WINDOW_START + s["end"], 3),
                             "sourceUnitIds": [s["sourceUnitId"]], "text": tr[s["id"]]["target"],
                             "textGroupId": "translation-" + s["sourceUnitId"]} for s in sent]}
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
        release = {"schemaVersion": "sermon-target-language-release-package-v2", "packageId": f"{PAGE_ID}-{loc}-production-v1",
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
    write_json(out / "assets-summary.json", {"pageId": PAGE_ID, "englishSourcePackageJsonSha256": esp_sha,
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
    bl.write(out / "publish-config.json", bl.publication_config(base, out, environment="production"))
    write_json(out / "staged-changes.json", {"pageId": PAGE_ID, "changedPaths": added, "base": str(base)})


def cmd_stage1(baseline_dir: Path, assets: Path, out: Path) -> dict:
    # User-approved 2026-10-22: the live v4/v3 were written before 8b703903 and differ from the
    # v5 projection only in page default locales; stage 1 publishes the re-projected catalogs.
    public = baseline_dir / "public"
    read = lambda name: json.loads((public / contract.CATALOG_FILES[name]).read_text())
    v4, v3, changes = contract.repair_projected_defaults(read(contract.CATALOG_V5), read(contract.CATALOG_V4), read(contract.CATALOG_V3))
    files = {}
    if changes:
        for name, value in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
            files[contract.CATALOG_FILES[name]] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stage(baseline_dir, out, assets / "public", files)
    write_json(out / "catalog-default-locale-repair.json", {"reason": "pre-8b703903 v4/v3 default locales re-projected from live v5",
                                                            "approvedBy": "user (chat, 2026-10-22)", "changes": changes})
    return {"staged": str(out), "files": len(json.loads((out / "staged-changes.json").read_text())["changedPaths"]),
            "defaultLocaleChanges": len(changes)}


def cmd_publish(snapshot: Path) -> dict:
    config = bl.read(snapshot / "publish-config.json")
    contract.require(not (snapshot / "deployment-attempt-v2.json").exists(),
                     "This snapshot already has a deployment attempt; reconcile it, never retry")
    result = pub.publish(**config, request=pub.authenticated_transport(), reader=reader)
    return {k: result.get(k) for k in ("status", "newVersion", "baselineVersion", "catalogSha256")}


def cmd_verify(assets: Path, out: Path) -> dict:
    checks = []
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        for asset in release["assets"]:
            status, data = reader(ORIGIN + asset["path"])
            digest = hashlib.sha256(data).hexdigest()
            row = {"path": asset["path"], "status": status, "sha256": digest, "pass": status == 200 and digest == asset["sha256"]}
            if asset["role"] == "audio":
                with urlopen(Request(ORIGIN + asset["path"], headers={"Range": "bytes=0-1023", "Cache-Control": "no-cache"}),
                             timeout=120) as r:
                    part = r.read()
                    row.update(rangeStatus=r.status, contentRange=r.headers.get("Content-Range"),
                               contentType=r.headers.get("Content-Type"))
                row["pass"] = (row["pass"] and row["rangeStatus"] == 206 and len(part) == 1024
                               and row["contentRange"] == f"bytes 0-1023/{len(data)}")
            checks.append(row)
    evidence = {"schemaVersion": "sentence-first-podcast-http-verification-v1", "origin": ORIGIN, "pageId": PAGE_ID,
                "checks": checks, "status": "pass" if all(c["pass"] for c in checks) else "fail"}
    write_json(out, evidence)
    return {"status": evidence["status"], "checks": len(checks), "failed": [c["path"] for c in checks if not c["pass"]]}


def cmd_stage2(stage1: Path, assets: Path, evidence_path: Path, out: Path) -> dict:
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
    # The new catalogs must be today's live catalogs plus exactly this page.
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
    return {"staged": str(out), "changed": sorted(files), "defaultPageId": v3["defaultPageId"]}


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


def cmd_fix_content(assets: Path, out: Path) -> dict:
    """2026-10-22 fix: content durationSeconds was the window length (2400.5) while its cues run on media
    time up to the window end (2406.0); iOS rejects cues past durationSeconds. New content files at new
    paths, so the published bytes are never overwritten; the releases are re-bound to them."""
    contract.require(not out.exists(), "Use a new fix directory")
    result = {}
    for loc in LOCALES:
        content = json.loads((assets / f"public/content/{PAGE_ID}/{loc}.json").read_text())
        captions = json.loads((assets / f"public/captions/{PAGE_ID}/{loc}.json").read_text())
        content["durationSeconds"] = WINDOW_END
        ios_cue_check(content["cues"], content["durationSeconds"], True)
        ios_cue_check(captions["cues"], content["audioDurationSeconds"], False)
        contract.require(len(content["cues"]) == len(captions["cues"])
                         and {c["textGroupId"] for c in content["cues"]} == {c["textGroupId"] for c in captions["cues"]},
                         "content and captions groups differ")
        rel = f"content/{PAGE_ID}/{loc}-r2.json"
        write_json(out / "public" / rel, content)
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        for asset in release["assets"]:
            if asset["role"] == "content":
                asset.update(path="/" + rel, sha256=sha_file(out / "public" / rel))
        release["packageId"] = f"{PAGE_ID}-{loc}-production-v2"
        contract.validate_release_schema(release)
        write_json(out / f"releases/{loc}.json", release)
        result[loc] = {"durationSeconds": content["durationSeconds"], "lastCueEnd": content["cues"][-1]["end"], "path": "/" + rel}
    return result


def cmd_stage_fix_release(base: Path, fix: Path, evidence_path: Path, out: Path) -> dict:
    """Replace the three releases (re-bound to the fixed content) and update only their hashes in the catalogs."""
    evidence = json.loads(evidence_path.read_text())
    contract.require(evidence["status"] == "pass", "HTTP verification did not pass")
    contract.require(json.loads((base / "deployment-attempt-v2.json").read_text()).get("status") == "deployed", "Base is not deployed")
    evidence_sha = sha_file(evidence_path)
    public = base / "public"
    files, hashes = {}, {}
    for loc in LOCALES:
        release = json.loads((fix / f"releases/{loc}.json").read_text())
        release.update(status="published_http_verified", httpVerification={"status": "pass", "evidenceSha256": evidence_sha})
        contract.validate_release_schema(release)
        data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        files[f"releases-v2/{PAGE_ID}/{loc}.json"] = data
        hashes[loc] = hashlib.sha256(data).hexdigest()
    old = {name: json.loads((public / contract.CATALOG_FILES[name]).read_text()) for name in contract.CATALOG_FILES}
    v5 = copy.deepcopy(old[contract.CATALOG_V5])
    page = next(p for p in v5["pages"] if p["id"] == PAGE_ID)
    for loc in LOCALES:
        page["targets"][loc]["releasePackageJsonSha256"] = hashes[loc]
    v4 = contract.project_legacy_catalog_v4(contract.validate_catalog_schema(v5))
    v3 = contract.project_human_catalog(v4)
    for name, new in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        strip = lambda c: {**c, "pages": [p for p in c["pages"] if p["id"] != PAGE_ID]}
        contract.require(strip(new) == strip(old[name]), name + ": other pages changed")
    for loc in LOCALES:
        release = json.loads(files[f"releases-v2/{PAGE_ID}/{loc}.json"])
        contract.validate_v2_release_target(release, page, loc)
        content_path = next(a["path"] for a in release["assets"] if a["role"] == "content").lstrip("/")
        contract.validate_content_target(json.loads((public / content_path).read_text()), page, loc)
    for name, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        files[contract.CATALOG_FILES[name]] = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stage(base, out, None, files, replace=frozenset(f"releases-v2/{PAGE_ID}/{loc}.json" for loc in LOCALES))
    return {"staged": str(out), "changed": sorted(files)}


def cmd_readback(stage2: Path) -> dict:
    results = {}
    for rel in [*contract.CATALOG_FILES.values(), *(f"releases-v2/{PAGE_ID}/{loc}.json" for loc in LOCALES)]:
        status, data = reader(ORIGIN + "/" + rel)
        results[rel] = status == 200 and hashlib.sha256(data).hexdigest() == sha_file(stage2 / "public" / rel)
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
    rb = sub.add_parser("readback"); rb.add_argument("--stage2", type=Path, required=True)
    fc = sub.add_parser("fix-content"); fc.add_argument("--assets", type=Path, required=True); fc.add_argument("--out", type=Path, required=True)
    fa = sub.add_parser("stage-fix-assets"); fa.add_argument("--base", type=Path, required=True)
    fa.add_argument("--fix", type=Path, required=True); fa.add_argument("--out", type=Path, required=True)
    fr = sub.add_parser("stage-fix-release"); fr.add_argument("--base", type=Path, required=True); fr.add_argument("--fix", type=Path, required=True)
    fr.add_argument("--evidence", type=Path, required=True); fr.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    if args.cmd == "fix-content":
        print(json.dumps(cmd_fix_content(args.assets, args.out), ensure_ascii=False)); return 0
    if args.cmd == "stage-fix-assets":
        stage(args.base, args.out, args.fix / "public")
        print(json.dumps({"staged": str(args.out)})); return 0
    if args.cmd == "stage-fix-release":
        print(json.dumps(cmd_stage_fix_release(args.base, args.fix, args.evidence, args.out), ensure_ascii=False)); return 0
    if args.cmd == "assets":
        result = cmd_assets(args.out)
    elif args.cmd == "baseline":
        result = bl.baseline(args.out, cache_public=args.cache_public, cache_receipt=args.cache_receipt, environment="production",
                             allow_default_locale_drift=True)
    elif args.cmd == "stage1":
        result = cmd_stage1(args.baseline, args.assets, args.out)
    elif args.cmd == "publish":
        result = cmd_publish(args.snapshot)
    elif args.cmd == "verify":
        result = cmd_verify(args.assets, args.out)
    elif args.cmd == "stage2":
        result = cmd_stage2(args.stage1, args.assets, args.evidence, args.out)
    else:
        result = cmd_readback(args.stage2)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
