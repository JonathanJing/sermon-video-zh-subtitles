from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import AppConfig


REPO_ROOT = Path(__file__).resolve().parents[1]
PREPARE_SCRIPT = REPO_ROOT / "scripts" / "prepare_live_link_playback.py"


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
    command = build_generation_command(request, AppConfig.from_env())
    if args.plan_only:
        print(json.dumps({"command": command}, indent=2))
        return 0
    subprocess.run(command, cwd=REPO_ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

