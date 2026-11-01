#!/usr/bin/env python3
"""Pre-publish / post-publish completeness gate for a sentence-first page.

Reads the live (or a local copy of the) published page and asserts that every
artifact that shares a release identity agrees with it:

  catalogs -> releases -> content/captions -> english reference
  catalogs -> alignment sidecar -> fingerprint indexes -> audio window
  weekly-guide manifest -> guide entry -> guide bytes
  page catalog title -> rendered page HTML

Usage:
  PYTHONPATH=packages/production/src:. .venv/bin/python tools/ops/sfa_publish_gate.py \
      --page-id revelation-jesus-marks-his-own-20261101 \
      --json-out artifacts/sentence-first-agent/<run>/publish-gate.json

Exit code 0 = all required checks pass, 1 = at least one failure, 2 = usage error.
This gate never writes to the published site.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

LOCALES = ("zh-Hans", "ko", "es")
GUIDE_PINS = {
    "schemaVersion": "tongxing-weekly-guide-manifest-v1",
    "seriesID": "revelation-comfort-and-hope",
    "translationSHA256": "d6c6064e8fab11ab012edd9535372a9f99b83cd5240b6014f5451795a9198f86",
    "cuvSHA256": "363afb38148f150b30fee727f4818faa821a0d17b4888c16be3e05bd462503bb",
}
MP3_BITRATES_V1 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
MP3_BITRATES_V2 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Gate:
    def __init__(self) -> None:
        self.checks: list[dict] = []

    def add(self, name: str, ok: bool, detail: str, required: bool = True) -> bool:
        self.checks.append({"check": name, "ok": bool(ok), "required": required, "detail": detail})
        return ok

    def require(self, name: str, ok: bool, detail: str) -> bool:
        return self.add(name, ok, detail, required=True)

    @property
    def failed(self) -> list[dict]:
        return [c for c in self.checks if c["required"] and not c["ok"]]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--origin", default="https://ai-for-god-sermon-audio.web.app")
    parser.add_argument("--guide-manifest", type=Path, help="local JSON instead of the live v1 manifest")
    parser.add_argument("--require-guide", action="store_true", help="fail when the page has no guide entry")
    parser.add_argument("--require-alignment", action="store_true", help="fail when the page has no alignment binding")
    parser.add_argument("--skip-alignment-drift", action="store_true", help="do not estimate the audio length from the MP3 header")
    parser.add_argument("--max-drift", type=float, default=0.12)
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def get(url: str, headers: dict | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def head(url: str) -> dict:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=60) as response:
        return dict(response.headers)


def audio_seconds(url: str) -> float | None:
    """Exact MP3 duration via ffprobe; CBR-header estimate as fallback."""
    import shutil
    import subprocess
    probe = shutil.which("ffprobe")
    if probe:
        try:
            out = subprocess.run(
                [probe, "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", url],
                capture_output=True, text=True, timeout=180, check=True)
            value = float(out.stdout.strip())
            if value > 0:
                return value
        except Exception:
            pass
    size = int(head(url).get("Content-Length") or 0)
    if size <= 0:
        return None
    status, raw = get(url, {"Range": "bytes=0-8191"})
    if status not in (200, 206) or len(raw) < 64:
        return None
    offset = 0
    if raw[:3] == b"ID3":
        tag_size = ((raw[6] & 0x7F) << 21) | ((raw[7] & 0x7F) << 14) | ((raw[8] & 0x7F) << 7) | (raw[9] & 0x7F)
        offset = 10 + tag_size
    limit = min(len(raw) - 4, offset + 16384)
    for index in range(offset, limit):
        if raw[index] != 0xFF or (raw[index + 1] & 0xE0) != 0xE0:
            continue
        version = (raw[index + 1] >> 3) & 0x03
        layer = (raw[index + 1] >> 1) & 0x03
        bitrate_index = (raw[index + 2] >> 4) & 0x0F
        if layer != 0x01 or bitrate_index in (0, 15):
            continue
        table = MP3_BITRATES_V1 if version != 0x02 else MP3_BITRATES_V2
        bitrate = table[bitrate_index] * 1000
        if bitrate:
            return (size - index) * 8 / bitrate
    return None


def check_catalog(gate: Gate, catalog: dict, page_id: str) -> tuple[dict | None, bytes]:
    gate.require("catalog.schema", catalog.get("schemaVersion") == "sermon-multilingual-catalog-v5",
                 f"schema={catalog.get('schemaVersion')}")
    pages = [p for p in catalog.get("pages", []) if p.get("id") == page_id]
    if not gate.require("catalog.page", len(pages) == 1, f"pages with id {page_id}: {len(pages)}"):
        return None, b""
    page = pages[0]
    gate.require("catalog.defaultPageId", catalog.get("defaultPageId") == page_id,
                 f"defaultPageId={catalog.get('defaultPageId')}")
    gate.require("catalog.locales", set(page.get("targets", {})) <= set(LOCALES),
                 f"targets={sorted(page.get('targets', {}))}")
    gate.require("catalog.title", isinstance(page.get("title"), str) and bool(page["title"].strip()),
                 f"title={page.get('title')!r}")
    return page, b""


def check_locale(gate: Gate, origin: str, page: dict, locale: str, reference: dict | None) -> None:
    target = page["targets"][locale]
    release_path = target.get("releasePackageUrl") or f"/releases-v2/{page['id']}/{locale}.json"
    status, release_raw = get(origin + release_path)
    if not gate.require(f"{locale}.release.http", status == 200 and bool(release_raw), f"GET {release_path} -> {status}"):
        return
    release_sha = sha(release_raw)
    gate.require(f"{locale}.release.catalog", release_sha == target.get("releasePackageJsonSha256"),
                 f"live {release_sha[:16]} vs catalog {str(target.get('releasePackageJsonSha256'))[:16]}")
    release = json.loads(release_raw)
    gate.require(f"{locale}.release.status",
                 release.get("status") == "published_http_verified"
                 and (release.get("httpVerification") or {}).get("status") == "pass",
                 f"status={release.get('status')} http={ (release.get('httpVerification') or {}).get('status') }")
    assets = {a.get("role"): a for a in release.get("assets") or [] if isinstance(a, dict)}
    gate.require(f"{locale}.release.assets", set(assets) == {"page", "content", "captions", "audio"},
                 f"roles={sorted(assets)}")

    status, content_raw = get(origin + assets["content"]["path"])
    if not gate.require(f"{locale}.content.http", status == 200, f"{status}"):
        return
    gate.require(f"{locale}.content.hash", sha(content_raw) == assets["content"].get("sha256"),
                 f"live {sha(content_raw)[:16]} vs release {str(assets['content'].get('sha256'))[:16]}")
    content = json.loads(content_raw)
    gate.require(f"{locale}.content.identity",
                 content.get("pageId") == page["id"] and content.get("targetLocale") == locale,
                 f"pageId={content.get('pageId')} targetLocale={content.get('targetLocale')}")
    duration = content.get("durationSeconds")
    audio_seconds_field = content.get("audioDurationSeconds", duration)
    gate.require(f"{locale}.content.duration", isinstance(duration, (int, float)) and duration > 0,
                 f"durationSeconds={duration}")
    drift = (audio_seconds_field or 0) - (duration or 0)
    gate.require(f"{locale}.content.drift", -0.1 < drift < 1.1, f"audioDuration-duration={drift:+.3f}s")

    status, captions_raw = get(origin + assets["captions"]["path"])
    if gate.require(f"{locale}.captions.http", status == 200, f"{status}"):
        gate.require(f"{locale}.captions.hash", sha(captions_raw) == assets["captions"].get("sha256"),
                     f"live {sha(captions_raw)[:16]} vs release {str(assets['captions'].get('sha256'))[:16]}")
        captions = json.loads(captions_raw)
        cues = captions.get("cues") or []
        content_cues = content.get("cues") or []
        gate.require(f"{locale}.captions.count", len(cues) == len(content_cues),
                     f"captions={len(cues)} content={len(content_cues)}")
        ends = [c.get("end") for c in cues if isinstance(c, dict)]
        gate.require(f"{locale}.captions.bounds",
                     bool(ends) and all(isinstance(e, (int, float)) and e <= (audio_seconds_field or 0) + 0.001 for e in ends),
                     f"last cue end={max(ends) if ends else None} audio={audio_seconds_field}")

    if reference is not None:
        block = (reference.get("targets") or {}).get(locale) or {}
        gate.require(f"{locale}.reference.identity",
                     block.get("releasePackageJsonSha256") == target.get("releasePackageJsonSha256"),
                     f"reference release {str(block.get('releasePackageJsonSha256'))[:16]} vs catalog {str(target.get('releasePackageJsonSha256'))[:16]}")
        gate.require(f"{locale}.reference.hashes",
                     block.get("contentSha256") == assets["content"].get("sha256")
                     and block.get("captionsSha256") == assets["captions"].get("sha256"),
                     "content/captions hashes differ")
        gate.require(f"{locale}.reference.blocks", len(block.get("blocks") or []) == len(content.get("cues") or []),
                     f"blocks={len(block.get('blocks') or [])} cues={len(content.get('cues') or [])}")


def check_alignment(gate: Gate, origin: str, page: dict, catalog: dict, require: bool, check_drift: bool,
                    max_drift: float) -> None:
    binding = page["targets"]["zh-Hans"].get("audioFingerprint")
    if not isinstance(binding, dict):
        gate.add("alignment.binding", not require, "no audioFingerprint in catalog", required=require)
        return
    for locale, target in page["targets"].items():
        gate.require(f"alignment.capability.{locale}", "alignment" in (target.get("capabilities") or []),
                     f"capabilities={target.get('capabilities')}")
    status, sidecar_raw = get(origin + f"/alignment/{page['id']}.json")
    if not gate.require("alignment.sidecar.http", status == 200, f"GET /alignment/<pageId>.json -> {status}"):
        return
    sidecar = json.loads(sidecar_raw)
    gate.require("alignment.sidecar.identity",
                 sidecar.get("schemaVersion") == "sermon-published-alignment-v1"
                 and sidecar.get("pageId") == page["id"]
                 and sidecar.get("sourceIdentitySha256") == page.get("sourceIdentitySha256"),
                 f"pageId={sidecar.get('pageId')}")
    gate.require("alignment.sidecar.targets", set(sidecar.get("targets") or {}) == set(page["targets"]),
                 f"targets={sorted(sidecar.get('targets') or {})}")
    window = None
    for locale, target in page["targets"].items():
        catalog_binding = target.get("audioFingerprint")
        sidecar_binding = ((sidecar.get("targets") or {}).get(locale) or {}).get("audioFingerprint")
        gate.require(f"alignment.sidecar.binding.{locale}", catalog_binding == sidecar_binding,
                     "sidecar binding differs from catalog")
        if not isinstance(catalog_binding, dict):
            continue
        status, index_raw = get(origin + catalog_binding.get("indexUrl", ""))
        if not gate.require(f"alignment.index.http.{locale}", status == 200, f"{status}"):
            continue
        gate.require(f"alignment.index.hash.{locale}", sha(index_raw) == catalog_binding.get("indexSha256"),
                     f"live {sha(index_raw)[:16]} vs binding {str(catalog_binding.get('indexSha256'))[:16]}")
        index = json.loads(index_raw)
        gate.require(f"alignment.index.identity.{locale}",
                     index.get("pageId") == page["id"]
                     and index.get("trackSha256") == catalog_binding.get("trackSha256")
                     and index.get("sourceSha256") == catalog_binding.get("sourceSha256")
                     and index.get("sourceStartSeconds") == catalog_binding.get("sourceStartSeconds")
                     and index.get("sourceEndSeconds") == catalog_binding.get("sourceEndSeconds"),
                     f"index pageId={index.get('pageId')}")
        window = (catalog_binding.get("sourceStartSeconds"), catalog_binding.get("sourceEndSeconds"))
        if check_drift and window:
            status, content_raw = get(origin + f"/content/{page['id']}/{locale}.json")
            content = json.loads(content_raw) if status == 200 else {}
            if isinstance(content, dict) and content.get("durationSeconds"):
                catalog_binding = {**catalog_binding, "window": window}
                seconds = audio_seconds(origin + f"/media/{page['id']}/{locale}.mp3")
                if seconds is None:
                    gate.add(f"alignment.drift.{locale}", True, "audio length unavailable; skipped", required=False)
                else:
                    gap = abs(seconds - (window[1] - window[0]))
                    gate.require(f"alignment.drift.{locale}", gap <= max_drift,
                                 f"track≈{seconds:.3f}s vs window {window[1] - window[0]:.3f}s gap={gap:.3f}s")


def check_guide(gate: Gate, origin: str, page: dict, page_id: str, manifest_path: Path | None, require: bool) -> None:
    if manifest_path is not None:
        raw = manifest_path.read_bytes()
        source = str(manifest_path)
    else:
        status, raw = get(origin + "/weekly-guides/manifest-v1.json")
        source = origin + "/weekly-guides/manifest-v1.json"
        if status == 404:
            gate.add("guide.manifest", not require, f"no manifest at {source}", required=require)
            return
        if not gate.require("guide.manifest.http", status == 200, f"GET {source} -> {status}"):
            return
    manifest = json.loads(raw)
    gate.require("guide.pins", all(manifest.get(k) == v for k, v in GUIDE_PINS.items()),
                 f"schema={manifest.get('schemaVersion')} series={manifest.get('seriesID')}")
    gate.require("guide.humanApproval", manifest.get("humanApproval") is False
                 and manifest.get("review") == "machine_translation_not_human_reviewed",
                 f"humanApproval={manifest.get('humanApproval')} review={manifest.get('review')}")
    entries = manifest.get("entries") or []
    keys = [(e.get("pageID"), e.get("locale")) for e in entries]
    gate.require("guide.entries", len(keys) == len(set(keys)), f"entries={len(keys)}")
    matches = [e for e in entries if e.get("pageID") == page_id]
    if not matches:
        gate.add("guide.entry", not require, f"no entry for {page_id} in {source}", required=require)
        return
    gate.require("guide.entry.unique", len(matches) == 1, f"entries for page: {len(matches)}")
    entry = matches[0]
    target = page["targets"].get(entry.get("locale"))
    if not gate.require("guide.entry.locale", isinstance(target, dict), f"entry locale={entry.get('locale')}"):
        return
    edition = page["id"] if page.get("sourceMode") != "per_target" else target.get("editionId")
    gate.require("guide.entry.status", entry.get("status") == "available", f"status={entry.get('status')}")
    gate.require("guide.entry.edition", entry.get("editionId") == edition,
                 f"entry={entry.get('editionId')} page={edition}")
    identity = target.get("sourceIdentitySha256") if page.get("sourceMode") == "per_target" else page.get("sourceIdentitySha256")
    gate.require("guide.entry.identity", entry.get("sourceIdentitySha256") == identity,
                 f"entry={str(entry.get('sourceIdentitySha256'))[:16]} page={str(identity)[:16]}")
    gate.require("guide.entry.release", entry.get("releasePackageJsonSha256") == target.get("releasePackageJsonSha256"),
                 f"entry={str(entry.get('releasePackageJsonSha256'))[:16]} live={str(target.get('releasePackageJsonSha256'))[:16]}")
    status, guide_raw = get(origin + str(entry.get("path")))
    if not gate.require("guide.bytes.http", status == 200, f"GET {entry.get('path')} -> {status}"):
        return
    gate.require("guide.bytes.size", len(guide_raw) == entry.get("bytes"),
                 f"bytes={len(guide_raw)} entry={entry.get('bytes')}")
    gate.require("guide.bytes.hash", sha(guide_raw) == entry.get("sha256"),
                 f"live {sha(guide_raw)[:16]} vs entry {str(entry.get('sha256'))[:16]}")
    guide = json.loads(guide_raw)
    gate.require("guide.guide", guide.get("id") == page_id and guide.get("week") == entry.get("week")
                 and bool(guide.get("sections")), f"id={guide.get('id')} week={guide.get('week')} sections={len(guide.get('sections') or [])}")


def check_page_title(gate: Gate, origin: str, page: dict, locale: str = "zh-Hans") -> None:
    status, html = get(origin + f"/pages/{page['id']}/{locale}/index.html")
    if not gate.require("page.http", status == 200, f"GET page html -> {status}"):
        return
    text = html.decode("utf-8", "replace")
    gate.require("page.title", page.get("title", "") in text,
                 f"catalog title {page.get('title')!r} not found in rendered page html")


def main() -> int:
    args = parse_args()
    origin = args.origin.rstrip("/")
    page_id = args.page_id
    gate = Gate()
    status, catalog_raw = get(origin + "/multilingual-v5.json")
    if not gate.require("catalog.http", status == 200, f"GET /multilingual-v5.json -> {status}"):
        return finish(gate, args, origin, page_id, None)
    catalog = json.loads(catalog_raw)
    page, _ = check_catalog(gate, catalog, page_id)
    if page is None:
        return finish(gate, args, origin, page_id, catalog)
    status, reference_raw = get(origin + f"/english-reference/{page_id}.json")
    reference = json.loads(reference_raw) if status == 200 else None
    gate.require("reference.http", reference is not None, f"GET /english-reference/{page_id}.json -> {status}")
    if reference is not None:
        gate.require("reference.identity",
                     reference.get("schemaVersion") == "sermon-published-english-reference-v1"
                     and reference.get("reviewState") == "human_approved"
                     and reference.get("pageId") == page_id
                     and reference.get("sourceIdentitySha256") == page.get("sourceIdentitySha256"),
                     f"schema={reference.get('schemaVersion')} review={reference.get('reviewState')}")
        gate.require("reference.locales", set(reference.get("targets") or {}) == set(page["targets"]),
                     f"targets={sorted(reference.get('targets') or {})}")
    for locale in sorted(page["targets"]):
        check_locale(gate, origin, page, locale, reference)
    check_alignment(gate, origin, page, catalog, args.require_alignment, not args.skip_alignment_drift, args.max_drift)
    check_guide(gate, origin, page, page_id, args.guide_manifest, args.require_guide)
    check_page_title(gate, origin, page)
    return finish(gate, args, origin, page_id, catalog)


def finish(gate: Gate, args: argparse.Namespace, origin: str, page_id: str, catalog: dict | None) -> int:
    report = {
        "schemaVersion": "sentence-first-publish-gate-v1",
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "origin": origin,
        "pageId": page_id,
        "catalogSha256": sha(json.dumps(catalog, sort_keys=True, separators=(",", ":")).encode()) if catalog else None,
        "status": "fail" if gate.failed else "pass",
        "failed": [c["check"] for c in gate.failed],
        "checks": gate.checks,
    }
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("schemaVersion", "origin", "pageId", "status", "failed")},
                     ensure_ascii=False))
    if gate.failed:
        for check in gate.failed:
            print(f"FAIL {check['check']}: {check['detail']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
