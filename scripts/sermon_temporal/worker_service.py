"""Manage the local background production worker with execution always disabled."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from scripts.sermon_execution_harness import atomic_json, utc_now
from .local_io import ROOT, TEMPORAL_ROOT, process_identity, read_json, receipt_process_alive
from .server import manager_lock

RECEIPT = TEMPORAL_ROOT / "production-worker.json"
LOG = TEMPORAL_ROOT / "production-worker.log"


def status():
    if not RECEIPT.exists():
        return {"status": "not_started", "receipt": str(RECEIPT)}
    record = read_json(RECEIPT)
    alive = receipt_process_alive(record)
    return {**record, "status": "running" if alive else "stopped_or_identity_changed", "ownedProcessAlive": alive,
            "receipt": str(RECEIPT), "healthScope": "process_identity_only_not_activity_success"}


def stop():
    with manager_lock(TEMPORAL_ROOT / "worker-service"):
        record = status()
        if not record.get("ownedProcessAlive"):
            return {**record, "stoppedByThisCall": False}
        # Never signal a stored PID without its matching start/command identity.
        if process_identity(record["pid"]) != record["process_identity"]:
            raise ValueError("Worker PID identity changed; refusing to signal it")
        os.killpg(record["pid"], signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and receipt_process_alive(record):
            time.sleep(.1)
        if receipt_process_alive(record):
            os.killpg(record["pid"], signal.SIGKILL)
        return {**status(), "stoppedByThisCall": True, "evidencePreserved": True}


def start():
    with manager_lock(TEMPORAL_ROOT / "worker-service"):
        current = status()
        if current.get("ownedProcessAlive"):
            if current.get("productionExecuteEnabled") is not False:
                raise ValueError("Existing managed worker is not explicitly read-only; preserve and inspect it")
            return current
        offset = LOG.stat().st_size if LOG.exists() else 0
        with LOG.open("ab") as log:
            process = subprocess.Popen([str(TEMPORAL_ROOT / "runtime/venv/bin/python"), "-m",
                "scripts.sermon_temporal.worker", "--profile", "production"], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, close_fds=True)
        record = {"schemaVersion": "sermon-temporal-worker-service-v1", "pid": process.pid,
            "process_identity": process_identity(process.pid), "profile": "production", "productionExecuteEnabled": False,
            "log": str(LOG), "startedAt": utc_now()}
        atomic_json(RECEIPT, record)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Read-only worker exited during startup; see retained production-worker.log")
            with LOG.open("rb") as log:
                log.seek(offset)
                ready = b"Worker ready:" in log.read()
            if ready:
                record["process_identity"] = process_identity(process.pid)
                atomic_json(RECEIPT, record)
                return status()
            time.sleep(.1)
        raise RuntimeError("Worker did not report readiness; retained receipt can safely stop the owned process")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    args = parser.parse_args(argv)
    print(json.dumps({"start": start, "stop": stop, "status": status}[args.action](), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
