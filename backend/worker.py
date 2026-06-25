from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import AppConfig
from .observability import command_stage, log_event, url_summary


REPO_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "prepare_live_link_playback.py"
TRANSLATE_SCRIPT = REPO_ROOT / "scripts" / "translate_playback_with_openai.py"
NOTES_SCRIPT = REPO_ROOT / "scripts" / "generate_notes_with_openai.py"
PROMOTE_SCRIPT = REPO_ROOT / "scripts" / "promote_sunday_manifest.py"
NOTES_MODEL = "gpt-5.5-mini"
NOTES_REASONING_EFFORT = "medium"


@dataclass(frozen=True)
class GenerationRequest:
    sunday: str
    live_url: str
    session_id: str | None = None
    sermon_url: str | None = None
    sermon_start: str | None = None
    playback_lang: str | None = None
    max_segments: int = 80
    playback_speed: float = 18.0
    dry_run_gcs: bool = False


@dataclass(frozen=True)
class GenerationPlan:
    session_id: str
    prefix: str
    commands: list[list[str]]


def build_generation_command(
    request: GenerationRequest,
    config: AppConfig,
    work_root: Path = Path("/tmp/sermon-worker"),
) -> list[str]:
    if not config.artifact_bucket:
        raise ValueError("SERMON_ARTIFACT_BUCKET is required to generate Sunday artifacts")
    if not config.openai_api_key_secret:
        raise ValueError("OPENAI_API_KEY_SECRET must point to Secret Manager, not raw key material")

    session_id = request.session_id or default_session_id()
    run_root = work_root / request.sunday / session_id
    out_dir = run_root / "artifacts"
    web_out = run_root / "web" / "playback-simulation.generated.js"
    prefix = "/".join(
        part.strip("/")
        for part in [config.artifact_prefix, request.sunday, "runs", session_id]
        if part.strip("/")
    )

    command = [
        sys.executable,
        str(PREPARE_SCRIPT),
        "--live-url",
        request.live_url,
        "--out-dir",
        str(out_dir),
        "--web-out",
        str(web_out),
        "--max-segments",
        str(request.max_segments),
        "--playback-speed",
        str(request.playback_speed),
        "--gcs-bucket",
        config.artifact_bucket,
        "--gcs-prefix",
        prefix,
        "--api-key-secret",
        config.openai_api_key_secret,
    ]
    if request.sermon_url:
        command.extend(["--sermon-url", request.sermon_url])
    if request.sermon_start:
        command.extend(["--sermon-start", request.sermon_start])
    if request.playback_lang:
        command.extend(["--playback-lang", request.playback_lang])
    if request.dry_run_gcs:
        command.append("--gcs-dry-run")
    return command


def build_generation_plan(
    request: GenerationRequest,
    config: AppConfig,
    work_root: Path = Path("/tmp/sermon-worker"),
) -> GenerationPlan:
    if not config.artifact_bucket:
        raise ValueError("SERMON_ARTIFACT_BUCKET is required to generate Sunday artifacts")
    if not config.openai_api_key_secret:
        raise ValueError("OPENAI_API_KEY_SECRET must point to Secret Manager, not raw key material")

    session_id = request.session_id or default_session_id()
    run_root = work_root / request.sunday / session_id
    web_out = run_root / "web" / "playback-simulation.generated.js"
    translation_out_dir = run_root / "model-output"
    insights_out_dir = run_root / "insights"
    manifest_path = run_root / "artifacts" / "cloud-manifest.json"
    prefix = "/".join(
        part.strip("/")
        for part in [config.artifact_prefix, request.sunday, "runs", session_id]
        if part.strip("/")
    )
    stable_manifest_prefix = config.artifact_prefix.strip("/")

    prepare = build_generation_command(
        GenerationRequest(
            sunday=request.sunday,
            live_url=request.live_url,
            session_id=session_id,
            sermon_url=request.sermon_url,
            sermon_start=request.sermon_start,
            playback_lang=request.playback_lang,
            max_segments=request.max_segments,
            playback_speed=request.playback_speed,
            dry_run_gcs=request.dry_run_gcs,
        ),
        config,
        work_root=work_root,
    )
    translate = [
        sys.executable,
        str(TRANSLATE_SCRIPT),
        "--input",
        str(web_out),
        "--out",
        str(web_out),
        "--out-dir",
        str(translation_out_dir),
        "--api-key-secret",
        config.openai_api_key_secret,
        "--max-segments",
        str(request.max_segments),
    ]
    upload_translated_playback = [
        "gcloud",
        "storage",
        "cp",
        str(web_out),
        f"gs://{config.artifact_bucket}/{prefix}/web/playback-simulation.generated.js",
    ]
    generate_notes = [
        sys.executable,
        str(NOTES_SCRIPT),
        "--input",
        str(web_out),
        "--out-dir",
        str(insights_out_dir),
        "--model-output-dir",
        str(translation_out_dir),
        "--manifest",
        str(manifest_path),
        "--api-key-secret",
        config.openai_api_key_secret,
        "--model",
        NOTES_MODEL,
        "--reasoning-effort",
        NOTES_REASONING_EFFORT,
        "--gcs-bucket",
        config.artifact_bucket,
        "--gcs-prefix",
        prefix,
    ]
    if request.dry_run_gcs:
        generate_notes.append("--gcs-dry-run")
    promote = [
        sys.executable,
        str(PROMOTE_SCRIPT),
        "--source-manifest",
        f"gs://{config.artifact_bucket}/{prefix}/artifacts/cloud-manifest.json",
        "--sunday",
        request.sunday,
        "--gcs-bucket",
        config.artifact_bucket,
        "--gcs-prefix",
        stable_manifest_prefix,
    ]
    if request.dry_run_gcs:
        promote.append("--dry-run")
    return GenerationPlan(
        session_id=session_id,
        prefix=prefix,
        commands=[prepare, translate, upload_translated_playback, generate_notes, promote],
    )


def default_session_id() -> str:
    return "worker-" + datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")


def parse_generation_request(payload: dict, sunday: str) -> GenerationRequest:
    live_url = payload.get("liveUrl") or payload.get("live_url")
    if not live_url:
        raise ValueError("liveUrl is required")
    return GenerationRequest(
        sunday=sunday,
        live_url=live_url,
        session_id=payload.get("sessionId") or payload.get("session_id"),
        sermon_url=payload.get("sermonUrl") or payload.get("sermon_url"),
        sermon_start=payload.get("sermonStart") or payload.get("sermon_start"),
        playback_lang=payload.get("playbackLang") or payload.get("playback_lang"),
        max_segments=int(payload.get("maxSegments", 80)),
        playback_speed=float(payload.get("playbackSpeed", 18.0)),
        dry_run_gcs=bool(payload.get("dryRunGcs", False)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Sunday sermon caption artifacts.")
    parser.add_argument("--sunday", required=True, help="Sunday slice date, YYYY-MM-DD.")
    parser.add_argument("--live-url", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--sermon-url")
    parser.add_argument("--sermon-start")
    parser.add_argument("--playback-lang")
    parser.add_argument("--dry-run-gcs", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()

    request = GenerationRequest(
        sunday=args.sunday,
        live_url=args.live_url,
        session_id=args.session_id,
        sermon_url=args.sermon_url,
        sermon_start=args.sermon_start,
        playback_lang=args.playback_lang,
        dry_run_gcs=args.dry_run_gcs,
    )
    plan = build_generation_plan(request, AppConfig.from_env())
    if args.plan_only:
        log_event(
            "live_capture_plan_created",
            component="worker",
            sunday=request.sunday,
            sessionId=plan.session_id,
            runPrefix=plan.prefix,
            liveSource=url_summary(request.live_url),
            commandCount=len(plan.commands),
        )
        print(json.dumps({"sessionId": plan.session_id, "prefix": plan.prefix, "commands": plan.commands}, indent=2))
        return 0
    log_event(
        "live_capture_worker_started",
        component="worker",
        sunday=request.sunday,
        sessionId=plan.session_id,
        runPrefix=plan.prefix,
        liveSource=url_summary(request.live_url),
    )
    for command in plan.commands:
        stage = command_stage(command)
        log_event(
            "worker_stage_started",
            component="worker",
            sunday=request.sunday,
            sessionId=plan.session_id,
            runPrefix=plan.prefix,
            stage=stage,
        )
        subprocess.run(command, cwd=REPO_ROOT, check=True)
        log_event(
            "worker_stage_completed",
            component="worker",
            sunday=request.sunday,
            sessionId=plan.session_id,
            runPrefix=plan.prefix,
            stage=stage,
        )
    log_event(
        "captions_ready",
        component="worker",
        sunday=request.sunday,
        sessionId=plan.session_id,
        runPrefix=plan.prefix,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
