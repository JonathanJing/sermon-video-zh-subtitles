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
    generation_progress_dir: str = "/tmp/sermon-generation-progress"
    generation_progress_gcs_prefix: str | None = None
    live_playback_dir: str = "/tmp/sermon-live-playback"
    live_playback_gcs_prefix: str | None = None
    operator_notify_webhook_url: str | None = None
    live_source_monitor_state_dir: str = "/tmp/sermon-live-source-monitor"
    live_source_monitor_state_uri: str | None = None
    youtube_api_key_secret: str | None = None
    operator_notify_sendgrid_secret: str | None = None
    operator_notify_recipients_secret: str | None = None
    operator_notify_sender_secret: str | None = None
    supervisor_job_project: str | None = None
    supervisor_job_location: str | None = None
    supervisor_job_name: str | None = None
    supervisor_job_container: str | None = None
    supervisor_job_timeout_seconds: int = 14_400
    supervisor_default_mode: str = "shadow"

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
            generation_progress_dir=os.getenv("GENERATION_PROGRESS_DIR", "/tmp/sermon-generation-progress"),
            generation_progress_gcs_prefix=empty_to_none(os.getenv("GENERATION_PROGRESS_GCS_PREFIX")),
            live_playback_dir=os.getenv("LIVE_PLAYBACK_DIR", "/tmp/sermon-live-playback"),
            live_playback_gcs_prefix=empty_to_none(os.getenv("LIVE_PLAYBACK_GCS_PREFIX")),
            operator_notify_webhook_url=empty_to_none(os.getenv("OPERATOR_NOTIFY_WEBHOOK_URL")),
            live_source_monitor_state_dir=os.getenv(
                "LIVE_SOURCE_MONITOR_STATE_DIR",
                "/tmp/sermon-live-source-monitor",
            ),
            live_source_monitor_state_uri=empty_to_none(os.getenv("LIVE_SOURCE_MONITOR_STATE_URI")),
            youtube_api_key_secret=empty_to_none(os.getenv("YOUTUBE_API_KEY_SECRET")),
            operator_notify_sendgrid_secret=empty_to_none(os.getenv("OPERATOR_NOTIFY_SENDGRID_SECRET")),
            operator_notify_recipients_secret=empty_to_none(os.getenv("OPERATOR_NOTIFY_RECIPIENTS_SECRET")),
            operator_notify_sender_secret=empty_to_none(os.getenv("OPERATOR_NOTIFY_SENDER_SECRET")),
            supervisor_job_project=empty_to_none(
                os.getenv("SERMON_SUPERVISOR_JOB_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT")
            ),
            supervisor_job_location=empty_to_none(os.getenv("SERMON_SUPERVISOR_JOB_LOCATION")),
            supervisor_job_name=empty_to_none(os.getenv("SERMON_SUPERVISOR_JOB_NAME")),
            supervisor_job_container=empty_to_none(os.getenv("SERMON_SUPERVISOR_JOB_CONTAINER")),
            supervisor_job_timeout_seconds=int(
                os.getenv("SERMON_SUPERVISOR_JOB_TIMEOUT_SECONDS", "14400")
            ),
            supervisor_default_mode=supervisor_mode(
                os.getenv("SERMON_SUPERVISOR_MODE", "shadow")
            ),
        )


def empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def supervisor_mode(value: str) -> str:
    mode = str(value or "").strip().lower()
    if mode not in {"shadow", "execute"}:
        raise ValueError("SERMON_SUPERVISOR_MODE must be shadow or execute")
    return mode


def current_sunday(today: date | None = None, timezone: str = DEFAULT_TIMEZONE) -> date:
    """Return the most recent Sunday in the configured local timezone."""

    if today is None:
        today = datetime.now(ZoneInfo(timezone)).date()
    return today - timedelta(days=(today.weekday() + 1) % 7)


def upcoming_sunday(today: date | None = None, timezone: str = DEFAULT_TIMEZONE) -> date:
    """Return the next Sunday, using today when today is already Sunday."""

    if today is None:
        today = datetime.now(ZoneInfo(timezone)).date()
    days_until_sunday = (6 - today.weekday()) % 7
    return today + timedelta(days=days_until_sunday)
