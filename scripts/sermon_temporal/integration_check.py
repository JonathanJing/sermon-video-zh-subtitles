"""Real SDK/native-server integration, isolated synthetic inputs; never production execution."""
from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid

from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import CancelledError, WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from scripts.sermon_execution_harness import atomic_json, utc_now
from . import server
from .client import build_request, submit
from .contracts import SIGNAL_SCHEMA, ResumeSignal
from .fixtures import initialize, write_approval
from .local_io import ROOT, TEMPORAL_ROOT, file_sha, private_directory, read_json, receipt_process_alive
from .workflows import SaturdayWorkflow


async def until(check, *, timeout=45, label="condition"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = await check()
        if last:
            return last
        await asyncio.sleep(.2)
    raise AssertionError(f"Timed out waiting for {label}; last={last!r}")


async def state_when(handle, predicate, label, timeout=45):
    async def check():
        try:
            state = await handle.query(SaturdayWorkflow.status, rpc_timeout=timedelta(seconds=5))
        except RPCError as exc:
            # A killed worker's sticky queue can outlive the client query deadline.
            if exc.status in (RPCStatusCode.CANCELLED, RPCStatusCode.DEADLINE_EXCEEDED, RPCStatusCode.UNAVAILABLE):
                return None
            raise
        return state if predicate(state) else None
    return await until(check, timeout=timeout, label=label)


async def file_when(path, predicate=lambda value: True, timeout=45):
    async def check():
        value = read_json(path) if path.exists() else None
        return value if value is not None and predicate(value) else None
    return await until(check, timeout=timeout, label=str(path))


async def wake(handle, binding, reason, *, epoch=None):
    if epoch is None:
        current = await handle.query(SaturdayWorkflow.status, rpc_timeout=timedelta(seconds=10))
        epoch = current["recovery_epoch"]
    await handle.signal(SaturdayWorkflow.evidence_changed,
                        ResumeSignal(SIGNAL_SCHEMA, uuid.uuid4().hex, binding, reason, epoch))


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Check:
    def __init__(self, root):
        self.root = private_directory(root)
        self.worker = None
        self.worker_serial = 0
        self.port, self.ui_port = free_port(), free_port()
        while self.ui_port == self.port:
            self.ui_port = free_port()
        self.address = f"127.0.0.1:{self.port}"
        self.report = {"schemaVersion": "sermon-temporal-integration-v1", "startedAt": utc_now(),
                       "scope": "actual-sdk-native-server-synthetic-only", "root": str(root), "checks": {}}
        self.report["sourceSha256"] = {str(path.relative_to(ROOT)): file_sha(path)
            for path in sorted((ROOT / "scripts/sermon_temporal").glob("*.py"))}
        self.report["runtime"] = read_json(TEMPORAL_ROOT / "runtime/runtime-manifest.json")
        self.report["dependencySha256"] = {name: file_sha(ROOT / name) for name in (
            "scripts/sermon_execution_harness.py", "scripts/sermon_guarded_command.py", "scripts/run_saturday_harness.py",
            "scripts/sermon_production_supervisor.py", "experiments/sermon-dubbing-poc/continue_saturday_dubbing.py")}

    async def start_server(self):
        record = await asyncio.to_thread(server.start, self.root / "server", port=self.port, ui_port=self.ui_port)
        self.report["server"] = record
        return await Client.connect(self.address)

    async def start_worker(self):
        self.worker_serial += 1
        log_path = self.root / f"worker-{self.worker_serial}.log"
        with log_path.open("ab") as log:
            self.worker = subprocess.Popen([sys.executable, "-m", "scripts.sermon_temporal.worker",
                "--address", self.address, "--profile", "fixture", "--state-root", str(self.root / "worker-state")],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        async def ready():
            if self.worker.poll() is not None:
                raise AssertionError(f"Worker startup failed; see {log_path}")
            return "Worker ready:" in log_path.read_text(errors="replace")
        await until(ready, label="worker ready")

    async def stop_worker(self, hard=False):
        if self.worker and self.worker.poll() is None:
            # Popen identifies only the process created here. Hard loss deliberately
            # leaves the adapter's separate group alive to test uncertain outcomes.
            self.worker.send_signal(signal.SIGKILL if hard else signal.SIGTERM)
            try:
                await asyncio.to_thread(self.worker.wait, timeout=10)
            except subprocess.TimeoutExpired:
                self.worker.kill()
                await asyncio.to_thread(self.worker.wait, timeout=5)

    def fixture(self, name, duration=.2, approved=False, nested=False):
        config = initialize(self.root / name, name=f"{self.root.name}-{name}", duration=duration)
        if nested:
            data = read_json(config)
            data["nestedCancellationFixture"] = True
            data["nestedDepth"] = 3
            atomic_json(config, data)
        if approved:
            write_approval(config)
        request = build_request(config, profile="fixture", allow_execute=True,
                                activity_timeout_seconds=90, heartbeat_timeout_seconds=3)
        return config, request

    async def duplicate(self, client, request):
        try:
            await submit(client, request)
        except WorkflowAlreadyStartedError:
            return True
        raise AssertionError("Duplicate workflow submission was accepted")

    async def run(self):
        client = await self.start_server()
        await self.start_worker()
        config, request = self.fixture("review")
        handle = await submit(client, request)
        initial = await state_when(handle, lambda s: s["phase"] == "waiting_evidence", "initial review wait")
        assert initial["execution_attempts"] == 0 and not initial["observation"]["approval_valid"]
        await self.duplicate(client, request)
        original_run = (await handle.describe()).run_id
        await self.stop_worker()
        await asyncio.to_thread(server.stop, self.root / "server")
        assert (self.root / "server" / "temporal.sqlite").exists()
        client = await self.start_server()
        await self.start_worker()
        handle = client.get_workflow_handle(request.workflow_id())
        restored = await state_when(handle, lambda s: s["phase"] == "waiting_evidence", "persistent review wait")
        assert (await handle.describe()).run_id == original_run
        assert restored["observation"] == initial["observation"]
        await wake(handle, "0" * 64, "Synthetic stale binding must be rejected")
        await state_when(handle, lambda s: s["rejected_signals"] == 1, "stale signal rejection")
        binding = initial["observation"]["source_binding"]
        # An exact current signal without the existing human approval must not run.
        await wake(handle, binding, "Synthetic missing approval check")
        no_approval = await state_when(handle, lambda s: s["accepted_signals"] == 1 and s["phase"] == "waiting_evidence",
                                       "signal without approval")
        assert no_approval["execution_attempts"] == 0
        write_approval(config)
        timeline_path = config.parent / "timeline.json"
        timeline = read_json(timeline_path)
        timeline["revision"] = 2
        atomic_json(timeline_path, timeline)
        await wake(handle, binding, "Synthetic changed timeline invalidates prior approval and signal")
        changed = await state_when(handle, lambda s: s["rejected_signals"] == 2 and s["phase"] == "waiting_evidence",
                                   "timeline source gate")
        assert changed["execution_attempts"] == 0 and not changed["observation"]["approval_valid"]
        assert changed["observation"]["source_binding"] != binding
        write_approval(config)
        await wake(handle, changed["observation"]["source_binding"], "Synthetic fresh existing-validator approval")
        result = await asyncio.wait_for(handle.result(), 30)
        assert result["phase"] == "fixture_completed" and result["execution_attempts"] == 1
        assert read_json(config.parent / "starts.json")["count"] == 1
        await self.duplicate(client, request)
        self.report["checks"]["persistence_and_bound_review"] = {"pass": True, "workflowId": request.workflow_id(),
            "configSha256": request.config_sha256, "sourceSha256": file_sha(config.parent / "source.bin"),
            "runIdBeforeAndAfterRestart": original_run, "duplicateRunningRejected": True, "duplicateCompletedRejected": True,
            "signalCannotReplaceApproval": True, "changedTimelineRejected": True, "result": result}
        self.save()

        config, request = self.fixture("cancel", duration=30, approved=True, nested=True)
        handle = await submit(client, request)
        started = await file_when(config.parent / "starts.json")
        nested = [await file_when(config.parent / f"nested-child-{depth}.json") for depth in range(1, 4)]
        assert nested[0]["ignoresSigterm"] and all(receipt_process_alive(child) for child in nested)
        description = await handle.describe()
        assert any(a.heartbeat_details.payloads for a in description.raw_description.pending_activities)
        await handle.cancel()
        try:
            await asyncio.wait_for(handle.result(), 15)
        except WorkflowFailureError as exc:
            assert isinstance(exc.cause, CancelledError), str(exc)
        else:
            raise AssertionError("Cancelled workflow unexpectedly succeeded")
        receipt = await file_when(Path(started["receipt"]), lambda r: r["status"] == "cancelled")
        assert not receipt_process_alive(receipt) and not any(receipt_process_alive(child) for child in nested)
        assert not (config.parent / "result.json").exists()
        self.report["checks"]["cancellation"] = {"pass": True, "workflowId": request.workflow_id(),
            "heartbeatObserved": True, "adapterStopped": True, "nestedSigtermIgnoringChildStopped": True,
            "nestedChildren": nested, "nestedDepth": 3, "receipt": receipt}
        self.save()

        config, request = self.fixture("worker-loss", duration=30, approved=True)
        handle = await submit(client, request)
        started = await file_when(config.parent / "starts.json")
        executing = await state_when(handle, lambda s: s["phase"] == "executing", "execution before worker loss")
        old_epoch = executing["recovery_epoch"]
        await wake(handle, executing["observation"]["source_binding"], "Synthetic pre-failure queued signal", epoch=old_epoch)
        await state_when(handle, lambda s: s["rejected_signals"] == 1, "execution-time signal rejection")
        await self.stop_worker(hard=True)
        await self.start_worker()
        uncertain = await state_when(handle, lambda s: s["phase"] == "waiting_reconciliation",
                                     "worker loss reconciliation", timeout=35)
        assert uncertain["execution_attempts"] == 1 and uncertain["observation"]["runtime_busy"]
        assert uncertain["recovery_epoch"] == old_epoch + 1
        await wake(handle, uncertain["observation"]["source_binding"], "Synthetic delayed pre-failure signal", epoch=old_epoch)
        await state_when(handle, lambda s: s["rejected_signals"] == 2 and s["phase"] == "waiting_reconciliation",
                         "delayed old recovery epoch rejected")
        assert read_json(config.parent / "starts.json")["count"] == 1
        await file_when(config.parent / "result.json", timeout=40)
        still_waiting = await state_when(handle, lambda s: s["phase"] == "waiting_reconciliation", "fresh signal still required")
        assert still_waiting["execution_attempts"] == 1
        await wake(handle, uncertain["observation"]["source_binding"], "Synthetic retained receipt reconciliation")
        result = await asyncio.wait_for(handle.result(), 20)
        assert result["phase"] == "fixture_completed" and result["execution_attempts"] == 1
        assert read_json(config.parent / "starts.json")["count"] == 1
        history = await handle.fetch_history()
        events = [event for event in history.events if event.HasField("activity_task_scheduled_event_attributes")]
        executions = [event.activity_task_scheduled_event_attributes for event in events
                      if event.activity_task_scheduled_event_attributes.activity_type.name == "sermon.execute.v1"]
        assert len(executions) == 1 and executions[0].retry_policy.maximum_attempts == 1
        self.report["checks"]["worker_loss_no_execution_retry"] = {"pass": True, "workflowId": request.workflow_id(),
            "uncertainState": uncertain, "executionSchedules": 1, "executionMaxAttempts": 1, "localStarts": 1, "result": result}
        self.report["checks"]["worker_loss_no_execution_retry"]["queuedAndDelayedOldSignalsRejected"] = True
        self.save()

        config, request = self.fixture("inspect-recovery")
        saved = config.with_suffix(".saved")
        config.rename(saved)
        handle = await submit(client, request)
        failed = await state_when(handle, lambda s: s["phase"] == "waiting_evidence" and not s["observation"],
                                  "initial inspection failure")
        saved.rename(config)
        await wake(handle, failed["initial_inspection_binding"], "Synthetic restored identical config for inspection")
        recovered = await state_when(handle, lambda s: s["phase"] == "waiting_evidence" and bool(s["observation"]),
                                     "initial inspection recovery")
        assert recovered["execution_attempts"] == 0 and recovered["rejected_signals"] == 1
        write_approval(config)
        await wake(handle, recovered["observation"]["source_binding"], "Synthetic actual evidence binding")
        result = await asyncio.wait_for(handle.result(), 20)
        assert result["execution_attempts"] == 1
        self.report["checks"]["initial_inspection_recovery"] = {"pass": True, "workflowId": request.workflow_id(),
            "reinspectionCouldNotExecute": True, "result": result}
        self.report["status"] = "PASS"

    def save(self):
        atomic_json(self.root / "integration-report.json", self.report)

    async def finish(self):
        await self.stop_worker()
        # Only this unique test server is stopped. The operational local server
        # and production queue worker are intentionally outside this root.
        self.report["cleanup"] = await asyncio.to_thread(server.stop, self.root / "server")
        self.report["finishedAt"] = utc_now()
        self.save()


async def main_async(root):
    check = Check(root)
    try:
        await check.run()
    except BaseException as exc:
        check.report.update(status="FAIL", errorType=type(exc).__name__, error=str(exc))
        raise
    finally:
        await check.finish()
        print(json.dumps({"status": check.report.get("status"), "report": str(root / "integration-report.json")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    root = (args.root or TEMPORAL_ROOT / ("integration-" + uuid.uuid4().hex[:12])).resolve()
    if not root.is_relative_to(TEMPORAL_ROOT.resolve()) or root == TEMPORAL_ROOT.resolve() or root.exists():
        raise ValueError("Use a new unique child directory under artifacts/temporal; existing results are preserved")
    asyncio.run(main_async(root))


if __name__ == "__main__":
    main()
