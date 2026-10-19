#!/usr/bin/env python3
"""Apply an approved Cloud Run realtime update plan and run validations."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    args = parse_args()
    report = apply_plan(args)
    if args.out:
        out = resolve_repo_path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] in {"dry_run", "ok"} else 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True, help="cloud-run-realtime-update-plan.json.")
    parser.add_argument("--approve", action="store_true", help="Actually run the apply command from the plan.")
    parser.add_argument(
        "--rollback-on-failure",
        action="store_true",
        help="Run the plan rollback command if apply succeeds but validation fails.",
    )
    parser.add_argument("--skip-validation", action="store_true", help="Only run the apply command.")
    parser.add_argument("--out", type=Path, help="Optional execution report.")
    return parser.parse_args()


def apply_plan(args: argparse.Namespace) -> dict[str, Any]:
    plan = read_plan(args.plan)
    commands = plan.get("commands") if isinstance(plan.get("commands"), dict) else {}
    apply_command = command_argv(commands.get("apply"), "apply")
    rollback_command = command_argv(commands.get("rollback"), "rollback")
    validate_commands = [command_argv(item, "validate") for item in commands.get("validate") or []]
    required_runtime_env = [] if args.skip_validation else required_runtime_env_vars(validate_commands)
    token_sources = runtime_token_sources(required_runtime_env, apply_command)
    missing_runtime_env = [name for name, source in token_sources.items() if source == "missing"]

    if not args.approve:
        return {
            "schemaVersion": 1,
            "status": "dry_run",
            "approved": False,
            "requiredRuntimeEnv": required_runtime_env,
            "missingRuntimeEnv": missing_runtime_env,
            "runtimeTokenSources": token_sources,
            "wouldApply": redact_command(apply_command),
            "wouldValidate": [redact_command(command) for command in validate_commands],
            "wouldRollback": redact_command(rollback_command),
            "apiKeyMaterialIncluded": False,
            "secretReferencesIncluded": False,
            "secretResourceNamesIncluded": False,
            "eventTokenIncluded": False,
        }

    if missing_runtime_env:
        return {
            "schemaVersion": 1,
            "status": "missing_runtime_env",
            "approved": True,
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "missingRuntimeEnv": missing_runtime_env,
            "requiredRuntimeEnv": required_runtime_env,
            "runtimeTokenSources": token_sources,
            "apply": None,
            "validation": [],
            "rollback": None,
            "postApplyEvidence": plan.get("postApplyEvidence") or [],
            "apiKeyMaterialIncluded": False,
            "secretReferencesIncluded": False,
            "secretResourceNamesIncluded": False,
            "eventTokenIncluded": False,
        }

    try:
        runtime_tokens = load_runtime_tokens(required_runtime_env, apply_command)
    except Exception as exc:
        return {
            "schemaVersion": 1,
            "status": "runtime_token_access_failed",
            "approved": True,
            "startedAt": datetime.now(timezone.utc).isoformat(),
            "missingRuntimeEnv": [],
            "requiredRuntimeEnv": required_runtime_env,
            "runtimeTokenSources": token_sources,
            "error": sanitize_error_message(str(exc)),
            "apply": None,
            "validation": [],
            "rollback": None,
            "postApplyEvidence": plan.get("postApplyEvidence") or [],
            "apiKeyMaterialIncluded": False,
            "secretReferencesIncluded": False,
            "secretResourceNamesIncluded": False,
            "eventTokenIncluded": False,
        }

    apply_result = run_command(apply_command, "apply")
    validation_results: list[dict[str, Any]] = []
    rollback_result = None
    status = "ok"

    if apply_result["status"] != "ok":
        status = "apply_failed"
    elif not args.skip_validation:
        for command in validate_commands:
            result = run_command(expand_runtime_tokens(command, runtime_tokens), "validate")
            validation_results.append(result)
            if result["status"] != "ok":
                status = "validation_failed"
                break
        if status == "validation_failed" and args.rollback_on_failure:
            rollback_result = run_command(rollback_command, "rollback")
            if rollback_result["status"] != "ok":
                status = "rollback_failed"

    return {
        "schemaVersion": 1,
        "status": status,
        "approved": True,
        "startedAt": datetime.now(timezone.utc).isoformat(),
        "requiredRuntimeEnv": required_runtime_env,
        "missingRuntimeEnv": [],
        "runtimeTokenSources": token_sources,
        "apply": apply_result,
        "validation": validation_results,
        "rollback": rollback_result,
        "postApplyEvidence": plan.get("postApplyEvidence") or [],
        "apiKeyMaterialIncluded": False,
        "secretReferencesIncluded": False,
        "secretResourceNamesIncluded": False,
        "eventTokenIncluded": False,
    }


def run_command(command: list[str], stage: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {
            "stage": stage,
            "status": "failed",
            "argv": redact_command(command),
            "returncode": None,
            "stderrTail": str(exc)[:500],
        }
    return {
        "stage": stage,
        "status": "ok" if completed.returncode == 0 else "failed",
        "argv": redact_command(command),
        "returncode": completed.returncode,
        "stdoutTail": tail(completed.stdout),
        "stderrTail": tail(completed.stderr),
    }


def expand_runtime_tokens(command: list[str], runtime_tokens: dict[str, str] | None = None) -> list[str]:
    runtime_tokens = runtime_tokens or {}
    expanded = []
    for part in command:
        if part == "$INTERNAL_TASK_TOKEN":
            token = runtime_tokens.get("INTERNAL_TASK_TOKEN") or os.getenv("INTERNAL_TASK_TOKEN")
            if not token:
                raise SystemExit("INTERNAL_TASK_TOKEN environment variable is required for validation.")
            expanded.append(token)
        elif part == "$OPERATOR_ADMIN_TOKEN":
            token = runtime_tokens.get("OPERATOR_ADMIN_TOKEN") or os.getenv("OPERATOR_ADMIN_TOKEN")
            if not token:
                raise SystemExit("OPERATOR_ADMIN_TOKEN environment variable is required for validation.")
            expanded.append(token)
        else:
            expanded.append(part)
    return expanded


def required_runtime_env_vars(commands: list[list[str]]) -> list[str]:
    env_names = []
    for command in commands:
        for part in command:
            if part == "$INTERNAL_TASK_TOKEN":
                env_names.append("INTERNAL_TASK_TOKEN")
            elif part == "$OPERATOR_ADMIN_TOKEN":
                env_names.append("OPERATOR_ADMIN_TOKEN")
    return sorted(set(env_names))


def missing_runtime_env_vars(env_names: list[str]) -> list[str]:
    return [name for name in env_names if not os.getenv(name)]


def runtime_token_sources(env_names: list[str], apply_command: list[str]) -> dict[str, str]:
    secret_refs = update_secret_refs(apply_command)
    sources = {}
    for name in env_names:
        if os.getenv(name):
            sources[name] = "env"
        elif name in secret_refs:
            sources[name] = "secret_manager"
        else:
            sources[name] = "missing"
    return sources


def load_runtime_tokens(env_names: list[str], apply_command: list[str]) -> dict[str, str]:
    secret_refs = update_secret_refs(apply_command)
    project = command_option(apply_command, "--project")
    tokens = {}
    for name in env_names:
        env_value = os.getenv(name)
        if env_value:
            tokens[name] = env_value
            continue
        secret_ref = secret_refs.get(name)
        if not secret_ref:
            continue
        tokens[name] = access_secret(secret_ref, default_project=project)
    return tokens


def update_secret_refs(command: list[str]) -> dict[str, str]:
    refs = {}
    value = command_option(command, "--update-secrets")
    if not value:
        return refs
    for item in value.split(","):
        name, sep, secret_ref = item.partition("=")
        if sep and name and secret_ref:
            refs[name] = secret_ref
    return refs


def command_option(command: list[str], option: str) -> str | None:
    for index, part in enumerate(command[:-1]):
        if part == option:
            return command[index + 1]
    return None


def access_secret(secret_ref: str, *, default_project: str | None) -> str:
    secret, version = split_secret_ref(secret_ref)
    if secret.startswith("projects/"):
        parts = secret.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "projects" and parts[2] == "secrets":
            project = parts[1]
            secret_name = parts[3]
        else:
            raise ValueError("Secret resource name in plan is not a valid Secret Manager secret.")
    else:
        if not default_project:
            raise ValueError("Plan secret reference requires --project in the apply command.")
        project = default_project
        secret_name = secret
    completed = subprocess.run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            version,
            "--secret",
            secret_name,
            "--project",
            project,
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    token = completed.stdout.strip()
    if not token:
        raise ValueError("Secret Manager returned an empty runtime token.")
    return token


def split_secret_ref(secret_ref: str) -> tuple[str, str]:
    if ":" not in secret_ref:
        return secret_ref, "latest"
    secret, version = secret_ref.rsplit(":", 1)
    return secret, version or "latest"


def command_argv(record: Any, name: str) -> list[str]:
    if not isinstance(record, dict) or not isinstance(record.get("argv"), list):
        raise SystemExit(f"Plan is missing commands.{name}.argv")
    command = [str(part) for part in record["argv"]]
    if not command:
        raise SystemExit(f"Plan command is empty: {name}")
    return command


def redact_command(command: list[str]) -> list[str]:
    redacted = []
    skip_next_secret = False
    skip_next_update_secrets = False
    for part in command:
        if skip_next_update_secrets:
            redacted.append(redact_update_secrets(part))
            skip_next_update_secrets = False
            continue
        if skip_next_secret:
            redacted.append("<redacted-runtime-token>" if part not in {"$INTERNAL_TASK_TOKEN", "$OPERATOR_ADMIN_TOKEN"} else part)
            skip_next_secret = False
            continue
        redacted.append(part)
        if part in {"--internal-task-token", "--admin-token"}:
            skip_next_secret = True
        elif part == "--update-secrets":
            skip_next_update_secrets = True
    return redacted


def redact_update_secrets(value: str) -> str:
    redacted = []
    for item in value.split(","):
        name, sep, _secret_ref = item.partition("=")
        redacted.append(f"{name}=<redacted-secret>" if sep else "<redacted-secret>")
    return ",".join(redacted)


def sanitize_error_message(message: str) -> str:
    clean = str(message or "unknown error")
    for token in ("INTERNAL_TASK_TOKEN", "OPERATOR_ADMIN_TOKEN"):
        value = os.getenv(token)
        if value:
            clean = clean.replace(value, "<redacted-runtime-token>")
    clean = re.sub(r"--secret[= ]['\"]?[^,'\"\]\s]+", "--secret <redacted-secret>", clean)
    clean = re.sub(r"projects/[^/\s,'\"]+/secrets/[^/\s,'\"]+(?:/versions/[^/\s,'\"]+)?", "projects/REDACTED/secrets/REDACTED/versions/REDACTED", clean)
    return clean[:500]


def read_plan(path: Path) -> dict[str, Any]:
    data = json.loads(resolve_repo_path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("--plan must be a JSON object")
    return data


def tail(text: str, limit: int = 2500) -> str:
    return text[-limit:] if len(text) > limit else text


def resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


if __name__ == "__main__":
    raise SystemExit(main())
