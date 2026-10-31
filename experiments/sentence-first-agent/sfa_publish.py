#!/usr/bin/env python3
"""Publish one sentence-first page from a page config (one driver for the page family).

The page identity, its runs, English source, verdict and output schema names live in
``pages/<pageId>.json`` (validated against ``pages/page-config.schema.json``). This file
holds the machinery that used to be copied per page; a new page is a new config, not a
new 500-line driver (runbook §10, DEV-SF-004).

Steps keep the historical subcommand order:

  validate  print the resolved identity and check the inputs exist
  assets    build page/content/captions/MP3, packages and releases per locale
  baseline  take a complete live Hosting snapshot
  stage1    baseline + new assets, catalogs unchanged, publish config
  publish   run the guarded publisher on a staged snapshot
  verify    GET/SHA every new asset and Range-check each MP3 on the live site
  stage2    stage1 + releases + appended catalogs (optionally the English reference)
  readback  compare the live catalogs/releases (and the English reference when staged)

Config paths are repository-relative unless absolute. The driver never writes
translations/review/speech or the single-writer files; it reads them. Special repair
paths (retract, alignment sidecar, fix-content, archived editions) stay in the legacy
per-page drivers.

  python3 $EXP/sfa_publish.py --config $EXP/pages/<pageId>.json validate
  python3 $EXP/sfa_publish.py --config $EXP/pages/<pageId>.json assets --out <dir>
  ... baseline / stage1 / publish / verify / stage2 / readback / stage-english-reference
"""
from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
WT = HERE.parents[1]
for entry in (str(WT), str(WT / "packages/production/src")):
    if entry not in sys.path:
        sys.path.insert(0, entry)
from scripts import tongxing_host  # noqa: E402,F401  binds the production package ports
from tongxing_production.delivery import baseline as bl, contract, publication as pub  # noqa: E402
from tongxing_production.delivery import published_english_reference as english_reference  # noqa: E402

CONFIG_SCHEMA = HERE / "pages" / "page-config.schema.json"


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def json_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def reader(url):
    with urlopen(Request(url, headers={"Cache-Control": "no-cache"}), timeout=120) as response:
        return response.status, response.read()


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


# --- page config ---------------------------------------------------------------

@dataclass(frozen=True)
class PageConfig:
    path: Path
    root: Path
    page_id: str
    environment: str
    locales: tuple[str, ...]
    default_target_locale: str
    runs_root: Path
    runs: dict[str, Path]
    source_url: str
    date: str
    window_start: float
    window_end: float
    english_source_path: Path
    approved_candidates: dict[str, Path]
    sentences: int
    speakers: str
    category: dict
    title: str
    meta: dict[str, dict]
    verdict_path: Path
    candidate_schema: str
    translation_basis: dict[str, str]
    audio_schema: str
    voices: str | tuple[str, ...]
    synchronization: str
    release_package_id: str
    verify_schema: str
    english_reference_mode: str
    include_environment_in_summary: bool
    allow_default_locale_drift: bool
    media_type: str
    source_mode: str

    def origin(self) -> str:
        return bl.hosting_target(self.environment)["origin"]

    def run_dir(self, locale: str) -> Path:
        return self.runs_root / self.runs[locale]

    def translation_basis_for(self, locale: str) -> str:
        template = self.translation_basis.get(locale) or self.translation_basis.get("default")
        contract.require(bool(template), f"candidate.translationBasis needs {locale} or default")
        return template.format(locale=locale)

    def voices_for(self, sentences: list[dict]) -> list[str]:
        if self.voices == "from-speakers":
            return sorted({sentence["speakerId"] for sentence in sentences})
        return list(self.voices)

    def release_id(self, locale: str) -> str:
        return self.release_package_id.format(pageId=self.page_id, locale=locale, environment=self.environment)

    def english_source(self) -> tuple[dict, str]:
        value = json.loads(self.english_source_path.read_text(encoding="utf-8"))
        return value, json_sha(value)

    def require_inputs(self) -> None:
        contract.require(self.english_source_path.is_file(), f"English source package missing: {self.english_source_path}")
        contract.require(self.verdict_path.is_file(), f"Human review verdict missing: {self.verdict_path}")
        for locale in self.locales:
            run = self.run_dir(locale)
            for name in ("sentences.jsonl", "translations.jsonl", "speech.jsonl", "schedule.json", "track.wav"):
                contract.require((run / name).is_file(), f"{locale}: run file missing: {run / name}")
        for locale, path in self.approved_candidates.items():
            contract.require(path.is_file(), f"{locale}: approved candidate missing: {path}")

    def identity(self) -> dict:
        return {"pageId": self.page_id, "environment": self.environment, "origin": self.origin(),
                "locales": list(self.locales), "defaultTargetLocale": self.default_target_locale,
                "runs": {locale: str(self.run_dir(locale)) for locale in self.locales},
                "englishSource": str(self.english_source_path), "verdict": str(self.verdict_path),
                "candidateApproved": {locale: str(path) for locale, path in self.approved_candidates.items()},
                "englishReference": self.english_reference_mode, "sentences": self.sentences}


def _resolve(value: str, root: Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (root / path)


def _schema_errors(data) -> list[str]:
    from jsonschema import Draft202012Validator
    schema = json.loads(CONFIG_SCHEMA.read_text(encoding="utf-8"))
    errors = []
    for error in sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path)):
        where = "/".join(str(part) for part in error.path) or "(root)"
        errors.append(f"{where}: {error.message}")
    return errors


def load_config(path: Path | str, root: Path = WT) -> PageConfig:
    path = _resolve(str(path), root)
    contract.require(path.is_file(), f"page config not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = _schema_errors(data)
    contract.require(not errors, "page config invalid: " + " | ".join(errors))

    locales = tuple(data["locales"])
    runs = {locale: data["runs"][locale] for locale in locales}
    config = PageConfig(
        path=path, root=root,
        page_id=data["pageId"], environment=data["environment"],
        locales=locales, default_target_locale=data["defaultTargetLocale"],
        runs_root=_resolve(data["runsRoot"], root), runs=runs,
        source_url=data["source"]["url"], date=data["source"]["date"],
        window_start=float(data["source"]["window"]["start"]), window_end=float(data["source"]["window"]["end"]),
        english_source_path=_resolve(data["source"]["englishSource"], root),
        approved_candidates={locale: _resolve(value, root)
                             for locale, value in data["candidate"].get("approved", {}).items()},
        sentences=int(data["sentences"]), speakers=data["speakers"],
        category=data["category"], title=data["title"], meta=data["meta"],
        verdict_path=_resolve(data["verdict"], root),
        candidate_schema=data["candidate"]["schemaVersion"],
        translation_basis=data["candidate"]["translationBasis"],
        audio_schema=data["audioPackage"]["schemaVersion"],
        voices=data["audioPackage"]["voices"],
        synchronization=data["audioPackage"]["synchronization"],
        release_package_id=data["releasePackageId"],
        verify_schema=data["verify"]["schemaVersion"],
        english_reference_mode=data["englishReference"]["mode"],
        include_environment_in_summary=bool(data.get("summary", {}).get("includeEnvironment", True)),
        allow_default_locale_drift=bool(data.get("baseline", {}).get("allowDefaultLocaleDrift", True)),
        media_type=data.get("mediaType", "podcast"),
        source_mode=data.get("sourceMode", "single_source"),
    )
    _check_consistency(config)
    return config


def _check_consistency(cfg: PageConfig) -> None:
    contract.require(set(cfg.runs) == set(cfg.locales), "runs must cover exactly the locales")
    contract.require(cfg.default_target_locale in cfg.locales, "defaultTargetLocale must be one of locales")
    contract.require(set(cfg.meta) == set(cfg.locales), "meta must cover exactly the locales")
    for locale in cfg.locales:
        contract.require(locale in cfg.translation_basis or "default" in cfg.translation_basis,
                         f"candidate.translationBasis needs {locale} or default")
    for locale in cfg.approved_candidates:
        contract.require(locale in cfg.locales, f"candidate.approved locale {locale} is not in locales")
    contract.require(cfg.window_start < cfg.window_end, "source.window.start must be < end")
    for locale in cfg.locales:
        release_id = cfg.release_id(locale)
        contract.require(cfg.page_id in release_id and locale in release_id,
                         f"releasePackageId does not include pageId/locale ({locale})")
        contract.require(cfg.environment in release_id, f"releasePackageId does not include the environment ({locale})")
        contract.require(cfg.origin().startswith("https://"), f"unknown Hosting origin for {cfg.environment}")


# --- assets --------------------------------------------------------------------

def cmd_validate(cfg: PageConfig) -> dict:
    cfg.require_inputs()
    english, _ = cfg.english_source()
    digest = hashlib.sha256(cfg.source_url.encode()).hexdigest()
    contract.require(digest == english["source"]["sourceUrlHash"],
                     "source.url differs from the English package's sourceUrlHash")
    return {"ok": True, **cfg.identity(), "sourceUrlHash": digest,
            "sourceMediaSha256": english["source"]["media"]["sha256"]}


def cmd_assets(cfg: PageConfig, out: Path) -> dict:
    contract.require(not out.exists(), "Use a new assets directory")
    cfg.require_inputs()
    esp, esp_sha = cfg.english_source()
    media = esp["source"]["media"]["sha256"]
    contract.require(hashlib.sha256(cfg.source_url.encode()).hexdigest() == esp["source"]["sourceUrlHash"],
                     "Source URL differs from the source package")
    verdict = cfg.verdict_path
    contract.require(json.loads(verdict.read_text(encoding="utf-8"))["verdict"] == "approved",
                     "Human review verdict is not approved")
    summary = {}
    for locale in cfg.locales:
        run = cfg.run_dir(locale)
        sent = rows(run / "sentences.jsonl")
        tr = {row["id"]: row for row in rows(run / "translations.jsonl")}
        sp = {row["id"]: row for row in rows(run / "speech.jsonl")}
        sched = {row["id"]: row for row in json.loads((run / "schedule.json").read_text())["sentences"]}
        contract.require(len(sent) == cfg.sentences
                         and all(sched.get(s["id"], {}).get("actualStart") is not None for s in sent),
                         f"{locale}: sentence table or schedule incomplete")
        approved = cfg.approved_candidates.get(locale)
        if approved:
            candidate_sha = json_sha(json.loads(approved.read_text(encoding="utf-8")))
        else:
            candidate = {"schemaVersion": cfg.candidate_schema, "pageId": cfg.page_id, "targetLocale": locale,
                         "englishSourcePackageJsonSha256": esp_sha,
                         "translationBasis": cfg.translation_basis_for(locale),
                         "humanReview": {"verdictSha256": sha_file(verdict), "status": "approved"},
                         "groups": [{"id": s["id"], "sourceUnitId": s["sourceUnitId"], "speakerId": s["speakerId"],
                                     "english": s["english"], "targetText": tr[s["id"]]["target"],
                                     "spokenText": sp[s["id"]]["spokenText"]} for s in sent]}
            write_json(out / f"packages/{locale}-candidate.json", candidate)
            candidate_sha = json_sha(candidate)
        mp3 = out / f"public/media/{cfg.page_id}/{locale}.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(run / "track.wav"),
                        "-c:a", "libmp3lame", "-b:a", "192k", str(mp3)], check=True)
        audio_seconds = round(float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(mp3)],
            capture_output=True, text=True, check=True).stdout.strip()), 3)
        audio_package = {"schemaVersion": cfg.audio_schema, "pageId": cfg.page_id, "targetLocale": locale,
                         "targetLanguageCandidateJsonSha256": candidate_sha,
                         "voices": cfg.voices_for(sent),
                         "track": {"wavSha256": sha_file(run / "track.wav"), "mp3Sha256": sha_file(mp3),
                                   "mp3DurationSeconds": audio_seconds},
                         "synchronization": cfg.synchronization,
                         "humanReview": {"verdictSha256": sha_file(verdict), "status": "approved"},
                         "units": [{"id": s["id"], "sourceUnitId": s["sourceUnitId"], "speakerId": s["speakerId"],
                                    "wavSha256": sha_file(run / f"tts/{s['id']}.wav"),
                                    "plannedStart": sched[s["id"]]["actualStart"],
                                    "seconds": sched[s["id"]]["dubSeconds"]} for s in sent]}
        write_json(out / f"packages/{locale}-audio-package.json", audio_package)
        audio_sha = json_sha(audio_package)
        captions = {"schemaVersion": "sermon-target-language-captions-v1", "pageId": cfg.page_id, "locale": locale,
                    "audioPackageJsonSha256": audio_sha,
                    "timingBasis": "concatenated target audio; natural unit durations; no source-video synchronization",
                    "cues": [{"start": round(sched[s["id"]]["actualStart"], 3),
                              "end": round(sched[s["id"]]["actualStart"] + sched[s["id"]]["dubSeconds"], 3),
                              "sourceUnitIds": [s["sourceUnitId"]], "text": tr[s["id"]]["target"],
                              "textGroupId": "translation-" + s["sourceUnitId"]} for s in sent]}
        write_json(out / f"public/captions/{cfg.page_id}/{locale}.json", captions)
        meta = cfg.meta[locale]
        content = {"schemaVersion": "sermon-full-video-text-content-v2", "pageId": cfg.page_id, "locale": locale,
                   "targetLocale": locale, "sourceLocale": "en", "status": "human_reviewed",
                   "contentStatus": "human_reviewed", "audioStatus": "human_reviewed", "reviewMode": "formal",
                   "date": cfg.date, "title": meta["title"], "series": meta["series"], "scripture": meta["scripture"],
                   "speaker": cfg.speakers, "durationSeconds": cfg.window_end, "audioDurationSeconds": audio_seconds,
                   "englishSourcePackageJsonSha256": esp_sha, "sourceMediaSha256": media,
                   "targetLanguageCandidateJsonSha256": candidate_sha,
                   "targetLanguageAudioPackageJsonSha256": audio_sha,
                   "cues": [{"start": round(cfg.window_start + s["start"], 3),
                             "end": round(cfg.window_start + s["end"], 3),
                             "sourceUnitIds": [s["sourceUnitId"]], "text": tr[s["id"]]["target"],
                             "textGroupId": "translation-" + s["sourceUnitId"]} for s in sent]}
        ios_cue_check(content["cues"], content["durationSeconds"], True)
        ios_cue_check(captions["cues"], audio_seconds, False)
        write_json(out / f"public/content/{cfg.page_id}/{locale}.json", content)
        body = "".join(f"<p>{html.escape(tr[s['id']]['target'])}</p>" for s in sent)
        page = (f'<!doctype html><html lang="{locale}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(meta["title"])}</title>'
                '<style>body{max-width:48rem;margin:auto;padding:1.2rem;font:1.1rem/1.7 system-ui}audio{width:100%}</style></head>'
                f'<body><h1>{html.escape(meta["title"])}</h1><p>{cfg.date} · {html.escape(cfg.speakers)}</p>'
                f'<p>{html.escape(meta["badge"])}</p>'
                f'<audio controls preload="none" src="/media/{cfg.page_id}/{locale}.mp3"></audio>'
                f'<p><a href="{cfg.source_url}">{html.escape(meta["source"])}</a></p>'
                f'<p>{html.escape(meta["note"])}</p>{body}</body></html>')
        page_path = out / f"public/pages/{cfg.page_id}/{locale}/index.html"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(page, encoding="utf-8")
        release = {"schemaVersion": "sermon-target-language-release-package-v2", "packageId": cfg.release_id(locale),
                   "pageId": cfg.page_id, "sourceLocale": "en", "targetLocale": locale, "interfaceLocale": locale,
                   "contentLocale": locale, "audioLocale": locale,
                   "targetLanguageCandidateJsonSha256": candidate_sha,
                   "spokenTargetLanguageCandidateJsonSha256": candidate_sha,
                   "targetLanguageAudioPackageJsonSha256": audio_sha, "status": "candidate",
                   "contentStatus": "human_reviewed", "audioStatus": "human_reviewed",
                   "assets": [{"role": role, "path": path, "sha256": sha_file(out / "public" / path.lstrip("/"))}
                              for role, path in (("page", f"/pages/{cfg.page_id}/{locale}/index.html"),
                                                 ("content", f"/content/{cfg.page_id}/{locale}.json"),
                                                 ("audio", f"/media/{cfg.page_id}/{locale}.mp3"),
                                                 ("captions", f"/captions/{cfg.page_id}/{locale}.json"))],
                   "httpVerification": {"status": "not_run", "evidenceSha256": None},
                   "deviceAcceptance": {"status": "not_run", "evidenceSha256": None},
                   "venueAcceptance": {"status": "not_run", "evidenceSha256": None}, "issues": []}
        contract.validate_release_schema(release)
        write_json(out / f"releases/{locale}.json", release)
        summary[locale] = {"cues": len(sent), "audioSeconds": audio_seconds, "mp3Bytes": mp3.stat().st_size}
    assets_summary = {"pageId": cfg.page_id, "englishSourcePackageJsonSha256": esp_sha,
                      "sourceMediaSha256": media, "locales": summary}
    if cfg.include_environment_in_summary:
        assets_summary["environment"] = cfg.environment
    write_json(out / "assets-summary.json", assets_summary)
    return summary


# --- staging and deployment ----------------------------------------------------

def stage(cfg: PageConfig, base: Path, out: Path, add_public: Path | None,
          files: dict[str, bytes] | None = None, replace: frozenset[str] = frozenset()) -> None:
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
    bl.write(out / "publish-config.json", bl.publication_config(base, out, environment=cfg.environment))
    write_json(out / "staged-changes.json", {"pageId": cfg.page_id, "environment": cfg.environment,
                                            "changedPaths": added, "base": str(base)})


def cmd_stage1(cfg: PageConfig, baseline_dir: Path, assets: Path, out: Path) -> dict:
    public = baseline_dir / "public"
    read = lambda name: json.loads((public / contract.CATALOG_FILES[name]).read_text())
    v4, v3, changes = contract.repair_projected_defaults(read(contract.CATALOG_V5), read(contract.CATALOG_V4),
                                                         read(contract.CATALOG_V3))
    files = {}
    if changes:
        for name, value in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
            files[contract.CATALOG_FILES[name]] = (
                json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stage(cfg, baseline_dir, out, assets / "public", files)
    write_json(out / "catalog-default-locale-repair.json",
               {"reason": "live v4/v3 default locales re-projected from live v5", "changes": changes})
    return {"staged": str(out),
            "files": len(json.loads((out / "staged-changes.json").read_text())["changedPaths"]),
            "defaultLocaleChanges": len(changes)}


def cmd_publish(snapshot: Path) -> dict:
    config = bl.read(snapshot / "publish-config.json")
    contract.require(not (snapshot / "deployment-attempt-v2.json").exists(),
                     "This snapshot already has a deployment attempt; reconcile it, never retry")
    result = pub.publish(**config, request=pub.authenticated_transport(), reader=reader)
    return {key: result.get(key) for key in ("status", "newVersion", "baselineVersion", "catalogSha256")}


def cmd_verify(cfg: PageConfig, assets: Path, out: Path) -> dict:
    origin = cfg.origin()
    checks = []
    for locale in cfg.locales:
        release = json.loads((assets / f"releases/{locale}.json").read_text())
        for asset in release["assets"]:
            status, data = reader(origin + asset["path"])
            digest = hashlib.sha256(data).hexdigest()
            row = {"path": asset["path"], "status": status, "sha256": digest,
                   "pass": status == 200 and digest == asset["sha256"]}
            if asset["role"] == "audio":
                with urlopen(Request(origin + asset["path"],
                                     headers={"Range": "bytes=0-1023", "Cache-Control": "no-cache"}),
                             timeout=120) as response:
                    part = response.read()
                    row.update(rangeStatus=response.status, contentRange=response.headers.get("Content-Range"),
                               contentType=response.headers.get("Content-Type"))
                row["pass"] = (row["pass"] and row["rangeStatus"] == 206 and len(part) == 1024
                               and row["contentRange"] == f"bytes 0-1023/{len(data)}")
            checks.append(row)
    evidence = {"schemaVersion": cfg.verify_schema, "origin": origin, "pageId": cfg.page_id,
                "checks": checks, "status": "pass" if all(check["pass"] for check in checks) else "fail"}
    write_json(out, evidence)
    return {"status": evidence["status"], "checks": len(checks),
            "failed": [check["path"] for check in checks if not check["pass"]]}


def _page_entry(cfg: PageConfig, esp: dict, esp_sha: str, targets: dict) -> dict:
    return {"id": cfg.page_id, "date": cfg.date, "title": cfg.title,
            "defaultTargetLocale": cfg.default_target_locale, "displayCategory": cfg.category,
            "mediaType": cfg.media_type, "sourceLocale": "en", "sourceIdentitySha256": esp_sha,
            "sourceMediaSha256": esp["source"]["media"]["sha256"], "sourceMode": cfg.source_mode,
            "sourceUrl": cfg.source_url, "targets": targets}


def build_reference(cfg: PageConfig, public: Path) -> dict:
    if cfg.english_reference_mode == "clip":
        return _build_clip_reference(cfg, public)
    return english_reference.build_reference(public, cfg.page_id, cfg.english_source_path)


def cmd_stage2(cfg: PageConfig, stage1: Path, assets: Path, evidence_path: Path, out: Path,
               with_english: bool = False) -> dict:
    evidence = json.loads(evidence_path.read_text())
    contract.require(evidence["status"] == "pass", "HTTP verification did not pass")
    attempt = json.loads((stage1 / "deployment-attempt-v2.json").read_text())
    contract.require(attempt.get("status") == "deployed", "Stage 1 is not deployed")
    evidence_sha = sha_file(evidence_path)
    esp, esp_sha = cfg.english_source()
    files, targets = {}, {}
    for locale in cfg.locales:
        release = json.loads((assets / f"releases/{locale}.json").read_text())
        release.update(status="published_http_verified",
                       httpVerification={"status": "pass", "evidenceSha256": evidence_sha})
        contract.validate_release_schema(release)
        data = (json.dumps(release, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode()
        files[f"releases-v2/{cfg.page_id}/{locale}.json"] = data
        targets[locale] = {"audioStatus": "human_reviewed", "capabilities": ["text", "captions", "audio"],
                           "contentStatus": "human_reviewed",
                           "releasePackageJsonSha256": hashlib.sha256(data).hexdigest(),
                           "releasePackageUrl": f"/releases-v2/{cfg.page_id}/{locale}.json"}
    public = stage1 / "public"
    old = {name: json.loads((public / contract.CATALOG_FILES[name]).read_text()) for name in contract.CATALOG_FILES}
    contract.require(all(page["id"] != cfg.page_id for value in old.values() for page in value["pages"]),
                     "Page already in a live catalog")
    page = _page_entry(cfg, esp, esp_sha, targets)
    v5 = copy.deepcopy(old[contract.CATALOG_V5])
    v5["pages"].append(page)
    contract.validate_catalog_schema(v5)
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    for name, new in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        contract.require(sum(entry["id"] == cfg.page_id for entry in new["pages"]) == 1,
                         name + ": page missing from projection")
        contract.require({**new, "pages": [entry for entry in new["pages"] if entry["id"] != cfg.page_id]} == old[name],
                         name + ": projection changed other pages")
    for locale in cfg.locales:
        release = json.loads(files[f"releases-v2/{cfg.page_id}/{locale}.json"])
        contract.validate_v2_release_target(release, page, locale)
        contract.validate_content_target(
            json.loads((public / f"content/{cfg.page_id}/{locale}.json").read_text()), page, locale)
    for name, value in ((contract.CATALOG_V5, v5), (contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        files[contract.CATALOG_FILES[name]] = (
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    stage(cfg, stage1, out, None, files)
    result = {"staged": str(out), "changed": sorted(files), "defaultPageId": v3["defaultPageId"]}
    if with_english:
        reference = build_reference(cfg, out / "public")
        rel = f"english-reference/{cfg.page_id}.json"
        target = out / "public" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((json.dumps(reference, ensure_ascii=False, indent=2) + "\n").encode())
        result["englishReference"] = {"path": "/" + rel, "sha256": sha_file(target),
                                      "blocks": {locale: len(value["blocks"])
                                                 for locale, value in reference["targets"].items()}}
    return result


def cmd_stage_english_reference(cfg: PageConfig, base: Path, out: Path) -> dict:
    reference = build_reference(cfg, base / "public")
    rel = f"english-reference/{cfg.page_id}.json"
    data = (json.dumps(reference, ensure_ascii=False, indent=2) + "\n").encode()
    stage(cfg, base, out, None, {rel: data}, replace=frozenset([rel]))
    return {"staged": str(out), "path": "/" + rel, "sha256": hashlib.sha256(data).hexdigest(),
            "blocks": {locale: len(value["blocks"]) for locale, value in reference["targets"].items()}}


def cmd_readback(cfg: PageConfig, stage2: Path) -> dict:
    origin = cfg.origin()
    results = {}
    for rel in [*contract.CATALOG_FILES.values(),
                *(f"releases-v2/{cfg.page_id}/{locale}.json" for locale in cfg.locales)]:
        status, data = reader(origin + "/" + rel)
        results[rel] = status == 200 and hashlib.sha256(data).hexdigest() == sha_file(stage2 / "public" / rel)
    extra = stage2 / "public" / "english-reference" / f"{cfg.page_id}.json"
    if extra.exists():
        status, data = reader(origin + f"/english-reference/{cfg.page_id}.json")
        results[f"english-reference/{cfg.page_id}.json"] = (
            status == 200 and hashlib.sha256(data).hexdigest() == sha_file(extra))
    return {"pass": all(results.values()), "checks": results}


def _build_clip_reference(cfg: PageConfig, public: Path) -> dict:
    """English comparison for a clip page: a contiguous ordered subset of the approved units."""
    er = english_reference
    source = er.read_json(cfg.english_source_path)
    er.require(source.get("schemaVersion") == "sermon-english-source-package-v1", "Unsupported source package")
    er.require(source.get("status") == "ready_for_translation" and source.get("translationEligible") is True,
               "English source is not approved for translation")
    review = source.get("review", {})
    er.require(review.get("humanApproval") is True, "English source needs human approval")
    checks = ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries")
    er.require(all(review.get("checks", {}).get(key) == "approved" for key in checks), "Incomplete source approval")
    window = source["source"]["approvedWindow"]
    er.require(window.get("humanApproval") is True and window.get("status") == "approved", "Unapproved source window")
    er.read_evidence(window["evidence"])
    er.read_evidence(source["transcript"]["artifact"])
    anchors = er.read_evidence(source["anchors"]["artifact"])
    receipt = er.read_evidence(review["evidence"])
    er.require(receipt.get("humanApproval") is True
               and all(receipt.get("checks", {}).get(key) == "approved" for key in checks),
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
    pages = [page for page in catalog["pages"] if page["id"] == cfg.page_id]
    er.require(len(pages) == 1, "Page must occur exactly once in catalog")
    page = pages[0]
    er.require(page["sourceIdentitySha256"] == source_sha, "Catalog source identity mismatch")
    targets = {}
    for locale, target in page["targets"].items():
        release = er.read_json(er.public_path(public, target["releasePackageUrl"]),
                               sha256=target["releasePackageJsonSha256"])
        er.require(release.get("status") == "published_http_verified"
                   and release.get("contentStatus") in allowed,
                   f"Unpublished or unreviewed release: {locale}")
        er.require(release.get("pageId") == cfg.page_id and release.get("targetLocale") == locale
                   and release.get("contentLocale") == locale, f"Release identity mismatch: {locale}")
        assets = {}
        for role in ("content", "captions"):
            matches = [asset for asset in release["assets"] if asset["role"] == role]
            er.require(len(matches) == 1, f"Expected one {role} asset: {locale}")
            asset = matches[0]
            assets[role] = (er.read_json(er.public_path(public, asset["path"]), sha256=asset["sha256"]),
                            asset["sha256"])
        content, content_sha = assets["content"]
        captions, captions_sha = assets["captions"]
        er.require(content.get("pageId") == cfg.page_id and content.get("targetLocale") == locale
                   and content.get("status") == release["contentStatus"],
                   f"Content identity/status mismatch: {locale}")
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
                   "english": " ".join(english[unit_id] for unit_id in group["sourceUnitIds"])}
                  for group in groups]
        targets[locale] = {"contentSha256": content_sha, "captionsSha256": captions_sha,
                           "releasePackageJsonSha256": target["releasePackageJsonSha256"], "blocks": blocks}
    er.require(targets, "Page has no published targets")
    return {"schemaVersion": "sermon-published-english-reference-v1", "pageId": cfg.page_id,
            "sourceIdentitySha256": source_sha, "sourceMediaSha256": media_sha,
            "reviewState": "human_approved", "targets": targets}


# --- command line --------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True, help="pages/<pageId>.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate", help="print the resolved page identity and check inputs")
    assets = sub.add_parser("assets"); assets.add_argument("--out", type=Path, required=True)
    baseline = sub.add_parser("baseline"); baseline.add_argument("--out", type=Path, required=True)
    baseline.add_argument("--cache-public", type=Path); baseline.add_argument("--cache-receipt", type=Path)
    stage1 = sub.add_parser("stage1")
    stage1.add_argument("--baseline", type=Path, required=True)
    stage1.add_argument("--assets", type=Path, required=True)
    stage1.add_argument("--out", type=Path, required=True)
    publish = sub.add_parser("publish"); publish.add_argument("--snapshot", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--assets", type=Path, required=True); verify.add_argument("--out", type=Path, required=True)
    stage2 = sub.add_parser("stage2")
    stage2.add_argument("--stage1", type=Path, required=True); stage2.add_argument("--assets", type=Path, required=True)
    stage2.add_argument("--evidence", type=Path, required=True); stage2.add_argument("--out", type=Path, required=True)
    stage2.add_argument("--with-english", action="store_true",
                        help="build and stage the English reference in this same deploy")
    readback = sub.add_parser("readback"); readback.add_argument("--stage2", type=Path, required=True)
    english = sub.add_parser("stage-english-reference")
    english.add_argument("--base", type=Path, required=True); english.add_argument("--out", type=Path, required=True)
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    for name in ("out", "baseline", "assets", "snapshot", "stage1", "stage2", "evidence", "base",
                 "cache_public", "cache_receipt"):
        value = getattr(args, name, None)
        if isinstance(value, Path):
            setattr(args, name, value.expanduser().resolve())
    config_path = args.config.expanduser()
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()
    try:
        cfg = load_config(config_path)
        if args.cmd == "validate":
            result = cmd_validate(cfg)
        elif args.cmd == "assets":
            result = cmd_assets(cfg, args.out)
        elif args.cmd == "baseline":
            result = bl.baseline(args.out, cache_public=args.cache_public, cache_receipt=args.cache_receipt,
                                 environment=cfg.environment,
                                 allow_default_locale_drift=cfg.allow_default_locale_drift)
        elif args.cmd == "stage1":
            result = cmd_stage1(cfg, args.baseline, args.assets, args.out)
        elif args.cmd == "publish":
            result = cmd_publish(args.snapshot)
        elif args.cmd == "verify":
            result = cmd_verify(cfg, args.assets, args.out)
        elif args.cmd == "stage2":
            result = cmd_stage2(cfg, args.stage1, args.assets, args.evidence, args.out,
                                with_english=args.with_english)
        elif args.cmd == "stage-english-reference":
            result = cmd_stage_english_reference(cfg, args.base, args.out)
        else:
            result = cmd_readback(cfg, args.stage2)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        print(f"sfa_publish: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
