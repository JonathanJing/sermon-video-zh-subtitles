#!/usr/bin/env python3
"""Plan or apply publishing a local Sunday manifest evidence tree to GCS."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.validate_sunday_manifest import validate_manifest_contract


DEFAULT_LOCAL_ROOT = REPO_ROOT / "artifacts" / "evidence" / "manifest-promotion-guard"
DEFAULT_OUT = REPO_ROOT / "artifacts" / "evidence" / "gcs-sunday-manifest-publish-plan.json"


def main() -> int:
    args = parse_args()
    report = build_publish_plan(
        sunday=args.sunday,
        local_root=resolve_repo_path(args.local_root),
        bucket=args.bucket,
        prefix=args.prefix,
        session_id=args.session_id,
        apply=args.apply,
    )
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"planned", "applied"} else 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sunday", required=True, help="Sunday date, YYYY-MM-DD.")
    parser.add_argument("--local-root", type=Path, default=DEFAULT_LOCAL_ROOT)
    parser.add_argument("--bucket", required=True, help="GCS bucket name or gs://bucket.")
    parser.add_argument("--prefix", default="sundays", help="GCS prefix for Sunday artifacts.")
    parser.add_argument(
        "--session-id",
        default="local-manifest-contract",
        help="Run session id under <prefix>/<sunday>/runs/<session-id>/.",
    )
    parser.add_argument("--apply", action="store_true", help="Execute gcloud storage cp commands.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    return parser.parse_args()


def build_publish_plan(
    *,
    sunday: str,
    local_root: Path,
    bucket: str,
    prefix: str,
    session_id: str,
    apply: bool,
) -> dict[str, Any]:
    bucket_name = normalize_bucket(bucket)
    clean_prefix = normalize_prefix(prefix)
    clean_session = sanitize_path_part(session_id)
    run_prefix = join_gcs_parts(clean_prefix, sunday, "runs", clean_session)
    stable_prefix = join_gcs_parts(clean_prefix, sunday)
    run_manifest_uri = gcs_uri(bucket_name, run_prefix, "artifacts/cloud-manifest.json")
    stable_manifest_uri = gcs_uri(bucket_name, stable_prefix, "cloud-manifest.json")

    local_manifest_path = local_root / "cloud-manifest.json"
    local_manifest = read_json(local_manifest_path)
    local_validation = validate_manifest_contract(
        manifest=local_manifest,
        manifest_uri=display_path(local_manifest_path),
        sunday=sunday,
        expected_readiness="published",
        expected_source_mode="youtube-live-archive",
        require_readable_artifacts=True,
    )
    if local_validation["status"] != "ok":
        return failure_report(
            sunday=sunday,
            local_root=local_root,
            bucket_name=bucket_name,
            prefix=clean_prefix,
            failed_checks=local_validation["failedChecks"],
            message="Local Sunday manifest contract failed; refusing to plan GCS publish.",
        )

    run_manifest = build_gcs_manifest(
        local_manifest,
        local_root=local_root,
        bucket_name=bucket_name,
        run_prefix=run_prefix,
        run_manifest_uri=run_manifest_uri,
        stable_manifest_uri=stable_manifest_uri,
    )
    stable_manifest = dict(run_manifest)
    stable_manifest["sourceManifest"] = run_manifest_uri
    stable_manifest["publishedManifest"] = stable_manifest_uri
    if isinstance(stable_manifest.get("readiness"), dict):
        stable_manifest["readiness"] = dict(stable_manifest["readiness"])
        stable_manifest["readiness"]["publishedManifest"] = stable_manifest_uri

    gcs_validation = validate_manifest_contract(
        manifest=stable_manifest,
        manifest_uri=stable_manifest_uri,
        sunday=sunday,
        expected_readiness="published",
        expected_source_mode="youtube-live-archive",
        require_readable_artifacts=False,
    )
    if gcs_validation["status"] != "ok" or gcs_validation["publicGcsArtifacts"] is not True:
        return failure_report(
            sunday=sunday,
            local_root=local_root,
            bucket_name=bucket_name,
            prefix=clean_prefix,
            failed_checks=gcs_validation["failedChecks"] or ["public_gcs_artifacts"],
            message="Generated GCS manifest did not satisfy the public GCS manifest contract.",
        )

    copy_steps = artifact_copy_steps(stable_manifest, local_root=local_root)
    commands = [step["command"] for step in copy_steps]
    commands.extend(
        [
            ["gcloud", "storage", "cp", "<generated-run-manifest>", run_manifest_uri],
            ["gcloud", "storage", "cp", "<generated-stable-manifest>", stable_manifest_uri],
            [
                sys.executable,
                "scripts/validate_sunday_manifest.py",
                "--manifest",
                stable_manifest_uri,
                "--sunday",
                sunday,
                "--require-readable-artifacts",
                "--out",
                "artifacts/evidence/sunday-manifest-validation.json",
            ],
        ]
    )

    applied_steps: list[dict[str, Any]] = []
    if apply:
        applied_steps = apply_publish(
            copy_steps=copy_steps,
            run_manifest=run_manifest,
            stable_manifest=stable_manifest,
            run_manifest_uri=run_manifest_uri,
            stable_manifest_uri=stable_manifest_uri,
        )

    return {
        "schemaVersion": 1,
        "status": "applied" if apply else "planned",
        "sunday": sunday,
        "artifactLocation": "gcs",
        "bucket": bucket_name,
        "prefix": clean_prefix,
        "sessionId": clean_session,
        "localRoot": display_path(local_root),
        "runManifestUri": run_manifest_uri,
        "stableManifestUri": stable_manifest_uri,
        "localValidation": {
            "status": local_validation["status"],
            "artifactLocation": local_validation["artifactLocation"],
            "publicGcsArtifacts": local_validation["publicGcsArtifacts"],
            "readableArtifactsRequired": local_validation["readableArtifactsRequired"],
            "failedChecks": local_validation["failedChecks"],
        },
        "gcsManifestValidation": {
            "status": gcs_validation["status"],
            "artifactLocation": gcs_validation["artifactLocation"],
            "publicGcsArtifacts": gcs_validation["publicGcsArtifacts"],
            "readableArtifactsRequired": gcs_validation["readableArtifactsRequired"],
            "failedChecks": gcs_validation["failedChecks"],
        },
        "artifacts": [
            {
                "localPath": step["localPath"],
                "source": display_path(Path(step["source"])),
                "destination": step["destination"],
            }
            for step in copy_steps
        ],
        "commands": commands,
        "appliedSteps": applied_steps,
        "nextAction": (
            "Run this script with --apply, then rerun validate_sunday_manifest.py against "
            f"{stable_manifest_uri}."
            if not apply
            else "Rerun validate_sunday_manifest.py against the stable gs:// manifest and refresh the production evidence matrix."
        ),
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def build_gcs_manifest(
    manifest: dict[str, Any],
    *,
    local_root: Path,
    bucket_name: str,
    run_prefix: str,
    run_manifest_uri: str,
    stable_manifest_uri: str,
) -> dict[str, Any]:
    planned = dict(manifest)
    planned["outputs"] = []
    for item in manifest.get("outputs") or []:
        if not isinstance(item, dict):
            continue
        local_path = str(item.get("localPath") or "")
        if not local_path:
            continue
        source = local_root / local_path
        if not source.is_file():
            raise SystemExit(f"local manifest output is missing: {display_path(source)}")
        planned["outputs"].append(
            {
                **item,
                "localPath": local_path,
                "gcsUri": gcs_uri(bucket_name, run_prefix, local_path),
            }
        )
    planned["sourceManifest"] = run_manifest_uri
    planned["publishedManifest"] = stable_manifest_uri
    planned["apiKeyMaterialIncluded"] = False
    planned["secretResourceNamesIncluded"] = False
    return planned


def artifact_copy_steps(manifest: dict[str, Any], *, local_root: Path) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for item in manifest.get("outputs") or []:
        if not isinstance(item, dict):
            continue
        local_path = str(item.get("localPath") or "")
        destination = str(item.get("gcsUri") or "")
        if not local_path or not destination:
            continue
        source = local_root / local_path
        steps.append(
            {
                "localPath": local_path,
                "source": str(source),
                "destination": destination,
                "command": ["gcloud", "storage", "cp", str(source), destination],
            }
        )
    return steps


def apply_publish(
    *,
    copy_steps: list[dict[str, Any]],
    run_manifest: dict[str, Any],
    stable_manifest: dict[str, Any],
    run_manifest_uri: str,
    stable_manifest_uri: str,
) -> list[dict[str, Any]]:
    applied = []
    for step in copy_steps:
        completed = subprocess.run(step["command"], cwd=REPO_ROOT, check=False, capture_output=True, text=True)
        applied.append(command_result(step["command"], completed.returncode))
        if completed.returncode != 0:
            raise SystemExit(f"gcloud upload failed for {step['localPath']}")
    for payload, destination, label in [
        (run_manifest, run_manifest_uri, "run-manifest"),
        (stable_manifest, stable_manifest_uri, "stable-manifest"),
    ]:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            temp_path = Path(handle.name)
        command = ["gcloud", "storage", "cp", str(temp_path), destination]
        completed = subprocess.run(command, cwd=REPO_ROOT, check=False, capture_output=True, text=True)
        temp_path.unlink(missing_ok=True)
        applied.append(command_result(command, completed.returncode, label=label))
        if completed.returncode != 0:
            raise SystemExit(f"gcloud upload failed for {label}")
    return applied


def command_result(command: list[str], return_code: int, label: str | None = None) -> dict[str, Any]:
    return {
        "label": label,
        "returnCode": return_code,
        "command": sanitize_command(command),
    }


def failure_report(
    *,
    sunday: str,
    local_root: Path,
    bucket_name: str,
    prefix: str,
    failed_checks: list[str],
    message: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "status": "failed",
        "sunday": sunday,
        "localRoot": display_path(local_root),
        "bucket": bucket_name,
        "prefix": prefix,
        "failedChecks": failed_checks,
        "message": message,
        "apiKeyMaterialIncluded": False,
        "secretResourceNamesIncluded": False,
    }


def read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{display_path(path)} must contain a JSON object")
    return data


def normalize_bucket(bucket: str) -> str:
    clean = bucket.removeprefix("gs://").strip("/")
    if not clean or "/" in clean or clean in {".", ".."}:
        raise SystemExit("--bucket must be a GCS bucket name, not a path")
    return clean


def normalize_prefix(prefix: str) -> str:
    clean = prefix.strip().strip("/")
    if any(part in {".", ".."} for part in clean.split("/") if part):
        raise SystemExit("--prefix cannot contain . or ..")
    return clean


def sanitize_path_part(value: str) -> str:
    clean = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in value.strip())
    clean = clean.strip("-_")
    if not clean:
        raise SystemExit("path part cannot be empty")
    return clean


def join_gcs_parts(*parts: str) -> str:
    return "/".join(part.strip("/") for part in parts if part.strip("/"))


def gcs_uri(bucket: str, prefix: str, local_path: str) -> str:
    object_name = join_gcs_parts(prefix, local_path)
    return f"gs://{bucket}/{object_name}" if object_name else f"gs://{bucket}"


def sanitize_command(command: list[str]) -> list[str]:
    return [part if "token=" not in part.lower() else part.split("?", 1)[0] + "?token=REDACTED" for part in command]


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def display_path(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
