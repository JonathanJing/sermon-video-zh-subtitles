#!/usr/bin/env python3
"""Discover Sunday live-source candidates and choose the 11:30 caption input."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
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


DEFAULT_TIMEZONE = "America/Los_Angeles"
DEFAULT_MARINERS_ONLINE_URL = "https://www.marinerschurch.org/irvine/"
DEFAULT_YOUTUBE_STREAMS_URL = "https://www.youtube.com/@marinerschurch/streams"
USABLE_STATES = {"live", "upcoming", "was_live", "available", "manual_available"}
SERVICE_ORDER = ["830", "1000", "manual"]


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
    report = run_monitor(args)
    if args.post_generate:
        report["generationPost"] = post_generation_request(report, args)
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
        choices=["auto", "830", "1000"],
        help="Which service window to evaluate. auto checks 8:30 then 10:00.",
    )
    parser.add_argument("--expected-title", help="Expected sermon title for same-sermon confidence.")
    parser.add_argument("--manual-url", action="append", default=[], help="Authorized/manual source URL fallback.")
    parser.add_argument("--mariners-online-url", default=DEFAULT_MARINERS_ONLINE_URL)
    parser.add_argument("--youtube-streams-url", default=DEFAULT_YOUTUBE_STREAMS_URL)
    parser.add_argument("--fixture-json", type=Path, help="Offline fixture containing source candidates.")
    parser.add_argument("--out", type=Path, default=Path("artifacts/live-source-monitor/report.json"))
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
    candidates = load_candidates(args)
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


def load_candidates(args: argparse.Namespace) -> list[SourceCandidate]:
    candidates: list[SourceCandidate] = []
    fixture_sources = getattr(args, "fixture_sources", None)
    if fixture_sources is not None:
        candidates.extend(candidates_from_fixture({"sources": fixture_sources}, args.expected_title))
    elif args.fixture_json:
        fixture = json.loads(resolve_repo_path(args.fixture_json).read_text(encoding="utf-8"))
        candidates.extend(candidates_from_fixture(fixture, args.expected_title))
    else:
        candidates.extend(fetch_default_candidates(args))
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


def fetch_default_candidates(args: argparse.Namespace) -> list[SourceCandidate]:
    fetcher = default_fetcher
    return [
        fetch_candidate(
            kind="mariners-online",
            service="830",
            url=args.mariners_online_url,
            expected_title=args.expected_title,
            fetcher=fetcher,
        ),
        fetch_candidate(
            kind="youtube-streams",
            service="830",
            url=args.youtube_streams_url,
            expected_title=args.expected_title,
            fetcher=fetcher,
        ),
        fetch_candidate(
            kind="mariners-online",
            service="1000",
            url=args.mariners_online_url,
            expected_title=args.expected_title,
            fetcher=fetcher,
        ),
        fetch_candidate(
            kind="youtube-streams",
            service="1000",
            url=args.youtube_streams_url,
            expected_title=args.expected_title,
            fetcher=fetcher,
        ),
    ]


def fetch_candidate(
    *,
    kind: str,
    service: str,
    url: str,
    expected_title: str | None,
    fetcher: Callable[[str], str],
) -> SourceCandidate:
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
    return SourceCandidate(
        kind=kind,
        service=service,
        url=url,
        state=state,
        title=title,
        same_sermon_confidence=score_same_sermon(title, expected_title),
        evidence="fetched-page",
    )


def choose_source(
    candidates: list[SourceCandidate],
    *,
    service: str,
    min_confidence: float,
) -> SourceCandidate | None:
    order = [service] if service in {"830", "1000"} else SERVICE_ORDER
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
    kind_rank = {"manual-url": 3, "youtube-streams": 2, "mariners-online": 1}.get(candidate.kind, 0)
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
        if selected.service == "1000":
            return "8:30 source missing or not confirmed; using 10:00 fallback."
        if selected.service == "manual":
            return "Automatic live source missing or not confirmed; using operator-provided source."
        return None
    if operator_alert:
        return "No usable 8:30/10:00 source by alert deadline; prepare iPad mic or authorized audio fallback."
    return "No usable 8:30/10:00 source found yet."


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


def infer_state(html: str) -> str:
    lower = html.lower()
    if any(token in lower for token in ["live now", "watch live", "is live", "\"is_live\":true"]):
        return "live"
    if any(token in lower for token in ["upcoming", "scheduled", "premieres"]):
        return "upcoming"
    if any(token in lower for token in ["was live", "livestream"]):
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
        "manual": "manual",
    }
    return aliases.get(text, text or "manual")


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
