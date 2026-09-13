"""Project-Python adapter: existing validators and scripts, never a new approval.

Fixture actions are local fake work and are explicitly unable to dispatch the
production harness. Production execute requires both worker and request grants.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import sys
import time

from scripts.sermon_execution_harness import ExecutionTerminated, atomic_json, bounded_process, utc_now, work_lock
from .contracts import Observation, Request, digest
from .local_io import ROOT, TEMPORAL_ROOT, active_execution, file_sha, private_directory, process_identity, read_json


def load_config(request: Request) -> dict:
    request.validate()
    path = Path(request.config_path)
    if file_sha(path) != request.config_sha256:
        raise ValueError("Temporal request configuration changed; existing request cannot adopt it")
    config = read_json(path)
    expected = "sermon-temporal-fixture-v1" if request.profile == "fixture" else "sermon-temporal-operator-v1"
    if (config.get("schemaVersion") != expected or config.get("sunday") != request.sunday
            or config.get("sourceKey") != request.source_key):
        raise ValueError("Configuration profile/date/source differs from the immutable request")
    if request.profile == "fixture":
        root = Path(config["fixtureRoot"]).resolve()
        if not root.is_relative_to(TEMPORAL_ROOT.resolve()) or not path.resolve().is_relative_to(root):
            raise ValueError("Fixture files must stay inside artifacts/temporal and cannot target production artifacts")
        if not isinstance(config.get("durationSeconds"), (int, float)) or not 0 <= config["durationSeconds"] <= 120:
            raise ValueError("Fixture duration must be between 0 and 120 seconds")
    return config


def fixture_observation(request: Request, config: dict, state_dir: Path, exclude=None) -> Observation:
    # The actual project validator is reused even for fake source/timeline data.
    from scripts.sermon_production_supervisor import json_digest, validate_window_approval
    root = Path(config["fixtureRoot"]).resolve()
    source_sha = file_sha(root / "source.bin")
    timeline = read_json(root / "timeline.json")
    binding = digest([request.source_key, source_sha, json_digest(timeline)])
    busy = active_execution(state_dir, exclude=exclude)
    if source_sha != config["sourceSha256"]:
        return Observation(status="waiting_source_binding", source_binding=binding, runtime_busy=busy,
                           reason="Fixture source bytes changed")
    approval_path = root / "approval.json"
    approval = read_json(approval_path) if approval_path.exists() else None
    valid, reason = validate_window_approval(approval, sunday=request.sunday,
        live_url=config["sourceUrl"], timeline_report=timeline)
    output_path = root / "result.json"
    output = read_json(output_path) if output_path.exists() else {}
    complete = valid and output.get("fixtureOnly") is True and output.get("sourceBinding") == binding
    return Observation(status="fixture_completed" if complete else "ready" if valid and not busy else "waiting_review",
        source_binding=binding, action_token=digest([binding, "fixture_execute"]), executable=valid and not busy,
        terminal=complete, terminal_scope="fixture_only" if complete else "", approval_valid=valid,
        runtime_busy=busy, original_action="existing_window_approval_validator", evidence_path=str(root), reason=reason or "")


def production_args(config: dict):
    from scripts import run_saturday_harness as harness
    argv = config.get("harnessArgv")
    if (not isinstance(argv, list) or any(not isinstance(item, str) for item in argv)
            or any(flag in argv for flag in ("--mode", "--out", "--help", "-h"))):
        raise ValueError("Use existing harness arguments without mode/output overrides")
    args = harness.parse_args(["--mode", "inspect", *argv])
    if args.sunday != config["sunday"]:
        raise ValueError("Harness Sunday differs from immutable Temporal request")
    # A durable request is attached to an already identified source. Discovery
    # remains in the existing operator workflow; it is not replayed by Temporal.
    if not args.skip_source_refresh:
        raise ValueError("Source-bound Temporal requests require explicit --skip-source-refresh")
    if not config.get("expectedPdfSlug") or not isinstance(config.get("expectedSources"), dict):
        raise ValueError("Explicit PDF slug and per-route source pins are required")
    if file_sha(args.bridge_config) != config.get("bridgeConfigSha256"):
        raise ValueError("Bridge configuration changed outside the immutable Temporal request")
    return args


def route_bindings(bridge: dict, plan: dict | None) -> dict:
    """Bind actual validated media/job inputs; bridge reports have no generic media hash field."""
    bindings = {}
    for route, item in bridge.get("routes", {}).items():
        value = {"sourceId": item.get("sourceId"), "sourceAudioSha256": None, "jobSha256": None}
        if item.get("status") in {"ready_to_prepare", "ready_to_resume", "waiting_conversation_review"}:
            job_path = Path(item["work"]) / "job.json"
            if job_path.is_file():
                # inspect_bridge has validated this frozen job and all inputs.
                # Hash again so mutations before execution change the binding.
                job = read_json(job_path)
                audio = job["inputs"]["sourceAudio"]
                measured = file_sha(Path(audio["path"]))
                if measured != audio["sha256"] or job["sourceId"] != item["sourceId"]:
                    raise ValueError("Validated bridge job source changed while forming its binding")
                value.update(sourceAudioSha256=measured, jobSha256=file_sha(job_path))
            elif plan and plan.get("route") == route:
                source = plan["authorization"]["sources"][0]
                measured = file_sha(Path(item["run"]) / "pipeline" / "source_clip.m4a")
                if source["sourceId"] != item["sourceId"] or source["sha256"] != measured:
                    raise ValueError("Prepared route media changed after bridge validation")
                value["sourceAudioSha256"] = measured
            else:
                # A healthy nonselected prepare route was also validated by the
                # bridge; preserve its distinct clip rather than conflating weeks.
                value["sourceAudioSha256"] = file_sha(Path(item["run"]) / "pipeline" / "source_clip.m4a")
        bindings[route] = value
    return bindings


def production_observation(request: Request, config: dict, state_dir: Path, exclude=None) -> Observation:
    from scripts import sermon_production_supervisor as supervisor
    args = production_args(config)
    snapshot = supervisor.production_snapshot(supervisor.SupervisorConfig(
        sunday=args.sunday, state_file=args.state_file, work_root=args.work_root,
        gcs_bucket=args.gcs_bucket or None, gcs_prefix=args.gcs_prefix,
        api_key_secret=args.api_key_secret, youtube_api_key_secret=args.youtube_api_key_secret,
        youtube_cookies_file=args.youtube_cookies, glossary=args.glossary))
    dubbing_dir = ROOT / "experiments" / "sermon-dubbing-poc"
    if str(dubbing_dir) not in sys.path:
        sys.path.insert(0, str(dubbing_dir))
    from continue_saturday_dubbing import inspect_bridge
    bridge, plan = inspect_bridge(args.bridge_config, request.sunday, args.supervisor_report)
    routes = bridge.get("routes", {})
    route_sources = route_bindings(bridge, plan)
    binding = digest([request.source_key, snapshot.get("slug"),
                      (snapshot.get("timeline") or {}).get("reportSha256"), route_sources])
    busy = active_execution(state_dir, exclude=exclude)
    mismatch = snapshot.get("slug") != config["expectedPdfSlug"]
    mismatch |= any(item.get("sourceId") and config["expectedSources"].get(route) != item["sourceId"]
                    for route, item in routes.items())
    if mismatch:
        return Observation(status="waiting_source_binding", source_binding=binding, runtime_busy=busy,
                           reason="Current source differs from explicit PDF/route pins")
    action = (snapshot.get("recommendedAction") or {}).get("action", "inspect_unknown_state")
    selected = routes.get(bridge.get("selectedRoute"), {})
    candidate = selected.get("status") == "waiting_conversation_review" and bool(selected.get("candidateEvidence"))
    ready = action in {"run_timeline_probe", "resume_failed_timeline", "run_reading_pdf_generation"}
    ready |= bridge.get("status") in {"ready_to_prepare", "ready_to_resume"}
    full_evidence = {"schemaVersion": "sermon-temporal-inspection-v1", "snapshot": snapshot, "bridge": bridge}
    evidence = state_dir / "current-inspection.json"
    atomic_json(evidence, full_evidence)
    return Observation(status="candidate_ready_for_review" if candidate else "ready" if ready and not busy else "waiting_evidence",
        source_binding=binding, action_token=digest([binding, action, bridge.get("status"), selected.get("work")]),
        executable=ready and not busy, terminal=candidate, terminal_scope="candidate_handoff_only" if candidate else "",
        approval_valid=(snapshot.get("windowApproval") or {}).get("valid") is True,
        runtime_busy=busy, original_action=action, evidence_path=str(evidence),
        reason=(snapshot.get("recommendedAction") or {}).get("reason", ""))


def observe(request: Request, config: dict, state_dir: Path, exclude=None) -> Observation:
    result = (fixture_observation if request.profile == "fixture" else production_observation)(request, config, state_dir, exclude)
    result.validate()
    return result


def execute(request: Request, config: dict, state_dir: Path, expected_binding: str,
            *, allow_production_execute: bool, receipt: Path) -> Observation:
    if not request.allow_execute or (request.profile == "production" and not allow_production_execute):
        result = observe(request, config, state_dir, receipt)
        result.executable = False
        result.status = "execution_not_enabled"
        result.reason = "Both immutable request and production worker must explicitly enable execution"
        return result
    with work_lock(state_dir / "execution"):
        current = observe(request, config, state_dir, receipt)
        if current.source_binding != expected_binding:
            current.executable = False
            current.status = "waiting_source_binding"
            current.reason = "Source/timeline changed immediately before execution"
            return current
        if not current.executable or current.terminal:
            return current
        if request.profile == "fixture":
            root = Path(config["fixtureRoot"]).resolve()
            starts = root / "starts.json"
            prior = read_json(starts) if starts.exists() else {"count": 0}
            atomic_json(starts, {"fixtureOnly": True, "count": prior["count"] + 1, "pid": os.getpid(),
                                "processIdentity": process_identity(os.getpid()), "receipt": str(receipt)})
            if config.get("nestedCancellationFixture") is True:
                bounded_process([sys.executable, "-m", "scripts.sermon_temporal.fixture_child", "--root", str(root),
                    "--duration", str(config["durationSeconds"]), "--depth", str(config.get("nestedDepth", 1))],
                    timeout=config["durationSeconds"] + 20, check=True)
            else:
                time.sleep(config["durationSeconds"])
            # Recheck approval and source after the fake long operation as well.
            fresh = fixture_observation(request, config, state_dir, receipt)
            if fresh.source_binding != expected_binding or not fresh.approval_valid:
                raise ValueError("Fixture evidence changed while running")
            atomic_json(root / "result.json", {"schemaVersion": "sermon-temporal-fixture-result-v1",
                        "fixtureOnly": True, "sourceBinding": fresh.source_binding, "completedAt": utc_now()})
        else:
            from scripts import run_saturday_harness as harness
            args = production_args(config)
            args.mode = "execute"
            args.out = state_dir / "harness-execute.json"
            # Preserve the existing source locks, leases, QA and PDF/GCS contract.
            report = harness.run(args, runner=bounded_process)
            if report.get("errors"):
                raise RuntimeError("Existing Saturday harness requires recovery; retained report must be inspected")
        return observe(request, config, state_dir, receipt)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--action", choices=("inspect", "execute"), required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--expected-binding", default="")
    parser.add_argument("--allow-production-execute", action="store_true")
    args = parser.parse_args(argv)
    request = Request(**read_json(args.request))
    config = load_config(request)
    state_dir = private_directory(args.state_dir.resolve())
    receipt = args.receipt.resolve()
    if receipt.parent != state_dir or not receipt.name.startswith(args.action + "-"):
        raise ValueError("Activity receipt must belong to this local workflow state directory")
    record = {"schemaVersion": "sermon-temporal-activity-v1", "profile": request.profile, "action": args.action,
              "pid": os.getpid(), "process_identity": process_identity(os.getpid()), "status": "running",
              "startedAt": utc_now(), "requestSha256": digest(asdict(request)), "configSha256": request.config_sha256}
    atomic_json(receipt, record)
    def terminate(signum, frame):
        raise InterruptedError("Activity adapter was cancelled")
    signal.signal(signal.SIGTERM, terminate)
    try:
        result = observe(request, config, state_dir, receipt) if args.action == "inspect" else execute(
            request, config, state_dir, args.expected_binding,
            allow_production_execute=args.allow_production_execute, receipt=receipt)
        record.update(status="returned", result=asdict(result))
        print(json.dumps(asdict(result), ensure_ascii=False))
        return 0
    except BaseException as exc:
        record.update(status="cancelled" if isinstance(exc, (KeyboardInterrupt, InterruptedError, ExecutionTerminated)) else "failed",
                      errorType=type(exc).__name__)
        raise
    finally:
        record["endedAt"] = utc_now()
        atomic_json(receipt, record)


if __name__ == "__main__":
    raise SystemExit(main())
