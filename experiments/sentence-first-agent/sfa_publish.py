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
from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
import re
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
TITLE_TABLE_DEFAULT = "docs/series-sermon-titles.zh.md"


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
    title_check: dict | None
    title_table_path: Path

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
        title_check=data.get("titleCheck"),
        title_table_path=_resolve((data.get("titleCheck") or {}).get("table", TITLE_TABLE_DEFAULT), root),
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


# --- preflight gates -----------------------------------------------------------

RECEIPT_SCHEMA = "sentence-first-human-review-verdict-v1"
DECISION_SCHEMA = "sentence-first-frozen-decisions-v1"


def _english_source_checks(cfg: PageConfig) -> tuple[dict, str]:
    esp, esp_sha = cfg.english_source()
    contract.require(esp.get("schemaVersion") == "sermon-english-source-package-v1",
                     "Unsupported English source package")
    contract.require(esp.get("status") == "ready_for_translation",
                     "English source is not approved for translation")
    contract.require(esp.get("translationEligible") is True, "English source is not translation-eligible")
    contract.require((esp.get("review") or {}).get("humanApproval") is True, "English source needs human approval")
    window = esp["source"]["approvedWindow"]
    contract.require(window.get("humanApproval") is True and window.get("status") == "approved",
                     "Source window is not approved")
    contract.require(hashlib.sha256(cfg.source_url.encode()).hexdigest() == esp["source"]["sourceUrlHash"],
                     "source.url differs from the English package's sourceUrlHash")
    return esp, esp_sha


def _receipt_checks(cfg: PageConfig) -> dict:
    receipt = json.loads(cfg.verdict_path.read_text(encoding="utf-8"))
    contract.require(receipt.get("schemaVersion") == RECEIPT_SCHEMA, "Unsupported review verdict schema")
    contract.require(receipt.get("verdict") == "approved", "Human review verdict is not approved")
    contract.require(receipt.get("pageId") in (None, cfg.page_id), "Verdict pageId differs from the config")
    warnings = []
    try:
        reviewed_at = datetime.fromisoformat(str(receipt.get("reviewedAt", "")).replace("Z", "+00:00"))
    except ValueError as exc:
        contract.require(False, f"reviewedAt is not ISO-8601: {exc}")
    if reviewed_at.tzinfo is None:
        reviewed_at = reviewed_at.replace(tzinfo=timezone.utc)
        warnings.append("reviewedAt has no timezone offset; treated as UTC")
    contract.require(reviewed_at <= datetime.now(timezone.utc) + timedelta(seconds=120),
                     "reviewedAt is in the future")
    note = str(receipt.get("note") or "")
    contract.require("未听审" not in note, "review verdict note still says 未听审")
    locales = receipt.get("locales") or {}
    for locale in cfg.locales:
        entry = locales.get(locale)
        contract.require(isinstance(entry, dict), f"Review verdict has no entry for {locale}")
        track = cfg.run_dir(locale) / "track.wav"
        contract.require(entry.get("trackWavSha256") == sha_file(track),
                         f"{locale}: track.wav changed after the review; the receipt no longer binds the audio")
        review_mp3 = cfg.run_dir(locale) / "review.mp3"
        if review_mp3.is_file() and entry.get("reviewMp3Sha256"):
            contract.require(entry["reviewMp3Sha256"] == sha_file(review_mp3),
                             f"{locale}: review.mp3 changed after the review")
        elif entry.get("reviewMp3Sha256") and not review_mp3.is_file():
            warnings.append(f"{locale}: verdict binds a review.mp3 that is not in the run directory")
    return {"reviewedAt": receipt.get("reviewedAt"), "reviewer": receipt.get("reviewer"), "warnings": warnings}


def _decision_checks(cfg: PageConfig, *, allow_missing: bool) -> dict:
    decisions, warnings = {}, []
    for locale in cfg.locales:
        path = cfg.run_dir(locale) / "decisions.json"
        if not path.is_file():
            if allow_missing:
                warnings.append(f"{locale}: decisions.json missing (allowed by --allow-missing-decisions)")
                continue
            contract.require(False, f"{locale}: decisions.json missing; start the run with sfa.py start "
                                    "or pass --allow-missing-decisions for a legacy run")
        data = json.loads(path.read_text(encoding="utf-8"))
        contract.require(data.get("schemaVersion") == DECISION_SCHEMA, f"{locale}: unsupported decisions schema")
        contract.require(data.get("publish") is True, f"{locale}: decisions say publish=false")
        contract.require(isinstance(data.get("sync"), bool), f"{locale}: sync decision is not recorded")
        contract.require(isinstance(data.get("title"), str) and bool(data["title"].strip()),
                         f"{locale}: the frozen title is empty")
        contract.require(locale in (data.get("locales") or []), f"{locale}: decisions do not list this locale")
        decisions[locale] = {key: data.get(key) for key in ("form", "sync", "publish", "title")}
    return {"decisions": decisions, "warnings": warnings}


TITLE_COLUMNS = {"zh-Hans": "zh", "ko": "ko", "es": "es"}


def parse_title_table(path: Path) -> dict:
    """Sections of docs/series-sermon-titles.zh.md: main rows plus the published-difference table."""
    sections, current = {}, None
    heading = re.compile(r"^##\s+(.+?)（`([a-z0-9][a-z0-9-]*)`）\s*$")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        match = heading.match(line)
        if match:
            current = sections.setdefault(match.group(2), {"key": match.group(2), "zhName": match.group(1),
                                                           "rows": [], "differences": {}})
            continue
        if not line.startswith("|") or current is None:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 8 and cells[0].isdigit():
            current["rows"].append({"week": int(cells[0]), "date": cells[1], "english": cells[2],
                                    "scripture": cells[3], "speaker": cells[4],
                                    "zh": cells[5], "ko": cells[6], "es": cells[7]})
        elif len(cells) == 3 and cells[0].isdigit():
            current["differences"][int(cells[0])] = {"table": cells[1], "published": cells[2]}
    contract.require(bool(sections), f"no title table found in {path}")
    return sections


def find_title_row(sections: dict, english_title: str, series_key: str | None = None):
    wanted = english_title.strip().casefold()
    matches = [(section, row) for section in sections.values()
               if not series_key or section["key"] == series_key
               for row in section["rows"] if row["english"].strip().casefold() == wanted]
    contract.require(len(matches) == 1,
                     f"English title {english_title!r} matches {len(matches)} rows in the title table")
    return matches[0]


def cmd_check_title(cfg: PageConfig) -> dict:
    """Check the page titles against the title table, or against the explicitly frozen published titles."""
    spec = cfg.title_check
    contract.require(spec is not None,
                     "page config has no titleCheck block (mode table|published|approved_exception)")
    mode = spec["mode"]
    published = spec.get("publishedTitles") or {}
    if mode != "table":
        missing = [locale for locale in cfg.locales if locale not in published]
        contract.require(not missing, f"titleCheck.publishedTitles misses {missing} for mode {mode}")
        contract.require(bool((spec.get("reason") or "").strip()), f"titleCheck mode {mode} needs a reason")
        if mode == "approved_exception":
            contract.require(bool((spec.get("approvedBy") or "").strip()),
                             "titleCheck mode approved_exception needs approvedBy")
    contract.require(cfg.title_table_path.is_file(), f"title table not found: {cfg.title_table_path}")
    sections = parse_title_table(cfg.title_table_path)
    section, row = find_title_row(sections, spec["englishTitle"], spec.get("seriesKey"))
    actual = {locale: cfg.meta[locale]["title"] for locale in cfg.locales}
    expected, problems, warnings = {}, [], []
    if mode == "table":
        for locale in cfg.locales:
            expected[locale] = f"{cfg.meta[locale]['series']} · {row[TITLE_COLUMNS[locale]]}"
        if "zh-Hans" in cfg.locales and cfg.meta["zh-Hans"]["series"] != section["zhName"]:
            problems.append({"locale": "zh-Hans",
                             "detail": f"series {cfg.meta['zh-Hans']['series']!r} differs from the table "
                                       f"section {section['zhName']!r}"})
    else:
        expected = {locale: published[locale] for locale in cfg.locales}
    difference = section["differences"].get(row["week"])
    if difference:
        warnings.append(f"week {row['week']} has a published-title difference: table {difference['table']!r} "
                        f"vs published {difference['published']!r}")
    for locale in cfg.locales:
        if actual[locale] != expected[locale]:
            problems.append({"locale": locale,
                             "detail": f"page title {actual[locale]!r} differs from the title table value {expected[locale]!r}"})
    if cfg.title != cfg.meta[cfg.default_target_locale]["title"]:
        problems.append({"locale": cfg.default_target_locale,
                         "detail": f"config.title {cfg.title!r} differs from meta.title "
                                   f"{cfg.meta[cfg.default_target_locale]['title']!r}"})
    return {"ok": not problems, "mode": mode, "series": section["key"], "week": row["week"],
            "englishTitle": row["english"], "tableRow": row, "expected": expected, "actual": actual,
            "problems": problems, "warnings": warnings}


def _journal_checks(cfg: PageConfig, *, allow_missing: bool) -> list[str]:
    """The runbook's pre-publish journal gates: full preflight (fail) and consistency (warn)."""
    warnings = []
    for locale in cfg.locales:
        path = cfg.run_dir(locale) / "journal.ndjson"
        if not path.is_file():
            contract.require(allow_missing, f"{locale}: journal.ndjson missing; cannot prove l1.preflight ran")
            warnings.append(f"{locale}: journal.ndjson missing (allowed by --allow-missing-journal-gates)")
            continue
        finished = {json.loads(line)["stage"] for line in path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and json.loads(line).get("event") == "finished"}
        contract.require("l1.preflight" in finished,
                         f"{locale}: journal has no finished l1.preflight; run the full preflight before TTS")
        if "l2.consistency" not in finished:
            warnings.append(f"{locale}: journal has no finished l2.consistency (consistency_check.py)")
    return warnings


def cmd_preflight(cfg: PageConfig, *, allow_missing_decisions: bool = False,
                  allow_missing_title_check: bool = False,
                  allow_missing_journal_gates: bool = False) -> dict:
    """The publish gate before assets: identity, English approval, receipt freshness, decisions."""
    cfg.require_inputs()
    esp, esp_sha = _english_source_checks(cfg)
    receipt = _receipt_checks(cfg)
    decision_info = _decision_checks(cfg, allow_missing=allow_missing_decisions)
    journal_warnings = _journal_checks(cfg, allow_missing=allow_missing_journal_gates)
    if cfg.title_check is None:
        contract.require(allow_missing_title_check,
                         "page config has no titleCheck block; add it or pass --allow-missing-title-check")
        title_info = {"skipped": "no titleCheck block (legacy config)"}
    else:
        title_info = cmd_check_title(cfg)
        contract.require(title_info["ok"], "title check failed: "
                         + " | ".join(problem["detail"] for problem in title_info["problems"]))
    return {"ok": True, "pageId": cfg.page_id, "environment": cfg.environment, "origin": cfg.origin(),
            "locales": list(cfg.locales), "englishSourceJsonSha256": esp_sha,
            "sourceMediaSha256": esp["source"]["media"]["sha256"],
            "verdict": {"reviewedAt": receipt["reviewedAt"], "reviewer": receipt["reviewer"]},
            "decisions": decision_info["decisions"],
            "titleCheck": {"mode": title_info.get("mode"), "series": title_info.get("series"),
                           "week": title_info.get("week"), "expected": title_info.get("expected"),
                           "actual": title_info.get("actual"), "skipped": title_info.get("skipped")},
            "warnings": receipt["warnings"] + decision_info["warnings"] + journal_warnings
                        + title_info.get("warnings", [])}


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _public_file(public: Path, rel: str, problems: list) -> Path | None:
    cleaned = rel.lstrip("/")
    if ".." in Path(cleaned).parts:
        problems.append({"path": rel, "detail": "unsafe public path"})
        return None
    return public / cleaned


def _check_staged_assets(cfg: PageConfig, snapshot: Path, assets: Path,
                         baseline: Path | None) -> dict:
    """Pre-first-deploy check: releases live in the assets dir, the catalog has no page yet."""
    public = snapshot / "public"
    contract.require(public.is_dir(), f"not a snapshot: {snapshot}")
    problems, warnings, current = [], [], set()
    for name, catalog in sorted((name, _read_json(public / name)) for name in contract.CATALOG_FILES.values()
                                if (public / name).is_file()):
        if any(page.get("id") == cfg.page_id for page in catalog.get("pages", [])):
            problems.append({"path": name, "detail": "page is already in a snapshot catalog before the first deploy"})
    for locale in cfg.locales:
        release_path = assets / "releases" / f"{locale}.json"
        if not release_path.is_file():
            problems.append({"path": f"assets/releases/{locale}.json", "detail": "release file missing from the assets directory"})
            continue
        release = _read_json(release_path)
        if release.get("pageId") != cfg.page_id or release.get("targetLocale") != locale:
            problems.append({"path": f"assets/releases/{locale}.json", "detail": "release identity mismatch"})
        try:
            contract.validate_v2_asset_paths(release, cfg.page_id, locale)
        except ValueError as exc:
            problems.append({"path": f"assets/releases/{locale}.json", "detail": str(exc)})
        for asset in release.get("assets", []):
            target = _public_file(public, asset.get("path", ""), problems)
            if target is None or not target.is_file():
                problems.append({"path": asset.get("path", ""), "detail": f"{locale}: staged asset missing"})
                continue
            digest = sha_file(target)
            current.add(digest)
            if digest != asset.get("sha256"):
                problems.append({"path": asset["path"], "detail": f"{locale}: staged asset hash differs from the release"})
    stale = []
    if baseline is not None:
        baseline_public = baseline / "public"
        old_hashes = set()
        old_catalog = baseline_public / "multilingual-v3.json"
        if old_catalog.is_file():
            for entry in _read_json(old_catalog).get("pages", []):
                if entry.get("id") == cfg.page_id:
                    warnings.append("page already exists in the baseline catalog; this is a rebuild, not a first deploy")
                    for target in (entry.get("targets") or {}).values():
                        if target.get("releasePackageJsonSha256"):
                            old_hashes.add(target["releasePackageJsonSha256"])
        for path in sorted(public.rglob("*")):
            if not path.is_file() or path.suffix not in (".json", ".html", ".txt", ".xml"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for digest in sorted(old_hashes - current):
                if digest in text:
                    stale.append({"path": "/" + path.relative_to(public).as_posix(), "hash": digest})
        problems.extend({"path": item["path"], "detail": "still references an old release hash"} for item in stale)
    return {"ok": not problems, "pageId": cfg.page_id, "environment": cfg.environment,
            "snapshot": str(snapshot), "mode": "staged-assets", "problems": problems,
            "warnings": warnings, "staleReferences": stale,
            "checked": {"catalog": "must not contain the page yet", "locales": list(cfg.locales),
                        "assets": str(assets), "baselineScanned": baseline is not None}}


def cmd_publish_check(cfg: PageConfig, snapshot: Path, *, baseline: Path | None = None,
                      require_english_reference: bool = False,
                      require_announcements: bool = False,
                      assets: Path | None = None) -> dict:
    """Verify every cross-artifact hash binding before a deploy, and scan for stale old hashes.

    With ``assets`` set, check the first deploy instead: releases still live in the assets
    directory and the snapshot catalog must not contain the page yet.
    """
    if assets is not None:
        return _check_staged_assets(cfg, snapshot, assets, baseline)
    public = snapshot / "public"
    contract.require(public.is_dir(), f"not a snapshot: {snapshot}")
    problems, warnings = [], []
    _, esp_sha = cfg.english_source()
    catalog_path = public / "multilingual-v3.json"
    contract.require(catalog_path.is_file(), "snapshot has no multilingual-v3.json")
    catalog = _read_json(catalog_path)
    pages = [page for page in catalog.get("pages", []) if page.get("id") == cfg.page_id]
    contract.require(len(pages) == 1, f"page appears {len(pages)} times in the live catalog")
    page = pages[0]
    if page.get("sourceIdentitySha256") != esp_sha:
        problems.append({"path": "multilingual-v3.json", "detail": "catalog source identity differs from the English package"})
    v5_path = public / "multilingual-v5.json"
    if v5_path.is_file():
        v5_pages = [entry for entry in _read_json(v5_path).get("pages", []) if entry.get("id") == cfg.page_id]
        if len(v5_pages) != 1:
            problems.append({"path": "multilingual-v5.json", "detail": "page missing from the v5 catalog"})
        else:
            for locale in cfg.locales:
                if ((v5_pages[0].get("targets") or {}).get(locale) or {}).get("releasePackageJsonSha256") != \
                        ((page.get("targets") or {}).get(locale) or {}).get("releasePackageJsonSha256"):
                    problems.append({"path": "multilingual-v5.json", "detail": f"{locale}: v5 release hash differs from v3"})

    content_by_locale, current_hashes = {}, set()
    for locale in cfg.locales:
        target = (page.get("targets") or {}).get(locale)
        if not isinstance(target, dict):
            problems.append({"path": "multilingual-v3.json", "detail": f"{locale}: no target"})
            continue
        release_rel = target.get("releasePackageUrl", "")
        release_path = _public_file(public, release_rel, problems)
        if release_path is None or not release_path.is_file():
            problems.append({"path": release_rel, "detail": f"{locale}: release file missing"})
            continue
        release_sha = sha_file(release_path)
        if release_sha != target.get("releasePackageJsonSha256"):
            problems.append({"path": release_rel, "detail": f"{locale}: release hash differs from the catalog"})
        current_hashes.add(release_sha)
        release = _read_json(release_path)
        if release.get("pageId") != cfg.page_id or release.get("targetLocale") != locale:
            problems.append({"path": release_rel, "detail": f"{locale}: release identity mismatch"})
        if release.get("status") != "published_http_verified":
            problems.append({"path": release_rel, "detail": f"{locale}: release status is {release.get('status')!r}"})
        assets = {}
        for role in ("page", "content", "captions", "audio"):
            matches = [asset for asset in release.get("assets", []) if asset.get("role") == role]
            if len(matches) != 1:
                problems.append({"path": release_rel, "detail": f"{locale}: expected one {role} asset"})
                continue
            asset = matches[0]
            asset_path = _public_file(public, asset.get("path", ""), problems)
            if asset_path is None or not asset_path.is_file():
                problems.append({"path": asset.get("path", ""), "detail": f"{locale}: {role} file missing"})
                continue
            digest = sha_file(asset_path)
            if digest != asset.get("sha256"):
                problems.append({"path": asset["path"], "detail": f"{locale}: {role} hash differs from the release"})
            assets[role] = (asset_path, digest)
            current_hashes.add(digest)
        content_path, content_digest = assets.get("content", (None, None))
        captions_path, captions_digest = assets.get("captions", (None, None))
        if content_path is None or captions_path is None:
            continue
        content, captions = _read_json(content_path), _read_json(captions_path)
        content_by_locale[locale] = (content, content_digest, captions_digest)
        if content.get("englishSourcePackageJsonSha256") != esp_sha:
            problems.append({"path": str(content_path.relative_to(public)), "detail": f"{locale}: content source hash mismatch"})
        if content.get("targetLanguageCandidateJsonSha256") != release.get("targetLanguageCandidateJsonSha256"):
            problems.append({"path": str(content_path.relative_to(public)), "detail": f"{locale}: content candidate hash mismatch"})
        cues = content.get("cues") or []
        if not cues:
            problems.append({"path": str(content_path.relative_to(public)), "detail": f"{locale}: content has no cues"})
        elif cues[-1]["end"] > float(content.get("durationSeconds", 0)) + 0.001:
            problems.append({"path": str(content_path.relative_to(public)), "detail": f"{locale}: last cue ends after durationSeconds"})
        group_ids = [cue.get("textGroupId") for cue in cues]
        if len(set(group_ids)) != len(group_ids):
            problems.append({"path": str(content_path.relative_to(public)), "detail": f"{locale}: duplicate textGroupId"})
        if [cue.get("textGroupId") for cue in captions.get("cues", [])] != group_ids:
            problems.append({"path": str(captions_path.relative_to(public)), "detail": f"{locale}: captions group order differs from content"})
        if captions.get("audioPackageJsonSha256") != release.get("targetLanguageAudioPackageJsonSha256"):
            problems.append({"path": str(captions_path.relative_to(public)), "detail": f"{locale}: captions audio-package hash mismatch"})

    english_path = public / "english-reference" / f"{cfg.page_id}.json"
    english_info = {"present": english_path.is_file(), "locales": []}
    if english_path.is_file():
        reference = _read_json(english_path)
        if reference.get("pageId") != cfg.page_id:
            problems.append({"path": str(english_path.relative_to(public)), "detail": "English reference pageId mismatch"})
        for locale in cfg.locales:
            target = (reference.get("targets") or {}).get(locale)
            if not isinstance(target, dict):
                problems.append({"path": str(english_path.relative_to(public)), "detail": f"{locale}: English reference misses the locale"})
                continue
            english_info["locales"].append(locale)
            content, content_digest, captions_digest = content_by_locale.get(locale, (None, None, None))
            if target.get("contentSha256") != content_digest or target.get("captionsSha256") != captions_digest:
                problems.append({"path": str(english_path.relative_to(public)),
                                 "detail": f"{locale}: English reference binds older content/captions"})
            blocks = target.get("blocks") or []
            if content is not None and len(blocks) != len(content.get("cues") or []):
                problems.append({"path": str(english_path.relative_to(public)),
                                 "detail": f"{locale}: English reference has {len(blocks)} blocks for {len(content.get('cues') or [])} cues"})
    elif require_english_reference:
        problems.append({"path": f"english-reference/{cfg.page_id}.json", "detail": "English reference is required but missing"})
    else:
        warnings.append("English reference is not staged yet (the third deploy adds it)")

    announcements_info = {"present": (public / "weekly-announcements-v1.json").is_file(), "entries": 0}
    ann_path = public / "weekly-announcements-v1.json"
    if ann_path.is_file():
        announcements = _read_json(ann_path).get("announcements", [])
        for locale in cfg.locales:
            target = (page.get("targets") or {}).get(locale) or {}
            release_sha = target.get("releasePackageJsonSha256")
            entries = [item for item in announcements
                       if item.get("pageID") == cfg.page_id and item.get("locale") == locale]
            if not entries:
                (problems if require_announcements else warnings).append(
                    f"{locale}: no weekly-announcements entry for this page")
                continue
            for entry in entries:
                announcements_info["entries"] += 1
                if entry.get("releaseSHA256") != release_sha:
                    problems.append({"path": "weekly-announcements-v1.json",
                                     "detail": f"{locale}: announcement binds an older release hash"})
                if entry.get("sourceIdentitySHA256") != esp_sha:
                    problems.append({"path": "weekly-announcements-v1.json",
                                     "detail": f"{locale}: announcement source identity differs"})
    elif require_announcements:
        problems.append({"path": "weekly-announcements-v1.json", "detail": "announcement sidecar is required but missing"})
    else:
        warnings.append("weekly-announcements-v1.json is not in this snapshot")

    stale = []
    if baseline is not None:
        baseline_public = baseline / "public"
        old_hashes = set()
        old_catalog = baseline_public / "multilingual-v3.json"
        if old_catalog.is_file():
            for entry in _read_json(old_catalog).get("pages", []):
                if entry.get("id") != cfg.page_id:
                    continue
                for target in (entry.get("targets") or {}).values():
                    if target.get("releasePackageJsonSha256"):
                        old_hashes.add(target["releasePackageJsonSha256"])
        old_reference = baseline_public / "english-reference" / f"{cfg.page_id}.json"
        if old_reference.is_file():
            for target in (_read_json(old_reference).get("targets") or {}).values():
                for key in ("contentSha256", "captionsSha256", "releasePackageJsonSha256"):
                    if target.get(key):
                        old_hashes.add(target[key])
        stale_hashes = sorted(old_hashes - current_hashes)
        if stale_hashes:
            for path in sorted(public.rglob("*")):
                if not path.is_file() or path.suffix not in (".json", ".html", ".txt", ".xml"):
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for digest in stale_hashes:
                    if digest in text:
                        stale.append({"path": "/" + path.relative_to(public).as_posix(), "hash": digest})
    if stale:
        for item in stale:
            problems.append({"path": item["path"], "detail": "still references an old release/content/captions hash"})

    return {"ok": not problems, "pageId": cfg.page_id, "environment": cfg.environment,
            "snapshot": str(snapshot), "problems": problems, "warnings": warnings,
            "staleReferences": stale,
            "checked": {"catalog": "multilingual-v3.json", "locales": list(cfg.locales),
                        "englishReference": english_info, "announcements": announcements_info,
                        "baselineScanned": baseline is not None}}


# --- assets --------------------------------------------------------------------

def cmd_validate(cfg: PageConfig) -> dict:
    cfg.require_inputs()
    english, _ = cfg.english_source()
    digest = hashlib.sha256(cfg.source_url.encode()).hexdigest()
    contract.require(digest == english["source"]["sourceUrlHash"],
                     "source.url differs from the English package's sourceUrlHash")
    result = {"ok": True, **cfg.identity(), "sourceUrlHash": digest,
              "sourceMediaSha256": english["source"]["media"]["sha256"]}
    if cfg.title_check is not None:
        title_check = cmd_check_title(cfg)
        result["titleCheck"] = title_check
        result["ok"] = result["ok"] and title_check["ok"]
    return result


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
        # Single-speaker runs carry the voice on each speech row instead of a sentence speakerId.
        for sentence in sent:
            sentence.setdefault("speakerId", sp[sentence["id"]].get("speaker") or "")
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
    return {"ok": evidence["status"] == "pass", "status": evidence["status"], "checks": len(checks),
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
    # The weekly release contract appends the page and makes it the catalog default
    # (docs/tongxing-weekly-release.zh.md, 合并 row). The v4/v3 projections inherit it.
    v5["defaultPageId"] = cfg.page_id
    contract.validate_catalog_schema(v5)
    v4 = contract.project_legacy_catalog_v4(v5)
    v3 = contract.project_human_catalog(v4)
    for name, new in ((contract.CATALOG_V4, v4), (contract.CATALOG_V3, v3)):
        contract.require(sum(entry["id"] == cfg.page_id for entry in new["pages"]) == 1,
                         name + ": page missing from projection")
        contract.require([entry for entry in new["pages"] if entry["id"] != cfg.page_id] == old[name]["pages"],
                         name + ": projection changed other pages")
        contract.require({key: value for key, value in new.items() if key not in ("pages", "defaultPageId")}
                         == {key: value for key, value in old[name].items() if key not in ("pages", "defaultPageId")},
                         name + ": projection changed catalog metadata")
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
    return {"ok": all(results.values()), "pass": all(results.values()), "checks": results}


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
    preflight = sub.add_parser("preflight", help="publish gate: English approval, receipt freshness, decisions, titles")
    preflight.add_argument("--allow-missing-decisions", action="store_true",
                           help="legacy run without decisions.json (recorded in run.md instead)")
    preflight.add_argument("--allow-missing-title-check", action="store_true",
                           help="legacy config without a titleCheck block")
    preflight.add_argument("--allow-missing-journal-gates", action="store_true",
                           help="legacy run without the l1.preflight journal gate")
    title = sub.add_parser("check-title", help="check the page titles against the title table")
    title.add_argument("--allow-missing", action="store_true", help="do not fail when titleCheck is absent")
    check = sub.add_parser("publish-check", help="verify hash bindings and hunt stale hashes before a deploy")
    check.add_argument("--snapshot", type=Path, required=True)
    check.add_argument("--assets", type=Path,
                       help="first-deploy mode: verify the assets directory against the staged snapshot")
    check.add_argument("--baseline", type=Path, help="live baseline snapshot; enables the old-hash scan")
    check.add_argument("--require-english-reference", action="store_true")
    check.add_argument("--require-announcements", action="store_true")
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
        elif args.cmd == "preflight":
            result = cmd_preflight(cfg, allow_missing_decisions=args.allow_missing_decisions,
                                   allow_missing_title_check=args.allow_missing_title_check,
                                   allow_missing_journal_gates=args.allow_missing_journal_gates)
        elif args.cmd == "check-title":
            if cfg.title_check is None and args.allow_missing:
                result = {"ok": True, "skipped": "no titleCheck block"}
            else:
                result = cmd_check_title(cfg)
        elif args.cmd == "publish-check":
            result = cmd_publish_check(cfg, args.snapshot, baseline=args.baseline,
                                       require_english_reference=args.require_english_reference,
                                       require_announcements=args.require_announcements,
                                       assets=args.assets)
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
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
