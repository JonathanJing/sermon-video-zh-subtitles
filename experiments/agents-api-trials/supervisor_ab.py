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
import os
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


def live_tool_trace(result: dict, run_dir: Path) -> list[dict]:
    """Bind durable tool receipts to the API's function-call item names."""
    names = {item.get("call_id"): item.get("name")
             for item in result.get("items", [])
             if isinstance(item, dict) and item.get("type") == "function_call"
             and isinstance(item.get("call_id"), str)}
    return [{"name": names.get(record.get("call_id")),
             "output": record.get("output"), "error": record.get("error")}
            for record in (json.loads(path.read_text(encoding="utf-8"))
                           for path in (run_dir / "tool-results").glob("*.json"))]


def payload(model: str, sunday: str, *, page_release: bool = False) -> dict:
    return {
        "agent": {"model": model, "reasoning": {"effort": "medium"},
                  "instructions": supervisor_instructions("agents-api", page_release=page_release),
                  "tools": supervisor.tool_definitions(False, SupervisorDecision.model_json_schema()),
                  "multi_agent": {"enabled": False}},
        "environment": {"type": "none"},
        "input": f"Inspect and safely advance Sunday {sunday}. Mode: shadow. Use persisted evidence and only the exposed tools.",
    }


def write_case_report(run_dir: Path, row: dict) -> None:
    """Atomically preserve the measured row before batch progress is rewritten."""
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=run_dir,
                                     prefix=".case-report-", suffix=".tmp", delete=False) as stream:
        json.dump(row, stream, ensure_ascii=False, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
        pending = Path(stream.name)
    pending.replace(run_dir / "case-report.json")


def restore_case_reports(cases: list[dict], root: Path, prior_rows: list[dict]) -> None:
    """Import timings from an older progress/final report after checking session identity."""
    fixtures = {case["id"]: case for case in cases}
    seen = set()
    for row in prior_rows:
        case_id, model = row.get("caseId"), row.get("model")
        if case_id not in fixtures or model not in MODELS or (case_id, model) in seen:
            raise ValueError("prior live report has an unknown or duplicate case")
        seen.add((case_id, model))
        case = fixtures[case_id]
        run_dir = root / case_id / model
        bound = payload(model, "2026-09-27",
                        page_release=case["snapshot"].get("workflowScope") == "page_release")
        bound["agent"]["model"] = "<arm>"
        result_path = run_dir / "result.json"
        if (row.get("backend") != "live" or row.get("runDirectory") != str(run_dir)
                or row.get("caseSha256") != digest(case["snapshot"])
                or row.get("commonPayloadSha256") != digest(bound)
                or not isinstance(row.get("elapsedSeconds"), (int, float))
                or not result_path.exists()
                or row.get("sessionId") != json.loads(result_path.read_text(encoding="utf-8")).get("session_id")):
            raise ValueError("prior live case does not match its bound session")
        if not (run_dir / "case-report.json").exists():
            write_case_report(run_dir, row)


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
    experiment_payload = payload(model, config.sunday,
                                 page_release=snapshot.get("workflowScope") == "page_release")
    common_payload = copy.deepcopy(experiment_payload)
    common_payload["agent"]["model"] = "<arm>"
    case_hash = digest(snapshot)
    common_hash = digest(common_payload)
    if backend == "live":
        # The fixture must remain identical on restart. The binding is outside
        # the session directory so the Agents runner's empty-directory rule holds.
        binding_path = run_dir.parent / f"{model}-binding.json"
        binding = {"caseSha256": case_hash, "payloadSha256": digest(experiment_payload)}
        if binding_path.exists():
            if json.loads(binding_path.read_text(encoding="utf-8")) != binding:
                raise ValueError("live case or payload changed; use a new run root")
        else:
            binding_path.write_text(json.dumps(binding, sort_keys=True) + "\n", encoding="utf-8")
        report_path = run_dir / "case-report.json"
        result_path = run_dir / "result.json"
        if report_path.exists():
            saved = json.loads(report_path.read_text(encoding="utf-8"))
            if (not result_path.exists() or saved.get("caseId") != case_id
                    or saved.get("model") != model or saved.get("backend") != backend
                    or saved.get("caseSha256") != case_hash
                    or saved.get("commonPayloadSha256") != common_hash
                    or saved.get("runDirectory") != str(run_dir)
                    or saved.get("sessionId") != json.loads(result_path.read_text(encoding="utf-8")).get("session_id")
                    or not isinstance(saved.get("elapsedSeconds"), (int, float))):
                raise ValueError("saved live case report does not match its bound session")
            return saved
        if result_path.exists():
            raise ValueError("completed live session lacks its elapsed-time report; reconcile before resuming")
    client = ReplayClient(script) if backend == "replay" else AgentsAPIClient()
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
    trace = client.submitted if backend == "replay" else live_tool_trace(result, run_dir)
    row = {
        "caseId": case_id, "model": model, "reasoningEffort": "medium", "backend": backend,
        "caseSha256": case_hash, "commonPayloadSha256": common_hash,
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
    if backend == "live":
        # Cache the complete row before the batch progress file is rewritten.
        # Reopening result.json is nearly instant and cannot measure the original run.
        write_case_report(run_dir, row)
    return row


def run_experiment(cases: list[dict], *, backend: str, root: Path,
                   max_seconds: float = 120,
                   prior_rows: list[dict] | None = None,
                   on_result: Callable[[list[dict]], None] | None = None) -> dict:
    if backend == "live" and prior_rows is not None:
        restore_case_reports(cases, root, prior_rows)
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
        prior_rows = None
        if args.out.exists():
            prior = json.loads(args.out.read_text(encoding="utf-8"))
            if prior.get("backend") != "live" or not isinstance(prior.get("cases"), list):
                parser.error("existing --out is not a live experiment report")
            prior_rows = prior["cases"]
        report = run_experiment(cases, backend="live", root=root,
                                max_seconds=args.max_seconds_per_case,
                                prior_rows=prior_rows,
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
