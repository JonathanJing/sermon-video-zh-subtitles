#!/usr/bin/env python3
"""Build a bounded public Firebase snapshot from local four-layer evidence.

This is a read-only adapter. It never upgrades a production package or deploys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts import four_layer_progress as progress


SCHEMA = "sermon-public-tracker-snapshot-v1"
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
MAX_BYTES = 512 * 1024


def read_json(path: Path | None) -> dict | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def https_url(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    parts = urlsplit(value)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    return value if len(value) <= 2048 else None


def public_source_url(value: str | None) -> str | None:
    safe = https_url(value)
    if not safe:
        return None
    host = (urlsplit(safe).hostname or "").lower()
    parts = urlsplit(safe)
    return safe if (host == "marinerschurch.org" or host.endswith(".marinerschurch.org")) \
        and not parts.query and not parts.fragment else None


def public_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if "T" in value else None


def video_id(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    candidate = None
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        candidate = parse_qs(parts.query).get("v", [None])[0]
    elif host == "youtu.be":
        candidate = parts.path.lstrip("/").split("/", 1)[0]
    return candidate if candidate and VIDEO_ID.fullmatch(candidate) else None


def source_summary(monitor: dict | None, previous_source_state: dict | None,
                   source_page_url: str | None, service_date: str | None) -> tuple[dict, dict]:
    if source_page_url and not https_url(source_page_url):
        raise ValueError("source page URL must be HTTPS")
    if monitor and service_date and monitor.get("sunday") != service_date:
        raise ValueError("source monitor date does not match service date")
    selected = (monitor or {}).get("selectedSource") or {}
    found = (monitor or {}).get("status") == "source_detected"
    url = https_url(selected.get("url")) if found else None
    current_id = video_id(url)
    previous_source = previous_source_state or {}
    previous_id = previous_source.get("videoId")
    if not found:
        change = "not_detected" if monitor else "not_checked"
    elif not current_id:
        change = "video_id_unknown"
    elif not previous_id:
        change = "first_seen"
    else:
        change = ("updated" if previous_id != current_id else
                  previous_source.get("videoChange") if previous_source.get("videoChange") in {"first_seen", "updated"}
                  else "unchanged")
    changed_at = ((monitor or {}).get("checkedAt") if change in {"first_seen", "updated"}
                  and current_id != previous_id else previous_source.get("lastChangeAt"))
    raw_monitor_status = (monitor or {}).get("status", "not_checked")
    monitor_status = raw_monitor_status if raw_monitor_status in {
        "source_detected", "fallback", "not_checked"} else "unknown"
    raw_video_state = selected.get("state") if found else None
    video_state = raw_video_state if raw_video_state in {
        "live", "upcoming", "was_live", "available", "manual_available"} else None
    public = {
        "inputPageUrl": public_source_url(source_page_url),
        "inputPageConfigured": bool(source_page_url),
        "monitorStatus": monitor_status,
        "checkedAt": public_timestamp((monitor or {}).get("checkedAt")),
        "videoPresent": bool(found and url),
        "videoState": video_state,
        "videoChange": change,
        "lastChangeAt": public_timestamp(changed_at),
    }
    private = {"videoId": current_id or previous_id, "videoChange": change,
               "lastChangeAt": changed_at}
    return public, private


def verified_file(receipt: dict | None, path: str, *, require_range: bool = False) -> bool:
    if not receipt or receipt.get("status") not in {"pass", "passed"} and receipt.get("passed") is not True:
        return False
    for item in receipt.get("files", []):
        if item.get("path") != path:
            continue
        if item.get("hashMatch") is False or item.get("status") not in {None, 200}:
            return False
        if require_range:
            range_record = item.get("range") or {}
            return range_record.get("status") == 206 and range_record.get("bytesMatch") is True
        return True
    return False


def fingerprint_status(binding: dict | None, page_id: str, audio_shas: set[str],
                       public_root: Path | None, receipt: dict | None) -> dict:
    if not isinstance(binding, dict):
        return {"status": "not_generated", "trackSha256": None}
    path = str(binding.get("indexUrl") or "")
    sha = str(binding.get("indexSha256") or "")
    track_sha = str(binding.get("trackSha256") or "")
    match = re.fullmatch(r"/fingerprints/([a-f0-9]{16})-landmarks\.json", path)
    if (not match or match.group(1) != sha[:16]
            or not re.fullmatch(r"[a-f0-9]{64}", sha)
            or not re.fullmatch(r"[a-f0-9]{64}", track_sha)
            or binding.get("pageId") != page_id):
        return {"status": "binding_invalid", "trackSha256": None}
    if track_sha not in audio_shas:
        return {"status": "binding_invalid", "trackSha256": track_sha}
    if not public_root:
        return {"status": "declared_unchecked", "trackSha256": track_sha}
    index = public_root / path.lstrip("/")
    if not index.is_file() or index.is_symlink() or not index.resolve().is_relative_to(public_root.resolve()):
        return {"status": "index_missing", "trackSha256": track_sha}
    if hashlib.sha256(index.read_bytes()).hexdigest() != sha:
        return {"status": "hash_mismatch", "trackSha256": track_sha}
    status = "http_verified" if verified_file(receipt, path.lstrip("/")) else "generated_local"
    return {"status": status, "trackSha256": track_sha}


def local_fingerprint(week: dict | None, public_root: Path | None, receipt: dict | None) -> dict:
    tracks = (week or {}).get("tracks") or []
    return fingerprint_status((week or {}).get("audioFingerprint"), (week or {}).get("id"),
                              {track.get("sha256") for track in tracks}, public_root, receipt)


def catalog_week(catalog: dict | None, page_id: str) -> dict | None:
    matches = [week for week in (catalog or {}).get("weeks", [])
               if isinstance(week, dict) and week.get("id") == page_id]
    if len(matches) > 1:
        raise ValueError("duplicate page ID in catalog")
    return matches[0] if matches else None


def release_packages(paths: list[Path], page_id: str, locales: list[str]) -> dict:
    result = {}
    for path in paths:
        package = read_json(path)
        if package.get("schemaVersion") != "sermon-target-language-release-package-v1":
            raise ValueError(f"unsupported release package: {path}")
        locale = package.get("targetLocale")
        if package.get("pageId") != page_id or locale not in locales or locale in result:
            raise ValueError(f"release package identity mismatch or duplicate: {path}")
        sha = lambda value: isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value)
        verification = package.get("httpVerification") or {}
        assets = package.get("assets")
        if (package.get("sourceLocale") != "en" or package.get("contentLocale") != locale
                or package.get("status") not in {"candidate", "published_http_verified", "withdrawn"}
                or package.get("contentStatus") not in {"draft", "machine_reviewed", "human_reviewed"}
                or package.get("audioStatus") not in {"unavailable", "candidate", "human_reviewed"}
                or package.get("audioLocale") not in {None, locale}
                or not sha(package.get("targetLanguageCandidateJsonSha256"))
                or (package.get("targetLanguageAudioPackageJsonSha256") is not None
                    and not sha(package.get("targetLanguageAudioPackageJsonSha256")))
                or not isinstance(assets, list) or not assets
                or any(not isinstance(asset, dict) or asset.get("role") not in {
                    "catalog", "content", "audio", "captions", "download", "page", "other"}
                       or not sha(asset.get("sha256")) or not isinstance(asset.get("path"), str)
                       or not asset["path"] for asset in assets)
                or verification.get("status") not in {"not_run", "pass", "fail"}
                or (verification.get("status") == "pass"
                    and not sha(verification.get("evidenceSha256")))):
            raise ValueError(f"incomplete or invalid release package evidence: {path}")
        if package["status"] == "published_http_verified" and (
                verification["status"] != "pass" or package["contentStatus"] != "human_reviewed"):
            raise ValueError(f"published release package lacks review or HTTP evidence: {path}")
        result[locale] = package
    return result


def fingerprint_bindings(paths: list[Path], page_id: str, locales: list[str]) -> dict:
    result = {}
    for path in paths:
        binding = read_json(path)
        locale = binding.get("targetLocale")
        if (binding.get("schemaVersion") != "sermon-tracker-fingerprint-v1"
                or binding.get("pageId") != page_id or locale not in locales or locale in result):
            raise ValueError(f"fingerprint evidence identity mismatch or duplicate: {path}")
        result[locale] = binding
    return result


def locale_delivery(locale: str, package: dict | None, week: dict | None,
                    public_root: Path | None, receipt: dict | None,
                    site_url: str | None, page_id: str,
                    binding: dict | None = None) -> dict:
    if package and package.get("status") == "withdrawn":
        return {"pageStatus": "withdrawn", "pageUrl": None,
                "voiceStatus": "withdrawn", "voicePublished": False,
                "fingerprint": {"status": "withdrawn", "trackSha256": None},
                "origin": "canonical_release_package"}
    if binding:
        audio_shas = {asset.get("sha256") for asset in (package or {}).get("assets", [])
                      if asset.get("role") == "audio"}
        fingerprint = fingerprint_status(binding, page_id, audio_shas, public_root, receipt)
    else:
        fingerprint = local_fingerprint(week, public_root, receipt) if package is None and locale == "zh-Hans" else {
            "status": "not_generated", "trackSha256": None}
    if package:
        http_pass = package.get("httpVerification", {}).get("status") == "pass"
        published = package.get("status") == "published_http_verified" and http_pass
        audio_status = package.get("audioStatus", "unknown")
        return {
            "pageStatus": "published_http_verified" if published else "release_candidate",
            "pageUrl": f"{site_url}/?week={page_id}&lang={locale}" if published and site_url else None,
            "voiceStatus": audio_status,
            "voicePublished": published and audio_status == "human_reviewed"
                              and any(a.get("role") == "audio" for a in package.get("assets", [])),
            "fingerprint": fingerprint,
            "origin": "canonical_release_package",
        }
    poc_tracks = [track for track in (week or {}).get("tracks", [])
                  if isinstance(track, dict) and track.get("locale") == locale
                  and track.get("scope") == "machine_poc_not_production"]
    if week and poc_tracks:
        if len(poc_tracks) > 1:
            raise ValueError(f"duplicate POC track for {locale}")
        track = poc_tracks[0] if poc_tracks else None
        media_path = str((track or {}).get("audioUrl") or "").lstrip("/")
        audio_http = bool(media_path and verified_file(receipt, media_path, require_range=True))
        catalog_http = verified_file(receipt, "weekly.json")
        review = str(week.get("contentReview") or "")
        return {
            "pageStatus": "poc_catalog_http_verified" if catalog_http else "poc_catalog_local",
            "pageUrl": f"{site_url}/?week={page_id}" if site_url and catalog_http else None,
            "voiceStatus": "poc_track_http_verified" if audio_http else
                           ("poc_track_listed" if track else "not_generated"),
            "voicePublished": False,
            "fingerprint": fingerprint,
            "pocCandidateStatus": review if review in {
                "machine_review_pass_human_review_pending", "candidate", "human_reviewed"
            } else "unknown",
            "pocScreeningStatus": (track or {}).get("machineScreening", {}).get("status")
                                  if (track or {}).get("machineScreening", {}).get("status")
                                  in {"pass", "requires_review", "fail"} else "unknown",
            "pocVoiceReview": "pending" if (track or {}).get("voiceSampleReview") == "pending"
                              else "unknown",
            "origin": "dev_poc_catalog",
        }
    if week and week.get("humanApproval") is False:
        return {"pageStatus": "not_generated", "pageUrl": None,
                "voiceStatus": "not_generated", "voicePublished": False,
                "fingerprint": fingerprint, "origin": "no_release_evidence"}
    if locale == "zh-Hans" and week:
        tracks = week.get("tracks") or []
        track = next((t for t in tracks if t.get("sha256") == fingerprint.get("trackSha256")), None)
        if track is None and tracks:
            track = tracks[0]
        media_path = str((track or {}).get("audioUrl") or "").lstrip("/")
        audio_http = bool(media_path and verified_file(receipt, media_path, require_range=True))
        return {
            "pageStatus": "legacy_catalog_http_verified" if verified_file(receipt, "weekly.json")
                          else "legacy_catalog_local",
            "pageUrl": f"{site_url}/?week={page_id}" if site_url and verified_file(receipt, "weekly.json") else None,
            "voiceStatus": "legacy_track_http_verified" if audio_http else
                           ("legacy_track_listed" if track else "not_generated"),
            "voicePublished": False,
            "fingerprint": fingerprint,
            "origin": "legacy_catalog_v1",
        }
    return {"pageStatus": "not_generated", "pageUrl": None, "voiceStatus": "not_generated",
            "voicePublished": False, "fingerprint": fingerprint, "origin": "no_release_evidence"}


def build_snapshot(ledger: dict, *, monitor: dict | None = None,
                   previous_source_state: dict | None = None,
                   source_page_url: str | None = None, service_date: str | None = None,
                   catalog: dict | None = None, public_root: Path | None = None,
                   receipt: dict | None = None, packages: dict | None = None,
                   fingerprints: dict | None = None,
                   site_url: str | None = None) -> dict:
    if site_url and not https_url(site_url):
        raise ValueError("site URL must be HTTPS")
    if catalog and catalog.get("schemaVersion") != "sermon-weekly-catalog-v1":
        raise ValueError("only validated legacy catalog v1 is supported; use release packages for new locales")
    page_id = ledger["pageId"]
    week = catalog_week(catalog, page_id)
    report = progress.summary(ledger)
    source, _private_source = source_summary(monitor, previous_source_state,
                                             source_page_url, service_date)
    def public_row(row: dict) -> dict:
        return {key: row[key] for key in ("layer", "locale", "complete", "total", "percent")}
    locales = []
    for locale in ledger["locales"]:
        layers = {str(layer): public_row(next(row for row in report["rows"]
                                         if row["layer"] == layer and row["locale"] == locale))
                  for layer in (2, 3, 4)}
        delivery = locale_delivery(locale, (packages or {}).get(locale), week,
                                   public_root, receipt, site_url, page_id,
                                   (fingerprints or {}).get(locale))
        delivery["fingerprint"] = {"status": delivery["fingerprint"]["status"]}
        locales.append({"locale": locale, "layers": layers,
                        "delivery": delivery,
                        "acceptance": {kind: {"status": ledger["acceptance"][locale][kind]["status"]}
                                       for kind in ("device", "venue")}})
    steps = [{"id": key, "layer": step["layer"], "locale": step["locale"],
              "status": step["status"], "doneUnits": step["doneUnits"],
              "totalUnits": step["totalUnits"]}
             for key, step in ledger["steps"].items()]
    snapshot = {
        "schemaVersion": SCHEMA,
        "pageId": page_id,
        "target": ledger["target"],
        "serviceDate": service_date,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ledgerUpdatedAt": ledger["updatedAt"],
        "source": source,
        "progress": {"complete": report["complete"], "total": report["total"],
                     "blockerCount": len(report["blockers"]),
                     "blockedStepIds": [item.split(":", 1)[0] for item in report["blockers"]],
                     "missingEstimateCount": len(report["missingEstimates"]),
                     "activeUnits": report["activeUnits"],
                     "earliestContinuousEta": report["earliestContinuousEta"],
                     "remainingSerialMinutes": report["remainingSerialMinutes"]},
        "sharedLayer1": public_row(next(row for row in report["rows"] if row["layer"] == 1)),
        "locales": locales,
        "steps": steps,
        "readOnly": True,
    }
    if len(json.dumps(snapshot, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise ValueError("tracker snapshot exceeds size limit")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source-monitor", type=Path)
    parser.add_argument("--source-state", type=Path,
                        help="Private local video-ID comparison state; never publish this file")
    parser.add_argument("--source-page-url")
    parser.add_argument("--service-date")
    parser.add_argument("--catalog", type=Path)
    parser.add_argument("--public-root", type=Path)
    parser.add_argument("--http-receipt", type=Path)
    parser.add_argument("--release-package", type=Path, action="append", default=[])
    parser.add_argument("--fingerprint-evidence", type=Path, action="append", default=[])
    parser.add_argument("--site-url")
    args = parser.parse_args()
    private_state_path = args.source_state or args.out.with_name("source-video-state.private.json")
    private_source_state = read_json(private_state_path) if private_state_path.exists() else None
    ledger = progress.load(args.ledger)
    if private_source_state and (private_source_state.get("pageId") != ledger["pageId"]
                                 or private_source_state.get("serviceDate") != args.service_date):
        private_source_state = None
    packages = release_packages(args.release_package, ledger["pageId"], ledger["locales"])
    fingerprints = fingerprint_bindings(args.fingerprint_evidence, ledger["pageId"], ledger["locales"])
    monitor = read_json(args.source_monitor)
    snapshot = build_snapshot(ledger, monitor=monitor,
                              previous_source_state=private_source_state,
                              source_page_url=args.source_page_url, service_date=args.service_date,
                              catalog=read_json(args.catalog), public_root=args.public_root,
                              receipt=read_json(args.http_receipt), packages=packages,
                              fingerprints=fingerprints,
                              site_url=args.site_url)
    progress.save(args.out, snapshot)
    if monitor:
        _, next_private_state = source_summary(monitor, private_source_state,
                                                args.source_page_url, args.service_date)
        next_private_state["pageId"] = ledger["pageId"]
        next_private_state["serviceDate"] = args.service_date
        progress.save(private_state_path, next_private_state)
    print(json.dumps({"pageId": snapshot["pageId"], "source": snapshot["source"]["videoChange"],
                      "complete": snapshot["progress"]["complete"],
                      "total": snapshot["progress"]["total"], "out": str(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
