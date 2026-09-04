from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DELETABLE_STATUSES = {"completed", "incomplete", "recovered_incomplete"}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def retention_plan(
    root: str | Path,
    retention_days: int = 30,
    keep_latest: int = 10,
    now: datetime | None = None,
) -> dict[str, Any]:
    if retention_days < 1 or keep_latest < 0:
        raise ValueError("retention_days must be >= 1 and keep_latest must be >= 0")
    session_root = Path(root).resolve()
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(days=retention_days)
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if not session_root.is_dir():
        return {"root": str(session_root), "retentionDays": retention_days, "keepLatest": keep_latest, "delete": [], "skipped": [], "deleteBytes": 0}
    valid: list[tuple[datetime, Path, dict[str, Any]]] = []
    for directory in session_root.iterdir():
        if not directory.is_dir():
            continue
        manifest_path = directory / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            skipped.append({"sessionId": directory.name, "reason": "missing_or_invalid_manifest"})
            continue
        status = str(manifest.get("status") or "")
        if status not in DELETABLE_STATUSES:
            skipped.append({"sessionId": directory.name, "reason": f"protected_status:{status or 'unknown'}"})
            continue
        ended = _parse_time(manifest.get("stoppedAt") or manifest.get("finalizedAt") or manifest.get("createdAt"))
        if ended is None:
            ended = datetime.fromtimestamp(directory.stat().st_mtime, timezone.utc)
        valid.append((ended, directory, manifest))
    valid.sort(key=lambda item: item[0], reverse=True)
    protected = {directory for _, directory, _ in valid[:keep_latest]}
    for ended, directory, manifest in valid:
        if directory in protected:
            skipped.append({"sessionId": directory.name, "reason": "keep_latest"})
        elif ended >= cutoff:
            skipped.append({"sessionId": directory.name, "reason": "within_retention_window"})
        else:
            candidates.append({
                "sessionId": directory.name,
                "directory": str(directory),
                "status": manifest.get("status"),
                "endedAt": ended.isoformat(),
                "bytes": directory_size(directory),
            })
    return {
        "root": str(session_root),
        "retentionDays": retention_days,
        "keepLatest": keep_latest,
        "delete": candidates,
        "skipped": skipped,
        "deleteBytes": sum(item["bytes"] for item in candidates),
    }


def apply_retention(plan: dict[str, Any]) -> list[str]:
    root = Path(plan["root"]).resolve()
    deleted: list[str] = []
    for item in plan.get("delete", []):
        target = Path(item["directory"]).resolve()
        if target.parent != root or target == root:
            raise ValueError(f"unsafe retention target: {target}")
        manifest = target / "manifest.json"
        if not target.is_dir() or not manifest.is_file():
            raise ValueError(f"retention target changed after planning: {target}")
        shutil.rmtree(target)
        deleted.append(item["sessionId"])
    return deleted
