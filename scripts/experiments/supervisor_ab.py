#!/usr/bin/env python3
"""Isolated, read-only Agents API Supervisor A/B experiment.

Replay validates the harness and scoring without a network call. Live runs use
the same payload, production read-only tools and deterministic decision verifier.
Neither mode can invoke a production mutation or write an approval.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sermon_agents_supervisor as supervisor  # noqa: E402
from scripts.run_sermon_production_supervisor_agent import (  # noqa: E402
    SupervisorDecision, supervisor_instructions, verify_decision,
)
from scripts.sermon_agents_api import AgentsAPIClient, run_agent_session  # noqa: E402
from scripts.sermon_production_supervisor import SupervisorConfig  # noqa: E402

MODELS = ("gpt-6-sol", "gpt-6-luna")
FIXTURES = Path(__file__).with_name("supervisor_ab_fixtures.json")


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def load_cases(path: Path) -> list[dict]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixtures must be a nonempty JSON array")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) - {"id", "snapshot", "script", "scripts_by_model"}:
            raise ValueError("invalid fixture fields")
        if not isinstance(case.get("id"), str) or not case["id"].replace("-", "").isalnum():
            raise ValueError("invalid fixture id")
        if case["id"] in ids:
            raise ValueError("duplicate fixture id")
        ids.add(case["id"])
        snapshot = case.get("snapshot")
        recommendation = snapshot.get("recommendedAction") if isinstance(snapshot, dict) else None
        if not isinstance(recommendation, dict) or not isinstance(recommendation.get("action"), str):
            raise ValueError("fixture lacks recommendedAction")
        if not isinstance(recommendation.get("humanActionRequired"), bool):
            raise ValueError("fixture lacks humanActionRequired boolean")
        for script in [case.get("script"), *(case.get("scripts_by_model") or {}).values()]:
            if not isinstance(script, list) or not script:
                raise ValueError("fixture script must be nonempty")
            for call in script:
                if not isinstance(call, dict) or call.get("name") not in {
                    "inspect_production_state", "submit_supervisor_decision"
                } or not isinstance(call.get("arguments"), dict):
                    raise ValueError("fixture contains a non-read-only tool call")
    return cases


class ReplayClient:
    """Minimal Agents session emulator; one scripted required action per poll."""

    def __init__(self, script: list[dict]):
        self.script = script
        self.index = -1
        self.submitted: list[dict] = []
        self.payload: dict | None = None

    def set_deadline(self, _deadline):
        pass

    def create_session(self, payload: dict) -> dict:
        self.payload = copy.deepcopy(payload)
        return {"id": "sess_replay"}

    def retrieve_session(self, _session_id: str) -> dict:
        self.index += 1
        if self.index >= len(self.script):
            return {"required_actions": []}
        call = self.script[self.index]
        return {"required_actions": [{"type": "function_call", "turn_id": "turn_replay",
                                      "call_id": f"call_{self.index + 1}", **call}]}

    def list_turns(self, _session_id: str) -> list[dict]:
        return [{"id": "turn_replay", "subagent_id": None,
                 "status": "completed" if self.index >= len(self.script) else "running"}]

    def list_items(self, _session_id: str) -> list[dict]:
        return []

    def submit_tool_result(self, _session_id: str, call: dict, output=None, *, error=None):
        self.submitted.append({"name": call["name"], "output": output, "error": error})

    def cancel(self, _session_id: str) -> dict:
        return {}


def request_ids(result: dict) -> list[str] | None:
    """Only report actual request-id fields; session/turn IDs are different IDs."""
    found: set[str] = set()
    for obj in [*result.get("turns", []), *result.get("items", [])]:
        if isinstance(obj, dict):
            for key in ("request_id", "requestId", "x_request_id"):
                value = obj.get(key)
                if isinstance(value, str) and value:
                    found.add(value)
    return sorted(found) or None


def payload(model: str, sunday: str, *, page_release: bool = False) -> dict:
    return {
        "agent": {"model": model, "reasoning": {"effort": "medium"},
                  "instructions": supervisor_instructions("agents-api", page_release=page_release),
                  "tools": supervisor.tool_definitions(False, SupervisorDecision.model_json_schema()),
                  "multi_agent": {"enabled": False}},
        "environment": {"type": "none"},
        "input": f"Inspect and safely advance Sunday {sunday}. Mode: shadow. Use persisted evidence and only the exposed tools.",
    }


def run_case(case: dict, model: str, *, backend: str, root: Path,
             max_seconds: float = 120) -> dict:
    if model not in MODELS or backend not in {"replay", "live"}:
        raise ValueError("unsupported model or backend")
    case_id = case["id"]
    run_dir = root / case_id / model
    run_dir.mkdir(parents=True, exist_ok=True)
    snapshot = copy.deepcopy(case["snapshot"])
    config = SupervisorConfig(sunday="2026-09-27", state_file=str(run_dir / "unused-state.json"),
                              work_root=run_dir, gcs_bucket=None)
    outbound = supervisor.remote_snapshot(snapshot, config.sunday)
    tool = supervisor.ProductionTools(config, False, run_dir, SupervisorDecision)
    script = (case.get("scripts_by_model") or {}).get(model, case["script"])
    client = ReplayClient(script) if backend == "replay" else AgentsAPIClient()
    experiment_payload = payload(model, config.sunday,
                                 page_release=snapshot.get("workflowScope") == "page_release")
    common_payload = copy.deepcopy(experiment_payload)
    common_payload["agent"]["model"] = "<arm>"
    if backend == "live":
        # The fixture must remain identical on restart. The binding is outside
        # the session directory so the Agents runner's empty-directory rule holds.
        binding_path = run_dir.parent / f"{model}-binding.json"
        binding = {"caseSha256": digest(snapshot), "payloadSha256": digest(experiment_payload)}
        if binding_path.exists():
            if json.loads(binding_path.read_text(encoding="utf-8")) != binding:
                raise ValueError("live case or payload changed; use a new run root")
        else:
            binding_path.write_text(json.dumps(binding, sort_keys=True) + "\n", encoding="utf-8")
    started = time.monotonic()
    # Patch only the snapshot reader. ProductionTools retains its actual
    # allowlist, submit guards and persisted tool ledger.
    with patch.object(supervisor.workflow, "snapshot", return_value=copy.deepcopy(snapshot)):
        result = run_agent_session(client, run_dir, experiment_payload, tool,
                                   max_seconds=max_seconds, max_tool_calls=8,
                                   poll_seconds=0 if backend == "replay" else 2,
                                   resume=(backend == "live" and (run_dir / "state.json").exists()))
    elapsed = time.monotonic() - started
    decision = tool.state["decision"]
    truth = verify_decision({}, snapshot, "shadow")
    verified = verify_decision(decision or {}, snapshot, "shadow")
    trace = client.submitted if backend == "replay" else [
        {"name": record.get("name"), "output": record.get("output"), "error": record.get("error")}
        for record in (json.loads(path.read_text(encoding="utf-8"))
                       for path in (run_dir / "tool-results").glob("*.json"))]
    return {
        "caseId": case_id, "model": model, "reasoningEffort": "medium", "backend": backend,
        "caseSha256": digest(snapshot), "commonPayloadSha256": digest(common_payload),
        "outboundSnapshot": outbound, "outboundSha256": digest(outbound),
        "sessionStatus": result["status"], "sessionId": result["session_id"],
        "requestIds": request_ids(result), "usage": result.get("usage"),
        "usageStatus": "reported" if result.get("usage") is not None else "unknown",
        "costStatus": "unknown",
        "elapsedSeconds": round(elapsed, 6), "toolCalls": result["tool_calls"],
        "toolTrace": trace, "modelDecision": decision,
        "deterministicExpected": {key: truth[key] for key in ("status", "action", "human_action_required")},
        "verifiedDecision": {key: verified[key] for key in
                             ("status", "action", "human_action_required", "modelDecisionAccepted")},
        "falseCompletionClaim": bool(decision and decision.get("status") == "complete"
                                     and truth["status"] != "complete"),
        "runDirectory": str(run_dir),
    }


def run_experiment(cases: list[dict], *, backend: str, root: Path,
                   max_seconds: float = 120,
                   on_result: Callable[[list[dict]], None] | None = None) -> dict:
    rows = []
    # Alternating order avoids consistently giving one model the earlier live slot.
    for index, case in enumerate(cases):
        for model in (MODELS if index % 2 == 0 else MODELS[::-1]):
            rows.append(run_case(case, model, backend=backend, root=root,
                                 max_seconds=max_seconds))
            if on_result:
                on_result(rows)
    aggregate = {}
    for model in MODELS:
        subset = [row for row in rows if row["model"] == model]
        times = sorted(row["elapsedSeconds"] for row in subset)
        usages = [supervisor.usage_summary({"usage": row["usage"]}) for row in subset]
        def token_total(field: str) -> int | None:
            values = [usage[field] for usage in usages]
            return sum(values) if all(value is not None for value in values) else None
        aggregate[model] = {
            "cases": len(subset),
            "acceptedDecisions": sum(row["verifiedDecision"]["modelDecisionAccepted"] for row in subset),
            "falseCompletionClaims": sum(row["falseCompletionClaim"] for row in subset),
            "completedSessions": sum(row["sessionStatus"] == "completed" for row in subset),
            "elapsedSeconds": round(sum(row["elapsedSeconds"] for row in subset), 6),
            "elapsedP50Seconds": times[math.ceil(0.5 * len(times)) - 1],
            "elapsedP95Seconds": times[math.ceil(0.95 * len(times)) - 1],
            "toolCalls": sum(row["toolCalls"] for row in subset),
            "inputTokens": token_total("input_tokens"),
            "outputTokens": token_total("output_tokens"),
            "totalTokens": token_total("total_tokens"),
            "usageUnknownCases": sum(row["usage"] is None for row in subset),
            "requestIdsUnknownCases": sum(row["requestIds"] is None for row in subset),
        }
    return {"schemaVersion": "supervisor-ab.v1", "backend": backend,
            "interpretation": ("simulated_protocol_only" if backend == "replay" else "live_model_comparison"),
            "models": list(MODELS), "cases": rows, "aggregate": aggregate}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--backend", choices=("replay", "live"), default="replay")
    parser.add_argument("--allow-paid-api", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run-root", type=Path,
                        help="Durable isolated session directory; required for live runs")
    parser.add_argument("--max-seconds-per-case", type=float, default=120)
    args = parser.parse_args()
    if args.backend == "live" and not args.allow_paid_api:
        parser.error("live backend requires --allow-paid-api")
    if args.backend == "live" and args.run_root is None:
        parser.error("live backend requires --run-root for session recovery")
    if args.max_seconds_per_case <= 0:
        parser.error("--max-seconds-per-case must be positive")
    cases = load_cases(args.fixtures)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    def save_progress(rows: list[dict]):
        args.out.write_text(json.dumps({"schemaVersion": "supervisor-ab.progress.v1",
                                        "backend": args.backend, "cases": rows},
                                       ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
    if args.backend == "live":
        root = args.run_root.resolve()
        if args.out.resolve().is_relative_to(root):
            parser.error("--out must be outside --run-root")
        root.mkdir(parents=True, exist_ok=True)
        report = run_experiment(cases, backend="live", root=root,
                                max_seconds=args.max_seconds_per_case,
                                on_result=save_progress)
    else:
        with tempfile.TemporaryDirectory(prefix="supervisor-ab-") as temporary:
            report = run_experiment(cases, backend="replay", root=Path(temporary),
                                    max_seconds=args.max_seconds_per_case)
        for row in report["cases"]:
            row.pop("runDirectory")
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(json.dumps({"backend": args.backend, "cases": len(report["cases"]),
                      "aggregate": report["aggregate"], "out": str(args.out)},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
