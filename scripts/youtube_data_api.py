#!/usr/bin/env python3
"""Small YouTube Data API client for public video and livestream metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import requests


VIDEOS_LIST_URL = "https://www.googleapis.com/youtube/v3/videos"
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class YouTubeDataApiError(RuntimeError):
    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--api-key-secret", required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    from backend.cloud import access_secret

    metadata = video_metadata(args.video_id, api_key=access_secret(args.api_key_secret))
    report = {
        "status": "ok" if metadata else "not_found",
        "metadata": metadata,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if metadata else 2


def video_metadata(
    video_id: str,
    *,
    api_key: str,
    requester=requests.get,
    timeout: float = 30.0,
) -> dict[str, Any] | None:
    response = requester(
        VIDEOS_LIST_URL,
        params={
            "part": "snippet,contentDetails,liveStreamingDetails,status",
            "id": video_id,
            "key": api_key,
        },
        timeout=timeout,
    )
    try:
        payload = response.json()
    except Exception as exc:
        raise YouTubeDataApiError(f"YouTube Data API returned non-JSON HTTP {response.status_code}") from exc
    if response.status_code != 200:
        error = payload.get("error") if isinstance(payload, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        raise YouTubeDataApiError(f"YouTube Data API HTTP {response.status_code}: {message or 'request failed'}")
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return None
    return normalize_video_resource(items[0])


def normalize_video_resource(resource: dict[str, Any]) -> dict[str, Any]:
    video_id = str(resource.get("id") or "")
    snippet = resource.get("snippet") if isinstance(resource.get("snippet"), dict) else {}
    details = resource.get("contentDetails") if isinstance(resource.get("contentDetails"), dict) else {}
    live = resource.get("liveStreamingDetails") if isinstance(resource.get("liveStreamingDetails"), dict) else {}
    status = resource.get("status") if isinstance(resource.get("status"), dict) else {}
    broadcast_content = str(snippet.get("liveBroadcastContent") or "none")
    actual_start = live.get("actualStartTime")
    actual_end = live.get("actualEndTime")
    scheduled_start = live.get("scheduledStartTime")

    if actual_end:
        live_status = "was_live"
    elif broadcast_content == "live" or (actual_start and not actual_end):
        live_status = "is_live"
    elif broadcast_content == "upcoming" or (scheduled_start and not actual_start):
        live_status = "is_upcoming"
    else:
        live_status = "not_live"

    result = {
        "id": video_id,
        "title": snippet.get("title"),
        "channel_id": snippet.get("channelId"),
        "channel": snippet.get("channelTitle"),
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
        "live_status": live_status,
        "is_live": live_status == "is_live",
        "was_live": live_status == "was_live",
        "media_type": "livestream" if live else "video",
        "availability": status.get("privacyStatus"),
        "duration": parse_iso8601_duration(details.get("duration")),
        "actual_start_time": actual_start,
        "actual_end_time": actual_end,
        "scheduled_start_time": scheduled_start,
        "scheduled_end_time": live.get("scheduledEndTime"),
        "concurrent_viewers": live.get("concurrentViewers"),
        "metadata_provider": "youtube-data-api-v3",
    }
    return {key: value for key, value in result.items() if value is not None}


def parse_iso8601_duration(value: Any) -> float | None:
    text = str(value or "")
    match = re.fullmatch(
        r"P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?",
        text,
    )
    if not match:
        return None
    return (
        float(match.group("days") or 0) * 86400
        + float(match.group("hours") or 0) * 3600
        + float(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )


if __name__ == "__main__":
    raise SystemExit(main())
