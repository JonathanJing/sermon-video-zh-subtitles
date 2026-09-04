#!/usr/bin/env python3
"""Sample local gateway readiness and explicit process RSS into the soak TSV.

Example: --gateway-pid <gateway> --mlx-pid <ASR> --ollama-pid <model-runner>
Use verified model process PIDs, not the Ollama desktop app's PID. A missing PID
argument or failed measurement is blank; an observed exited process has RSS 0.
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import math
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import urlopen


FIELDS = (
    "timestamp", "elapsed_s", "http_code", "status", "asr_available", "live_available",
    "gateway_pid", "gateway_rss_kb", "mlx_pid", "mlx_rss_kb", "ollama_pid",
    "ollama_rss_kb", "swap_used_mb", "memory_free_percent", "health_error",
)


def parse_swap_used_mb(output: str) -> float | None:
    match = re.search(r"\bused\s*=\s*([0-9.]+)\s*([KMGT])", output)
    if not match:
        return None
    return float(match.group(1)) * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024**2}[match.group(2)]


def parse_memory_free_percent(output: str) -> int | None:
    match = re.search(r"System-wide memory free percentage:\s*(\d+)%", output)
    return int(match.group(1)) if match else None


def health_fields(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"health_error": "invalid_health_object"}

    def available(key: str) -> bool | None:
        section = payload.get(key)
        value = section.get("available") if isinstance(section, dict) else None
        return value if isinstance(value, bool) else None

    return {
        "status": payload.get("status") if payload.get("status") in ("ready", "degraded") else None,
        "asr_available": available("asr"), "live_available": available("liveStream"),
    }


def read_health(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=3) as response:
            return {"http_code": response.status, **health_fields(json.load(response))}
    except HTTPError as error:
        return {"http_code": error.code, "health_error": "http_error"}
    except (URLError, OSError, ValueError) as error:
        # Do not persist response bodies, URLs with credentials or exception text.
        return {"health_error": type(error).__name__}


def command_output(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=3)
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def process_rss_kb(pid: int | None) -> int | None:
    if pid is None:
        return None
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "rss="], capture_output=True, text=True,
            check=False, timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode == 1 and not result.stdout.strip():
        return 0
    return int(result.stdout.strip()) if result.returncode == 0 and result.stdout.strip().isdigit() else None


def sample(url: str, elapsed: float, pids: dict[str, int | None]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(), "elapsed_s": round(elapsed, 3),
        **read_health(url),
        "swap_used_mb": parse_swap_used_mb(command_output(["sysctl", "-n", "vm.swapusage"]) or ""),
        "memory_free_percent": parse_memory_free_percent(command_output(["memory_pressure", "-Q"]) or ""),
    }
    for label, pid in pids.items():
        row[f"{label}_pid"] = pid
        row[f"{label}_rss_kb"] = process_rss_kb(pid)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--health-url", default="http://127.0.0.1:8766/api/health")
    parser.add_argument("--duration-seconds", type=float, required=True)
    parser.add_argument("--interval-seconds", type=float, default=10)
    parser.add_argument("--gateway-pid", type=int)
    parser.add_argument("--mlx-pid", type=int)
    parser.add_argument("--ollama-pid", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = urlparse(args.health_url)
    try:
        local = url.hostname == "localhost" or ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        local = False
    if not local or url.scheme not in {"http", "https"} or url.username or url.password or url.query or url.fragment:
        parser.error("health URL must be a local loopback URL without credentials or query parameters")
    pids = {"gateway": args.gateway_pid, "mlx": args.mlx_pid, "ollama": args.ollama_pid}
    if not all(math.isfinite(value) and value > 0 for value in (args.duration_seconds, args.interval_seconds)) or any(pid is not None and pid < 1 for pid in pids.values()):
        parser.error("duration, interval and supplied PIDs must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # Exclusive creation prevents accidental overwrite or mixing distinct runs.
    with args.output.open("x", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS, delimiter="\t")
        writer.writeheader()
        try:
            while (elapsed := time.monotonic() - started) <= args.duration_seconds:
                row = sample(args.health_url, elapsed, pids)
                writer.writerow({key: str(value).lower() if isinstance(value, bool) else value for key, value in row.items()})
                output.flush()
                remaining = args.duration_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    break
                time.sleep(min(args.interval_seconds, remaining))
        except KeyboardInterrupt:
            pass
    print(args.output)


if __name__ == "__main__":
    main()
