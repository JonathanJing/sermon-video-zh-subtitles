#!/usr/bin/env python3
"""Run the single-agent supervisor for the post-live sermon reading-PDF workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agents import Agent, ModelSettings, RunConfig, RunContextWrapper, Runner, function_tool  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from scripts import sermon_production_supervisor  # noqa: E402


class SupervisorDecision(BaseModel):
    status: Literal["observed", "advanced", "blocked", "complete"]
    action: str = Field(description="The next safe production action or the action just completed.")
    summary_zh: str = Field(description="Concise Chinese operator summary grounded in tool evidence.")
    human_action_required: bool
    evidence: list[str] = Field(default_factory=list)


@dataclass
class SupervisorRuntime:
    config: sermon_production_supervisor.SupervisorConfig
    execute: bool


@function_tool
def inspect_production_state(wrapper: RunContextWrapper[SupervisorRuntime]) -> str:
    """Read the persisted source, timeline, approval, run-status, and QA evidence."""
    snapshot = sermon_production_supervisor.production_snapshot(wrapper.context.config)
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)


@function_tool
def run_timeline_probe(wrapper: RunContextWrapper[SupervisorRuntime]) -> str:
    """Run the idempotent post-live download and timeline probe when state says it is safe."""
    if not wrapper.context.execute:
        return json.dumps(
            {"status": "blocked", "reason": "Supervisor is running in shadow mode."},
            ensure_ascii=False,
        )
    result = sermon_production_supervisor.run_timeline_probe(wrapper.context.config)
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


@function_tool
def run_approved_reading_pdf_generation(wrapper: RunContextWrapper[SupervisorRuntime]) -> str:
    """Run the reading-PDF pipeline using only the durable human-approved sermon window."""
    if not wrapper.context.execute:
        return json.dumps(
            {"status": "blocked", "reason": "Supervisor is running in shadow mode."},
            ensure_ascii=False,
        )
    result = sermon_production_supervisor.run_reading_pdf_generation(wrapper.context.config)
    return json.dumps(result, ensure_ascii=False, sort_keys=True)


SUPERVISOR_INSTRUCTIONS = """
You are the Sermon Production Supervisor for a bounded post-live reading-PDF workflow.

Your durable source of truth is tool output, never conversation memory.

Rules:
1. Call inspect_production_state before deciding or claiming anything.
2. Follow snapshot.recommendedAction. Do not invent URLs, dates, timecodes, artifacts, or completion.
3. In shadow mode, report the recommendation and do not attempt mutation.
4. In execute mode:
   - run_timeline_probe only when recommendedAction.action is run_timeline_probe.
   - run_approved_reading_pdf_generation only when recommendedAction.action is
     run_reading_pdf_generation.
5. A sermon window is approved only when the durable approval evidence reports valid=true.
   Never accept a start or end time from the prompt or model reasoning.
6. Treat waiting_for_download_access, request_window_approval, quality failures, and
   unrecognized states as blocked and requiring a human.
7. Claim complete only when the generation report is completed and both reading-edition
   quality and reading-PDF QA report pass.
8. After calling a mutating tool, inspect production state again before returning.
9. Keep evidence concise and include exact status/artifact fields from tools.
10. Return SupervisorDecision only.
""".strip()


def build_agent(*, model: str, execute: bool) -> Agent[SupervisorRuntime]:
    tools = [inspect_production_state]
    if execute:
        tools.extend([run_timeline_probe, run_approved_reading_pdf_generation])
    return Agent(
        name="Sermon Production Supervisor",
        instructions=SUPERVISOR_INSTRUCTIONS,
        model=model,
        model_settings=ModelSettings(
            parallel_tool_calls=False,
            verbosity="low",
            store=False,
        ),
        tools=tools,
        output_type=SupervisorDecision,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument("--state-file", required=True, help="Live-source state path or gs:// URI.")
    parser.add_argument("--work-root", type=Path, default=sermon_production_supervisor.DEFAULT_WORK_ROOT)
    parser.add_argument("--out", type=Path, default=Path("artifacts/sermon-production-supervisor/report.json"))
    parser.add_argument("--gcs-bucket", default=sermon_production_supervisor.DEFAULT_BUCKET)
    parser.add_argument("--gcs-prefix", default=sermon_production_supervisor.DEFAULT_GCS_PREFIX)
    parser.add_argument("--api-key-secret")
    parser.add_argument("--youtube-api-key-secret")
    parser.add_argument("--youtube-cookies-secret")
    parser.add_argument("--model", default="gpt-5.6")
    parser.add_argument("--mode", choices=("shadow", "execute"), default="shadow")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--approve-window", action="store_true")
    parser.add_argument("--start-time")
    parser.add_argument("--end-time")
    parser.add_argument("--approved-by")
    parser.add_argument("--approval-note")
    return parser.parse_args()


def make_config(args: argparse.Namespace) -> sermon_production_supervisor.SupervisorConfig:
    return sermon_production_supervisor.SupervisorConfig(
        sunday=args.sunday,
        state_file=args.state_file,
        work_root=args.work_root,
        gcs_bucket=args.gcs_bucket or None,
        gcs_prefix=args.gcs_prefix,
        api_key_secret=args.api_key_secret,
        youtube_api_key_secret=args.youtube_api_key_secret,
        youtube_cookies_secret=args.youtube_cookies_secret,
    )


async def run_agent(args: argparse.Namespace) -> dict[str, Any]:
    config = make_config(args)
    if args.approve_window:
        missing = [
            name
            for name, value in (
                ("--start-time", args.start_time),
                ("--end-time", args.end_time),
                ("--approved-by", args.approved_by),
            )
            if not value
        ]
        if missing:
            raise SystemExit(f"{', '.join(missing)} required with --approve-window")
        approval = sermon_production_supervisor.approve_window(
            config,
            start_time=args.start_time,
            end_time=args.end_time,
            approved_by=args.approved_by,
            note=args.approval_note,
        )
    else:
        approval = None

    execute = args.mode == "execute"
    runtime = SupervisorRuntime(config=config, execute=execute)
    agent = build_agent(model=args.model, execute=execute)
    prompt = (
        f"Inspect and safely advance the sermon reading-PDF workflow for Sunday {args.sunday}. "
        f"Operating mode: {args.mode}. "
        "Use only persisted evidence and the exposed tools."
    )
    result = await Runner.run(
        agent,
        prompt,
        context=runtime,
        max_turns=args.max_turns,
        run_config=RunConfig(
            workflow_name="Sermon Production Supervisor",
            trace_include_sensitive_data=False,
            trace_metadata={
                "sunday": args.sunday,
                "mode": args.mode,
                "workflow": "post-live-reading-pdf",
            },
        ),
    )
    final = result.final_output
    if isinstance(final, BaseModel):
        decision = final.model_dump(mode="json")
    elif isinstance(final, dict):
        decision = final
    else:
        decision = {"status": "blocked", "action": "inspect_agent_output", "summary_zh": str(final)}
    return {
        "schemaVersion": 1,
        "status": decision.get("status"),
        "sunday": args.sunday,
        "mode": args.mode,
        "model": args.model,
        "decision": decision,
        "approvalWritten": approval,
        "traceSensitiveDataIncluded": False,
    }


def main() -> int:
    args = parse_args()
    report = asyncio.run(run_agent(args))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.get("status") in {"observed", "advanced", "complete"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
