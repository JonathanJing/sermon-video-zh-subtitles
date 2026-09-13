"""Manage one loopback, SQLite-backed local Temporal server with PID identity checks."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import time

from scripts.sermon_execution_harness import atomic_json, utc_now
from .local_io import TEMPORAL_ROOT, file_sha, private_directory, process_identity, read_json, receipt_process_alive

CLI_VERSION = "1.8.3"
DEFAULT_BINARY = TEMPORAL_ROOT / "runtime" / "temporal"


@contextmanager
def manager_lock(root: Path):
    private_directory(root)
    with (root / ".manager.lock").open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield


def port_available(port: int) -> bool:
    with socket.socket() as sock:
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def health(binary: Path, port: int) -> bool:
    result = subprocess.run([str(binary), "operator", "cluster", "health", "--address", f"127.0.0.1:{port}",
                             "--command-timeout", "3s", "--disable-config-env", "--disable-config-file"],
                            capture_output=True, text=True, timeout=5, check=False)
    return result.returncode == 0 and "SERVING" in result.stdout


def status(root: Path) -> dict:
    root = root.resolve()
    path = root / "server.json"
    if not path.is_file():
        return {"schemaVersion": "sermon-temporal-server-v1", "status": "not_started", "root": str(root)}
    record = read_json(path)
    owned = receipt_process_alive(record)
    binary = Path(record["binary"])
    executable_unchanged = binary.is_file() and file_sha(binary) == record["binarySha256"]
    healthy = owned and executable_unchanged and health(binary, record["port"])
    return {**record, "status": "running" if healthy else "unhealthy" if owned else "stopped_or_identity_changed",
            "ownedProcessAlive": owned, "healthy": healthy, "sqliteExists": Path(record["database"]).is_file(),
            "ui": f"http://127.0.0.1:{record['uiPort']}", "deploymentScope": "single-host-persistent-local-not-ha"}


def start(root: Path, *, binary=DEFAULT_BINARY, port=17233, ui_port=18233) -> dict:
    root, binary = root.resolve(), Path(binary).resolve()
    if any(type(value) is not int or not 1024 <= value <= 65535 for value in (port, ui_port)) or port == ui_port:
        raise ValueError("Use two distinct unprivileged loopback ports")
    with manager_lock(root):
        current = status(root)
        if current.get("ownedProcessAlive"):
            if current["port"] != port or current["uiPort"] != ui_port or current["binary"] != str(binary):
                raise ValueError("Existing managed server has different arguments; preserve it and stop explicitly first")
            return current
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError("Install the pinned, checksum-verified Temporal CLI in the isolated runtime first")
        version = subprocess.run([str(binary), "--version"], capture_output=True, text=True, timeout=5, check=True).stdout.strip()
        if f"temporal version {CLI_VERSION} " not in version:
            raise ValueError("CLI version differs from the pinned local persistence runtime")
        if not port_available(port) or not port_available(ui_port):
            raise ValueError("A requested loopback port is already in use; no unrelated process will be stopped")
        database = root / "temporal.sqlite"
        command = [str(binary), "server", "start-dev", "--ip", "127.0.0.1", "--ui-ip", "127.0.0.1",
            "--port", str(port), "--ui-port", str(ui_port), "--db-filename", str(database),
            "--ui-disable-news-fetch", "--log-level", "warn", "--disable-config-env", "--disable-config-file"]
        with (root / "server.log").open("ab") as log:
            process = subprocess.Popen(command, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                       start_new_session=True, close_fds=True)
        record = {"schemaVersion": "sermon-temporal-server-v1", "pid": process.pid,
            "process_identity": process_identity(process.pid), "binary": str(binary), "binarySha256": file_sha(binary),
            "version": version, "port": port, "uiPort": ui_port, "database": str(database), "startedAt": utc_now()}
        atomic_json(root / "server.json", record)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Temporal server exited during startup; inspect retained server.log")
            if health(binary, port):
                return status(root)
            time.sleep(.25)
        raise RuntimeError("Managed Temporal server did not become healthy; retained PID and logs identify it")


def stop(root: Path) -> dict:
    root = root.resolve()
    with manager_lock(root):
        current = status(root)
        if not current.get("ownedProcessAlive"):
            return {**current, "stoppedByThisCall": False}
        pid = current["pid"]
        # Never trust a saved PID alone: command/start identity must still match.
        if process_identity(pid) != current["process_identity"]:
            raise ValueError("PID identity changed; refusing to signal an unrelated process")
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and receipt_process_alive(current):
            time.sleep(.1)
        if receipt_process_alive(current):
            os.killpg(pid, signal.SIGKILL)
        return {**status(root), "stoppedByThisCall": True, "databasePreserved": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    parser.add_argument("--root", type=Path, default=TEMPORAL_ROOT / "server")
    parser.add_argument("--binary", type=Path, default=DEFAULT_BINARY)
    parser.add_argument("--port", type=int, default=17233)
    parser.add_argument("--ui-port", type=int, default=18233)
    args = parser.parse_args(argv)
    result = start(args.root, binary=args.binary, port=args.port, ui_port=args.ui_port) if args.action == "start" else (
        stop(args.root) if args.action == "stop" else status(args.root))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
