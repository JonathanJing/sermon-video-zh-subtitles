"""Agents API adapter for the existing guarded post-live production tools.

The remote session chooses among named operations. Credentials, subprocess
commands and human-approval writes remain outside the agent's tool interface.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any
import uuid

from scripts import sermon_accounting, sermon_production_supervisor as production
from scripts import sermon_end_to_end as workflow
from scripts.sermon_agents_api import AgentsAPIClient, AgentsAPIError, run_agent_session, _write_json


ALLOWED_ACTIONS = frozenset({
    "wait_for_source", "inspect_state", "waiting_for_matching_sunday", "restore_artifact_access",
    "request_window_approval", "inspect_publication_evidence", "complete", "inspect_quality_evidence",
    "review_quality_failure", "inspect_generation_failure", "wait_for_active_run", "run_timeline_probe",
    "waiting_for_source", "waiting_for_post_live", "operator_download_handoff",
    "run_reading_pdf_generation", "resume_failed_timeline", "inspect_timeline_failure", "inspect_unrecognized_state",
})


ACTION_STAGES = {
    "run_timeline_probe": "timeline",
    "resume_failed_timeline": "timeline",
    "run_reading_pdf_generation": "generation",
}

ALLOWED_ACTIONS = ALLOWED_ACTIONS | frozenset(workflow.ACTIONS + workflow.WAIT_ACTIONS)
ACTION_STAGES.update({action: "release_" + action for action in workflow.ACTIONS})


def executable_stage(snapshot: dict) -> str | None:
    recommendation = snapshot.get("recommendedAction") or {}
    if recommendation.get("humanActionRequired"):
        return None
    action = recommendation.get("action")
    return ACTION_STAGES.get(action) if isinstance(action, str) else None


def safe_workflow_job(value):
    if not isinstance(value, dict):
        return {}
    status = value.get("status")
    job_id = value.get("jobId")
    if not isinstance(status, str) or status not in {"queued", "running", "succeeded", "failed", "uncertain"} or not isinstance(job_id, str) or not re.fullmatch(r"[a-f0-9]{64}", job_id):
        return {}
    return {"jobId": job_id, "status": status}


def remote_snapshot(snapshot: dict, sunday: str) -> dict:
    """Explicit outbound allowlist: date, action enum and evidence booleans only.

    No paths, config, URLs, text, identities, approval details, logs or secrets.
    The complete snapshot stays in the local report for the operator.
    """
    from datetime import date
    recommendation = snapshot.get("recommendedAction") or {}
    action = recommendation.get("action")
    if not isinstance(action, str) or action not in ALLOWED_ACTIONS:
        action = "inspect_unrecognized_state"
    generation = snapshot.get("generation") or {}
    quality = snapshot.get("quality") or {}
    return {
        **({"workflowComplete": snapshot.get("workflowComplete") is True, "workflowScope": "page_release",
             "workflowJob": safe_workflow_job(snapshot.get("workflowJob"))}
           if snapshot.get("workflowScope") == "page_release" else {}),
        "schemaVersion": "sermon-agent-state-minimal-v2" if snapshot.get("workflowScope") == "page_release" else "sermon-agent-state-minimal-v1", "sunday": date.fromisoformat(sunday).isoformat(),
        "recommendedAction": {"action": action, "reasonCode": action,
                              "humanActionRequired": recommendation.get("humanActionRequired") is True},
        "sourceAvailable": bool(snapshot.get("source") or snapshot.get("liveSource")),
        "timelinePresent": bool(snapshot.get("timeline")),
        "windowApprovalValid": (snapshot.get("windowApproval") or {}).get("valid") is True,
        "generationCompleted": generation.get("status") == "completed",
        "publicationVerified": (generation.get("publication") or {}).get("status") == "pass",
        "qualityPassed": {key: (quality.get(key) or {}).get("status") == "pass"
                          for key in ("readingEdition", "readingPdf", "sermonInterpretationPdf")},
        "activeStageLeases": {key: bool((snapshot.get("activeLeases") or {}).get(key))
                              for key in ("timeline", "generation")},
    }


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str,
                                    allow_nan=False).encode()).hexdigest()


def read_object(path: Path) -> dict:
    if path.is_symlink():
        raise AgentsAPIError("symlink_state_not_allowed")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise AgentsAPIError("invalid_local_state")
    return value


def pointer_run(root: Path, pointer: Path) -> tuple[Path, bool]:
    """Read a prior session without contacting or cancelling its remote run."""
    previous = read_object(pointer)
    name = previous.get("runName", "")
    if not isinstance(name, str) or Path(name).name != name or not name.startswith("run-"):
        raise AgentsAPIError("invalid_run_pointer")
    directory = root / name
    if directory.is_symlink() or (directory / "tool-results").is_symlink():
        raise AgentsAPIError("symlink_state_not_allowed")
    result_path = directory / "result.json"
    terminal = read_object(result_path) if result_path.exists() else {}
    # Timeout/budget stops and cancel acknowledgements are not terminal proof.
    known_terminal = (terminal.get("status") in {"completed", "failed", "cancelled"}
                      or terminal.get("observed_root_status") in {"completed", "failed", "cancelled"})
    uncertain_tool = any(read_object(path).get("status") != "completed"
                         for path in (directory / "tool-results").glob("*.json"))
    return directory, not known_terminal or uncertain_tool


def tool_definitions(execute: bool, decision_schema: dict, release_enabled: bool = False) -> list[dict]:
    names = [("inspect_production_state", "Read current source, approval, leases, QA and the deterministic next action.")]
    if execute:
        names.extend([
            ("run_timeline_probe", "Prepare and validate source media without model-based boundary discovery. The operator supplies sermon start/end times; at most once per session."),
            ("run_approved_reading_pdf_generation", "Run the guarded dual-PDF stage using existing valid human approval; at most once per session."),
        ])
    if execute and release_enabled:
        names.extend((action, "Start the permitted durable release stage; inspect state afterwards. Never grants review or publication authorization.") for action in workflow.ACTIONS)
    tools = [{"type": "function", "name": name, "description": description,
              "parameters": {"type": "object", "properties": {}, "required": [], "additionalProperties": False}}
             for name, description in names]
    tools.append({"type": "function", "name": "submit_supervisor_decision",
                  "description": "Submit only after fresh inspection and no unattempted executable stage remains in execute mode. Shadow, completion, waiting, human gates or an already attempted stage may be reported. End the turn only after status recorded; a blocked submission requires following its reasonCode.",
                  "parameters": {**decision_schema, "additionalProperties": False}})
    return tools


def bound_configuration(config):
    value = asdict(config)
    path = workflow.configuration(config)
    if path is not None:
        value["releaseWorkflowSha256"] = workflow.config_hash(path)
    else:
        # Preserve pre-extension session fingerprints for the default workflow.
        value.pop("release_workflow_config", None)
    return value


class ProductionTools:
    def __init__(self, config, execute: bool, directory: Path, decision_type):
        self.config, self.execute = config, execute
        self.directory, self.decision_type = directory, decision_type
        self.state_path = directory / "production-tool-state.json"
        self.state = read_object(self.state_path) if self.state_path.exists() else {
            "schemaVersion": 1, "inspected": False, "needsInspection": True,
            "attemptedStages": [], "decision": None}
        binding = fingerprint({"config": bound_configuration(config), "execute": execute})
        if self.state.get("configFingerprint", binding) != binding:
            raise AgentsAPIError("production_configuration_changed")
        self.state["configFingerprint"] = binding

    def save(self):
        _write_json(self.state_path, self.state)

    def __call__(self, name: str, arguments: dict) -> dict:
        current_binding = fingerprint({"config": bound_configuration(self.config), "execute": self.execute})
        if self.state["configFingerprint"] != current_binding:
            raise AgentsAPIError("production_configuration_changed")
        if not isinstance(arguments, dict):
            raise AgentsAPIError("invalid_tool_arguments")
        if name == "submit_supervisor_decision":
            if not self.state["inspected"] or self.state["needsInspection"]:
                return {"status": "blocked", "reasonCode": "inspect_current_state_before_decision"}
            if set(arguments) - set(self.decision_type.model_fields):
                raise AgentsAPIError("invalid_decision_fields")
            decision = self.decision_type.model_validate(arguments, strict=True).model_dump(mode="json")
            if self.state["decision"] is not None and self.state["decision"] != decision:
                return {"status": "blocked", "reasonCode": "decision_already_submitted"}
            # The world can change after inspection. Do not let a premature
            # final answer close a session that still has authorized work.
            snapshot = workflow.snapshot(self.config)
            stage = executable_stage(snapshot)
            if self.execute and stage and stage not in self.state["attemptedStages"]:
                self.state["needsInspection"] = True
                self.save()
                return {"status": "blocked", "reasonCode": "unattempted_executable_stage",
                        "stage": stage, "requiresFreshInspection": True,
                        "recommendedAction": remote_snapshot(snapshot, self.config.sunday)["recommendedAction"]}
            self.state["decision"] = decision
            self.save()
            return {"status": "recorded", "productionComplete": False, "instruction": "End this turn. The host verifies production state separately."}
        if arguments:
            raise AgentsAPIError("production_tools_accept_no_arguments")
        if self.state["decision"] is not None:
            return {"status": "blocked", "reasonCode": "decision_already_submitted"}
        if name == "inspect_production_state":
            snapshot = workflow.snapshot(self.config)
            self.state.update(inspected=True, needsInspection=False)
            self.save()
            return remote_snapshot(snapshot, self.config.sunday)
        allowed = {
            "run_timeline_probe": ("timeline", {"run_timeline_probe", "resume_failed_timeline"}, production.run_timeline_probe),
            "run_approved_reading_pdf_generation": ("generation", {"run_reading_pdf_generation"}, production.run_reading_pdf_generation),
        }
        if getattr(self.config, "release_workflow_config", None):
            allowed.update({action: ("release_" + action, {action}, lambda config, action=action: workflow.start_action(config, action))
                            for action in workflow.ACTIONS})
        if name not in allowed:
            raise AgentsAPIError("unknown_production_tool")
        if not self.execute:
            return {"status": "blocked", "reasonCode": "shadow_mode"}
        if not self.state["inspected"] or self.state["needsInspection"]:
            return {"status": "blocked", "reasonCode": "inspect_current_state_before_mutation"}
        stage, actions, operation = allowed[name]
        if stage in self.state["attemptedStages"]:
            return {"status": "skipped", "reasonCode": "stage_already_attempted_in_session"}
        snapshot = workflow.snapshot(self.config)
        recommendation = snapshot.get("recommendedAction") or {}
        if recommendation.get("action") not in actions or recommendation.get("humanActionRequired"):
            return {"status": "blocked", "reasonCode": "current_state_does_not_allow_stage",
                    "recommendedAction": remote_snapshot(snapshot, self.config.sunday)["recommendedAction"]}
        # Persist domain-level deduplication BEFORE any possible side effect.
        # A different model call_id cannot bypass this fence after a restart.
        self.state["attemptedStages"].append(stage)
        self.state["needsInspection"] = True
        self.save()
        result = operation(self.config)
        # Subprocess output and command/configuration stay in the production
        # ledger. The remote model receives only the bounded operation outcome.
        allowed_status = {"completed", "failed", "blocked", "skipped", "already_running", "requires_operator_review",
                          "waiting_for_source", "waiting_for_matching_sunday", "waiting_for_post_live", "waiting_for_download_access", "queued", "running", "succeeded", "uncertain"}
        status = result.get("status")
        safe = {"status": status if isinstance(status, str) and status in allowed_status else "requires_fresh_inspection"}
        if type(result.get("returnCode")) is int:
            safe["returnCode"] = result["returnCode"]
        safe.update(safe_workflow_job(result))
        safe["stage"] = stage
        safe["requiresFreshInspection"] = True
        return safe


def usage_summary(result: dict) -> dict:
    """Best-effort counters; requests and exact billing are not observable here."""
    usage = result.get("usage")
    if isinstance(usage, dict) and "turns" in usage:
        values = [turn.get("usage") for turn in usage["turns"]]
    elif isinstance(usage, dict):
        values = [usage]
    else:
        values = []
    counters = {"requests": None}
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        available = [value.get(field) if isinstance(value, dict) else None for value in values]
        counters[field] = sum(available) if available and all(type(v) is int and v >= 0 for v in available) else None
    return counters


def session_report(args, config, instructions, decision_type, verify_decision, *, client=None) -> dict:
    """Run/resume under a local lock; never fall back to a second backend on error."""
    execute = args.mode == "execute"
    timeout = getattr(args, "agent_timeout_seconds", 21600)
    if not math.isfinite(timeout) or timeout <= 0 or not 1 <= args.max_turns <= 100:
        raise AgentsAPIError("invalid_supervisor_limits")
    schema = decision_type.model_json_schema()
    configuration = {"model": args.model, "mode": args.mode, "config": bound_configuration(config)}
    binding = fingerprint(configuration)
    payload = {
        "agent": {"model": args.model, "reasoning": {"effort": "medium"}, "instructions": instructions,
                  "tools": tool_definitions(execute, schema, bool(getattr(config, "release_workflow_config", None))), "multi_agent": {"enabled": False}},
        "environment": {"type": "none"},
        "input": f"Inspect and safely advance Sunday {args.sunday}. Mode: {args.mode}. Use persisted evidence and only the exposed tools.",
    }
    root = Path(args.out).parent / "agents-api-runs"
    if root.is_symlink():
        raise AgentsAPIError("invalid_run_root")
    root.mkdir(parents=True, exist_ok=True)
    pointer = root / ("active-" + binding[:16] + ".json")
    # Serialize configuration changes as well as repeated runs of one binding.
    lock_path = root / "supervisor.lock"
    lock = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AgentsAPIError("supervisor_already_running") from None
        explicit = getattr(args, "agent_run_dir", None)
        resume = bool(getattr(args, "resume_agent_session", False))
        if explicit:
            directory = Path(explicit).expanduser().resolve()
            if Path(explicit).is_symlink():
                raise AgentsAPIError("invalid_run_directory")
        elif resume:
            raise AgentsAPIError("resume_requires_agent_run_dir")
        else:
            directory = None
            # Removed/changed configuration fields change the binding. Never
            # silently abandon an older remote session or its pending tool.
            for prior_pointer in sorted(root.glob("active-*.json")):
                if prior_pointer == pointer:
                    continue
                _, unresolved = pointer_run(root, prior_pointer)
                if unresolved:
                    raise AgentsAPIError("prior_configuration_session_unresolved_inspect_existing_run")
            if pointer.exists():
                old, unresolved = pointer_run(root, pointer)
                if unresolved:
                    directory, resume = old, True
            if directory is None:
                name = "run-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:12]
                directory = root / name
                directory.mkdir(mode=0o700)
                _write_json(pointer, {"runName": name, "binding": binding})
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        tools = ProductionTools(config, execute, directory, decision_type)
        # State creation is owned by run_agent_session, whose new-directory
        # contract must see an empty directory before the first function call.
        client = client or AgentsAPIClient()
        try:
            with sermon_accounting.sdk_invocation(args.model, backend="agents-api") as receipt:
                result = run_agent_session(client, directory, payload, tools,
                                           max_seconds=timeout, max_tool_calls=args.max_turns, resume=resume)
                receipt["usage"] = usage_summary(result)
                if result.get("status") != "completed":
                    raise AgentsAPIError("remote_turn_" + str(result.get("status", "unknown")))
                decision = tools.state.get("decision")
                if not isinstance(decision, dict):
                    raise AgentsAPIError("structured_decision_missing")
        except AgentsAPIError as exc:
            snapshot = workflow.snapshot(config)
            saved = read_object(directory / "state.json") if (directory / "state.json").exists() else {}
            return {
                "schemaVersion": 1, "status": "failed", "sunday": args.sunday, "mode": args.mode,
                "model": args.model, "agentBackend": "agents-api", "finalSnapshot": snapshot,
                "decision": {"status": "blocked", "action": "inspect_agents_api_session", "summary_zh": "Agents API 会话未通过完成检查；已保留状态与工具结果。", "human_action_required": False, "modelDecisionAccepted": False, "evidence": [exc.code]},
                "agentSession": {"id": saved.get("session_id"), "runDirectory": str(directory), "errorCode": exc.code,
                                 "status": saved.get("status"), "usage": None, "costStatus": "unknown"},
                "traceSensitiveDataIncluded": False,
            }
        snapshot = workflow.snapshot(config)
        verified = verify_decision(decision, snapshot, args.mode,
                                   attempted_stages=tools.state["attemptedStages"])
        return {
            "schemaVersion": 1, "status": verified["status"], "sunday": args.sunday, "mode": args.mode,
            "model": args.model, "agentBackend": "agents-api", "decision": verified, "modelDecision": decision,
            "finalSnapshot": snapshot, "traceSensitiveDataIncluded": False,
            "agentSession": {"id": result["session_id"], "status": result["status"], "runDirectory": str(directory),
                             "toolCalls": result["tool_calls"], "usage": result.get("usage"), "costStatus": "unknown",
                             "artifactErrors": result.get("artifact_errors", [])},
        }
    finally:
        os.close(lock)
