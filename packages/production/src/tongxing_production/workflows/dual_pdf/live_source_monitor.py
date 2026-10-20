#!/usr/bin/env python3
"""Discover Sunday live-source candidates and choose the 11:30 caption input."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import quote
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.observability import log_event, stable_hash, url_summary  # noqa: E402
from backend.cloud import access_secret, read_gcs_text, write_gcs_text  # noqa: E402
from scripts import youtube_data_api  # noqa: E402


DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_MARINERS_ONLINE_URL = "https://www.marinerschurch.org/irvine/"
DEFAULT_YOUTUBE_STREAMS_URL = "https://www.youtube.com/@marinerschurch/streams"
DEFAULT_YOUTUBE_LIVE_URL = "https://www.youtube.com/@marinerschurch/live"
USABLE_STATES = {"live", "upcoming", "was_live", "available", "manual_available"}
YOUTUBE_STREAM_STATES = {"live", "upcoming", "was_live"}
SERVICE_ORDER = ["830", "1000", "manual"]
SATURDAY_SERVICE_ORDER = ["sat400", "sat530", "manual"]
NOTIFIABLE_STATUSES = {"source_detected", "fallback"}


@dataclass(frozen=True)
class SourceCandidate:
    kind: str
    service: str
    url: str
    state: str
    title: str | None = None
    scheduled_start_at: str | None = None
    actual_start_at: str | None = None
    same_sermon_confidence: float | None = None
    evidence: str | None = None
    error: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "service": self.service,
            "state": self.state,
            "title": self.title,
            "url": self.url,
            "urlHash": stable_hash(self.url) if self.url else None,
            "scheduledStartAt": self.scheduled_start_at,
            "actualStartAt": self.actual_start_at,
            "sameSermonConfidence": self.same_sermon_confidence,
            "evidence": self.evidence,
            "error": self.error,
        }


def main() -> int:
    args = parse_args()
    previous_state = read_state(args.state_file)
    report = run_monitor(args)
    if args.post_generate:
        report["generationPost"] = post_generation_request(report, args)
    notification = build_notification(report, previous_state)
    if notification["shouldNotify"] and args.notify_webhook_url:
        notification["delivery"] = send_webhook_notification(args.notify_webhook_url, notification)
    elif notification["shouldNotify"] and getattr(args, "notify_sendgrid_secret", None):
        notification["delivery"] = send_sendgrid_notification(
            args.notify_sendgrid_secret,
            getattr(args, "notify_recipients_secret", None),
            getattr(args, "notify_sender_secret", None),
            notification,
        )
    report["notification"] = notification
    write_state(args.state_file, report, previous_state, notification)
    out = resolve_repo_path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    log_event(
        "live_source_monitor_completed",
        component="live-source-monitor",
        sunday=args.sunday,
        status=report["status"],
        selectedService=report.get("selectedSource", {}).get("service"),
        selectedKind=report.get("selectedSource", {}).get("kind"),
        operatorAlert=report.get("operatorAlert"),
        candidateCount=len(report.get("candidates", [])),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"source_detected", "fallback"} else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument(
        "--service",
        default="auto",
        choices=["auto", "830", "1000", "sat-auto", "sat400", "sat530"],
        help="Which service window to evaluate. auto checks Sunday 8:30 then 10:00; sat-auto checks Saturday 4:00 then 5:30.",
    )
    parser.add_argument("--expected-title", help="Expected sermon title for same-sermon confidence.")
    parser.add_argument("--manual-url", action="append", default=[], help="Authorized/manual source URL fallback.")
    parser.add_argument("--mariners-online-url", default=DEFAULT_MARINERS_ONLINE_URL)
    parser.add_argument("--youtube-streams-url", default=DEFAULT_YOUTUBE_STREAMS_URL)
    parser.add_argument("--youtube-live-url", default=DEFAULT_YOUTUBE_LIVE_URL)
    parser.add_argument("--fixture-json", type=Path, help="Offline fixture containing source candidates.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/live-source-monitor/report.json"))
    parser.add_argument("--state-file", default="artifacts/live-source-monitor/state.json")
    parser.add_argument("--notify-webhook-url", help="Operator notification webhook URL. Use env or secrets in production.")
    parser.add_argument("--notify-sendgrid-secret", help="Secret containing a SendGrid API key.")
    parser.add_argument("--notify-recipients-secret", help="Secret containing comma-separated or JSON recipient emails.")
    parser.add_argument("--notify-sender-secret", help="Secret containing the verified sender email.")
    parser.add_argument("--youtube-api-key-secret", help="Secret Manager resource/name containing a YouTube Data API key.")
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--now", help="Override current time, ISO-8601.")
    parser.add_argument("--min-confidence", type=float, default=0.70)
    parser.add_argument("--operator-alert-time", default="09:58", help="HH:MM local time for no-source alert.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8080")
    parser.add_argument("--post-generate", action="store_true", help="POST the selected generationRequest to backend.")
    parser.add_argument("--admin-token", help="Operator bearer token for backend generation endpoint.")
    parser.add_argument("--internal-task-token", help="Internal task token for scheduler/task calls.")
    args = parser.parse_args()
    validate_sunday(args.sunday)
    return args


def run_monitor(args: argparse.Namespace) -> dict[str, Any]:
    checked_at = now_iso(args.now, args.timezone)
    candidates = load_candidates(args, checked_at)
    decision = choose_source(
        candidates,
        service=args.service,
        min_confidence=args.min_confidence,
    )
    operator_alert = should_alert_operator(
        selected=decision,
        now_value=checked_at,
        alert_time=args.operator_alert_time,
        timezone=args.timezone,
    )
    status = "source_detected" if decision else "fallback"
    fallback_reason = fallback_reason_for(decision, operator_alert)
    selected = decision or operator_audio_candidate(args.sunday, checked_at, fallback_reason)
    generation_request = generation_request_for(selected, args.sunday)

    return {
        "schemaVersion": 1,
        "status": status,
        "sunday": args.sunday,
        "checkedAt": checked_at,
        "timezone": args.timezone,
        "selectedSource": selected.to_public_dict(),
        "operatorAlert": operator_alert,
        "fallbackReason": fallback_reason,
        "generationRequest": generation_request,
        "candidates": [candidate.to_public_dict() for candidate in candidates],
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def load_candidates(args: argparse.Namespace, checked_at: str | None = None) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    fixture_sources = getattr(args, "fixture_sources", None)
    if fixture_sources is not None:
        candidates.extend(candidates_from_fixture({"sources": fixture_sources}, args.expected_title))
    elif args.fixture_json:
        fixture = json.loads(resolve_repo_path(args.fixture_json).read_text(encoding="utf-8"))
        candidates.extend(candidates_from_fixture(fixture, args.expected_title))
    else:
        candidates.extend(fetch_default_candidates(args, checked_at))
    for index, manual_url in enumerate(args.manual_url, start=1):
        candidates.append(
            SourceCandidate(
                kind="manual-url",
                service="manual",
                url=manual_url,
                state="manual_available",
                title=f"Manual authorized source {index}",
                same_sermon_confidence=1.0,
                evidence="operator-provided",
            )
        )
    return candidates


def candidates_from_fixture(fixture: dict[str, Any], expected_title: str | None) -> list[SourceCandidate]:
    sources = fixture.get("sources")
    if not isinstance(sources, list):
        raise SystemExit("fixture JSON must include sources[]")
    candidates = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        title = string_or_none(item.get("title"))
        confidence = item.get("sameSermonConfidence")
        if confidence is None:
            confidence = score_same_sermon(title, expected_title)
        candidates.append(
            SourceCandidate(
                kind=str(item.get("kind") or "fixture"),
                service=normalize_service(item.get("service")),
                url=str(item.get("url") or ""),
                state=str(item.get("state") or "unknown"),
                title=title,
                scheduled_start_at=string_or_none(item.get("scheduledStartAt") or item.get("scheduled_start_at")),
                actual_start_at=string_or_none(item.get("actualStartAt") or item.get("actual_start_at")),
                same_sermon_confidence=clamp_confidence(confidence),
                evidence=string_or_none(item.get("evidence")),
                error=string_or_none(item.get("error")),
            )
        )
    return candidates


def fetch_default_candidates(args: argparse.Namespace, checked_at: str | None = None) -> list[SourceCandidate]:
    fetcher = default_fetcher
    services = SATURDAY_SERVICE_ORDER[:2] if str(args.service).startswith("sat") else ["830", "1000"]
    candidates: list[SourceCandidate] = []
    for service in services:
        target_date = target_service_date(args.sunday, service)
        candidates.append(
            fetch_candidate(
                kind="youtube-streams",
                service=service,
                url=args.youtube_streams_url,
                expected_title=args.expected_title,
                fetcher=fetcher,
                target_date=target_date,
                timezone=args.timezone,
            )
        )
        candidates.append(
            fetch_candidate(
                kind="youtube-live",
                service=service,
                url=args.youtube_live_url,
                expected_title=args.expected_title,
                fetcher=fetcher,
                target_date=target_date,
                timezone=args.timezone,
            )
        )
        if not service.startswith("sat"):
            candidates.append(
                fetch_candidate(
                    kind="mariners-online",
                    service=service,
                    url=args.mariners_online_url,
                    expected_title=args.expected_title,
                    fetcher=fetcher,
                    target_date=target_date,
                    timezone=args.timezone,
                )
            )
    secret_name = getattr(args, "youtube_api_key_secret", None)
    if not secret_name:
        return candidates
    try:
        api_key = access_secret(secret_name)
    except Exception:
        return candidates
    cache: dict[str, dict[str, Any] | None] = {}
    enriched = [enrich_candidate_with_data_api(item, api_key, args.timezone, cache) for item in candidates]
    deduped: dict[tuple[str, str], SourceCandidate] = {}
    for item in enriched:
        key = (item.url, item.service)
        current = deduped.get(key)
        if current is None or "youtube-data-api-v3" in str(item.evidence):
            deduped[key] = item
    return list(deduped.values())


def enrich_candidate_with_data_api(
    candidate: SourceCandidate,
    api_key: str,
    timezone: str,
    cache: dict[str, dict[str, Any] | None] | None = None,
) -> SourceCandidate:
    video_id = youtube_video_id_from_url(candidate.url)
    if not video_id:
        return candidate
    metadata_cache = cache if cache is not None else {}
    if video_id not in metadata_cache:
        try:
            metadata_cache[video_id] = youtube_data_api.video_metadata(video_id, api_key=api_key)
        except Exception:
            metadata_cache[video_id] = None
    metadata = metadata_cache[video_id]
    if not metadata:
        return candidate
    observed = metadata.get("actual_start_time") or metadata.get("scheduled_start_time")
    service = classify_service_from_start_time(observed, timezone) or candidate.service
    state = state_from_youtube_metadata(metadata)
    evidence = "+".join(filter(None, [candidate.evidence, "youtube-data-api-v3-service-time"]))
    return replace(
        candidate,
        service=service,
        state=state,
        title=string_or_none(metadata.get("title")) or candidate.title,
        url=string_or_none(metadata.get("webpage_url")) or candidate.url,
        scheduled_start_at=local_iso_from_api_time(metadata.get("scheduled_start_time"), timezone),
        actual_start_at=local_iso_from_api_time(metadata.get("actual_start_time"), timezone),
        evidence=evidence,
    )


def classify_service_from_start_time(value: Any, timezone: str) -> str | None:
    observed = parse_api_datetime(value, timezone)
    if observed is None:
        return None
    targets = (
        ((16, 0), "sat400"),
        ((17, 30), "sat530"),
    ) if observed.weekday() == 5 else (
        ((8, 30), "830"),
        ((10, 0), "1000"),
    ) if observed.weekday() == 6 else ()
    if not targets:
        return None
    observed_minutes = observed.hour * 60 + observed.minute
    (_, service), distance = min(
        (
            ((target, service), abs(observed_minutes - target[0] * 60 - target[1]))
            for target, service in targets
        ),
        key=lambda item: item[1],
    )
    return service if distance <= 75 else None


def parse_api_datetime(value: Any, timezone: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed.astimezone(ZoneInfo(timezone))


def local_iso_from_api_time(value: Any, timezone: str) -> str | None:
    parsed = parse_api_datetime(value, timezone)
    return parsed.isoformat() if parsed else None


def fetch_candidate(
    *,
    kind: str,
    service: str,
    url: str,
    expected_title: str | None,
    fetcher: Callable[[str], str],
    target_date: date | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> SourceCandidate:
    if kind == "youtube-live":
        page_html = None
        try:
            page_html = fetcher(url)
        except Exception:
            page_html = None
        return youtube_live_candidate_from_url(
            service=service,
            url=url,
            page_title=extract_title(page_html) if page_html else kind,
            page_html=page_html,
            expected_title=expected_title,
            target_date=target_date,
            timezone=timezone,
        )
    try:
        html = fetcher(url)
    except Exception as exc:
        return SourceCandidate(
            kind=kind,
            service=service,
            url=url,
            state="unavailable",
            same_sermon_confidence=0.0,
            error=str(exc)[:160],
        )
    title = extract_title(html) or kind
    state = infer_state(html)
    if kind == "youtube-streams":
        youtube_candidate = youtube_stream_candidate_from_page(
            service=service,
            page_html=html,
            page_url=url,
            page_title=title,
            page_state=state,
            expected_title=expected_title,
            fetcher=fetcher,
            target_date=target_date,
            timezone=timezone,
        )
        if youtube_candidate:
            return youtube_candidate
        return SourceCandidate(
            kind="youtube-streams",
            service=service,
            url=url,
            state="unavailable",
            title=title,
            same_sermon_confidence=0.0,
            evidence="streams-page-validation-failed",
            error="streams tab did not expose target live/upcoming/was_live stream",
        )
    return SourceCandidate(
        kind=kind,
        service=service,
        url=url,
        state=state,
        title=title,
        same_sermon_confidence=score_same_sermon(title, expected_title),
        evidence="fetched-page",
    )


def youtube_stream_candidate_from_page(
    *,
    service: str,
    page_html: str,
    page_url: str,
    page_title: str,
    page_state: str,
    expected_title: str | None,
    fetcher: Callable[[str], str],
    target_date: date | None,
    timezone: str,
) -> SourceCandidate | None:
    urls = extracted_youtube_watch_urls(page_html)
    errors: list[str] = []
    urls.extend(url for url in youtube_stream_watch_urls_from_tab(page_url) if url not in urls)
    for watch_url in urls[:8]:
        try:
            video_html = fetcher(watch_url)
        except Exception as exc:
            errors.append(str(exc)[:80])
            continue
        metadata = youtube_video_metadata(watch_url)
        title = string_or_none(metadata.get("title")) if metadata else None
        state = state_from_youtube_metadata(metadata) if metadata else infer_state(video_html)
        actual_start = local_iso_from_metadata(metadata, timezone) if metadata else None
        if state in YOUTUBE_STREAM_STATES and metadata_is_target_service(metadata, target_date, timezone):
            return SourceCandidate(
                kind="youtube-streams",
                service=service,
                url=watch_url,
                state=state,
                title=title or extract_title(video_html) or page_title,
                actual_start_at=actual_start,
                same_sermon_confidence=score_same_sermon(title or extract_title(video_html) or page_title, expected_title),
                evidence="yt-dlp-watch-metadata",
            )
    if urls:
        return SourceCandidate(
            kind="youtube-streams",
            service=service,
            url=page_url,
            state="unavailable",
            title=page_title,
            same_sermon_confidence=0.0,
            evidence="watch-page-validation-failed",
            error="; ".join(errors[:2]) or "no extracted watch URL validated as live/upcoming/was_live",
        )
    if page_state in YOUTUBE_STREAM_STATES:
        return SourceCandidate(
            kind="youtube-streams",
            service=service,
            url=page_url,
            state=page_state,
            title=page_title,
            same_sermon_confidence=score_same_sermon(page_title, expected_title),
            evidence="fetched-page-no-watch-url",
        )
    return None


def youtube_live_candidate_from_url(
    *,
    service: str,
    url: str,
    page_title: str,
    expected_title: str | None,
    target_date: date | None,
    timezone: str,
    page_html: str | None = None,
) -> SourceCandidate:
    metadata = youtube_video_metadata(url)
    title = string_or_none(metadata.get("title")) if metadata else None
    state = state_from_youtube_metadata(metadata)
    actual_start = local_iso_from_metadata(metadata, timezone) if metadata else None
    video_id = youtube_video_id_from_url(str(metadata.get("webpage_url") or "")) if metadata else None
    if not video_id and metadata:
        video_id = string_or_none(metadata.get("id"))
    watch_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else url
    if state in YOUTUBE_STREAM_STATES and metadata_is_target_service(metadata, target_date, timezone):
        return SourceCandidate(
            kind="youtube-live",
            service=service,
            url=watch_url,
            state=state,
            title=title or page_title,
            actual_start_at=actual_start,
            same_sermon_confidence=score_same_sermon(title or page_title, expected_title),
            evidence="yt-dlp-channel-live-metadata",
        )
    live_watch_url = youtube_live_watch_url_from_channel(url)
    if live_watch_url:
        return SourceCandidate(
            kind="youtube-live",
            service=service,
            url=live_watch_url,
            state="live",
            title=title or page_title,
            same_sermon_confidence=score_same_sermon(title or page_title, expected_title),
            actual_start_at=actual_start,
            evidence="yt-dlp-channel-live-url",
        )
    return SourceCandidate(
        kind="youtube-live",
        service=service,
        url=url,
        state="unavailable",
        title=title or page_title,
        same_sermon_confidence=0.0,
        actual_start_at=actual_start,
        evidence="channel-live-validation-failed",
        error="channel live URL did not resolve to target live/upcoming/was_live stream",
    )


def youtube_live_watch_url_from_channel(url: str) -> str | None:
    info = youtube_extract_info(url, flat=True)
    if not isinstance(info, dict):
        return None
    direct_url = youtube_watch_url_from_entry(info)
    if direct_url:
        return direct_url
    entries = info.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                watch_url = youtube_watch_url_from_entry(entry)
                if watch_url:
                    return watch_url
    return None


def youtube_stream_watch_urls_from_tab(url: str) -> list[str]:
    info = youtube_extract_info(url, flat=True)
    if not isinstance(info, dict):
        return []
    entries = info.get("entries")
    if not isinstance(entries, list):
        return []
    urls: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        watch_url = youtube_watch_url_from_entry(entry)
        if watch_url and watch_url not in urls:
            urls.append(watch_url)
    return urls


def youtube_extract_info(url: str, *, flat: bool = False) -> dict[str, Any] | None:
    try:
        from yt_dlp import YoutubeDL  # type: ignore
    except ImportError:
        return youtube_extract_info_with_cli(url, flat=flat)
    try:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "js_runtimes": {"node": {}},
        }
        if flat:
            options.update({"extract_flat": True, "playlistend": 8})
        else:
            options["noplaylist"] = True
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None
    return info if isinstance(info, dict) else None


def youtube_extract_info_with_cli(url: str, *, flat: bool = False) -> dict[str, Any] | None:
    executable = shutil.which("yt-dlp")
    if not executable:
        return None
    command = [
        executable,
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
        "--quiet",
        "--js-runtimes",
        "node",
    ]
    if flat:
        command.extend(["--flat-playlist", "--playlist-end", "8"])
    else:
        command.append("--no-playlist")
    command.append(url)
    try:
        proc = subprocess.run(command, check=False, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return info if isinstance(info, dict) else None


def youtube_watch_url_from_entry(entry: dict[str, Any]) -> str | None:
    webpage_url = string_or_none(entry.get("webpage_url") or entry.get("url"))
    if webpage_url:
        video_id = youtube_video_id_from_url(webpage_url)
        if video_id:
            return f"https://www.youtube.com/watch?v={video_id}"
    video_id = string_or_none(entry.get("id"))
    if video_id and re.fullmatch(r"[-_A-Za-z0-9]{11}", video_id):
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def youtube_video_id_from_url(url: str) -> str | None:
    patterns = [
        r"(?:[?&]v=)([-_A-Za-z0-9]{11})",
        r"youtube\.com/live/([-_A-Za-z0-9]{11})",
        r"youtu\.be/([-_A-Za-z0-9]{11})",
        r"youtube\.com/embed/([-_A-Za-z0-9]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    if re.fullmatch(r"[-_A-Za-z0-9]{11}", url):
        return url
    return None


def youtube_video_metadata(url: str) -> dict[str, Any] | None:
    return youtube_extract_info(url, flat=False)


def state_from_youtube_metadata(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return "unavailable"
    live_status = str(metadata.get("live_status") or "")
    if live_status == "is_live" or metadata.get("is_live") is True:
        return "live"
    if live_status in {"is_upcoming", "not_yet_live"}:
        return "upcoming"
    if live_status in {"was_live", "post_live"} or metadata.get("was_live") is True:
        return "was_live"
    if metadata.get("media_type") == "livestream":
        return "was_live"
    return "available"


def metadata_is_target_service(metadata: dict[str, Any] | None, target_date: date | None, timezone: str) -> bool:
    if not metadata:
        return False
    if metadata.get("media_type") != "livestream" and not (
        metadata.get("was_live") is True or metadata.get("is_live") is True
    ):
        return False
    if target_date is None:
        return True
    observed = local_date_from_metadata(metadata, timezone)
    return observed == target_date


def local_iso_from_metadata(metadata: dict[str, Any] | None, timezone: str) -> str | None:
    timestamp = metadata_timestamp(metadata)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, ZoneInfo(timezone)).isoformat()


def local_date_from_metadata(metadata: dict[str, Any] | None, timezone: str) -> date | None:
    timestamp = metadata_timestamp(metadata)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, ZoneInfo(timezone)).date()


def metadata_timestamp(metadata: dict[str, Any] | None) -> int | None:
    if not metadata:
        return None
    for key in ("release_timestamp", "timestamp", "available_at"):
        value = metadata.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    upload_date = str(metadata.get("upload_date") or "")
    if re.fullmatch(r"\d{8}", upload_date):
        parsed = date.fromisoformat(f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}")
        return int(datetime.combine(parsed, time.min).timestamp())
    return None


def target_service_date(sunday: str, service: str) -> date | None:
    try:
        sunday_date = date.fromisoformat(sunday)
    except ValueError:
        return None
    if str(service).startswith("sat"):
        return sunday_date - timedelta(days=1)
    return sunday_date


def choose_source(
    candidates: list[SourceCandidate],
    *,
    service: str,
    min_confidence: float,
) -> SourceCandidate | None:
    if service in {"830", "1000", "sat400", "sat530"}:
        order = [service]
    elif service in {"sat-auto", "saturday"}:
        order = SATURDAY_SERVICE_ORDER
    else:
        order = SERVICE_ORDER
    for service_id in order:
        matching = [
            candidate
            for candidate in candidates
            if candidate.service == service_id and candidate_is_usable(candidate, min_confidence)
        ]
        if matching:
            return sorted(matching, key=candidate_rank, reverse=True)[0]
    return None


def candidate_is_usable(candidate: SourceCandidate, min_confidence: float) -> bool:
    if not candidate.url:
        return False
    confidence = candidate.same_sermon_confidence
    return candidate.state in USABLE_STATES and confidence is not None and confidence >= min_confidence


def candidate_rank(candidate: SourceCandidate) -> tuple[float, int]:
    kind_rank = {"manual-url": 3, "youtube-live": 2, "youtube-streams": 2, "mariners-online": 1}.get(
        candidate.kind, 0
    )
    return (candidate.same_sermon_confidence or 0.0, kind_rank)


def should_alert_operator(
    *,
    selected: SourceCandidate | None,
    now_value: str,
    alert_time: str,
    timezone: str,
) -> bool:
    if selected:
        return False
    now_local = datetime.fromisoformat(now_value).astimezone(ZoneInfo(timezone))
    hour, minute = parse_hhmm(alert_time)
    return now_local.time() >= time(hour, minute)


def fallback_reason_for(selected: SourceCandidate | None, operator_alert: bool) -> str | None:
    if selected:
        if selected.service == "sat530":
            return "4:00 Saturday source missing or not confirmed; using 5:30 Saturday fallback."
        if selected.service == "1000":
            return "8:30 source missing or not confirmed; using 10:00 fallback."
        if selected.service == "manual":
            return "Automatic live source missing or not confirmed; using operator-provided source."
        return None
    if operator_alert:
        return "No usable scheduled source by alert deadline; prepare iPad mic or authorized audio fallback."
    return "No usable scheduled source found yet."


def operator_audio_candidate(sunday: str, checked_at: str, reason: str | None) -> SourceCandidate:
    return SourceCandidate(
        kind="operator-audio",
        service="manual",
        url="",
        state="fallback",
        title=f"Operator audio fallback for {sunday}",
        same_sermon_confidence=0.0,
        actual_start_at=checked_at,
        evidence=reason,
    )


def generation_request_for(candidate: SourceCandidate, sunday: str) -> dict[str, Any] | None:
    if not candidate.url:
        return None
    return {
        "triggerSource": "live-source-monitor",
        "sunday": sunday,
        "liveUrl": candidate.url,
        "sourceKind": candidate.kind,
        "service": candidate.service,
        "sameSermonConfidence": candidate.same_sermon_confidence,
    }


def post_generation_request(report: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    generation_request = report.get("generationRequest")
    if not isinstance(generation_request, dict) or not generation_request.get("liveUrl"):
        return {"status": "skipped", "reason": "no_generation_request"}
    url = (
        f"{normalize_backend_url(args.backend_url)}"
        f"/api/admin/sundays/{quote(str(report['sunday']))}/generate"
    )
    headers = {"Content-Type": "application/json"}
    if args.admin_token:
        headers["Authorization"] = f"Bearer {args.admin_token}"
    if args.internal_task_token:
        headers["X-Internal-Task-Token"] = args.internal_task_token
    body = json.dumps(generation_request).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            response_text = response.read().decode("utf-8", errors="replace")
            return {
                "status": "posted",
                "statusCode": response.status,
                "endpoint": safe_endpoint(url),
                "responseSummary": response_text[:240],
                "authMaterialIncluded": False,
            }
    except HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        return {
            "status": "failed",
            "statusCode": exc.code,
            "endpoint": safe_endpoint(url),
            "responseSummary": response_text[:240],
            "authMaterialIncluded": False,
        }
    except Exception as exc:
        return {
            "status": "failed",
            "endpoint": safe_endpoint(url),
            "error": str(exc)[:200],
            "authMaterialIncluded": False,
        }


def default_fetcher(url: str) -> str:
    request = Request(url, headers={"User-Agent": "sermon-caption-live-source-monitor/1.0"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except URLError as exc:
        raise RuntimeError(str(exc)) from exc


def normalize_backend_url(value: str) -> str:
    clean = str(value or "").strip().rstrip("/")
    if not clean.startswith(("http://", "https://")):
        raise SystemExit("--backend-url must start with http:// or https://")
    return clean


def safe_endpoint(url: str) -> str:
    return url.split("?", 1)[0]


def extract_title(html: str) -> str | None:
    patterns = [
        r"<meta\s+property=[\"']og:title[\"']\s+content=[\"']([^\"']+)",
        r"<title[^>]*>(.*?)</title>",
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return compact_text(match.group(1))
    return None


def extracted_youtube_watch_urls(html: str) -> list[str]:
    patterns = [
        r"watch\?v=([A-Za-z0-9_-]{11})",
        r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"',
    ]
    seen: set[str] = set()
    urls: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, html):
            video_id = match.group(1)
            if video_id in seen:
                continue
            seen.add(video_id)
            urls.append(f"https://www.youtube.com/watch?v={video_id}")
    return urls


def infer_state(html: str) -> str:
    lower = html.lower()
    if any(token in lower for token in ["live now", "watch live", "is live", "\"is_live\":true"]):
        return "live"
    if any(token in lower for token in ["upcoming", "scheduled", "premieres"]):
        return "upcoming"
    if any(token in lower for token in ["was live", "livestream", "post_live", "\"live_status\":\"post_live\""]):
        return "was_live"
    return "available"


def score_same_sermon(title: str | None, expected_title: str | None) -> float:
    if not expected_title:
        return 0.75 if title else 0.0
    if not title:
        return 0.0
    return round(SequenceMatcher(None, normalize_title(title), normalize_title(expected_title)).ratio(), 3)


def normalize_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.lower()).strip()


def normalize_service(value: Any) -> str:
    text = str(value or "").strip().lower().replace(":", "")
    aliases = {
        "830": "830",
        "0830": "830",
        "8:30": "830",
        "8 30": "830",
        "1000": "1000",
        "10:00": "1000",
        "10 00": "1000",
        "sat4": "sat400",
        "sat400": "sat400",
        "saturday400": "sat400",
        "saturday4": "sat400",
        "sat530": "sat530",
        "saturday530": "sat530",
        "saturday5:30": "sat530",
        "saturday530pm": "sat530",
        "sat-auto": "sat-auto",
        "saturday": "sat-auto",
        "manual": "manual",
    }
    return aliases.get(text, text or "manual")


def read_state(path: Any) -> dict[str, Any]:
    if not path:
        return {}
    try:
        text = read_state_text(path)
    except Exception:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_state(
    path: Any,
    report: dict[str, Any],
    previous_state: dict[str, Any],
    notification: dict[str, Any],
) -> None:
    if not path:
        return
    notifications = previous_state.get("notifications")
    if not isinstance(notifications, dict):
        notifications = {}
    if notification_delivered(notification) and notification.get("dedupeKey"):
        notifications[str(notification["dedupeKey"])] = report.get("checkedAt")
    selected_source, generation_request, preserved_source = persisted_source(report, previous_state)
    state = {
        "schemaVersion": 1,
        "updatedAt": report.get("checkedAt"),
        # A later fallback must not erase a confirmed URL for the same Sunday.
        # The post-live worker depends on this state after the stream ends.
        "lastStatus": "source_detected" if preserved_source else report.get("status"),
        "lastMonitorStatus": report.get("status"),
        "lastMonitorCheckedAt": report.get("checkedAt"),
        "lastSunday": report.get("sunday"),
        "lastSelectedSource": selected_source,
        "lastGenerationRequest": generation_request,
        "lastSelectedUrlHash": selected_source.get("urlHash"),
        "sourcePreservedAfterFallback": preserved_source,
        "lastOperatorAlert": report.get("operatorAlert"),
        "notifications": notifications,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    write_state_text(path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True))


def persisted_source(
    report: dict[str, Any],
    previous_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, bool]:
    """Keep a confirmed same-Sunday source if a later poll returns fallback."""
    selected = report.get("selectedSource")
    source = selected if isinstance(selected, dict) else {}
    generation = report.get("generationRequest")
    generation_request = generation if isinstance(generation, dict) else None
    if source.get("url"):
        return source, generation_request, False

    previous_source = previous_state.get("lastSelectedSource")
    previous_generation = previous_state.get("lastGenerationRequest")
    if (
        previous_state.get("lastSunday") == report.get("sunday")
        and isinstance(previous_source, dict)
        and previous_source.get("url")
        and isinstance(previous_generation, dict)
        and previous_generation.get("liveUrl")
    ):
        return previous_source, previous_generation, True
    return source, generation_request, False


def read_state_text(path: Any) -> str:
    value = str(path)
    if value.startswith("gs://"):
        return read_gcs_text(value)
    resolved = resolve_repo_path(Path(value))
    if not resolved.exists():
        raise FileNotFoundError(value)
    return resolved.read_text(encoding="utf-8")


def write_state_text(path: Any, text: str) -> None:
    value = str(path)
    if value.startswith("gs://"):
        write_gcs_text(value, text)
        return
    resolved = resolve_repo_path(Path(value))
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(text, encoding="utf-8")


def build_notification(report: dict[str, Any], previous_state: dict[str, Any]) -> dict[str, Any]:
    status = str(report.get("status") or "")
    source = report.get("selectedSource") if isinstance(report.get("selectedSource"), dict) else {}
    url_hash = source.get("urlHash")
    service = source.get("service") or "unknown"
    if status not in NOTIFIABLE_STATUSES:
        return {"shouldNotify": False, "reason": "status_not_notifiable"}
    if status == "source_detected" and url_hash:
        dedupe_key = f"source_detected:{report.get('sunday')}:{url_hash}"
        title = "已捕获直播链接"
    elif status == "fallback" and report.get("operatorAlert"):
        dedupe_key = f"fallback:{report.get('sunday')}:{service}"
        title = "直播链接捕获失败，需要人工接管"
    else:
        return {"shouldNotify": False, "reason": "waiting_for_alert_deadline"}
    notifications = previous_state.get("notifications") if isinstance(previous_state, dict) else {}
    already_sent = isinstance(notifications, dict) and dedupe_key in notifications
    return {
        "shouldNotify": not already_sent,
        "reason": "already_notified" if already_sent else "new_state",
        "dedupeKey": dedupe_key,
        "title": title,
        "message": notification_message(title, report),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def notification_delivered(notification: dict[str, Any]) -> bool:
    delivery = notification.get("delivery")
    return isinstance(delivery, dict) and delivery.get("status") == "posted"


def notification_message(title: str, report: dict[str, Any]) -> str:
    source = report.get("selectedSource") if isinstance(report.get("selectedSource"), dict) else {}
    url = source.get("url") or "(no URL)"
    return "\n".join(
        [
            title,
            f"Sunday: {report.get('sunday')}",
            f"Service: {source.get('service')}",
            f"Status: {report.get('status')}",
            f"Source: {source.get('kind')} / {source.get('state')}",
            f"URL: {url}",
            f"Checked: {report.get('checkedAt')}",
            f"Next: {report.get('fallbackReason') or '已可进入字幕/翻译链路'}",
        ]
    )


def send_webhook_notification(webhook_url: str, notification: dict[str, Any]) -> dict[str, Any]:
    if not webhook_url.startswith(("https://", "http://")):
        return {"status": "skipped", "reason": "invalid_webhook_url"}
    body = json.dumps(
        {
            "content": notification.get("message"),
            "text": notification.get("message"),
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = Request(webhook_url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            response.read()
            if 200 <= response.status <= 299:
                return {"status": "posted", "statusCode": response.status, "authMaterialIncluded": False}
            return {"status": "failed", "statusCode": response.status, "authMaterialIncluded": False}
    except HTTPError as exc:
        exc.read()
        return {"status": "failed", "statusCode": exc.code, "authMaterialIncluded": False}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:160], "authMaterialIncluded": False}


def send_sendgrid_notification(
    api_key_secret: str | None,
    recipients_secret: str | None,
    sender_secret: str | None,
    notification: dict[str, Any],
) -> dict[str, Any]:
    if not api_key_secret or not recipients_secret or not sender_secret:
        return {"status": "not_configured"}
    try:
        api_key = access_secret(api_key_secret)
        recipients_value = access_secret(recipients_secret)
        sender = access_secret(sender_secret).strip()
        recipients = parse_recipient_emails(recipients_value)
        if not recipients or not sender:
            return {"status": "failed", "reason": "empty_sender_or_recipients"}
        payload = {
            "personalizations": [{"to": [{"email": email} for email in recipients]}],
            "from": {"email": sender},
            "subject": f"[讲道流程] {notification.get('title') or '需要处理'}",
            "content": [{"type": "text/plain", "value": str(notification.get("message") or "")}],
        }
        request = Request(
            "https://api.sendgrid.com/v3/mail/send",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=20) as response:
            response.read()
            return {
                "status": "posted" if 200 <= response.status <= 299 else "failed",
                "statusCode": response.status,
                "recipientCount": len(recipients),
                "authMaterialIncluded": False,
            }
    except HTTPError as exc:
        exc.read()
        return {"status": "failed", "statusCode": exc.code, "authMaterialIncluded": False}
    except Exception as exc:
        return {"status": "failed", "error": str(exc)[:160], "authMaterialIncluded": False}


def parse_recipient_emails(value: str) -> list[str]:
    text = value.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        values = [str(item) for item in parsed]
    elif isinstance(parsed, dict):
        raw = parsed.get("recipients") or parsed.get("emails") or []
        values = [str(item) for item in raw] if isinstance(raw, list) else [str(raw)]
    else:
        values = re.split(r"[,;\n]", text)
    return [item.strip() for item in values if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", item.strip())]


def clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))


def now_iso(value: str | None, timezone: str) -> str:
    if value:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        return parsed.astimezone(ZoneInfo(timezone)).isoformat()
    return datetime.now(ZoneInfo(timezone)).isoformat()


def parse_hhmm(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", value.strip())
    if not match:
        raise SystemExit("--operator-alert-time must be HH:MM")
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SystemExit("--operator-alert-time must be HH:MM")
    return hour, minute


def validate_sunday(value: str) -> None:
    parsed = date.fromisoformat(value)
    if parsed.weekday() != 6:
        raise SystemExit("--sunday must be a Sunday date")


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def string_or_none(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


if __name__ == "__main__":
    raise SystemExit(main())
