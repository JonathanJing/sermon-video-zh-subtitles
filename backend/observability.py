from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "severity": fields.pop("severity", "INFO"),
        "event": event,
        "component": fields.pop("component", "sermon-caption"),
        "loggedAt": datetime.now(timezone.utc).isoformat(),
        **{key: value for key, value in fields.items() if value is not None},
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), file=sys.stdout, flush=True)


def trigger_source(headers: Any, payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    explicit = payload.get("triggerSource") or payload.get("trigger_source")
    if explicit:
        return str(explicit)
    user_agent = str(_header(headers, "User-Agent") or "").lower()
    if _header(headers, "X-CloudScheduler") or "cloudscheduler" in user_agent or "cloud-scheduler" in user_agent:
        return "cloud-scheduler"
    if _header(headers, "X-CloudTasks-TaskName") or "cloudtasks" in user_agent or "cloud-tasks" in user_agent:
        return "cloud-tasks"
    if _header(headers, "X-Internal-Task-Token"):
        return "internal-task"
    return "operator"


def scheduler_job(headers: Any) -> str | None:
    return _header(headers, "X-CloudScheduler-JobName") or _header(headers, "X-CloudScheduler-ScheduleTime")


def url_summary(url: str | None) -> dict[str, str] | None:
    if not url:
        return None
    parsed = urlparse(url)
    return {
        "host": parsed.netloc,
        "path": parsed.path,
        "urlHash": stable_hash(url),
    }


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def command_stage(command: list[str]) -> str:
    joined = " ".join(command)
    if "run_openai_model_access_preflight.py" in joined:
        return "model-access-preflight"
    if "prepare_live_link_playback.py" in joined:
        return "prepare-live-playback"
    if "translate_playback_with_openai.py" in joined:
        return "translate-captions"
    if "export_playback_captions.py" in joined:
        return "export-translated-captions"
    if "validate_offline_chain.py" in joined:
        return "validate-offline-chain"
    if "generate_notes_with_openai.py" in joined:
        return "generate-insights"
    if "promote_sunday_manifest.py" in joined:
        return "promote-sunday-manifest"
    if "upload_file_to_gcs.py" in joined and "playback-simulation.generated.js" in joined:
        return "upload-translated-playback"
    if "upload_file_to_gcs.py" in joined and "cloud-manifest.json" in joined:
        return "upload-run-manifest"
    if command[:3] == ["gcloud", "storage", "cp"]:
        return "upload-translated-playback"
    return "unknown"


def client_ip_hash(headers: Any, client_address: tuple[str, int] | None) -> str | None:
    forwarded = str(_header(headers, "X-Forwarded-For") or "").split(",", 1)[0].strip()
    ip = forwarded or (client_address[0] if client_address else "")
    return stable_hash(ip) if ip else None


def _header(headers: Any, name: str) -> str | None:
    if headers is None:
        return None
    try:
        value = headers.get(name)
    except AttributeError:
        value = headers.get(name.lower()) if isinstance(headers, dict) else None
    return str(value) if value else None
