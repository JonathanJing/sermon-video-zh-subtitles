"""Fail-closed Spark session checks for real Tongxing production adapters.

Tests can explicitly inject a verifier. There is no environment mock bypass;
the CLI never supplies that seam. Completed cache replay remains independent
of the live session, while every real adapter call checks current admission.
"""
from __future__ import annotations
import inspect
import os
from pathlib import Path
import socket
import sys


def require_session(*, verifier=None):
    if verifier is not None:
        return verifier()
    from scripts.spark_exclusive_session import Client
    return _checked_receipt(Client.from_environment().require_ready())


def _checked_receipt(receipt):
    if os.environ.get("SPARK_EXCLUSIVE_SOCKET") and (
            not isinstance(receipt, dict) or not isinstance(receipt.get("jobId"), str)
            or not receipt["jobId"]):
        from scripts.spark_exclusive_session import SessionError
        raise SessionError("container_parent_job_binding_required")
    return receipt


def _native_process_identity():
    if not sys.platform.startswith("linux"):
        from scripts.spark_exclusive_session import SessionError
        raise SessionError("model_session_requires_bound_live_parent")
    # /proc fields after the parenthesized comm begin with field 3; starttime
    # is field 22. The exact start tick rejects a recycled Linux PID.
    stat = Path("/proc/self/stat").read_text().rsplit(")", 1)[1].split()
    return (os.getpid(), int(stat[19]), socket.gethostname(),
            Path("/proc/sys/kernel/random/boot_id").read_text().strip())


def require_bound_model_session(*, verifier=None):
    """A live parent hold must own this process before any CUDA/model load."""
    if verifier is not None:
        return verifier()
    from scripts.spark_exclusive_session import Client, Engine, SessionError
    client = Client.from_environment()
    receipt = _checked_receipt(client.require_ready())
    if os.environ.get("SPARK_EXCLUSIVE_SOCKET"):
        return receipt  # Gateway verifies the active bound host runner.
    job_id = os.environ.get("SPARK_EXCLUSIVE_JOB_ID")
    if not job_id:
        raise SessionError("model_session_requires_bound_live_parent")
    current = client.request("status")
    state, inventory = current["session"], current["inventory"]
    job = state["jobs"].get(job_id)
    pid, ticks, host, boot_id = _native_process_identity()
    own = next((row for row in inventory["processes"] if row.get("pid") == pid), None)
    if (state["sessionId"] != client.session_id or state["owner"] != client.owner
            or state["status"] != "running" or not job or job["status"] != "active"
            or job["sessionId"] != client.session_id or job["owner"] != client.owner
            or inventory["host"] != host or inventory["bootId"] != boot_id
            or receipt["bootId"] != boot_id or not own or own.get("unreadable")
            or own.get("startTicks") != ticks
            or pid not in Engine.descendants(inventory["processes"],
                [(row["pid"], row["startTicks"]) for row in job["processes"]])):
        raise SessionError("model_session_requires_bound_live_parent")
    return {**receipt, "jobId": job_id}


class SessionBoundCaller:
    """Keep transport protocol attributes and check before new real work."""
    def __init__(self, caller, *, verifier=None, purpose="production-model-call"):
        self.caller = caller
        self.verifier = verifier
        self.purpose = purpose

    def __getattr__(self, name):
        return getattr(self.caller, name)

    def admit_resource(self, payload):
        require_session(verifier=self.verifier)
        admit = getattr(self.caller, "admit_resource", None)
        return admit(payload) if admit is not None else None

    def __call__(self, *args, **kwargs):
        # Reject invalid adapter calls before reserving a durable dispatcher
        # hold. Python performs this same binding before entering the callable.
        try:
            inspect.signature(self.caller).bind(*args, **kwargs)
        except (TypeError, ValueError) as exc:
            from scripts.spark_exclusive_session import SessionError
            raise SessionError("model_caller_arguments_invalid_before_dispatch") from exc
        if self.verifier is not None:
            require_session(verifier=self.verifier)
            return self.caller(*args, **kwargs)
        from scripts.spark_exclusive_session import Client
        client = Client.from_environment()
        if os.environ.get("SPARK_EXCLUSIVE_SOCKET"):
            # The read-only container gateway authenticates its active parent
            # job. That durable parent hold protects the entire child process;
            # containers cannot create, release, or restore session state.
            _checked_receipt(client.require_ready())
            return self.caller(*args, **kwargs)
        # start_job checks live admission and creates the durable hold under
        # the same host lock, so finish cannot race between check and dispatch.
        hold = client.start_job(self.purpose)
        try:
            result = self.caller(*args, **kwargs)
        except BaseException:
            try:
                client.end_job(hold, process_exited=False, outcome="unknown")
            except Exception:
                pass  # Never replace the original error or release unknown work.
            raise
        client.end_job(hold, process_exited=True, outcome="known_terminal")
        return result
