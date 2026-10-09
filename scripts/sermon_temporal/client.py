"""Request construction and duplicate-safe Temporal submission."""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temporalio.client import Client

from .contracts import REQUEST_SCHEMA, Request, validate_configuration_profile
from .local_io import file_sha, read_json


def build_request(config_path: Path, *, profile: str, allow_execute=False,
                  activity_timeout_seconds=25260, heartbeat_timeout_seconds=20) -> Request:
    path = config_path.resolve()
    config = read_json(path)
    request = Request(schema_version=REQUEST_SCHEMA, profile=profile, sunday=config["sunday"],
        source_key=config["sourceKey"], config_path=str(path), config_sha256=file_sha(path),
        allow_execute=allow_execute, activity_timeout_seconds=activity_timeout_seconds,
        heartbeat_timeout_seconds=heartbeat_timeout_seconds)
    request.validate()
    validate_configuration_profile(config, profile)
    return request


async def submit(client: Client, request: Request):
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
    from .workflows import SaturdayWorkflow
    request.validate()
    return await client.start_workflow(SaturdayWorkflow.run, request, id=request.workflow_id(),
        task_queue=request.task_queue(), id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
        memo={"profile": request.profile, "sunday": request.sunday, "source_key": request.source_key,
              "configuration_sha256": request.config_sha256, "approval_granted_by_temporal": False},
        static_summary="Saturday source-bound orchestration; existing approvals remain authoritative")


async def submit_unified(client: Client, request):
    """Submit only an explicitly transferred run; never create another ledger."""
    from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
    from .unified import UnifiedRequest, project_call
    from .contracts import QUEUE_PREFIX
    if not isinstance(request, UnifiedRequest):
        raise ValueError('UnifiedRequest required')
    state = project_call("inspect", request)
    from temporalio.exceptions import WorkflowAlreadyStartedError
    workflow_id='unified-' + request.run_key + '-r' + str(state['runRevision'])
    try:
        return await client.start_workflow('SermonUnifiedV1', request,
            id=workflow_id, task_queue=QUEUE_PREFIX + 'production',
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            id_conflict_policy=WorkflowIDConflictPolicy.FAIL,
            memo={'plan_hash': request.plan_hash, 'approval_granted_by_temporal': False})
    except WorkflowAlreadyStartedError:
        handle=client.get_workflow_handle(workflow_id)
        await handle.signal('evidence_changed')
        return handle
