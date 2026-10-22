#!/usr/bin/env python3
"""Select an explicit local OpenAI environment and optional DeepSeek key, without shell-sourcing secrets."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
NAMES = {f"OPENAI_{env}_{suffix}" for env in ("DEV", "PROD")
         for suffix in ("API_KEY", "PROJECT_ID")}


def child_environment(path, environment, inherited=None):
    if path.is_symlink() or not path.is_file():
        raise ValueError("credential_file_missing_or_symlink")
    if path.stat().st_mode & 0o077:
        raise ValueError("credential_file_requires_mode_600")
    values = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, value = line.partition("=")
        name, value = name.strip(), value.strip()
        if not sep or name not in NAMES or name in values:
            raise ValueError("invalid_credential_file_assignment")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        # No interpolation, shell evaluation, multiline values or inline comments.
        if any(c.isspace() for c in value) or any(c in value for c in "`$#"):
            raise ValueError("invalid_credential_file_value")
        values[name] = value
    if environment not in ("dev", "prod"):
        raise ValueError("unknown_environment")
    prefix = f"OPENAI_{environment.upper()}_"
    key, project = values.get(prefix + "API_KEY"), values.get(prefix + "PROJECT_ID")
    if not key or not project or project.startswith("REPLACE_") or not re.fullmatch(r"proj_[A-Za-z0-9_-]+", project):
        raise ValueError("selected_environment_not_configured")
    other = "OPENAI_PROD_" if environment == "dev" else "OPENAI_DEV_"
    if (values.get(other + "API_KEY") == key or values.get(other + "PROJECT_ID") == project):
        raise ValueError("cross_environment_credential_or_project")
    env = dict(os.environ if inherited is None else inherited)
    for name in list(env):
        if name in NAMES or name in {"OPENAI_API_KEY", "OPENAI_PROJECT_ID", "OPENAI_ORG_ID", "OPENAI_ORGANIZATION", "CODEX_API_KEY", "OPENAI_API_KEY_SECRET"}:
            env.pop(name)
    env.update(OPENAI_API_KEY=key, OPENAI_PROJECT_ID=project,
               SERMON_OPENAI_ENVIRONMENT=environment,
               SERMON_OPENAI_CREDENTIAL_ALIAS=f"tongxing-{environment}-runtime")
    return env


def deepseek_environment(path, inherited):
    """Add the optional DeepSeek key from a separate 600-mode local file.

    A missing file is allowed: OpenAI-only runs stay valid. An existing but
    malformed file fails closed so a paid DeepSeek dispatch never starts with a
    partial credential.
    """
    if not path.exists():
        return dict(inherited)
    if path.is_symlink() or not path.is_file():
        raise ValueError("deepseek_credential_file_missing_or_symlink")
    if path.stat().st_mode & 0o077:
        raise ValueError("deepseek_credential_file_requires_mode_600")
    value = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, candidate = line.partition("=")
        name, candidate = name.strip(), candidate.strip()
        if not sep or name != "DEEPSEEK_API_KEY" or value is not None:
            raise ValueError("invalid_deepseek_credential_assignment")
        if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in "\"'":
            candidate = candidate[1:-1]
        if any(c.isspace() for c in candidate) or any(c in candidate for c in "`$#"):
            raise ValueError("invalid_deepseek_credential_value")
        value = candidate
    if not value:
        raise ValueError("deepseek_credential_file_missing_key")
    env = dict(inherited)
    env["DEEPSEEK_API_KEY"] = value
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True, choices=("dev", "prod"))
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env.openai")
    parser.add_argument("--deepseek-env-file", type=Path,
                        default=Path.home() / ".config/tongxing/deepseek.env")
    parser.add_argument("--check", action="store_true", help="Check selected configuration without dispatch.")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        env = deepseek_environment(args.deepseek_env_file,
                                   child_environment(args.env_file, args.environment))
    except (ValueError, OSError, UnicodeError) as exc:
        print(str(exc) if type(exc) is ValueError else "credential_file_unreadable", file=sys.stderr)
        return 2
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if args.check:
        if command:
            parser.error("--check does not accept a command")
        print(f"{args.environment}: local configuration valid; provider access not tested")
        return 0
    if not command:
        parser.error("command required after --")
    return subprocess.run(command, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
