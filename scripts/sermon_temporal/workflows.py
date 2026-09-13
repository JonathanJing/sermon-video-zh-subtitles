"""Only deterministic control flow is replayed; all effects live in Activities."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError, is_cancelled_exception

from .contracts import ActivityInput, Observation, Request, ResumeSignal, SIGNAL_SCHEMA, STATE_SCHEMA, digest


@workflow.defn(name="SermonSaturdayV1")
class SaturdayWorkflow:
    def __init__(self):
        self.state = {"schema_version": STATE_SCHEMA, "phase": "starting", "observation": None,
                      "execution_attempts": 0, "rejected_signals": 0, "accepted_signals": 0,
                      "recovery_epoch": 0,
                      "workflow_complete": False, "audio_published": False}
        self.pending: list[ResumeSignal] = []
        self.seen_signals: set[str] = set()

    @workflow.query
    def status(self) -> dict:
        return self.state

    @workflow.signal
    def evidence_changed(self, signal: ResumeSignal):
        current = self.state.get("observation") or {}
        expected = current.get("source_binding") or self.state.get("initial_inspection_binding")
        if (signal.schema_version != SIGNAL_SCHEMA or not signal.signal_id or len(signal.signal_id) > 128
                or not signal.reason.strip() or len(signal.reason) > 2000
                or self.state["phase"] == "executing"
                or type(signal.recovery_epoch) is not int or signal.recovery_epoch != self.state["recovery_epoch"]
                or signal.expected_binding != expected):
            self.state["rejected_signals"] += 1
            return
        if signal.signal_id in self.seen_signals:
            return
        self.seen_signals.add(signal.signal_id)
        self.pending.append(signal)
        self.state["accepted_signals"] += 1

    async def inspect(self, request: Request) -> Observation:
        result = await workflow.execute_activity("sermon.inspect.v1", ActivityInput(request), result_type=Observation,
            start_to_close_timeout=timedelta(seconds=min(request.activity_timeout_seconds, 300)),
            heartbeat_timeout=timedelta(seconds=request.heartbeat_timeout_seconds),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1),
                                     maximum_interval=timedelta(seconds=5)),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
        result.validate()
        self.state["observation"] = asdict(result)
        return result

    @workflow.run
    async def run(self, request: Request) -> dict:
        try:
            request.validate()
        except ValueError as exc:
            raise ApplicationError(str(exc), type="InvalidRequest", non_retryable=True) from exc
        self.state.update(profile=request.profile, sunday=request.sunday, source_key=request.source_key,
            initial_inspection_binding=digest(["initial_inspection_only", request.profile, request.sunday,
                                              request.source_key, request.config_sha256]))
        uncertain = False
        require_signal = False
        previous_action = ""
        while True:
            try:
                if require_signal:
                    self.state["phase"] = "waiting_reconciliation" if uncertain else "waiting_evidence"
                    await workflow.wait_condition(lambda: bool(self.pending))
                    signal = self.pending.pop(0)
                else:
                    signal = None
                self.state["phase"] = "inspecting"
                try:
                    observed = await self.inspect(request)
                except ActivityError as exc:
                    if is_cancelled_exception(exc):
                        raise asyncio.CancelledError from exc
                    self.state["phase"] = "waiting_inspection_recovery"
                    self.state["last_error"] = "Read-only inspection could not finish; no execution was retried"
                    require_signal = True
                    continue
                # A signal wakes validation; it is never an approval. Changes to
                # the underlying source/timeline invalidate even accepted signals.
                if signal is not None and signal.expected_binding != observed.source_binding:
                    self.state["rejected_signals"] += 1
                    self.state["last_error"] = "Source/timeline changed; signal did not authorize this evidence"
                    require_signal = True
                    continue
                if observed.terminal:
                    self.state["phase"] = "fixture_completed" if request.profile == "fixture" else "candidate_handoff_ready"
                    self.state["completion_scope"] = observed.terminal_scope
                    return self.state
                if not request.allow_execute:
                    self.state["phase"] = "inspection_only"
                    return self.state
                if observed.runtime_busy or not observed.executable or (uncertain and signal is None):
                    require_signal = True
                    continue
                if observed.action_token == previous_action and signal is None:
                    self.state["last_error"] = "No new executable evidence; further execution requires a bound resume signal"
                    require_signal = True
                    continue
                previous_action = observed.action_token
                self.state["phase"] = "executing"
                self.state["execution_attempts"] += 1
                try:
                    result = await workflow.execute_activity("sermon.execute.v1",
                        ActivityInput(request, observed.source_binding), result_type=Observation,
                        start_to_close_timeout=timedelta(seconds=request.activity_timeout_seconds),
                        heartbeat_timeout=timedelta(seconds=request.heartbeat_timeout_seconds),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                        cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED)
                    result.validate()
                    self.state["observation"] = asdict(result)
                    uncertain = False
                except ActivityError as exc:
                    if is_cancelled_exception(exc):
                        raise asyncio.CancelledError from exc
                    # max_attempts=1 also prevents heartbeat/worker-loss retries.
                    # Fresh inspection can recover a finished receipt; otherwise
                    # wait for an explicit signal before another execution.
                    self.state["recovery_epoch"] += 1
                    self.pending.clear()
                    uncertain = True
                    self.state["last_error"] = "Execution outcome unknown; inspecting receipts before any possible resume"
                require_signal = False
            except asyncio.CancelledError:
                self.state["phase"] = "cancelled"
                self.state["last_error"] = "Cancellation requested; remote outcome still belongs to existing recovery checks"
                raise
