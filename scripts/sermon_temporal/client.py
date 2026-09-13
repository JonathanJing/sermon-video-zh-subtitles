"""Request construction and duplicate-safe Temporal submission."""
from dataclasses import asdict
from pathlib import Path

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy

from .contracts import REQUEST_SCHEMA, Request
from .local_io import file_sha, read_json
from .workflows import SaturdayWorkflow


def build_request(config_path: Path, *, profile: str, allow_execute=False,
                  activity_timeout_seconds=25260, heartbeat_timeout_seconds=20) -> Request:
    path = config_path.resolve()
    config = read_json(path)
    request = Request(schema_version=REQUEST_SCHEMA, profile=profile, sunday=config["sunday"],
        source_key=config["sourceKey"], config_path=str(path), config_sha256=file_sha(path),
        allow_execute=allow_execute, activity_timeout_seconds=activity_timeout_seconds,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds)
    request.validate()
    expected_schema = "sermon-temporal-fixture-v1" if profile == "fixture" else "sermon-temporal-operator-v1"
    if config.get("schemaVersion") != expected_schema:
        raise ValueError("Client profile does not match configuration schema")
    return request


async def submit(client: Client, request: Request):
    request.validate()
    return await client.start_workflow(SaturdayWorkflow.run, request, id=request.workflow_id(),
        task_queue=request.task_queue(), id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
        memo={"profile": request.profile, "sunday": request.sunday, "source_key": request.source_key,
              "configuration_sha256": request.config_sha256, "approval_granted_by_temporal": False},
        static_summary="Saturday source-bound orchestration; existing approvals remain authoritative")
