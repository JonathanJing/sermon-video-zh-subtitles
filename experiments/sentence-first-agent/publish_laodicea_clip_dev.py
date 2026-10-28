#!/usr/bin/env python3
"""Re-list the 2026-09-20 Laodicea clip (Eric Geiger, 138 s, zh-Hans/ko/es) on the Dev site (experiment only).

The clip was published to Dev in September with v1 release packages, Dev-era content and bare caption
files; only the legacy v2 catalog lists it, so the current apps (catalog v3+) cannot open it. Its approved
text, captions, audio and fingerprint indexes are still live on Dev. This driver keeps the captions, audio
and fingerprints unchanged (each checked against the hash its v1 release recorded) and republishes:

  * /content/<pageId>/<locale>.json       full-video text content v2, same approved cues, rewritten in
                                          place with the official sermon title ("Jesus promises", excerpt)
  * /pages/<pageId>/<locale>/index.html   a plain page per locale
  * /media/<pageId>/<locale>.mp3          MP3 of the approved WAV (published releases play MP3 only); the
                                          WAV-bound fingerprints are left out, so no mic alignment on this page
  * /releases-v2/<pageId>/<locale>.json   v2 release packages, published_http_verified after HTTP checks
  * catalogs v5/v4/v3                     the page entry, other pages untouched
  * /english-reference/<pageId>.json      the English comparison, from the approved source package

Sequence: assets -> baseline -> stage1 -> publish -> verify -> stage2 -> publish -> readback.
2026-10-25 first attempt (stage) listed Dev candidate releases; iOS rejects candidate captions without a
natural-rate timing header, and this clip's dub is on the source clock, so the formal path is used instead.

  PYTHONPATH="packages/production/src:." .venv/bin/python experiments/sentence-first-agent/publish_laodicea_clip_dev.py assets --out ...
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from urllib.request import Request, urlopen

WT = Path(__file__).resolve().parents[2]
for entry in (str(WT), str(WT / "packages/production/src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.delivery import baseline as bl, contract, publication as pub  # noqa: E402
from tongxing_production.delivery import published_english_reference as english_reference  # noqa: E402

ENVIRONMENT = "dev"
PAGE_ID = "2026-09-20-laodicea-clip"
LOCALES = ("zh-Hans", "ko", "es")
LEGACY_CATALOG = "multilingual-v2.json"
CLIP = WT / "artifacts/multilingual-clip-20260920/20260920-blocks15-18-138s"
ENGLISH_SOURCE = CLIP / "layer1/3c1eb656c54b5f292c5493d88db54f2deab98220810a058d1ba003174f89daa1/english-source-package.json"
CATEGORY = {"schemaVersion": "sermon-page-display-category-v1",
            "labels": {"zh-Hans": "证道片段", "en": "Sermon clip", "ko": "설교 클립", "es": "Fragmento del sermón"}}
TITLE = {"zh-Hans": "耶稣的应许 · 启示录 2–3 章（片段）", "ko": "예수님의 약속 · 요한계시록 2–3장 (발췌)",
         "es": "Las promesas de Jesús · Apocalipsis 2–3 (fragmento)"}
SERIES = {"zh-Hans": "启示录：耶稣带来的安慰与盼望", "ko": "요한계시록: 예수님이 주시는 위로와 소망",
          "es": "Apocalipsis: El consuelo y la esperanza que Jesús trae"}
NOTE = {"zh-Hans": "Dev 测试页 · 2 分钟证道片段 · AI 合成配音 · 已人工审核。本项目与 Mariners Church 无隶属关系。",
        "ko": "Dev 테스트 페이지 · 2분 설교 클립 · AI 합성 음성 · 사람 검토 완료. 이 프로젝트는 Mariners Church와 관련이 없습니다.",
        "es": "Página de prueba (Dev) · fragmento de 2 minutos · voz sintetizada por IA · revisado por personas. "
              "Este proyecto no está afiliado a Mariners Church."}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    return sha_bytes(Path(path).read_bytes())


def json_sha(value) -> str:
    return sha_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def reader(url):
    with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=120) as response:
        return response.status, response.read()


def fetch(origin: str, path: str, sha256: str | None = None) -> bytes:
    status, data = reader(origin + path)
    contract.require(status == 200, f"{path}: HTTP {status}")
    contract.require(sha256 is None or sha_bytes(data) == sha256, f"{path}: live bytes differ from the recorded hash")
    return data


def cmd_assets(out: Path) -> dict:
    """Read the live legacy entry, verify every reused file, write the new page HTML and v2 releases."""
    contract.require(not out.exists(), "Use a new assets directory")
    origin = bl.hosting_target(ENVIRONMENT)["origin"]
    legacy = json.loads(fetch(origin, "/" + LEGACY_CATALOG))
    entries = [p for p in legacy["pages"] if p["id"] == PAGE_ID]
    contract.require(len(entries) == 1, "Legacy catalog entry missing")
    entry = entries[0]
    source = json.loads(ENGLISH_SOURCE.read_text(encoding="utf-8"))
    contract.require(json_sha(source) == entry["sourceIdentitySha256"], "English source package is not the published identity")
    write_json(out / "legacy-entry.json", entry)
    summary = {}
    for loc in LOCALES:
        target = entry["targets"][loc]
        v1 = json.loads(fetch(origin, target["releasePackageUrl"], target["releasePackageJsonSha256"]))
        assets = {a["role"]: a for a in v1["assets"]}
        content = json.loads(fetch(origin, assets["content"]["path"], assets["content"]["sha256"]))
        captions = json.loads(fetch(origin, assets["captions"]["path"], assets["captions"]["sha256"]))
        audio = fetch(origin, assets["audio"]["path"], assets["audio"]["sha256"])
        fp = target["audioFingerprint"]
        fetch(origin, fp["indexUrl"], fp["indexSha256"])
        contract.require(content["pageId"] == PAGE_ID and content["locale"] == loc
                         and content["englishSourcePackageJsonSha256"] == entry["sourceIdentitySha256"]
                         and content["targetLanguageCandidateJsonSha256"] == v1["targetLanguageCandidateJsonSha256"]
                         and content["targetLanguageAudioPackageJsonSha256"] == v1["targetLanguageAudioPackageJsonSha256"],
                         f"{loc}: content is not bound to its v1 release")
        v2 = {k: content[k] for k in ("pageId", "sourceLocale", "date", "durationSeconds", "englishSourcePackageJsonSha256",
                                      "targetLanguageCandidateJsonSha256", "targetLanguageAudioPackageJsonSha256",
                                      "scripture", "speaker", "summary", "outline", "cues")}
        v2.update(schemaVersion="sermon-full-video-text-content-v2", locale=loc, targetLocale=loc, status=v1["contentStatus"],
                  contentStatus=v1["contentStatus"], audioStatus=v1["audioStatus"], reviewMode="formal",
                  title=TITLE[loc], series=SERIES[loc], sourceMediaSha256=entry["sourceMediaSha256"],
                  audioDurationSeconds=round(float(content["durationSeconds"]), 3))
        content_rel = assets["content"]["path"].lstrip("/")
        write_json(out / "public" / content_rel, v2)
        body = "".join(f"<p>{html.escape(c['text'])}</p>" for c in v2["cues"])
        page = (f'<!doctype html><html lang="{loc}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(TITLE[loc])}</title>'
                '<style>body{max-width:48rem;margin:auto;padding:1.2rem;font:1.1rem/1.7 system-ui}audio{width:100%}</style></head>'
                f'<body><h1>{html.escape(TITLE[loc])}</h1><p>{v2["date"]} · {html.escape(v2["speaker"])}</p>'
                f'<audio controls preload="none" src="{assets["audio"]["path"]}"></audio>'
                f'<p>{html.escape(NOTE[loc])}</p>{body}</body></html>')
        page_rel = f"pages/{PAGE_ID}/{loc}/index.html"
        (out / "public" / page_rel).parent.mkdir(parents=True, exist_ok=True)
        (out / "public" / page_rel).write_text(page, encoding="utf-8")
        # published v2 releases play MP3 only: encode the approved, hash-verified WAV
        wav = out / "work" / f"{loc}.wav"
        wav.parent.mkdir(parents=True, exist_ok=True)
        wav.write_bytes(audio)
        mp3_rel = f"media/{PAGE_ID}/{loc}.mp3"
        (out / "public" / mp3_rel).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "192k",
                        str(out / "public" / mp3_rel)], check=True)
        release = {"schemaVersion": "sermon-target-language-release-package-v2", "packageId": f"{PAGE_ID}-{loc}-{ENVIRONMENT}-v3",
                   "pageId": PAGE_ID, "sourceLocale": "en", "targetLocale": loc, "interfaceLocale": loc,
                   "contentLocale": loc, "audioLocale": loc,
                   "targetLanguageCandidateJsonSha256": v1["targetLanguageCandidateJsonSha256"],
                   "spokenTargetLanguageCandidateJsonSha256": v1["targetLanguageCandidateJsonSha256"],
                   "targetLanguageAudioPackageJsonSha256": v1["targetLanguageAudioPackageJsonSha256"],
                   "status": "candidate", "contentStatus": v1["contentStatus"], "audioStatus": v1["audioStatus"],
                   "assets": [{"role": "page", "path": "/" + page_rel, "sha256": sha_file(out / "public" / page_rel)},
                              {"role": "content", "path": "/" + content_rel, "sha256": sha_file(out / "public" / content_rel)},
                              {"role": "audio", "path": "/" + mp3_rel, "sha256": sha_file(out / "public" / mp3_rel)},
                              {"role": "captions", "path": assets["captions"]["path"], "sha256": assets["captions"]["sha256"]}],
                   "httpVerification": {"status": "not_run", "evidenceSha256": None},
                   "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
                   "venueAcceptance": {"status": "not_run", "evidenceSha256": None}, "issues": []}
        contract.validate_release_schema(release)
        contract.validate_v2_asset_paths(release, PAGE_ID, loc)
        write_json(out / f"releases/{loc}.json", release)
        summary[loc] = {"cues": len(v2["cues"]), "captions": len(captions["cues"]), "audioBytes": len(audio), "title": TITLE[loc]}
    write_json(out / "assets-summary.json", {"pageId": PAGE_ID, "environment": ENVIRONMENT, "locales": summary})
    return summary


def build_reference(public: Path, page: dict) -> dict:
    """English comparison for the clip: approved source units, bound to each locale's release, content, captions.

    Same approval checks as published_english_reference.build_reference; the content here is the
    Dev-era schema (locale/contentStatus, no sourceMediaSha256) and the releases are Dev candidates."""
    er = english_reference
    source = er.read_json(ENGLISH_SOURCE)
    er.require(source.get("schemaVersion") == "sermon-english-source-package-v1", "Unsupported source package")
    er.require(source.get("status") == "ready_for_translation" and source.get("translationEligible") is True,
               "English source is not approved for translation")
    review = source.get("review", {})
    checks = ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries")
    er.require(review.get("humanApproval") is True and all(review.get("checks", {}).get(k) == "approved" for k in checks),
               "English source needs complete human approval")
    anchors = er.read_evidence(source["anchors"]["artifact"])
    units = anchors["sourceUnits"]
    english = {u["sourceUnitId"]: u["english"] for u in units}
    unit_ids = [u["sourceUnitId"] for u in units]
    er.require(review.get("reviewedSourceUnitIds") == unit_ids, "Source review does not cover all ordered units")
    source_sha = er.canonical_sha(source)
    er.require(page["sourceIdentitySha256"] == source_sha, "Catalog source identity mismatch")
    targets = {}
    for loc, target in page["targets"].items():
        release = er.read_json(er.public_path(public, target["releasePackageUrl"]), sha256=target["releasePackageJsonSha256"])
        er.require(release.get("pageId") == PAGE_ID and release.get("targetLocale") == loc, f"Release identity mismatch: {loc}")
        got = {}
        for role in ("content", "captions"):
            asset = [a for a in release["assets"] if a["role"] == role][0]
            got[role] = (er.read_json(er.public_path(public, asset["path"]), sha256=asset["sha256"]), asset["sha256"])
        content, content_sha = got["content"]
        captions, captions_sha = got["captions"]
        er.require(content.get("englishSourcePackageJsonSha256") == source_sha, f"Content source mismatch: {loc}")
        groups = content["cues"]
        er.require([c["textGroupId"] for c in captions["cues"]] == [g["textGroupId"] for g in groups],
                   f"Spoken captions do not match translation group order: {loc}")
        mapped = [u for g in groups for u in g["sourceUnitIds"]]
        er.require(mapped and all(u in english for u in mapped), f"Page maps an unapproved source unit: {loc}")
        targets[loc] = {"contentSha256": content_sha, "captionsSha256": captions_sha,
                        "releasePackageJsonSha256": target["releasePackageJsonSha256"],
                        "blocks": [{"textGroupId": g["textGroupId"], "sourceUnitIds": g["sourceUnitIds"],
                                    "english": " ".join(english[u] for u in g["sourceUnitIds"])} for g in groups]}
    return {"schemaVersion": "sermon-published-english-reference-v1", "pageId": PAGE_ID,
            "sourceIdentitySha256": source_sha, "sourceMediaSha256": source["source"]["media"]["sha256"],
            "reviewState": "human_approved", "targets": targets}


def snapshot_from(base: Path, out: Path) -> None:
    contract.require(not out.exists(), "Use a new snapshot directory")
    out.mkdir(parents=True)
    shutil.copytree(base / "public", out / "public")
    shutil.copyfile(base / "firebase.json", out / "firebase.json")
    shutil.copyfile(base / "baseline-receipt.json", out / "baseline-receipt.json")


def seal(base: Path, out: Path, added: list[str]) -> None:
    report = {**bl.catalog_report(out / "public"), "files": bl.files_report(out / "public")}
    bl.write(out / "seal-report.json", report)
    contract.validate_catalog_snapshot(out)
    if os.environ.get("LAODICEA_DRY_RUN") != "1":   # a dry run has no real prior deployment to chain from
        bl.write(out / "publish-config.json", bl.publication_config(base, out, environment=ENVIRONMENT))
    write_json(out / "staged-changes.json", {"pageId": PAGE_ID, "environment": ENVIRONMENT, "changedPaths": added,
                                             "base": str(base)})


def write_page(public: Path, assets: Path, releases: dict[str, dict], put) -> dict:
    """Write the releases and the page entry (official title) into catalogs v5/v4/v3; other pages unchanged."""
    legacy = json.loads((assets / "legacy-entry.json").read_text())
    targets = {}
    for loc in LOCALES:
        release = releases[loc]
        contract.validate_release_schema(release)
        data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        put(f"releases-v2/{PAGE_ID}/{loc}.json", data)
        lt = legacy["targets"][loc]
        # The legacy fingerprint indexes are bound to the WAV tracks; the MP3 release would not match them,
        # so this re-list carries no fingerprint and no alignment capability.
        targets[loc] = {"audioStatus": lt["audioStatus"], "contentStatus": lt["contentStatus"],
                        "capabilities": [c for c in lt["capabilities"] if c != "alignment"],
                        "releasePackageJsonSha256": sha_bytes(data), "releasePackageUrl": f"/releases-v2/{PAGE_ID}/{loc}.json"}
    old = {name: json.loads((public / contract.CATALOG_FILES[name]).read_text()) for name in contract.CATALOG_FILES}
    page = {"id": PAGE_ID, "date": legacy["date"], "title": TITLE["zh-Hans"], "defaultTargetLocale": "zh-Hans",
            "displayCategory": CATEGORY, "sourceLocale": "en", "sourceIdentitySha256": legacy["sourceIdentitySha256"],
            "sourceMediaSha256": legacy["sourceMediaSha256"], "sourceMode": "single_source", "targets": targets}
    v5 = copy.deepcopy(old[contract.CATALOG_V5])
    v5["pages"] = [page if p["id"] == PAGE_ID else p for p in v5["pages"]]
    if all(p["id"] != PAGE_ID for p in v5["pages"]):
        v5["pages"].append(page)
    contract.validate_catalog_schema(v5)
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    strip = lambda c: {**c, "pages": [p for p in c["pages"] if p["id"] != PAGE_ID]}
    for name, new in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        contract.require(sum(p["id"] == PAGE_ID for p in new["pages"]) == 1, name + ": page missing from projection")
        contract.require(strip(new) == strip(old[name]), name + ": projection changed other pages")
    for name, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        put(contract.CATALOG_FILES[name], (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode())
    return [p for p in v3["pages"] if p["id"] == PAGE_ID][0]


def cmd_stage1(baseline_dir: Path, assets: Path, out: Path) -> dict:
    """Content v2 and page HTML rewritten in place, with candidate releases and the catalog entry rebound to them."""
    snapshot_from(baseline_dir, out)
    added = []
    def put(rel: str, data: bytes):
        (out / "public" / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / "public" / rel).write_bytes(data)
        added.append("/" + rel)
    for src in sorted((assets / "public").rglob("*")):
        if src.is_file():
            rel = str(src.relative_to(assets / "public"))
            contract.require(rel.startswith((f"content/{PAGE_ID}/", f"pages/{PAGE_ID}/", f"media/{PAGE_ID}/")), "Unexpected asset: " + rel)
            put(rel, src.read_bytes())
    # keep the live catalog consistent: its (candidate) releases now bind the rewritten content
    write_page(out / "public", assets, {loc: json.loads((assets / f"releases/{loc}.json").read_text()) for loc in LOCALES}, put)
    seal(baseline_dir, out, added)
    return {"staged": str(out), "changed": added}


def cmd_verify(assets: Path, out: Path) -> dict:
    """Every asset each release will bind, read back from the live site by hash (audio also by Range)."""
    origin = bl.hosting_target(ENVIRONMENT)["origin"]
    checks = []
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        for asset in release["assets"]:
            status, data = reader(origin + asset["path"])
            row = {"path": asset["path"], "status": status, "sha256": sha_bytes(data),
                   "pass": status == 200 and sha_bytes(data) == asset["sha256"]}
            if asset["role"] == "audio":
                with urlopen(Request(origin + asset["path"], headers={"Range": "bytes=0-1023", "Cache-Control": "no-cache"}),
                             timeout=120) as r:
                    part = r.read()
                    row.update(rangeStatus=r.status, contentRange=r.headers.get("Content-Range"))
                row["pass"] = row["pass"] and row["rangeStatus"] == 206 and len(part) == 1024
            checks.append(row)
    evidence = {"schemaVersion": "laodicea-clip-http-verification-v1", "origin": origin, "pageId": PAGE_ID,
                "checks": checks, "status": "pass" if all(c["pass"] for c in checks) else "fail"}
    write_json(out, evidence)
    return {"status": evidence["status"], "checks": len(checks), "failed": [c["path"] for c in checks if not c["pass"]]}


def cmd_stage2(stage1: Path, assets: Path, evidence_path: Path, out: Path) -> dict:
    """Releases published_http_verified, the catalog entry with the official title, the English reference."""
    evidence = json.loads(evidence_path.read_text())
    contract.require(evidence["status"] == "pass", "HTTP verification did not pass")
    attempt = json.loads((stage1 / "deployment-attempt-v2.json").read_text())
    contract.require(attempt.get("status") == "deployed", "Stage 1 is not deployed")
    snapshot_from(stage1, out)
    public = out / "public"
    added = []
    def put(rel: str, data: bytes):
        (public / rel).parent.mkdir(parents=True, exist_ok=True)
        (public / rel).write_bytes(data)
        added.append("/" + rel)
    releases = {}
    for loc in LOCALES:
        release = json.loads((assets / f"releases/{loc}.json").read_text())
        release.update(status="published_http_verified", httpVerification={"status": "pass", "evidenceSha256": sha_file(evidence_path)})
        releases[loc] = release
    v3_page = write_page(public, assets, releases, put)
    for loc in LOCALES:
        contract.validate_v2_release_target(releases[loc], v3_page, loc)
        contract.validate_content_target(json.loads((public / f"content/{PAGE_ID}/{loc}.json").read_text()), v3_page, loc)
    reference = build_reference(public.resolve(), v3_page)
    put(f"english-reference/{PAGE_ID}.json", (json.dumps(reference, ensure_ascii=False, indent=2) + "\n").encode())
    seal(stage1, out, added)
    return {"staged": str(out), "changed": added, "englishBlocks": {k: len(v["blocks"]) for k, v in reference["targets"].items()}}


def cmd_publish(snapshot: Path) -> dict:
    config = bl.read(snapshot / "publish-config.json")
    contract.require(not (snapshot / "deployment-attempt-v2.json").exists(),
                     "This snapshot already has a deployment attempt; reconcile it, never retry")
    result = pub.publish(**config, request=pub.authenticated_transport(), reader=reader)
    return {k: result.get(k) for k in ("status", "newVersion", "baselineVersion", "catalogSha256")}


def cmd_readback(snapshot: Path) -> dict:
    origin = bl.hosting_target(ENVIRONMENT)["origin"]
    changed = json.loads((snapshot / "staged-changes.json").read_text())["changedPaths"]
    results = {}
    for rel in changed:
        status, data = reader(origin + rel)
        results[rel] = status == 200 and sha_bytes(data) == sha_file(snapshot / "public" / rel.lstrip("/"))
    return {"pass": all(results.values()), "failed": [k for k, v in results.items() if not v], "checked": len(results)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assets"); a.add_argument("--out", type=Path, required=True)
    b = sub.add_parser("baseline"); b.add_argument("--out", type=Path, required=True)
    s1 = sub.add_parser("stage1"); s1.add_argument("--baseline", type=Path, required=True)
    s1.add_argument("--assets", type=Path, required=True); s1.add_argument("--out", type=Path, required=True)
    pb = sub.add_parser("publish"); pb.add_argument("--snapshot", type=Path, required=True)
    v = sub.add_parser("verify"); v.add_argument("--assets", type=Path, required=True); v.add_argument("--out", type=Path, required=True)
    s2 = sub.add_parser("stage2"); s2.add_argument("--stage1", type=Path, required=True)
    s2.add_argument("--assets", type=Path, required=True); s2.add_argument("--evidence", type=Path, required=True)
    s2.add_argument("--out", type=Path, required=True)
    rb = sub.add_parser("readback"); rb.add_argument("--snapshot", type=Path, required=True)
    args = p.parse_args()
    if args.cmd == "assets":
        result = cmd_assets(args.out)
    elif args.cmd == "baseline":
        result = bl.baseline(args.out, environment=ENVIRONMENT, allow_default_locale_drift=True)
    elif args.cmd == "stage1":
        result = cmd_stage1(args.baseline, args.assets, args.out)
    elif args.cmd == "publish":
        result = cmd_publish(args.snapshot)
    elif args.cmd == "verify":
        result = cmd_verify(args.assets, args.out)
    elif args.cmd == "stage2":
        result = cmd_stage2(args.stage1, args.assets, args.evidence, args.out)
    else:
        result = cmd_readback(args.snapshot)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
