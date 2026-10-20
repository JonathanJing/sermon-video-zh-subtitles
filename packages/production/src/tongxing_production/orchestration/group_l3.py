"""Run the Layer 3 stages of a group merge as an ordered, resumable command plan.

Merge steps 7-9 (formal render, compaction/screening, audio package, audio QC) are
executed today by existing producers with operator-frozen commands. This module runs
those commands in order, records one receipt per stage, and refuses to continue when a
stage fails or its command still carries an unresolved placeholder. It never composes
a model prompt, edits a receipt or treats an exit code as content approval.

A stage is skipped only when its ``produces`` file already exists: that is resume, not
reuse authority. The stage command is bound by SHA-256 in the report; the report is run
evidence, never release material.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

CONFIG_SCHEMA = "sermon-group-l3-stages-v1"
REPORT_SCHEMA = "sermon-group-l3-stages-report-v1"
# Files the runner requires before any stage; additional string variables (locale, code,
# stage directory, extra receipts) may be declared and interpolated too.
REQUIRED_PATHS = ("speechJob", "source", "anchor", "candidate", "policy", "adapter", "registry")
STAGE_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
REQUIRED_STAGES = ("formal_render", "compact", "screen", "package", "audio_qc")


class StageRefused(ValueError):
    def __init__(self, stage: str, reason: str, group_ids: list[str] | None = None):
        self.stage, self.reason = stage, reason
        self.group_ids = sorted(set(group_ids or ()))
        super().__init__(f"{stage}:{reason}" + (f":{','.join(self.group_ids)}" if self.group_ids else ""))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def load_configuration(path: Path) -> dict:
    path = Path(path).resolve()
    config = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(config, dict) and config.get("schemaVersion") == CONFIG_SCHEMA,
             "invalid_group_l3_stages_config")
    _require(set(config) <= {"schemaVersion", "paths", "variables", "stages", "note"}
             and {"schemaVersion", "paths", "stages"} <= set(config), "unknown_group_l3_stages_field")
    _require("note" not in config or (isinstance(config["note"], str) and config["note"].strip()),
             "invalid_group_l3_note")
    variables = config.get("variables") or {}
    _require(isinstance(variables, dict)
             and all(isinstance(value, str) and value for value in variables.values()),
             "invalid_group_l3_variable")
    _require(isinstance(config["paths"], dict) and set(REQUIRED_PATHS) <= set(config["paths"]),
             "invalid_group_l3_paths")
    _require(all(isinstance(value, str) and value for value in config["paths"].values()),
             "invalid_group_l3_path_value")
    paths = {key: (path.parent / value if not Path(value).is_absolute() else Path(value))
             for key, value in config["paths"].items()}
    stages = config["stages"]
    _require(isinstance(stages, list) and stages, "group_l3_needs_stages")
    seen = set()
    for stage in stages:
        _require(isinstance(stage, dict)
                 and {"name", "command", "produces"} <= set(stage)
                 <= {"name", "command", "produces", "failures", "note"}
                 and isinstance(stage["name"], str) and STAGE_NAME.fullmatch(stage["name"])
                 and stage["name"] not in seen
                 and isinstance(stage["command"], list) and stage["command"]
                 and all(isinstance(part, str) and part for part in stage["command"])
                 and isinstance(stage["produces"], str) and stage["produces"]
                 and not Path(stage["produces"]).is_absolute()
                 and ".." not in Path(stage["produces"]).parts
                 and (stage.get("failures") is None
                      or (isinstance(stage["failures"], str) and stage["failures"]
                          and not Path(stage["failures"]).is_absolute()
                          and ".." not in Path(stage["failures"]).parts)),
                 "invalid_group_l3_stage")
        seen.add(stage["name"])
    return {"path": path, "paths": paths, "variables": variables, "stages": stages}


def _substitute(value: str, paths: dict) -> str:
    def replace(match: re.Match) -> str:
        name = match.group(1)
        _require(name in paths or name == "out", f"unknown_placeholder:{name}")
        return str(paths[name])
    return re.sub(r"\{([A-Za-z][A-Za-z0-9_]*)\}", replace, value)


def run_stages(config: dict, out: Path, *, dry_run: bool = False) -> dict:
    """Execute the configured stages in order; stop at the first failure."""
    out = Path(out)
    paths = {**config.get("variables", {}), **config["paths"], "out": out}
    for name in REQUIRED_PATHS:
        _require(Path(paths[name]).is_file(), f"missing_group_l3_input:{name}")
    _require(out.is_dir() or dry_run, "group_l3_output_must_exist")
    report = {"schemaVersion": REPORT_SCHEMA, "mode": "dry_run" if dry_run else "execute",
              "startedAt": _now(), "stages": [], "releaseEligible": False, "humanApproval": False}
    for stage in config["stages"]:
        name = stage["name"]
        produces = out / _substitute(stage["produces"], paths)
        if produces.exists():
            report["stages"].append({"name": name, "status": "skipped_existing",
                                     "produces": str(produces)})
            continue
        command = [_substitute(part, paths) for part in stage["command"]]
        _require(not any(re.search(r"\{[A-Za-z][A-Za-z0-9_]*\}", part) for part in command),
                 f"unresolved_placeholder:{name}")
        entry = {"name": name, "commandSha256": _command_sha256(command), "command": command,
                 "startedAt": _now()}
        if dry_run:
            entry["status"] = "planned"
            report["stages"].append(entry)
            continue
        started = time.monotonic()
        workdir = Path(config.get("variables", {}).get("repoRoot") or config["path"].parent)
        completed = subprocess.run(command, cwd=str(workdir), text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        entry.update(endedAt=_now(), seconds=round(time.monotonic() - started, 3),
                     exitCode=completed.returncode,
                     stdoutTail=_tail(completed.stdout), stderrTail=_tail(completed.stderr))
        if completed.returncode != 0:
            group_ids = _failed_groups(out, stage, paths)
            entry.update(status="failed", failedGroupIds=group_ids)
            report["stages"].append(entry)
            report["status"] = "failed"
            report["nextActions"] = [{"action": "redo", "groupIds": group_ids,
                                      "reason": f"{name} failed"}] if group_ids else []
            _write_report(out, report)
            raise StageRefused(name, f"exit {completed.returncode}", group_ids)
        if not produces.exists():
            # A zero exit that produced nothing is not a completed stage.
            entry["status"] = "failed"
            entry["reason"] = "produces_missing_after_success"
            report["stages"].append(entry)
            report["status"] = "failed"
            _write_report(out, report)
            raise StageRefused(name, "produces_missing_after_success")
        entry["status"] = "done"
        report["stages"].append(entry)
    report["status"] = "planned" if dry_run else "completed"
    _write_report(out, report)
    merge_dir = config["paths"].get("mergeDir")
    if merge_dir and Path(merge_dir).is_dir():
        # A latest-status pointer beside the candidate; the full evidence stays in out.
        _write_latest(Path(merge_dir) / "l3-stages.json", report)
    return report


def _failed_groups(out: Path, stage: dict, paths: dict) -> list[str]:
    """Group IDs a failed producer named in its own summary, if the stage declares one."""
    name = stage.get("failures")
    if not name:
        return []
    path = Path(out) / _substitute(name, paths)
    if not path.is_file():
        return []
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    found: list[str] = []
    for key in ("failedGroups", "failedGroupIds", "groupIds", "shortenGroupIds"):
        value = document.get(key) if isinstance(document, dict) else None
        if isinstance(value, list) and all(isinstance(item, str) and item for item in value):
            found.extend(value)
    return sorted(set(found))


def _command_sha256(command: list[str]) -> str:
    return hashlib.sha256(json.dumps(command, ensure_ascii=False).encode("utf-8")).hexdigest()


def _tail(value: str, limit: int = 2000) -> str:
    value = value or ""
    return value[-limit:]


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_latest(path: Path, report: dict) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_report(out: Path, report: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    path = out / "stage-report.json"
    temporary = out / f".stage-report.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    config = load_configuration(args.config)
    try:
        report = run_stages(config, args.out, dry_run=args.dry_run)
    except StageRefused as exc:
        print(json.dumps({"status": "failed", "stage": exc.stage, "reason": exc.reason,
                          "groupIds": exc.group_ids}))
        return 5
    print(json.dumps({"status": report["status"], "stages": len(report["stages"])}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
