#!/usr/bin/env python3
"""Write a sanitized worker caption-first generation plan report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.config import AppConfig
from backend.worker import GenerationRequest, build_generation_plan

PLACEHOLDER_OPENAI_SECRET = "projects/PROJECT/secrets/openai-api-key/versions/latest"


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", default="2026-06-28")
    parser.add_argument("--live-url", default="https://www.youtube.com/watch?v=example")
    parser.add_argument("--session-id", default="caption-first-plan")
    parser.add_argument("--artifact-bucket", default="sermon-zh-artifacts-ai-for-god")
    parser.add_argument("--artifact-prefix", default="sundays")
    parser.add_argument("--include-insights", action="store_true")
    parser.add_argument("--translations-jsonl")
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> dict:
    config = AppConfig(
        artifact_bucket=args.artifact_bucket,
        artifact_prefix=args.artifact_prefix,
        current_manifest_uri=None,
        sunday_manifest_uri_template=None,
        timezone="America/Los_Angeles",
        openai_api_key_secret=PLACEHOLDER_OPENAI_SECRET,
        operator_admin_token=None,
        internal_task_token=None,
        enable_inline_worker=False,
    )
    plan = build_generation_plan(
        GenerationRequest(
            sunday=args.sunday,
            live_url=args.live_url,
            session_id=args.session_id,
            dry_run_gcs=True,
            include_insights=args.include_insights,
            translations_jsonl=args.translations_jsonl,
        ),
        config,
    )
    stages = [stage_for_command(command) for command in plan.commands]
    notes_included = "notes" in stages
    promote_before_notes = "promote" in stages and (
        not notes_included or stages.index("promote") < stages.index("notes")
    )
    return {
        "schemaVersion": 1,
        "status": "ok",
        "sessionId": plan.session_id,
        "prefix": plan.prefix,
        "commandCount": len(plan.commands),
        "stages": stages,
        "translationMode": "saved_jsonl_replay" if args.translations_jsonl else "fresh_model_call",
        "notesIncluded": notes_included,
        "promoteBeforeNotes": promote_before_notes,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def stage_for_command(command: list[str]) -> str:
    joined = " ".join(command)
    if "run_openai_model_access_preflight.py" in joined:
        return "model-access"
    if "prepare_live_link_playback.py" in joined:
        return "prepare"
    if "translate_playback_with_openai.py" in joined:
        return "translate"
    if "export_playback_captions.py" in joined:
        return "export-captions"
    if "validate_offline_chain.py" in joined:
        return "validate-offline"
    if (
        ("upload_file_to_gcs.py" in joined or command[:3] == ["gcloud", "storage", "cp"])
        and "playback-simulation.generated.js" in joined
    ):
        return "upload-playback"
    if (
        ("upload_file_to_gcs.py" in joined or command[:3] == ["gcloud", "storage", "cp"])
        and "cloud-manifest.json" in joined
    ):
        return "upload-manifest"
    if "promote_sunday_manifest.py" in joined:
        return "promote"
    if "generate_notes_with_openai.py" in joined:
        return "notes"
    return "other"


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
