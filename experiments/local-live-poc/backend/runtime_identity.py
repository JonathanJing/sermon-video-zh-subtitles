"""Capture a small, secret-free identity for a local caption runtime.

Call once when the gateway is constructed, then persist that same identity in
each session. This module never reads environment variables, remote URLs or
model credentials. Unknown configuration keys are deliberately discarded.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import ipaddress
import json
import math
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse


CONFIGURATION_KEYS = frozenset({
    "asrProvider", "asrModelSha256", "asrFinalizationMode", "asrSilenceFrameCount",
    "vadThresholdRms", "vadSilenceMs", "vadMaxSegmentMs", "asrQueueLimit",
    "translationQueueLimit", "translationModel", "translationModelDigest",
    "translationPromptVersion", "translationPromptSha256", "translationStreaming",
    "translationTemperature", "translationTopK", "translationContextSize",
    "contextPolicy", "contentPackVersion", "contentPackSha256",
    "captionPresentationPolicy", "sampleRateHz", "frameDurationMs",
    "sourceAudioSha256", "sourceStartMs", "sourceEndMs",
    "translationUnitPolicy", "translationUnitMaxWaitMs", "translationUnitMaxSegments",
    "translationUnitMaxAudioDurationMs", "translationUnitMaxAudioGapMs",
    "sourceFragmentPolicy", "frontendOrigin", "frontendOrigins",
    "translationPromptFamily", "translationPromptHashScope",
})
VERSION_KEYS = frozenset({"ollama", "mlx_audio", "mlx", "whisper_cpp", "node"})


def validate_frontend_origin(value: str) -> str:
    """Accept an explicit HTTP loopback origin, never a remote/browser URL."""
    parsed = urlparse(value)
    try:
        port = parsed.port
        host = parsed.hostname or ""
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
        port = None
    if (
        parsed.scheme != "http" or not loopback or parsed.username is not None
        or parsed.password is not None or parsed.path not in {"", "/"}
        or parsed.query or parsed.fragment or port == 0
    ):
        raise ValueError("frontend origin must be an HTTP loopback origin without credentials, path, query, or fragment")
    hostname = f"[{host}]" if ":" in host else host
    return f"http://{hostname}" + (f":{port}" if port is not None else "")


def _scalar(value: Any) -> bool:
    return (
        value is None or isinstance(value, (str, bool, int))
        or isinstance(value, float) and math.isfinite(value)
    )


def _git_identity(repo_path: Path) -> dict[str, Any]:
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(repo_path), *args], capture_output=True, text=True,
            check=False, timeout=3,
        )

    try:
        revision = git("rev-parse", "HEAD")
        status = git("status", "--porcelain", "--untracked-files=normal")
        if revision.returncode or status.returncode:
            return {"revision": None, "dirty": None, "available": False}
        return {
            "revision": revision.stdout.strip(), "dirty": bool(status.stdout.strip()),
            "available": True,
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"revision": None, "dirty": None, "available": False}


def collect_runtime_identity(
    configuration: Mapping[str, Any],
    *,
    repo_path: Path | None = None,
    versions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return JSON-serializable identity; unavailable facts remain null.

    Pass resolved runtime settings, not an environment or complete health object.
    ``versions`` can supply verified provider versions from their own process;
    installed packages here describe only this Python interpreter. The stable
    SHA-256 excludes capture time and is not proof of a clean build when dirty.
    """
    packages: dict[str, str | None] = {}
    for name in ("mlx-audio", "mlx", "websockets"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    payload = {
        "schemaVersion": "local-live-runtime-identity-v1",
        "git": _git_identity(repo_path or Path(__file__).resolve().parent),
        "configuration": {
            key: value for key, value in configuration.items()
            if key in CONFIGURATION_KEYS and _scalar(value)
        },
        "runtime": {
            "python": platform.python_version(), "system": platform.system(),
            "release": platform.release(), "machine": platform.machine(),
            "gatewayPythonPackages": packages,
            "providerVersions": {
                key: value for key, value in (versions or {}).items()
                if key in VERSION_KEYS and _scalar(value)
            },
        },
    }
    fingerprint = hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()
    return {
        **payload, "fingerprintSha256": fingerprint,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
    }
