"""Local operational records. No Temporal history contains credentials or media."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def _storage_files():
    """storage/files.py (standard library only): the package module, or this checkout's file by path.

    The isolated Temporal venv installs only temporalio, so it loads the file under a private
    name without making the package importable; the project Python imports the package module."""
    try:
        from tongxing_production.storage import files
        return files
    except ModuleNotFoundError as exc:
        if exc.name != "tongxing_production":
            raise
    name = "sermon_temporal_storage_files"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "packages/production/src/tongxing_production/storage/files.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


atomic_json, utc_now = _storage_files().atomic_json, _storage_files().utc_now
TEMPORAL_ROOT = ROOT / "artifacts" / "temporal"
PROJECT_PYTHON = ROOT / ".venv" / "bin" / "python"


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_identity(pid: int) -> str | None:
    if type(pid) is not int or pid <= 1:
        return None
    result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "lstart=", "-o", "args="],
                            capture_output=True, text=True, timeout=5, check=False)
    if result.returncode or not result.stdout.strip():
        return None
    return hashlib.sha256(result.stdout.strip().encode()).hexdigest()


def receipt_process_alive(record: dict) -> bool:
    return bool(record.get("process_identity") and
                process_identity(record.get("pid")) == record["process_identity"])


def active_execution(state_dir: Path, *, exclude: Path | None = None) -> bool:
    for path in state_dir.glob("execute-*.json"):
        if exclude is not None and path == exclude:
            continue
        record = read_json(path)
        if record.get("status") == "running" and receipt_process_alive(record):
            return True
    return False


def private_directory(path: Path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path
