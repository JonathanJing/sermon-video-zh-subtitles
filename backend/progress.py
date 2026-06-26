from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cloud import read_gcs_text, write_gcs_text


PIPELINE_STAGES = [
    {
        "id": "source-discovery",
        "label": "发现直播源",
        "waitingLabel": "等待",
        "activeLabel": "确认中",
        "doneLabel": "已确认",
    },
    {
        "id": "live-capture",
        "label": "采集直播/归档",
        "waitingLabel": "等待",
        "activeLabel": "采集中",
        "doneLabel": "已采集",
    },
    {
        "id": "sermon-start",
        "label": "判断证道开始",
        "waitingLabel": "等待",
        "activeLabel": "定位中",
        "doneLabel": "已定位",
    },
    {
        "id": "transcript",
        "label": "英文听写",
        "waitingLabel": "等待",
        "activeLabel": "听写中",
        "doneLabel": "英文可见",
    },
    {
        "id": "translation",
        "label": "生成中文翻译",
        "waitingLabel": "等待",
        "activeLabel": "翻译中",
        "doneLabel": "中文可见",
    },
    {
        "id": "scripture",
        "label": "经文匹配",
        "waitingLabel": "等待",
        "activeLabel": "补充中",
        "doneLabel": "已补充",
    },
    {
        "id": "promotion",
        "label": "发布清单",
        "waitingLabel": "等待",
        "activeLabel": "发布中",
        "doneLabel": "Cloud Run",
    },
    {
        "id": "public-ready",
        "label": "会众页可用",
        "waitingLabel": "等待",
        "activeLabel": "验证中",
        "doneLabel": "已验证",
    },
]

COMMAND_STAGE_TO_PIPELINE = {
    "model-access-preflight": ["source-discovery"],
    "prepare-live-playback": ["live-capture", "sermon-start", "transcript"],
    "translate-captions": ["translation"],
    "export-translated-captions": ["translation"],
    "validate-offline-chain": ["translation"],
    "upload-translated-playback": ["promotion"],
    "upload-run-manifest": ["promotion"],
    "promote-sunday-manifest": ["promotion", "public-ready"],
    "generate-insights": ["scripture"],
}


class GenerationProgressStore:
    def __init__(self, root: Path, gcs_prefix: str | None = None) -> None:
        self.root = root
        self.gcs_prefix = normalize_gcs_prefix(gcs_prefix)

    def append(
        self,
        *,
        event: str,
        sunday: str,
        session_id: str,
        run_prefix: str | None = None,
        command_stage: str | None = None,
        trigger_source: str | None = None,
        command_count: int | None = None,
        error: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "schemaVersion": 1,
            "event": event,
            "loggedAt": datetime.now(timezone.utc).isoformat(),
            "sunday": sunday,
            "sessionId": session_id,
            "runPrefix": run_prefix,
            "commandStage": command_stage,
            "pipelineStages": pipeline_stages_for_command(command_stage),
            "triggerSource": trigger_source,
            "commandCount": command_count,
            "error": error[:500] if error else None,
            "status": status,
        }
        clean = {key: value for key, value in record.items() if value is not None}
        path = self.path_for(sunday, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(clean, ensure_ascii=False, sort_keys=True) + "\n")
        self.mirror_to_gcs(sunday, session_id)
        return clean

    def status(self, sunday: str, session_id: str | None = None) -> dict[str, Any]:
        gcs_status = self.status_from_gcs(sunday, session_id)
        local_status = None
        if session_id:
            path = self.path_for(sunday, session_id)
        else:
            path = self.latest_path_for_sunday(sunday)
        if path and path.exists():
            events = self.read_events(path)
            local_status = build_progress_status(sunday=sunday, session_id=session_id, events=events)
        if local_status and gcs_status:
            return newest_status(local_status, gcs_status)
        return local_status or gcs_status or self.empty_status(sunday, session_id)

    def read_events(self, path: Path) -> list[dict[str, Any]]:
        events = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                clean = line.strip()
                if not clean:
                    continue
                try:
                    event = json.loads(clean)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    events.append(event)
        return events

    def latest_path_for_sunday(self, sunday: str) -> Path | None:
        directory = self.root / safe_component(sunday)
        if not directory.exists():
            return None
        paths = [path for path in directory.glob("*.jsonl") if path.is_file()]
        if not paths:
            return None
        return max(paths, key=lambda path: path.stat().st_mtime)

    def path_for(self, sunday: str, session_id: str) -> Path:
        return self.root / safe_component(sunday) / f"{safe_component(session_id)}.jsonl"

    def empty_status(self, sunday: str, session_id: str | None = None) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "status": "missing",
            "sunday": sunday,
            "sessionId": session_id,
            "updatedAt": None,
            "runPrefix": None,
            "currentCommandStage": None,
            "failedCommandStage": None,
            "error": None,
            "events": [],
            "pipelineStages": initial_pipeline_stages(),
        }

    def mirror_to_gcs(self, sunday: str, session_id: str) -> None:
        if not self.gcs_prefix:
            return
        path = self.path_for(sunday, session_id)
        try:
            events = self.read_events(path)
            status = build_progress_status(sunday=sunday, session_id=session_id, events=events)
            write_gcs_text(self.gcs_session_events_uri(sunday, session_id), path.read_text(encoding="utf-8"), "application/x-ndjson")
            write_gcs_text(
                self.gcs_session_status_uri(sunday, session_id),
                json.dumps(status, ensure_ascii=False, sort_keys=True, indent=2),
            )
            write_gcs_text(
                self.gcs_latest_status_uri(sunday),
                json.dumps(status, ensure_ascii=False, sort_keys=True, indent=2),
            )
        except Exception:
            return

    def status_from_gcs(self, sunday: str, session_id: str | None = None) -> dict[str, Any] | None:
        if not self.gcs_prefix:
            return None
        uri = self.gcs_session_status_uri(sunday, session_id) if session_id else self.gcs_latest_status_uri(sunday)
        try:
            data = json.loads(read_gcs_text(uri))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def gcs_session_events_uri(self, sunday: str, session_id: str) -> str:
        return f"{self.gcs_prefix}/{safe_component(sunday)}/{safe_component(session_id)}.jsonl"

    def gcs_session_status_uri(self, sunday: str, session_id: str | None) -> str:
        clean_session = safe_component(session_id or "latest")
        return f"{self.gcs_prefix}/{safe_component(sunday)}/{clean_session}.status.json"

    def gcs_latest_status_uri(self, sunday: str) -> str:
        return f"{self.gcs_prefix}/{safe_component(sunday)}/latest-status.json"


def build_progress_status(
    *,
    sunday: str,
    session_id: str | None,
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    if not events:
        return GenerationProgressStore(Path("/tmp/unused")).empty_status(sunday, session_id)
    stages = {stage["id"]: {**stage, "state": "waiting", "statusLabel": stage["waitingLabel"]} for stage in PIPELINE_STAGES}
    overall = "planned"
    current_command_stage = None
    failed_command_stage = None
    error = None
    run_prefix = None
    latest_session_id = session_id
    updated_at = None

    for event in events:
        name = str(event.get("event") or "")
        latest_session_id = str(event.get("sessionId") or latest_session_id or "")
        updated_at = event.get("loggedAt") or updated_at
        run_prefix = event.get("runPrefix") or run_prefix
        command_stage = event.get("commandStage")
        mapped = pipeline_stages_for_command(command_stage)
        if name in {"live_capture_triggered", "live_capture_planned", "live_capture_worker_started"}:
            overall = "running" if name != "live_capture_planned" else "planned"
            mark_stage(stages, "source-discovery", "done")
        elif name == "worker_stage_started":
            overall = "running"
            current_command_stage = command_stage
            for pipeline_stage in mapped:
                mark_stage(stages, pipeline_stage, "active")
        elif name == "worker_stage_completed":
            overall = "running"
            current_command_stage = None
            for pipeline_stage in mapped:
                mark_stage(stages, pipeline_stage, "done")
        elif name == "worker_stage_failed":
            overall = "failed"
            current_command_stage = command_stage
            failed_command_stage = command_stage
            error = event.get("error") or error
            for pipeline_stage in mapped:
                mark_stage(stages, pipeline_stage, "failed")
        elif name == "captions_ready":
            overall = "completed"
            current_command_stage = None
            for stage_id in stages:
                if stages[stage_id]["state"] != "failed":
                    mark_stage(stages, stage_id, "done")

    return {
        "schemaVersion": 1,
        "status": overall,
        "sunday": sunday,
        "sessionId": latest_session_id or None,
        "updatedAt": updated_at,
        "runPrefix": run_prefix,
        "currentCommandStage": current_command_stage,
        "failedCommandStage": failed_command_stage,
        "error": error,
        "events": events[-25:],
        "pipelineStages": [stages[stage["id"]] for stage in PIPELINE_STAGES],
    }


def initial_pipeline_stages() -> list[dict[str, Any]]:
    return [{**stage, "state": "waiting", "statusLabel": stage["waitingLabel"]} for stage in PIPELINE_STAGES]


def mark_stage(stages: dict[str, dict[str, Any]], stage_id: str, state: str) -> None:
    stage = stages.get(stage_id)
    if not stage:
        return
    stage["state"] = state
    if state == "done":
        stage["statusLabel"] = stage["doneLabel"]
    elif state == "active":
        stage["statusLabel"] = stage["activeLabel"]
    elif state == "failed":
        stage["statusLabel"] = "失败"
    else:
        stage["statusLabel"] = stage["waitingLabel"]


def pipeline_stages_for_command(command_stage: str | None) -> list[str]:
    return list(COMMAND_STAGE_TO_PIPELINE.get(str(command_stage or ""), []))


def safe_component(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return clean.strip("._") or "unknown"


def newest_status(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    first_updated = str(first.get("updatedAt") or "")
    second_updated = str(second.get("updatedAt") or "")
    return second if second_updated > first_updated else first


def normalize_gcs_prefix(value: str | None) -> str | None:
    clean = str(value or "").strip().rstrip("/")
    if not clean:
        return None
    if not clean.startswith("gs://"):
        raise ValueError("generation progress GCS prefix must start with gs://")
    return clean


def default_generation_progress_gcs_prefix(
    artifact_bucket: str | None,
    artifact_prefix: str,
    explicit_prefix: str | None = None,
) -> str | None:
    if explicit_prefix:
        return normalize_gcs_prefix(explicit_prefix)
    if not artifact_bucket:
        return None
    clean_prefix = str(artifact_prefix or "").strip("/")
    object_prefix = "/".join(part for part in [clean_prefix, "generation-progress"] if part)
    return f"gs://{artifact_bucket}/{object_prefix}"
