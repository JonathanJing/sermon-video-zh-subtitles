#!/usr/bin/env python3
"""Spark-host runner (stdlib only): bind the dispatcher's job hold to this process, serve
the read-only admission socket for one offline GPU container, run it, close the gateway.

Mirrors experiments/spark-diagnostic-audio AdmissionGateway so the container's
SparkQwenSynthesizer passes require_bound_model_session through SPARK_EXCLUSIVE_SOCKET.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import socketserver
import stat
import struct
import subprocess
import sys
import threading


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_session_module(code_root):
    path = Path(code_root) / "packages/production/src/tongxing_production/compute/spark_exclusive_session.py"
    spec = importlib.util.spec_from_file_location("spark_exclusive_session", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdmissionGateway:
    @staticmethod
    def peer_uid(connection):
        _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        return uid

    def __init__(self, directory, session, hold, *, runner_pid):
        self.directory, self.session, self.job_id, self.runner_pid = Path(directory), session, hold["jobId"], runner_pid
        parent = self.directory.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        identity = parent.lstat()
        require(not parent.is_symlink() and identity.st_uid == os.getuid()
                and stat.S_IMODE(identity.st_mode) == 0o700, "gateway_parent_identity_rejected")
        self.directory.mkdir(mode=0o700, exist_ok=False)
        self.path = self.directory / "admission.sock"
        gateway = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    self.connection.settimeout(30)
                    require(gateway.peer_uid(self.connection) == os.getuid(), "gateway_peer_uid_rejected")
                    line = self.rfile.readline(16385)
                    require(len(line) <= 16384 and line.endswith(b"\n"), "gateway_request_too_large")
                    request = json.loads(line)
                    env = gateway.session.environment
                    require(type(request) is dict and set(request) == {"action", "session_id", "owner"}
                            and request["action"] == "require"
                            and request["session_id"] == env["SPARK_EXCLUSIVE_SESSION_ID"]
                            and request["owner"] == env["SPARK_EXCLUSIVE_SESSION_OWNER"],
                            "gateway_readonly_identity_required")
                    snapshot = gateway.session.request("status")
                    job = snapshot["session"]["jobs"].get(gateway.job_id)
                    process = next((row for row in snapshot["inventory"]["processes"]
                                    if row.get("pid") == gateway.runner_pid), None)
                    require(job is not None and job["status"] == "active"
                            and job["sessionId"] == request["session_id"] and job["owner"] == request["owner"]
                            and process is not None and not process.get("unreadable")
                            and {"pid": gateway.runner_pid, "startTicks": process["startTicks"]} in job["processes"],
                            "gateway_bound_runner_not_active")
                    response = {"result": {**gateway.session.require_ready(), "jobId": gateway.job_id}}
                except Exception as exc:  # no arguments or messages cross the container boundary
                    response = {"error": "gateway_admission_rejected:" + type(exc).__name__}
                wire = json.dumps(response).encode() + b"\n"
                if len(wire) > 65536:
                    wire = b'{"error":"gateway_response_too_large"}\n'
                self.wfile.write(wire)

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True
            allow_reuse_address = False

        self.server = Server(str(self.path), Handler)
        os.chmod(self.path, 0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        self.path.unlink(missing_ok=True)
        self.directory.rmdir()


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    os.environ.update(config["sessionEnvironment"])
    os.environ["SPARK_EXCLUSIVE_REMOTE_LOCAL"] = "1"
    session_module = load_session_module(config["codeRoot"])
    session = session_module.Client.from_environment()
    session.require_ready()
    session.bind_job(config["sparkHold"], pid=os.getpid())
    gateway = AdmissionGateway(config["gatewayDirectory"], session, config["sparkHold"], runner_pid=os.getpid())
    try:
        session.require_ready()
        Path(config["log"]).parent.mkdir(parents=True, exist_ok=True)
        with open(config["log"], "ab") as log:
            result = subprocess.run(config["command"], stdout=log, stderr=subprocess.STDOUT)
    finally:
        gateway.close()
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
