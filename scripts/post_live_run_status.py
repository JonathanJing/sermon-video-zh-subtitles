#!/usr/bin/env python3
"""Durable, idempotent status ledger for the post-live sermon workflow."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


STAGES = (
    "source_saved",
    "approval",
    "archive_ready",
    "downloaded",
    "clipped",
    "transcribed",
    "translated",
    "reviewed",
    "pdf_qa",
    "publication",
)


def new_status(sunday: str, *, source_url: str | None = None) -> dict[str, Any]:
    now = utc_now()
    return {
        "schemaVersion": 1,
        "sunday": sunday,
        "status": "running",
        "currentStage": None,
        "sourceUrl": source_url,
        "createdAt": now,
        "updatedAt": now,
        "stages": {
            stage: {"status": "pending", "attempts": 0, "durationSeconds": 0.0}
            for stage in STAGES
        },
        "blocker": None,
    }


def update_stage(
    payload: dict[str, Any] | None,
    sunday: str,
    stage: str,
    status: str,
    *,
    source_url: str | None = None,
    artifact: str | None = None,
    reason: str | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError(f"Unknown post-live stage: {stage}")
    result = payload if isinstance(payload, dict) else new_status(sunday, source_url=source_url)
    result.setdefault("stages", {})
    for name in STAGES:
        result["stages"].setdefault(name, {"status": "pending", "attempts": 0, "durationSeconds": 0.0})
    record = result["stages"][stage]
    previous = record.get("status")
    if status == "running" and previous != "running":
        record["attempts"] = int(record.get("attempts") or 0) + 1
        record["startedAt"] = utc_now()
    record["status"] = status
    if duration_seconds is not None:
        record["durationSeconds"] = round(max(0.0, float(duration_seconds)), 3)
    if artifact:
        artifacts = record.setdefault("artifacts", [])
        if artifact not in artifacts:
            artifacts.append(artifact)
    if reason:
        record["reason"] = reason
    elif status == "complete":
        record.pop("reason", None)
    if status == "complete":
        record["completedAt"] = utc_now()
    result["currentStage"] = stage
    result["updatedAt"] = utc_now()
    if source_url:
        result["sourceUrl"] = source_url
    result["blocker"] = {"stage": stage, "reason": reason} if status == "blocked" else None
    if status == "blocked":
        result["status"] = "blocked"
    else:
        result["status"] = "running"
    return result


def mark_terminal(
    payload: dict[str, Any] | None,
    sunday: str,
    status: str,
    *,
    stage: str | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    if status not in {"complete", "failed", "blocked"}:
        raise ValueError(f"Unsupported terminal status: {status}")
    result = payload if isinstance(payload, dict) else new_status(sunday)
    if stage and stage not in STAGES:
        raise ValueError(f"Unknown post-live stage: {stage}")
    if stage:
        result["currentStage"] = stage
    now = utc_now()
    result["status"] = status
    result["updatedAt"] = now
    result["completedAt"] = now
    result["blocker"] = (
        {"stage": result.get("currentStage"), "reason": reason}
        if status in {"failed", "blocked"} and reason
        else None
    )
    return result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
