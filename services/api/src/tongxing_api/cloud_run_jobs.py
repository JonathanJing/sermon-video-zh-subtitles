from __future__ import annotations

import re
from typing import Any


RESOURCE_PART_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def dispatch_cloud_run_job(
    *,
    project: str,
    location: str,
    job: str,
    args: list[str],
    timeout_seconds: int = 14_400,
    container_name: str | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Start one Cloud Run Job execution with bounded per-run argument overrides."""
    for label, value in (("project", project), ("location", location), ("job", job)):
        if not RESOURCE_PART_RE.fullmatch(str(value or "")):
            raise ValueError(f"invalid Cloud Run Job {label}")
    timeout_seconds = int(timeout_seconds)
    if timeout_seconds < 60 or timeout_seconds > 86_400:
        raise ValueError("Cloud Run Job timeout must be between 60 and 86400 seconds")
    if not args:
        raise ValueError("Cloud Run Job args are required")

    container_override: dict[str, Any] = {"args": [str(value) for value in args]}
    if container_name:
        if not RESOURCE_PART_RE.fullmatch(container_name):
            raise ValueError("invalid Cloud Run Job container name")
        container_override["name"] = container_name
    payload = {
        "overrides": {
            "containerOverrides": [container_override],
            "taskCount": 1,
            "timeout": f"{timeout_seconds}s",
        }
    }
    url = f"https://run.googleapis.com/v2/projects/{project}/locations/{location}/jobs/{job}:run"
    actual_session = session or authorized_session()
    response = actual_session.post(url, json=payload, timeout=30)
    response.raise_for_status()
    body = response.json()
    return {
        "status": "dispatched",
        "operationName": body.get("name"),
        "job": f"projects/{project}/locations/{location}/jobs/{job}",
        "argsCount": len(args),
        "timeoutSeconds": timeout_seconds,
    }


def authorized_session() -> Any:
    import google.auth  # type: ignore
    from google.auth.transport.requests import AuthorizedSession  # type: ignore

    credentials, _ = google.auth.default(scopes=[CLOUD_PLATFORM_SCOPE])
    return AuthorizedSession(credentials)
