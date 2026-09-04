#!/usr/bin/env python3
"""Run a self-cleaning transport smoke test against the Firebase dev project."""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from backend.firebase_publisher import (
    AccessTokenProvider,
    FirebaseCaptionPublisher,
    FirebasePublisherConfig,
)


EXPECTED_DATABASE_URL = "https://ai-for-god-caption-dev.firebaseio.com"
EXPECTED_VIEWER_URL = "https://ai-for-god-caption-dev.web.app"


def fetch_json(url: str) -> dict:
    with urlopen(url, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def authenticated_delete(url: str, token_provider: AccessTokenProvider) -> None:
    request = Request(
        url,
        method="DELETE",
        headers={"Authorization": f"Bearer {token_provider()}"},
    )
    with urlopen(request, timeout=8) as response:
        if response.status != 200:
            raise RuntimeError(f"Firebase cleanup failed with HTTP {response.status}")


def main() -> int:
    config = FirebasePublisherConfig.from_environment()
    if config is None:
        raise RuntimeError("Firebase runtime environment is not configured")
    if config.database_url != EXPECTED_DATABASE_URL or config.viewer_base_url != EXPECTED_VIEWER_URL:
        raise RuntimeError("Cloud smoke test is restricted to ai-for-god-caption-dev")

    token_provider = AccessTokenProvider()
    viewer_token = f"smoke_{secrets.token_urlsafe(24)}"
    node_url = f"{config.database_url}/sessions/{viewer_token}.json"
    publisher = FirebaseCaptionPublisher(config, token_provider=token_provider)

    try:
        publisher.start_session("cloud-smoke", viewer_token)
        publisher.publish("cloud-smoke", {
            "type": "asr.final",
            "segmentId": "smoke-1",
            "sourceTextEn": "We walk by faith, not by sight.",
        })
        publisher.publish("cloud-smoke", {
            "type": "translation.final",
            "segmentId": "smoke-1",
            "sourceTextEn": "We walk by faith, not by sight.",
            "targetTextZh": "我们凭信心而行，不凭眼见。",
        })
        publisher.work.join()

        status = publisher.status()
        if status["lastError"] or status["publishedCount"] != 3:
            raise RuntimeError(f"Publisher smoke write failed: {status}")

        snapshot = fetch_json(node_url)
        if snapshot.get("active", {}).get("targetTextZh") != "我们凭信心而行，不凭眼见。":
            raise RuntimeError("Anonymous viewer did not receive the final Chinese caption")

        try:
            fetch_json(f"{config.database_url}/.json")
        except HTTPError as error:
            if error.code not in {401, 403}:
                raise
        else:
            raise RuntimeError("Anonymous root read was unexpectedly allowed")

        with urlopen(f"{config.viewer_base_url}/s/{viewer_token}", timeout=8) as response:
            viewer_html = response.read().decode("utf-8")
            if response.status != 200 or "主日证道 · 中文字幕" not in viewer_html:
                raise RuntimeError("Firebase Hosting viewer route is not healthy")

        print(
            "Firebase cloud smoke passed: "
            f"3 writes, ack {status['lastWriteLatencyMs']} ms, "
            "anonymous token read allowed, root read denied, Hosting route healthy"
        )
        return 0
    finally:
        publisher.stop()
        authenticated_delete(node_url, token_provider)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Firebase cloud smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1)
