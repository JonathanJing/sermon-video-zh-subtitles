from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


DEFAULT_TIMEZONE = "America/Los_Angeles"


@dataclass(frozen=True)
class AppConfig:
    artifact_bucket: str | None
    artifact_prefix: str
    current_manifest_uri: str | None
    sunday_manifest_uri_template: str | None
    timezone: str
    openai_api_key_secret: str | None
    operator_admin_token: str | None
    internal_task_token: str | None
    enable_inline_worker: bool
    openai_api_key: str | None = None
    realtime_event_log_dir: str = "/tmp/sermon-realtime-events"
    realtime_event_gcs_prefix: str | None = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            artifact_bucket=empty_to_none(os.getenv("SERMON_ARTIFACT_BUCKET")),
            artifact_prefix=os.getenv("SERMON_ARTIFACT_PREFIX", "sundays").strip("/"),
            current_manifest_uri=empty_to_none(os.getenv("SERMON_CURRENT_MANIFEST_URI")),
            sunday_manifest_uri_template=empty_to_none(
                os.getenv("SERMON_SUNDAY_MANIFEST_URI_TEMPLATE")
            ),
            timezone=os.getenv("APP_TIMEZONE", DEFAULT_TIMEZONE),
            openai_api_key_secret=empty_to_none(os.getenv("OPENAI_API_KEY_SECRET")),
            operator_admin_token=empty_to_none(os.getenv("OPERATOR_ADMIN_TOKEN")),
            internal_task_token=empty_to_none(os.getenv("INTERNAL_TASK_TOKEN")),
            enable_inline_worker=os.getenv("ENABLE_INLINE_WORKER", "").lower()
            in {"1", "true", "yes"},
            openai_api_key=empty_to_none(os.getenv("OPENAI_API_KEY")),
            realtime_event_log_dir=os.getenv("REALTIME_EVENT_LOG_DIR", "/tmp/sermon-realtime-events"),
            realtime_event_gcs_prefix=empty_to_none(os.getenv("REALTIME_EVENT_GCS_PREFIX")),
        )


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def current_sunday(today: date | None = None, timezone: str = DEFAULT_TIMEZONE) -> date:
    """Return the most recent Sunday in the configured local timezone."""

    if today is None:
        today = datetime.now(ZoneInfo(timezone)).date()
    return today - timedelta(days=(today.weekday() + 1) % 7)
