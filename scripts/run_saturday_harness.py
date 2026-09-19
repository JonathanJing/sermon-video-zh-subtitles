#!/usr/bin/env python3
"""Explicit Saturday operator entry; inspect/shadow never starts child processes.

The existing PDF Supervisor and dubbing bridge retain all acceptance decisions.
This adapter sequences them and exposes separate evidence states, never a new
whole-workflow completion gate. Existing PDF publication remains part of the
authorized PDF contract; audio review and publication are not automated here.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.sermon_execution_harness import bounded_process

SCHEMA = "sermon-saturday-harness-report-v1"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "shadow", "execute"), default="inspect")
    parser.add_argument("--sunday", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--supervisor-report", type=Path, required=True)
    parser.add_argument("--bridge-config", type=Path, required=True)
    parser.add_argument("--bridge-report", type=Path, help="Optional saved bridge JSON for read-only inspection.")
    parser.add_argument("--gcs-bucket", required=True)
    parser.add_argument("--gcs-prefix", default="sundays")
    parser.add_argument("--api-key-secret", required=True)
    parser.add_argument("--youtube-api-key-secret", required=True)
    parser.add_argument("--youtube-cookies", type=Path)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--model", default="gpt-6-astra", help="PDF Supervisor model; generation models remain owned by its contract.")
    parser.add_argument("--agent-backend", choices=("agents-api", "sdk"), default="agents-api")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--skip-source-refresh", action="store_true")
    parser.add_argument("--pdf-timeout", type=float, default=21600, help="PDF child deadline in seconds.")
    parser.add_argument("--bridge-timeout", type=float, default=25200, help="Audio bridge child deadline in seconds.")
    parser.add_argument("--out", type=Path, help="Optional harness report; inspect/shadow only prints to stdout.")
    return parser.parse_args(argv)


def read_object(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def object_field(value, key):
    result = value.get(key) or {}
    if not isinstance(result, dict):
        raise ValueError(f"Expected object field: {key}")
    return result


def signature(path):
    try:
        path = Path(path)
        return path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def read_evidence(path, sunday, *, bridge=False, config_hash=None):
    if path is None or not Path(path).is_file():
        return {"status": "not_observed"}
    report = read_object(path)
    if report.get("week" if bridge else "sunday") != sunday:
        raise ValueError("Evidence belongs to another Sunday")
    if bridge:
        if report.get("schemaVersion") != "sermon-saturday-dubbing-bridge-report-v1":
            raise ValueError("Unsupported bridge evidence schema")
        if object_field(report, "config").get("sha256") != config_hash:
            raise ValueError("Bridge evidence belongs to a different configuration")
    else:
        snapshot = object_field(report, "finalSnapshot") or object_field(report, "snapshot")
        if snapshot and snapshot.get("sunday") != sunday:
            raise ValueError("Supervisor snapshot belongs to another Sunday")
    return report


def commands(args):
    state_file = args.state_file if args.state_file.startswith("gs://") else str(Path(args.state_file).expanduser().absolute())
    pdf = [sys.executable, str(ROOT / "scripts/run_codex_local_sermon_production.py"),
        "--mode", "execute", "--sunday", args.sunday, "--state-file", state_file,
        "--work-root", str(args.work_root.absolute()), "--out", str(args.supervisor_report.absolute()),
        "--gcs-bucket", args.gcs_bucket, "--gcs-prefix", args.gcs_prefix,
        "--api-key-secret", args.api_key_secret, "--youtube-api-key-secret", args.youtube_api_key_secret,
        "--notify-sendgrid-secret", "", "--notify-recipients-secret", "", "--notify-sender-secret", "",
        "--model", args.model, "--agent-backend", getattr(args, "agent_backend", "agents-api"),
        "--max-turns", str(args.max_turns)]
    if args.skip_source_refresh:
        pdf.append("--skip-source-refresh")
    for flag, value in (("--youtube-cookies", args.youtube_cookies), ("--glossary", args.glossary)):
        if value is not None:
            pdf += [flag, str(value.absolute())]
    bridge = [sys.executable, str(ROOT / "experiments/sermon-dubbing-poc/continue_saturday_dubbing.py"),
        "--week", args.sunday, "--config", str(args.bridge_config.absolute()),
        "--supervisor-report", str(args.supervisor_report.absolute()), "--execute"]
    return pdf, bridge


def stage_report(pdf, bridge, *, current_pdf=False, current_bridge=False):
    snapshot = object_field(pdf, "finalSnapshot") or object_field(pdf, "snapshot")
    routes = object_field(bridge, "routes")
    audio = {}
    for route in ("same_video", "live_archive"):
        evidence = object_field(routes, route)
        candidate = object_field(evidence, "candidateEvidence")
        audio[route] = {
            "sourceId": evidence.get("sourceId"), "work": evidence.get("work"),
            "status": evidence.get("status", "not_observed"),
            "evidenceFreshness": "current_bridge_validation" if current_bridge else "saved_snapshot_unverified",
            "humanReview": {"status": "not_verified_by_harness", "candidateReady": bool(candidate)},
            "synchronization": {"status": "report_bound_to_candidate" if candidate.get("timingReportSha256") else "not_verified",
                "timingReportSha256": candidate.get("timingReportSha256"),
                "acceptance": "not_inferred_from_receipt"},
            "publication": {"status": "not_verified", "attemptedByHarness": False},
        }
    return {
        "pdf": {"status": pdf.get("status", "not_observed"), "sourceSlug": snapshot.get("slug"),
            "recommendedAction": snapshot.get("recommendedAction"),
            "evidenceFreshness": "current_supervisor_validation" if current_pdf else "saved_snapshot_unverified",
            "windowApproval": snapshot.get("windowApproval"),
            "publication": object_field(snapshot, "generation").get("publication")},
        "audioCandidate": {"selectedRoute": bridge.get("selectedRoute"), "routes": audio},
        "humanReview": {"status": "not_verified_by_harness", "approvalWritten": False},
        "synchronization": {"status": "see_each_source_route"},
        "publication": {"pdf": "owned_by_existing_supervisor_contract", "audio": "not_attempted"},
    }


def run(args, *, runner=bounded_process):
    date.fromisoformat(args.sunday)
    if any(not math.isfinite(value) or value <= 0 for value in (args.pdf_timeout, args.bridge_timeout)):
        raise ValueError("Stage timeouts must be positive and finite")
    if args.mode != "execute" and args.out is not None:
        raise ValueError("--out requires --mode execute; inspect/shadow is read-only")
    if args.out is not None and args.out.resolve() in {
            p.resolve() for p in (args.supervisor_report, args.bridge_config, args.bridge_report) if p is not None}:
        raise ValueError("Harness output must not overwrite stage evidence or configuration")
    config = read_object(args.bridge_config)
    if config.get("schemaVersion") != "sermon-saturday-dubbing-bridge-v1" or args.sunday not in object_field(config, "weeks"):
        raise ValueError("Bridge configuration must explicitly contain this Sunday")
    config_hash = hashlib.sha256(args.bridge_config.read_bytes()).hexdigest()
    pdf = read_evidence(args.supervisor_report, args.sunday)
    bridge = read_evidence(args.bridge_report, args.sunday, bridge=True, config_hash=config_hash)
    pdf_command, bridge_command = commands(args)
    executions, errors = [], []
    current_pdf = current_bridge = False
    if args.mode == "execute":
        before = signature(args.supervisor_report)
        # Child owns leases, approval checks, logs and publication verification.
        try:
            from scripts.sermon_accounting import subprocess_environment
            child_env = subprocess_environment()
            child_env["SERMON_DUBBING_CONFIG"] = str(args.bridge_config.resolve())
            result = runner(pdf_command, cwd=ROOT, stdout=sys.stderr, stderr=sys.stderr, check=False,
                            timeout=args.pdf_timeout, env=child_env)
        except subprocess.TimeoutExpired:
            executions.append({"stage": "pdf", "status": "timed_out", "timeoutSeconds": args.pdf_timeout})
            errors.append("PDF child exceeded its deadline; inspect retained stage evidence before resuming")
        else:
            executions.append({"stage": "pdf", "exitCode": result.returncode})
            if result.returncode not in (0, 2):
                errors.append("PDF child exited unexpectedly; inspect its retained logs")
        after = signature(args.supervisor_report)
        if after is not None and after != before:
            pdf = read_evidence(args.supervisor_report, args.sunday)
            current_pdf = isinstance(pdf.get("finalSnapshot"), dict)
        if not current_pdf:
            errors.append("PDF child did not produce a fresh Supervisor snapshot; bridge execution skipped")
        elif errors:
            errors.append("Bridge execution skipped after PDF process failure")
        else:
            # Waiting/blocked PDF is not a cross-source veto: the bridge decides
            # whether a separately bound same-video or archive candidate is ready.
            try:
                result = runner(bridge_command, cwd=ROOT, capture_output=True, text=True, check=False, timeout=args.bridge_timeout)
            except subprocess.TimeoutExpired:
                executions.append({"stage": "audio_candidate", "status": "timed_out", "timeoutSeconds": args.bridge_timeout})
                errors.append("Dubbing bridge exceeded its deadline; remote model outcome may require reconciliation")
            else:
                executions.append({"stage": "audio_candidate", "exitCode": result.returncode})
                if result.returncode != 0:
                    errors.append("Dubbing bridge exited unsuccessfully; retained its existing evidence")
                else:
                    fresh = json.loads(result.stdout)
                    if (not isinstance(fresh, dict) or fresh.get("schemaVersion") != "sermon-saturday-dubbing-bridge-report-v1"
                            or fresh.get("week") != args.sunday or object_field(fresh, "config").get("sha256") != config_hash):
                        raise ValueError("Current bridge response does not match the explicit week/configuration")
                    bridge, current_bridge = fresh, True
    report = {"schemaVersion": SCHEMA, "checkedAt": datetime.now(timezone.utc).isoformat(),
        "sunday": args.sunday, "mode": args.mode,
        "status": "needs_attention" if errors else "inspection_only" if args.mode != "execute" else "stages_observed",
        "workflowComplete": False, "stages": stage_report(pdf, bridge, current_pdf=current_pdf, current_bridge=current_bridge),
        "inputs": {"supervisorReport": str(args.supervisor_report), "bridgeConfig": str(args.bridge_config),
            "bridgeConfigSha256": config_hash, "bridgeReport": str(args.bridge_report) if args.bridge_report else None},
        "executions": executions, "errors": errors,
        "nextActions": bridge.get("nextActions", []),
        "sourceSelection": "owned_by_existing_supervisor_and_bridge; same week does not imply same source",
        "notificationsSentByHarness": False, "audioPublicationAttempted": False}
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    try:
        report = run(parse_args(argv))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"schemaVersion": SCHEMA, "status": "invalid_or_unreadable_evidence", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
