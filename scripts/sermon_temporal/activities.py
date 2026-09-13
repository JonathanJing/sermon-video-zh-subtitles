"""Heartbeating activities wrap separate project-Python processes."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import signal
import time

from temporalio import activity
from temporalio.exceptions import ApplicationError

from scripts.sermon_execution_harness import atomic_json
from .contracts import ActivityInput, Observation
from .local_io import PROJECT_PYTHON, ROOT, private_directory


async def stop_process_group(process):
    for signum in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
        try:
            # bounded_process may need 2s TERM + 2s drain + 2s reap to
            # clean its own separate child group. Do not kill its adapter first.
            await asyncio.wait_for(process.wait(), timeout=10 if signum == signal.SIGTERM else 2)
            if signum == signal.SIGTERM:
                # Normal adapter shutdown cascades cancellation to its own child
                # groups. A direct-child exit is still followed by group cleanup.
                continue
            return
        except asyncio.TimeoutError:
            continue


class Activities:
    def __init__(self, *, profile: str, state_root: Path, allow_production_execute=False,
                 project_python=PROJECT_PYTHON):
        self.profile = profile
        self.state_root = state_root.resolve()
        self.allow_production_execute = allow_production_execute
        self.project_python = Path(project_python).absolute()

    @activity.defn(name="sermon.inspect.v1")
    async def inspect(self, item: ActivityInput) -> Observation:
        return await self.run_adapter("inspect", item)

    @activity.defn(name="sermon.execute.v1")
    async def execute(self, item: ActivityInput) -> Observation:
        return await self.run_adapter("execute", item)

    async def run_adapter(self, action: str, item: ActivityInput) -> Observation:
        item.request.validate()
        if item.request.profile != self.profile:
            raise ApplicationError("Worker/request profile mismatch; fixture and production queues are isolated",
                                   type="ProfileMismatch", non_retryable=True)
        info = activity.info()
        folder = private_directory(self.state_root / hashlib.sha256(info.workflow_id.encode()).hexdigest())
        request_path = folder / "request.json"
        atomic_json(request_path, asdict(item.request))
        suffix = hashlib.sha256(f"{info.workflow_run_id}:{info.activity_id}:{info.attempt}".encode()).hexdigest()[:24]
        receipt = folder / f"{action}-{suffix}.json"
        command = [str(self.project_python), "-m", "scripts.sermon_temporal.adapter",
                   "--request", str(request_path), "--action", action,
                   "--state-dir", str(folder), "--receipt", str(receipt)]
        if item.expected_binding:
            command += ["--expected-binding", item.expected_binding]
        if self.allow_production_execute:
            command.append("--allow-production-execute")
        process = None
        started = time.monotonic()
        communicate = None
        with (folder / f"{action}-{suffix}.stderr.log").open("ab") as log:
            try:
                activity.heartbeat({"phase": "starting", "action": action, "receipt": str(receipt)})
                process = await asyncio.create_subprocess_exec(*command, cwd=ROOT,
                    stdout=asyncio.subprocess.PIPE, stderr=log, start_new_session=True,
                    env={**os.environ, "SERMON_HARNESS_GUARDED_CHILDREN": "1"})
                communicate = asyncio.create_task(process.communicate())
                interval = min(1.0, item.request.heartbeat_timeout_seconds / 3)
                while not communicate.done():
                    activity.heartbeat({"phase": "running", "action": action, "pid": process.pid,
                                        "elapsed_seconds": round(time.monotonic() - started, 2), "receipt": str(receipt)})
                    await asyncio.wait({communicate}, timeout=interval)
                output, _ = await communicate
                if process.returncode:
                    raise ApplicationError("Project adapter failed; inspect retained activity receipt and logs",
                                           type="AdapterOutcomeUnknown", non_retryable=action == "execute")
                if len(output) > 1_048_576:
                    raise ApplicationError("Adapter response exceeded the bounded observation contract",
                                           type="InvalidObservation", non_retryable=True)
                result = Observation(**json.loads(output))
                result.validate()
                return result
            except asyncio.CancelledError:
                if process is not None:
                    await asyncio.shield(stop_process_group(process))
                raise
            except BaseException:
                if process is not None and process.returncode is None:
                    await stop_process_group(process)
                raise
            finally:
                if communicate is not None and not communicate.done():
                    communicate.cancel()
                    await asyncio.gather(communicate, return_exceptions=True)
