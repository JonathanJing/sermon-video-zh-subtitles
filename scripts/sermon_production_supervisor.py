#!/usr/bin/env python3
"""Deterministic state and tool layer for the sermon production supervisor agent."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.cloud import read_gcs_text, write_gcs_text  # noqa: E402
from backend.leases import LeaseHandle, acquire_lease, release_lease  # noqa: E402
from backend.observability import stable_hash, url_summary  # noqa: E402
from scripts import live_source_monitor, run_post_live_subtitle_generation  # noqa: E402


DEFAULT_BUCKET = "sermon-zh-artifacts-ai-for-god"
DEFAULT_GCS_PREFIX = "sundays"
DEFAULT_WORK_ROOT = Path("/tmp/sermon-post-live-subtitles")
TIMECODE_RE = re.compile(r"^(?P<hours>\d{1,3}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d(?:\.\d{1,3})?)$")


@dataclass(frozen=True)
class SupervisorConfig:
    sunday: str
    state_file: str
    work_root: Path = DEFAULT_WORK_ROOT
    gcs_bucket: str | None = DEFAULT_BUCKET
    gcs_prefix: str = DEFAULT_GCS_PREFIX
    api_key_secret: str | None = None
    youtube_api_key_secret: str | None = None
    youtube_cookies_secret: str | None = None
    youtube_cookies_file: Path | None = None
    discord_bot_token_secret: str | None = None
    discord_channel_id: str | None = None
    notify_sendgrid_secret: str | None = None
    notify_recipients_secret: str | None = None
    notify_sender_secret: str | None = None
    python_executable: str = sys.executable
    timeline_model: str = "gpt-transcribe"
    classifier_model: str = "gpt-5.6"
    reference_model: str = "gpt-transcribe"
    reading_model: str = "gpt-5.6-sol"
    glossary: Path | None = None
    lease_ttl_seconds: int = 14_400


def validate_config(config: SupervisorConfig) -> None:
    try:
        date.fromisoformat(config.sunday)
    except ValueError as exc:
        raise ValueError("sunday must be an ISO date in YYYY-MM-DD form") from exc
    if not str(config.state_file).strip():
        raise ValueError("state_file is required")
    if not str(config.work_root):
        raise ValueError("work_root is required")


def production_snapshot(config: SupervisorConfig) -> dict[str, Any]:
    """Read durable workflow evidence and return a sanitized supervisor snapshot."""
    validate_config(config)
    state = read_supervisor_state(config.state_file)
    source = run_post_live_subtitle_generation.selected_source_from_state(state)
    live_url = run_post_live_subtitle_generation.live_url_from_state(state, source)
    access_issues: list[dict[str, str]] = []
    source_lock = read_artifact_json(
        "sourceLock",
        access_issues,
        *artifact_read_locations(*source_lock_locations(config))
    )
    if valid_source_lock(source_lock, config.sunday):
        source = dict(source_lock.get("source") or {})
        live_url = str(source_lock["liveUrl"])
        source["url"] = live_url
    slug = run_post_live_subtitle_generation.slug_for(_slug_args(), live_url) if live_url else None
    locations = artifact_locations(config, slug) if slug else {}

    timeline_report = read_artifact_json(
        "timelineReport",
        access_issues,
        *artifact_read_locations(
            locations.get("timelineReportLocal"),
            locations.get("timelineReportGcs"),
        ),
    )
    approval = read_artifact_json(
        "windowApproval",
        access_issues,
        *artifact_read_locations(
            locations.get("windowApprovalLocal"),
            locations.get("windowApprovalGcs"),
        ),
    )
    generation_report = read_artifact_json(
        "generationReport",
        access_issues,
        *artifact_read_locations(
            locations.get("generationReportLocal"),
            locations.get("generationReportGcs"),
        ),
    )
    run_status = read_artifact_json(
        "runStatus",
        access_issues,
        *artifact_read_locations(
            locations.get("runStatusLocal"),
            locations.get("runStatusGcs"),
        ),
    )
    reading_qa = read_artifact_json(
        "readingPdfQa",
        access_issues,
        *artifact_read_locations(
            locations.get("readingQaLocal"),
            locations.get("readingQaGcs"),
        ),
    )
    reading_quality = read_artifact_json(
        "readingEditionQuality",
        access_issues,
        *artifact_read_locations(
            locations.get("readingQualityLocal"),
            locations.get("readingQualityGcs"),
        ),
    )
    timeline_lease = read_artifact_json(
        "timelineLease",
        access_issues,
        *artifact_read_locations(
            locations.get("timelineLeaseLocal"),
            locations.get("timelineLeaseGcs"),
        ),
    )
    generation_lease = read_artifact_json(
        "generationLease",
        access_issues,
        *artifact_read_locations(
            locations.get("generationLeaseLocal"),
            locations.get("generationLeaseGcs"),
        ),
    )

    approval_valid, approval_reason = validate_window_approval(
        approval,
        sunday=config.sunday,
        live_url=live_url,
        timeline_report=timeline_report,
    )
    recommended = recommend_action(
        sunday=config.sunday,
        live_url=live_url,
        state=state,
        timeline_report=timeline_report,
        approval_valid=approval_valid,
        approval_reason=approval_reason,
        generation_report=generation_report,
        run_status=run_status,
        reading_qa=reading_qa,
        reading_quality=reading_quality,
        access_issues=access_issues,
        timeline_lease=timeline_lease,
        generation_lease=generation_lease,
        publication_required=bool(config.gcs_bucket),
    )
    return {
        "schemaVersion": 1,
        "sunday": config.sunday,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "stateFile": config.state_file,
        "source": public_source(source),
        "liveSource": url_summary(live_url) if live_url else None,
        "slug": slug,
        "timeline": public_timeline_report(timeline_report),
        "windowApproval": public_approval(approval, approval_valid, approval_reason),
        "generation": public_generation_report(generation_report),
        "runStatus": public_run_status(run_status),
        "quality": {
            "readingEdition": public_quality_report(reading_quality),
            "readingPdf": public_quality_report(reading_qa),
        },
        "activeLeases": {
            "timeline": public_lease(timeline_lease),
            "generation": public_lease(generation_lease),
        },
        "recommendedAction": recommended,
        "accessIssues": access_issues,
        "locations": locations,
        "sourceLock": public_source_lock(source_lock),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def recommend_action(
    *,
    sunday: str,
    live_url: str | None,
    state: dict[str, Any],
    timeline_report: dict[str, Any] | None,
    approval_valid: bool,
    approval_reason: str | None,
    generation_report: dict[str, Any] | None,
    run_status: dict[str, Any] | None,
    reading_qa: dict[str, Any] | None,
    reading_quality: dict[str, Any] | None,
    access_issues: list[dict[str, str]] | None = None,
    timeline_lease: dict[str, Any] | None = None,
    generation_lease: dict[str, Any] | None = None,
    publication_required: bool = False,
) -> dict[str, Any]:
    if not live_url:
        return action("wait_for_source", "No persisted livestream URL is available.", human=True)
    if state.get("lastSunday") and not isinstance(state.get("lastSunday"), str):
        return action("inspect_state", "Persisted live-source state has an invalid Sunday value.", human=True)
    if state.get("lastSunday") and state.get("lastSunday") != sunday:
        return action(
            "waiting_for_matching_sunday",
            f"Persisted live-source state belongs to {state.get('lastSunday')}.",
            human=False,
        )
    if access_issues:
        labels = ", ".join(sorted({item["artifact"] for item in access_issues}))
        return action(
            "restore_artifact_access",
            f"Artifact evidence could not be read for: {labels}.",
            human=True,
        )

    generation_status = str((generation_report or {}).get("status") or "")
    if generation_status == "completed":
        reading_qa_pass = str((reading_qa or {}).get("status") or "") == "pass"
        reading_quality_pass = str((reading_quality or {}).get("status") or "") == "pass"
        if reading_qa_pass and reading_quality_pass:
            if not approval_valid:
                return action(
                    "request_window_approval",
                    approval_reason
                    or "The completed reading PDF is not bound to a valid current window approval.",
                    human=True,
                )
            publication_status = str(
                ((generation_report or {}).get("publication") or {}).get("status")
                or ""
            )
            if publication_required and publication_status != "pass":
                return action(
                    "inspect_publication_evidence",
                    "Generation and QA passed, but verified local/GCS artifact parity is missing.",
                    human=True,
                )
            return action(
                "complete",
                "Reading PDF generation completed and both quality reports passed.",
                human=False,
            )
        return action(
            "inspect_quality_evidence",
            "Generation reports completed, but required passing QA evidence is missing.",
            human=True,
        )

    blocker = (run_status or {}).get("blocker")
    if isinstance(blocker, dict) and blocker.get("reason") in {
        "reading_quality_needs_review",
        "pdf_qa_needs_review",
    }:
        return action(
            "review_quality_failure",
            f"Workflow is blocked at {blocker.get('stage')}: {blocker.get('reason')}.",
            human=True,
        )
    if generation_status in {"failed", "error"}:
        return action(
            "inspect_generation_failure",
            str(
                (generation_report or {}).get("reason")
                or "Reading-PDF generation failed and requires inspection."
            ),
            human=True,
        )
    if lease_active(generation_lease):
        return action(
            "wait_for_active_run",
            "A reading-PDF generation execution already holds the production lease.",
            human=False,
        )
    if lease_active(timeline_lease):
        return action(
            "wait_for_active_run",
            "A timeline execution already holds the production lease.",
            human=False,
        )

    timeline_status = str((timeline_report or {}).get("status") or "")
    if not timeline_report:
        return action(
            "run_timeline_probe",
            "The source exists, but no post-live timeline job report is available.",
            human=False,
        )
    if timeline_status in {"waiting_for_source", "waiting_for_matching_sunday", "waiting_for_post_live"}:
        return action(timeline_status, str(timeline_report.get("reason") or timeline_status), human=False)
    if timeline_status == "waiting_for_download_access":
        return action(
            "operator_download_handoff",
            str(
                timeline_report.get("nextAction")
                or "Provide an authorized local download handoff before continuing."
            ),
            human=True,
        )
    if timeline_status in {"requires_operator_review", "already_requires_operator_review"}:
        if not approval_valid:
            return action(
                "request_window_approval",
                approval_reason or "The suggested sermon window requires operator approval.",
                human=True,
            )
        return action(
            "run_reading_pdf_generation",
            "A valid operator-approved sermon window is available.",
            human=False,
        )
    if timeline_status in {"failed", "error"}:
        return action(
            "inspect_timeline_failure",
            str(timeline_report.get("reason") or "Timeline job failed."),
            human=True,
        )
    return action(
        "inspect_unrecognized_state",
        f"Timeline status {timeline_status or 'missing'} is not recognized.",
        human=True,
    )


def action(name: str, reason: str, *, human: bool) -> dict[str, Any]:
    return {
        "action": name,
        "reason": reason,
        "humanActionRequired": human,
    }


def approve_window(
    config: SupervisorConfig,
    *,
    start_time: str,
    end_time: str,
    approved_by: str,
    content_scope: str,
    note: str | None = None,
    gcs_writer: Callable[[str, str], None] = write_gcs_text,
) -> dict[str, Any]:
    """Persist a human-approved sermon window locally and, when configured, in GCS."""
    snapshot = production_snapshot(config)
    live_url = live_url_from_snapshot(snapshot, config=config)
    if not live_url:
        raise RuntimeError("Cannot approve a window before a livestream URL is persisted.")
    timeline = read_first_json(
        *artifact_read_locations(
            snapshot["locations"].get("timelineReportLocal"),
            snapshot["locations"].get("timelineReportGcs"),
        )
    )
    timeline_status = str((timeline or {}).get("status") or "")
    if timeline_status not in {"requires_operator_review", "already_requires_operator_review"}:
        raise RuntimeError("Cannot approve a window before the timeline job requires operator review.")
    start_seconds = parse_timecode(start_time)
    end_seconds = parse_timecode(end_time)
    if end_seconds <= start_seconds:
        raise ValueError("end_time must be later than start_time")
    approver = str(approved_by or "").strip()
    if not approver:
        raise ValueError("approved_by is required")
    if content_scope not in {"sermon_only", "sermon_plus_response"}:
        raise ValueError("content_scope must be sermon_only or sermon_plus_response")

    locations = snapshot["locations"]
    timeline_digest = json_digest(timeline)
    payload = {
        "schemaVersion": 2,
        "status": "approved",
        "sunday": config.sunday,
        "sourceUrlHash": stable_hash(live_url),
        "startTime": canonical_timecode(start_seconds),
        "endTime": canonical_timecode(end_seconds),
        "approvedBy": approver[:160],
        "contentScope": content_scope,
        "approvedAt": datetime.now(timezone.utc).isoformat(),
        "timelineReportSha256": timeline_digest,
        "note": str(note or "").strip()[:1000] or None,
        "humanApproval": True,
    }
    local_path = Path(locations["windowApprovalLocal"])
    gcs_uri = locations.get("windowApprovalGcs")
    if gcs_uri:
        gcs_writer(gcs_uri, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    write_local_json(local_path, payload)
    return payload


def run_timeline_probe(
    config: SupervisorConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    lease_acquirer: Callable[..., LeaseHandle | None] = acquire_lease,
    lease_releaser: Callable[[LeaseHandle], None] = release_lease,
) -> dict[str, Any]:
    snapshot = production_snapshot(config)
    action_name = snapshot["recommendedAction"]["action"]
    if action_name not in {"run_timeline_probe", "waiting_for_post_live"}:
        return {
            "status": "skipped",
            "reason": f"timeline probe is not valid while recommendedAction={action_name}",
            "snapshot": snapshot,
        }
    lease = lease_acquirer(
        execution_lease_location(snapshot, "timeline"),
        ttl_seconds=config.lease_ttl_seconds,
    )
    if lease is None:
        return {
            "status": "already_running",
            "reason": "Another timeline execution holds the production lease.",
        }
    try:
        ensure_source_lock(config, snapshot)
        command = build_timeline_command(config, snapshot)
        completed = runner(command, check=False, capture_output=True, text=True)
        report = read_first_json(
            *artifact_read_locations(
                snapshot["locations"].get("timelineReportLocal"),
                snapshot["locations"].get("timelineReportGcs"),
            )
        )
        return command_result(command, completed, report)
    finally:
        lease_releaser(lease)


def run_reading_pdf_generation(
    config: SupervisorConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    lease_acquirer: Callable[..., LeaseHandle | None] = acquire_lease,
    lease_releaser: Callable[[LeaseHandle], None] = release_lease,
) -> dict[str, Any]:
    snapshot = production_snapshot(config)
    if snapshot["recommendedAction"]["action"] != "run_reading_pdf_generation":
        return {
            "status": "blocked",
            "reason": snapshot["recommendedAction"]["reason"],
            "recommendedAction": snapshot["recommendedAction"],
        }
    approval = read_first_json(
        *artifact_read_locations(
            snapshot["locations"].get("windowApprovalLocal"),
            snapshot["locations"].get("windowApprovalGcs"),
        )
    )
    valid, reason = validate_window_approval(
        approval,
        sunday=config.sunday,
        live_url=live_url_from_snapshot(snapshot, config=config),
        timeline_report=read_first_json(
            *artifact_read_locations(
                snapshot["locations"].get("timelineReportLocal"),
                snapshot["locations"].get("timelineReportGcs"),
            )
        ),
    )
    if not valid:
        return {"status": "blocked", "reason": reason or "operator approval is invalid"}
    lease = lease_acquirer(
        execution_lease_location(snapshot, "generation"),
        ttl_seconds=config.lease_ttl_seconds,
    )
    if lease is None:
        return {
            "status": "already_running",
            "reason": "Another reading-PDF generation holds the production lease.",
        }
    try:
        return execute_reading_pdf_generation(
            config,
            snapshot,
            approval or {},
            runner=runner,
        )
    finally:
        lease_releaser(lease)


def resume_failed_reading_pdf_generation(
    config: SupervisorConfig,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    lease_acquirer: Callable[..., LeaseHandle | None] = acquire_lease,
    lease_releaser: Callable[[LeaseHandle], None] = release_lease,
    gcs_writer: Callable[[str, str], None] = write_gcs_text,
) -> dict[str, Any]:
    """Explicitly resume a failed generation after preserving its terminal evidence."""
    snapshot = production_snapshot(config)
    action_name = str(snapshot["recommendedAction"]["action"])
    if action_name not in {"inspect_generation_failure", "review_quality_failure"}:
        return {
            "status": "blocked",
            "reason": f"failed-generation resume is not valid while recommendedAction={action_name}",
            "recommendedAction": snapshot["recommendedAction"],
        }
    approval = read_first_json(
        *artifact_read_locations(
            snapshot["locations"].get("windowApprovalLocal"),
            snapshot["locations"].get("windowApprovalGcs"),
        )
    )
    valid, reason = validate_window_approval(
        approval,
        sunday=config.sunday,
        live_url=live_url_from_snapshot(snapshot, config=config),
        timeline_report=read_first_json(
            *artifact_read_locations(
                snapshot["locations"].get("timelineReportLocal"),
                snapshot["locations"].get("timelineReportGcs"),
            )
        ),
    )
    if not valid:
        return {"status": "blocked", "reason": reason or "operator approval is invalid"}
    lease = lease_acquirer(
        execution_lease_location(snapshot, "generation"),
        ttl_seconds=config.lease_ttl_seconds,
    )
    if lease is None:
        return {
            "status": "already_running",
            "reason": "Another reading-PDF generation holds the production lease.",
        }
    try:
        archived = archive_failed_generation_report(
            snapshot["locations"],
            gcs_writer=gcs_writer,
        )
        result = execute_reading_pdf_generation(
            config,
            snapshot,
            approval or {},
            runner=runner,
        )
        result["archivedFailure"] = archived
        return result
    finally:
        lease_releaser(lease)


def execute_reading_pdf_generation(
    config: SupervisorConfig,
    snapshot: dict[str, Any],
    approval: dict[str, Any],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    command = build_generation_command(config, snapshot, approval)
    completed = runner(command, check=False, capture_output=True, text=True)
    report = read_optional_json(snapshot["locations"]["generationReportLocal"])
    if report is None:
        report = build_generation_failure_report(completed, snapshot["locations"])
        write_local_json(Path(snapshot["locations"]["generationReportLocal"]), report)
    publish_generation_evidence(snapshot["locations"], report)
    return command_result(command, completed, report)


def build_timeline_command(config: SupervisorConfig, snapshot: dict[str, Any]) -> list[str]:
    command = [
        config.python_executable,
        str(REPO_ROOT / "scripts" / "run_post_live_timeline_job.py"),
        "--sunday",
        config.sunday,
        "--state-file",
        config.state_file,
        "--work-root",
        str(config.work_root),
        "--out",
        snapshot["locations"]["timelineReportLocal"],
        "--gcs-prefix",
        config.gcs_prefix,
        "--timeline-model",
        config.timeline_model,
        "--classifier-model",
        config.classifier_model,
    ]
    if config.gcs_bucket:
        command.extend(["--gcs-bucket", config.gcs_bucket])
    append_secret_flag(command, "--api-key-secret", config.api_key_secret)
    append_secret_flag(command, "--youtube-api-key-secret", config.youtube_api_key_secret)
    append_secret_flag(command, "--youtube-cookies-secret", config.youtube_cookies_secret)
    if config.youtube_cookies_file:
        command.extend(["--youtube-cookies", str(config.youtube_cookies_file)])
    append_secret_flag(command, "--discord-bot-token-secret", config.discord_bot_token_secret)
    if config.discord_channel_id:
        command.extend(["--discord-channel-id", config.discord_channel_id])
    append_secret_flag(command, "--notify-sendgrid-secret", config.notify_sendgrid_secret)
    append_secret_flag(command, "--notify-recipients-secret", config.notify_recipients_secret)
    append_secret_flag(command, "--notify-sender-secret", config.notify_sender_secret)
    return command


def build_generation_command(
    config: SupervisorConfig,
    snapshot: dict[str, Any],
    approval: dict[str, Any],
) -> list[str]:
    command = [
        config.python_executable,
        str(REPO_ROOT / "scripts" / "run_post_live_subtitle_generation.py"),
        "--sunday",
        config.sunday,
        "--state-file",
        config.state_file,
        "--work-root",
        str(config.work_root),
        "--out",
        snapshot["locations"]["generationReportLocal"],
        "--slug",
        str(snapshot["slug"]),
        "--start-time",
        str(approval["startTime"]),
        "--end-time",
        str(approval["endTime"]),
        "--approval-evidence",
        snapshot["locations"]["windowApprovalLocal"],
        "--output-mode",
        "reading",
        "--reference-model",
        config.reference_model,
        "--reading-edition-provider",
        "openai",
        "--reading-edition-model",
        config.reading_model,
        "--reading-edition-reasoning-effort",
        "high",
    ]
    if approval.get("contentScope"):
        command.extend(["--content-scope", str(approval["contentScope"])])
    if config.gcs_bucket:
        command.extend(["--gcs-bucket", config.gcs_bucket, "--gcs-prefix", config.gcs_prefix])
    if config.youtube_cookies_file:
        command.extend(["--youtube-cookies", str(config.youtube_cookies_file)])
    if config.glossary:
        command.extend(["--glossary", str(config.glossary)])
    append_secret_flag(command, "--api-key-secret", config.api_key_secret)
    return command


def artifact_locations(config: SupervisorConfig, slug: str) -> dict[str, str]:
    run_root = config.work_root / config.sunday / slug
    pipeline = run_root / "pipeline"
    prefix = "/".join(
        part.strip("/")
        for part in (config.gcs_prefix, config.sunday, "post-live-subtitles", slug)
        if part
    )

    def gcs(relative: str) -> str | None:
        if not config.gcs_bucket:
            return None
        return f"gs://{config.gcs_bucket}/{prefix}/{relative}"

    return {
        "runRoot": str(run_root),
        "timelineReportLocal": str(run_root / "timeline" / "agent-job-report.json"),
        "timelineReportGcs": gcs("timeline/job-report.json"),
        "windowApprovalLocal": str(run_root / "operator-window-approval.json"),
        "windowApprovalGcs": gcs("operator-window-approval.json"),
        "generationReportLocal": str(run_root / "agent-generation-report.json"),
        "generationReportGcs": gcs("agent-generation-report.json"),
        "timelineLeaseLocal": str(run_root / "leases" / "timeline.json"),
        "timelineLeaseGcs": gcs("leases/timeline.json"),
        "generationLeaseLocal": str(run_root / "leases" / "generation.json"),
        "generationLeaseGcs": gcs("leases/generation.json"),
        "runStatusLocal": str(run_root / "run-status.json"),
        "runStatusGcs": gcs("run-status.json"),
        "readingQaLocal": str(pipeline / "sermon_zh_en_reading.qa.json"),
        "readingQaGcs": gcs("pipeline/sermon_zh_en_reading.qa.json"),
        "readingQualityLocal": str(pipeline / "reading-edition-v2" / "reading_quality_report.json"),
        "readingQualityGcs": gcs("pipeline/reading-edition-v2/reading_quality_report.json"),
        "readingPdfLocal": str(pipeline / "sermon_zh_en_reading.pdf"),
        "readingPdfGcs": gcs("pipeline/sermon_zh_en_reading.pdf"),
    }


def source_lock_locations(config: SupervisorConfig) -> tuple[str, str | None]:
    local = config.work_root / config.sunday / "source-identity-lock.json"
    gcs = None
    if config.gcs_bucket:
        prefix = "/".join(
            part.strip("/")
            for part in (
                config.gcs_prefix,
                config.sunday,
                "post-live-subtitles",
                "source-identity-lock.json",
            )
            if part
        )
        gcs = f"gs://{config.gcs_bucket}/{prefix}"
    return str(local), gcs


def valid_source_lock(payload: dict[str, Any] | None, sunday: str) -> bool:
    return bool(
        isinstance(payload, dict)
        and payload.get("status") == "locked"
        and payload.get("sunday") == sunday
        and str(payload.get("liveUrl") or "").strip()
    )


def ensure_source_lock(
    config: SupervisorConfig,
    snapshot: dict[str, Any],
    *,
    gcs_writer: Callable[[str, str], None] = write_gcs_text,
) -> dict[str, Any]:
    local_location, gcs_location = source_lock_locations(config)
    existing = read_first_json(
        *artifact_read_locations(local_location, gcs_location)
    )
    if valid_source_lock(existing, config.sunday):
        return existing
    live_url = live_url_from_snapshot(snapshot, config=config)
    if not live_url:
        raise RuntimeError("Cannot lock source identity without a persisted livestream URL.")
    payload = {
        "schemaVersion": 1,
        "status": "locked",
        "sunday": config.sunday,
        "liveUrl": live_url,
        "sourceUrlHash": stable_hash(live_url),
        "source": {
            key: value
            for key, value in (snapshot.get("source") or {}).items()
            if key != "url"
        },
        "lockedAt": datetime.now(timezone.utc).isoformat(),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    if gcs_location:
        gcs_writer(gcs_location, text)
    write_local_json(Path(local_location), payload)
    return payload


def validate_window_approval(
    approval: dict[str, Any] | None,
    *,
    sunday: str,
    live_url: str | None,
    timeline_report: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    if not isinstance(approval, dict):
        return False, "No operator window approval is available."
    if approval.get("status") != "approved" or approval.get("humanApproval") is not True:
        return False, "Window approval is not marked as an explicit human approval."
    if approval.get("sunday") != sunday:
        return False, "Window approval belongs to a different Sunday."
    if not live_url or approval.get("sourceUrlHash") != stable_hash(live_url):
        return False, "Window approval does not match the persisted livestream source."
    try:
        start = parse_timecode(str(approval.get("startTime") or ""))
        end = parse_timecode(str(approval.get("endTime") or ""))
    except ValueError:
        return False, "Window approval contains an invalid timecode."
    if end <= start:
        return False, "Window approval end time is not later than its start time."
    if not str(approval.get("approvedBy") or "").strip():
        return False, "Window approval does not identify the human approver."
    content_scope = approval.get("contentScope")
    if content_scope is not None and content_scope not in {
        "sermon_only",
        "sermon_plus_response",
    }:
        return False, "Window approval contains an invalid content scope."
    if not isinstance(timeline_report, dict):
        return False, "The current timeline report is unavailable."
    if approval.get("timelineReportSha256") != json_digest(timeline_report):
        return False, "Window approval does not match the current timeline report."
    return True, None


def parse_timecode(value: str) -> float:
    match = TIMECODE_RE.fullmatch(str(value or "").strip())
    if not match:
        raise ValueError("timecode must use HH:MM:SS or HH:MM:SS.mmm")
    return (
        int(match.group("hours")) * 3600
        + int(match.group("minutes")) * 60
        + float(match.group("seconds"))
    )


def canonical_timecode(seconds: float) -> str:
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    if millis:
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}"


def read_first_json(*locations: str | None) -> dict[str, Any] | None:
    for location in locations:
        if not location:
            continue
        payload = read_optional_json(location)
        if payload is not None:
            return payload
    return None


def artifact_read_locations(local: str | None, gcs: str | None) -> tuple[str, ...]:
    """Use GCS as production authority; use local evidence only without GCS."""
    if gcs:
        return (gcs,)
    return (local,) if local else ()


def publish_generation_evidence(
    locations: dict[str, str],
    generation_report: dict[str, Any],
    *,
    gcs_writer: Callable[[str, str], None] = write_gcs_text,
) -> None:
    """Publish supporting evidence first and the generation report as the commit marker."""
    for local_key, gcs_key in (
        ("runStatusLocal", "runStatusGcs"),
        ("readingQualityLocal", "readingQualityGcs"),
        ("readingQaLocal", "readingQaGcs"),
    ):
        local = locations.get(local_key)
        gcs = locations.get(gcs_key)
        if not local or not gcs:
            continue
        payload = read_optional_json(local)
        if payload is not None:
            gcs_writer(gcs, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    generation_gcs = locations.get("generationReportGcs")
    if generation_gcs:
        gcs_writer(
            generation_gcs,
            json.dumps(generation_report, ensure_ascii=False, indent=2, sort_keys=True),
        )


def build_generation_failure_report(
    completed: subprocess.CompletedProcess[str],
    locations: dict[str, str],
) -> dict[str, Any]:
    run_status = read_optional_json(locations.get("runStatusLocal"))
    reading_quality = read_optional_json(locations.get("readingQualityLocal"))
    blocker = (run_status or {}).get("blocker")
    stage = (
        str(blocker.get("stage") or "")
        if isinstance(blocker, dict)
        else str((run_status or {}).get("currentStage") or "")
    )
    detail = (
        str(blocker.get("reason") or "")
        if isinstance(blocker, dict)
        else ""
    )
    reason = detail or (
        f"generation subprocess exited with code {completed.returncode}"
        if completed.returncode
        else "generation subprocess completed without writing its report"
    )
    quality_failures = (
        list(reading_quality.get("failures") or [])
        if isinstance(reading_quality, dict)
        else []
    )
    return {
        "schemaVersion": 2,
        "status": "failed",
        "reason": reason,
        "returnCode": completed.returncode,
        "failure": {
            "stage": stage or None,
            "reason": reason,
            "qualityFailures": quality_failures,
            "resumeEligible": bool(stage),
        },
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }


def archive_failed_generation_report(
    locations: dict[str, str],
    *,
    gcs_writer: Callable[[str, str], None] = write_gcs_text,
) -> dict[str, Any]:
    local = Path(locations["generationReportLocal"])
    report = read_first_json(
        *artifact_read_locations(
            str(local),
            locations.get("generationReportGcs"),
        )
    )
    if not isinstance(report, dict) or report.get("status") not in {"failed", "error"}:
        raise RuntimeError("No failed generation report is available to archive.")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archived_local = local.with_name(f"agent-generation-report.failed-{stamp}.json")
    write_local_json(archived_local, report)
    archived_gcs = None
    current_gcs = locations.get("generationReportGcs")
    if current_gcs:
        archived_gcs = current_gcs.rsplit("/", 1)[0] + f"/agent-generation-report.failed-{stamp}.json"
        gcs_writer(
            archived_gcs,
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        )
    if local.exists():
        local.unlink()
    return {
        "local": str(archived_local),
        "gcs": archived_gcs,
        "status": report.get("status"),
    }


def read_supervisor_state(location: str) -> dict[str, Any]:
    try:
        text = live_source_monitor.read_state_text(location)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        if location.startswith("gs://") and (
            exc.__class__.__name__ in {"NotFound", "NoSuchKey"} or "404" in str(exc)
        ):
            return {}
        raise
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Persisted live-source state is not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Persisted live-source state must be a JSON object.")
    return payload


def read_artifact_json(
    artifact: str,
    access_issues: list[dict[str, str]],
    *locations: str | None,
) -> dict[str, Any] | None:
    for location in locations:
        if not location:
            continue
        try:
            payload = read_optional_json(location)
        except Exception as exc:
            access_issues.append(
                {
                    "artifact": artifact,
                    "location": location,
                    "errorClass": exc.__class__.__name__,
                    "message": str(exc)[:300],
                }
            )
            continue
        if payload is not None:
            return payload
    return None


def read_optional_json(location: str) -> dict[str, Any] | None:
    try:
        text = read_gcs_text(location) if location.startswith("gs://") else Path(location).read_text(encoding="utf-8")
        payload = json.loads(text)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    except Exception as exc:
        if location.startswith("gs://") and (
            exc.__class__.__name__ in {"NotFound", "NoSuchKey"} or "404" in str(exc)
        ):
            return None
        raise
    return payload if isinstance(payload, dict) else None


def write_local_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def command_result(
    command: list[str],
    completed: subprocess.CompletedProcess[str],
    report: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "status": str((report or {}).get("status") or ("completed" if completed.returncode == 0 else "failed")),
        "returnCode": completed.returncode,
        "command": redact_command(command),
        "report": report,
        "stdoutTail": str(completed.stdout or "")[-2000:],
        "stderrTail": str(completed.stderr or "")[-2000:],
    }


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    secret_flags = {
        "--api-key-secret",
        "--youtube-api-key-secret",
        "--youtube-cookies-secret",
        "--youtube-cookies",
        "--discord-bot-token-secret",
        "--discord-channel-id",
        "--notify-sendgrid-secret",
        "--notify-recipients-secret",
        "--notify-sender-secret",
    }
    for part in command:
        if redact_next:
            redacted.append("REDACTED_SECRET_RESOURCE")
            redact_next = False
            continue
        redacted.append(part)
        if part in secret_flags:
            redact_next = True
    return redacted


def append_secret_flag(command: list[str], flag: str, value: str | None) -> None:
    if value:
        command.extend([flag, value])


def public_source(source: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    return {
        "kind": source.get("kind"),
        "service": source.get("service"),
        "state": source.get("state"),
        "title": source.get("title"),
        "url": url_summary(str(source.get("url") or "")) if source.get("url") else None,
    }


def public_source_lock(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    return {
        "status": payload.get("status"),
        "sunday": payload.get("sunday"),
        "sourceUrlHash": payload.get("sourceUrlHash"),
        "lockedAt": payload.get("lockedAt"),
    }


def public_timeline_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    return {
        "status": report.get("status"),
        "stage": report.get("stage"),
        "reason": report.get("reason"),
        "suggestedWindow": report.get("suggestedWindow"),
        "reviewInstructions": report.get("reviewInstructions"),
        "localHandoffReady": report.get("localHandoffReady"),
        "nextAction": report.get("nextAction"),
    }


def public_approval(
    approval: dict[str, Any] | None,
    valid: bool,
    reason: str | None,
) -> dict[str, Any]:
    if not isinstance(approval, dict):
        return {"status": "missing", "valid": False, "reason": reason}
    return {
        "status": approval.get("status"),
        "valid": valid,
        "reason": reason,
        "startTime": approval.get("startTime"),
        "endTime": approval.get("endTime"),
        "approvedBy": approval.get("approvedBy"),
        "approvedAt": approval.get("approvedAt"),
        "humanApproval": approval.get("humanApproval") is True,
        "contentScope": approval.get("contentScope") or "legacy_unspecified",
    }


def public_generation_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    return {
        "status": report.get("status"),
        "reason": report.get("reason"),
        "outputMode": report.get("outputMode"),
        "completedAt": report.get("completedAt"),
        "readingQualityReport": report.get("readingQualityReport"),
        "runStatus": report.get("runStatus"),
        "outputs": report.get("outputs"),
        "publication": report.get("publication"),
        "failure": report.get("failure"),
    }


def public_run_status(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    stages = report.get("stages") if isinstance(report.get("stages"), dict) else {}
    return {
        "status": report.get("status"),
        "currentStage": report.get("currentStage"),
        "blocker": report.get("blocker"),
        "stages": {
            name: {
                "status": data.get("status"),
                "attempts": data.get("attempts"),
                "durationSeconds": data.get("durationSeconds"),
                "reason": data.get("reason"),
                "artifacts": data.get("artifacts"),
            }
            for name, data in stages.items()
            if isinstance(data, dict)
        },
    }


def public_quality_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return None
    return {
        "status": report.get("status"),
        "qualityRuleVersion": report.get("qualityRuleVersion"),
        "pageCount": report.get("pageCount"),
        "issues": report.get("issues"),
        "checks": report.get("checks"),
    }


def public_lease(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not lease_active(payload):
        return None
    return {
        "status": payload.get("status"),
        "acquiredAt": payload.get("acquiredAt"),
        "expiresAt": payload.get("expiresAt"),
    }


def lease_active(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict) or payload.get("status") != "active":
        return False
    try:
        expires_at = datetime.fromisoformat(str(payload.get("expiresAt") or ""))
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


def execution_lease_location(snapshot: dict[str, Any], stage: str) -> str:
    locations = snapshot["locations"]
    gcs = locations.get(f"{stage}LeaseGcs")
    local = locations.get(f"{stage}LeaseLocal")
    if gcs:
        return str(gcs)
    if local:
        return str(local)
    raise RuntimeError(f"No lease location is configured for {stage}.")


def live_url_from_snapshot(
    snapshot: dict[str, Any],
    *,
    config: SupervisorConfig | None = None,
) -> str | None:
    if config is not None:
        locked = read_first_json(
            *artifact_read_locations(*source_lock_locations(config))
        )
        if valid_source_lock(locked, config.sunday):
            return str(locked["liveUrl"])
    state = read_supervisor_state(snapshot["stateFile"])
    source = run_post_live_subtitle_generation.selected_source_from_state(state)
    live_url = run_post_live_subtitle_generation.live_url_from_state(state, source)
    expected_hash = str((snapshot.get("liveSource") or {}).get("urlHash") or "")
    if live_url and expected_hash and stable_hash(live_url) != expected_hash:
        raise RuntimeError(
            "Persisted livestream source changed before the durable source lock was created."
        )
    return live_url


def json_digest(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _slug_args():
    class Args:
        slug = None

    return Args()
