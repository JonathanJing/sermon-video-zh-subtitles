"""Submit, inspect, resume or cancel an explicitly source-bound local workflow."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import timedelta
import json
from pathlib import Path
import uuid

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from .client import build_request, submit
from .contracts import ResumeSignal, SIGNAL_SCHEMA
from .fixtures import initialize, write_approval
from .worker import local_address
from .workflows import SaturdayWorkflow


async def execute(args):
    if args.action == "fixture-init":
        return {"fixtureOnly": True, "config": str(initialize(args.directory, name=args.name, duration=args.duration))}
    if args.action == "fixture-approve":
        write_approval(args.config)
        return {"fixtureOnly": True, "syntheticApprovalWritten": True}
    client = await Client.connect(local_address(args.address), namespace=args.namespace)
    if args.action == "submit":
        request = build_request(args.config, profile=args.profile, allow_execute=args.allow_execute,
            activity_timeout_seconds=args.activity_timeout, heartbeat_timeout_seconds=args.heartbeat_timeout)
        try:
            handle = await submit(client, request)
        except WorkflowAlreadyStartedError:
            return {"status": "duplicate_rejected", "workflowId": request.workflow_id(), "newExecutionStarted": False}
        return {"status": "started", "workflowId": handle.id, "runId": handle.first_execution_run_id,
                "profile": request.profile, "allowExecute": request.allow_execute}
    handle = client.get_workflow_handle(args.workflow_id)
    if args.action == "status":
        description = await handle.describe()
        state = await handle.query(SaturdayWorkflow.status, rpc_timeout=timedelta(seconds=10))
        return {"workflowId": handle.id, "serverStatus": description.status.name, "state": state}
    if args.action == "resume":
        epoch = args.recovery_epoch
        if epoch is None:
            state = await handle.query(SaturdayWorkflow.status, rpc_timeout=timedelta(seconds=10))
            epoch = state["recovery_epoch"]
        signal = ResumeSignal(SIGNAL_SCHEMA, args.signal_id or uuid.uuid4().hex, args.binding, args.reason, epoch)
        await handle.signal(SaturdayWorkflow.evidence_changed, signal)
        return {"workflowId": handle.id, "signalAcceptedByServer": True, "signalId": signal.signal_id,
                "recoveryEpoch": epoch,
                "approvalWritten": False, "note": "Worker must revalidate the original source-bound evidence"}
    if args.action == "cancel":
        await handle.cancel()
        return {"workflowId": handle.id, "cancellationRequested": True}
    if args.action == "result":
        return await asyncio.wait_for(handle.result(), timeout=args.timeout)
    raise ValueError("Unsupported command")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:17233")
    parser.add_argument("--namespace", default="default")
    commands = parser.add_subparsers(dest="action", required=True)
    start = commands.add_parser("submit")
    start.add_argument("--config", type=Path, required=True)
    start.add_argument("--profile", choices=("production", "fixture"), required=True)
    start.add_argument("--allow-execute", action="store_true")
    start.add_argument("--activity-timeout", type=float, default=25260)
    start.add_argument("--heartbeat-timeout", type=float, default=20)
    for name in ("status", "resume", "cancel", "result"):
        command = commands.add_parser(name)
        command.add_argument("--workflow-id", required=True)
        if name == "resume":
            command.add_argument("--binding", required=True)
            command.add_argument("--reason", required=True)
            command.add_argument("--signal-id")
            command.add_argument("--recovery-epoch", type=int)
        if name == "result":
            command.add_argument("--timeout", type=float, default=10)
    fixture = commands.add_parser("fixture-init")
    fixture.add_argument("--directory", type=Path, required=True)
    fixture.add_argument("--name", default="fixture-source")
    fixture.add_argument("--duration", type=float, default=.2)
    approve = commands.add_parser("fixture-approve")
    approve.add_argument("--config", type=Path, required=True)
    print(json.dumps(asyncio.run(execute(parser.parse_args(argv))), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
