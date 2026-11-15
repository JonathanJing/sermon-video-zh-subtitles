#!/usr/bin/env python3
"""Record a human-supplied sermon window for a full-service capture.

The capture deliberately keeps the whole service window (10:00–11:20): it
does not guess where the sermon starts or ends.  After a human has reviewed
the service, this tool writes ``sermon.window.json`` next to ``capture.json``:

  start/end       local wall-clock time (HH:MM[:SS]) or ISO-8601
  start-offset    seconds from the capture's actual start, instead of a clock time
  end-offset      seconds from the capture's actual start

The file binds the window to the SHA-256 of ``capture.json`` (and to
``session.json`` when present).  It is capture metadata, not a Layer 1
``approvedWindow``: the downstream Layer 1 package still needs its own
approval and evidence.

Usage
-----
  .venv/bin/python experiments/live-translate-capture/mark_window.py \\
      --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 \\
      --start 10:29:35 --end 11:02:10 \\
      --approved-by "Jony (chat)" \\
      --evidence "reviewed the full service recording; sermon starts after the announcement"

  # verify a previously recorded window
  ... --capture-dir ... --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SCHEMA = "live-translate-sermon-window/v1"
DEFAULT_TIMEZONE = "America/Los_Angeles"
BOUNDARY_TOLERANCE_S = 5.0
MIN_DURATION_S = 60.0


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_clock(value: str, tz: ZoneInfo, anchor_date) -> datetime:
    text = value.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text):
        parts = [int(part) for part in text.split(":")]
        hour, minute = parts[0], parts[1]
        second = parts[2] if len(parts) == 3 else 0
        return datetime.combine(anchor_date, dtime(hour, minute, second), tz).astimezone(timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def parse_offset(value: str) -> float:
    text = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    parts = text.split(":")
    if not 2 <= len(parts) <= 3 or not all(re.fullmatch(r"\d+(?:\.\d+)?", part) for part in parts):
        raise ValueError(f"offset must be seconds, MM:SS or HH:MM:SS: {value!r}")
    numbers = [float(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def load_capture(capture_dir: Path) -> dict[str, Any]:
    manifest_path = capture_dir / "capture.json"
    manifest = read_json(manifest_path, "capture manifest")
    window = manifest.get("window") or {}
    if not window.get("actual_start") or not window.get("actual_stop"):
        raise ValueError("capture manifest has no actual_start/actual_stop")
    return manifest


def resolve_window(
    capture_dir: Path,
    *,
    start: str | None,
    end: str | None,
    start_offset: str | None,
    end_offset: str | None,
    timezone_name: str | None,
) -> dict[str, Any]:
    capture_dir = capture_dir.resolve()
    manifest = load_capture(capture_dir)
    actual_start = parse_ts(manifest["window"]["actual_start"])
    actual_stop = parse_ts(manifest["window"]["actual_stop"])
    timezone_name = timezone_name or (manifest.get("host") or {}).get("timezone") or DEFAULT_TIMEZONE
    tz = ZoneInfo(timezone_name)
    anchor_date = actual_start.astimezone(tz).date()

    if start and start_offset:
        raise ValueError("pass --start or --start-offset, not both")
    if end and end_offset:
        raise ValueError("pass --end or --end-offset, not both")
    if not (start or start_offset) or not (end or end_offset):
        raise ValueError("both the sermon start and end are required")

    start_utc = (
        parse_clock(start, tz, anchor_date)
        if start
        else actual_start + timedelta(seconds=parse_offset(start_offset or "0"))
    )
    end_utc = (
        parse_clock(end, tz, anchor_date)
        if end
        else actual_start + timedelta(seconds=parse_offset(end_offset or "0"))
    )

    tolerance = timedelta(seconds=BOUNDARY_TOLERANCE_S)
    if start_utc < actual_start - tolerance:
        raise ValueError(f"sermon start {iso_utc(start_utc)} is before capture start {iso_utc(actual_start)}")
    if end_utc > actual_stop + tolerance:
        raise ValueError(f"sermon end {iso_utc(end_utc)} is after capture stop {iso_utc(actual_stop)}")
    if end_utc <= start_utc:
        raise ValueError("sermon end must be after sermon start")
    if (end_utc - start_utc).total_seconds() < MIN_DURATION_S:
        raise ValueError(f"sermon window is shorter than {MIN_DURATION_S:.0f}s")

    session_path = capture_dir / "session.json"
    session_payload = read_json(session_path, "session manifest") if session_path.exists() else None
    return {
        "capture_dir": capture_dir,
        "manifest": manifest,
        "actual_start": actual_start,
        "actual_stop": actual_stop,
        "start": start_utc,
        "end": end_utc,
        "timezone": timezone_name,
        "session": session_payload,
        "session_sha256": sha256_file(session_path) if session_path.exists() else None,
    }


def record_window(
    capture_dir: Path,
    *,
    start: str | None = None,
    end: str | None = None,
    start_offset: str | None = None,
    end_offset: str | None = None,
    approved_by: str,
    evidence: str,
    timezone_name: str | None = None,
    out: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if not approved_by.strip():
        raise ValueError("--approved-by is required")
    if not evidence.strip():
        raise ValueError("--evidence is required")
    resolved = resolve_window(
        capture_dir,
        start=start,
        end=end,
        start_offset=start_offset,
        end_offset=end_offset,
        timezone_name=timezone_name,
    )
    capture_dir = resolved["capture_dir"]
    out_path = (out or capture_dir / "sermon.window.json").resolve()
    start_utc = resolved["start"]
    end_utc = resolved["end"]
    actual_start = resolved["actual_start"]
    session = resolved["session"] or {}
    payload = {
        "schema": SCHEMA,
        "status": "human_supplied",
        "recorded_at": iso_utc(now_utc()),
        "capture": {
            "dir": str(capture_dir),
            "manifest_sha256": sha256_file(capture_dir / "capture.json"),
            "actual_start": iso_utc(actual_start),
            "actual_stop": iso_utc(resolved["actual_stop"]),
            "timezone": resolved["timezone"],
        },
        "session": (
            {"id": session.get("session_id"), "sha256": resolved["session_sha256"]}
            if session
            else None
        ),
        "sermon_window": {
            "start": iso_utc(start_utc),
            "end": iso_utc(end_utc),
            "start_offset_s": round((start_utc - actual_start).total_seconds(), 3),
            "end_offset_s": round((end_utc - actual_start).total_seconds(), 3),
            "duration_s": round((end_utc - start_utc).total_seconds(), 3),
        },
        "approved_by": approved_by.strip(),
        "evidence": evidence.strip(),
        "note": (
            "Human-supplied sermon window for a full-service capture. "
            "This is capture metadata, not a Layer 1 approvedWindow; downstream "
            "Layer 1 still needs its own source-bound approval."
        ),
    }

    if out_path.exists() and not force:
        existing = read_json(out_path, "sermon window")
        same = (
            existing.get("sermon_window", {}).get("start") == payload["sermon_window"]["start"]
            and existing.get("sermon_window", {}).get("end") == payload["sermon_window"]["end"]
            and existing.get("approved_by") == payload["approved_by"]
            and existing.get("evidence") == payload["evidence"]
        )
        if same:
            return existing
        raise ValueError(f"{out_path} already exists with a different window; pass --force to replace it")
    write_json(out_path, payload)
    return payload


def check_window(capture_dir: Path, *, out: Path | None = None) -> dict[str, Any]:
    capture_dir = capture_dir.resolve()
    out_path = (out or capture_dir / "sermon.window.json").resolve()
    payload = read_json(out_path, "sermon window")
    if payload.get("schema") != SCHEMA:
        raise ValueError(f"unexpected schema in {out_path}: {payload.get('schema')}")
    manifest = load_capture(capture_dir)
    actual_start = parse_ts(manifest["window"]["actual_start"])
    actual_stop = parse_ts(manifest["window"]["actual_stop"])
    current_hash = sha256_file(capture_dir / "capture.json")
    bound_hash = (payload.get("capture") or {}).get("manifest_sha256")
    if current_hash != bound_hash:
        raise ValueError("capture.json changed since the sermon window was recorded")
    window = payload.get("sermon_window") or {}
    start = parse_ts(window["start"])
    end = parse_ts(window["end"])
    if start < actual_start or end > actual_stop or end <= start:
        raise ValueError("recorded sermon window is outside the capture window")
    return {
        "ok": True,
        "file": str(out_path),
        "capture_manifest_sha256": current_hash,
        "sermon_window": window,
        "approved_by": payload.get("approved_by"),
        "evidence": payload.get("evidence"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record or verify a human-supplied sermon window for a full-service capture."
    )
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--start", help="HH:MM[:SS] local, or ISO-8601")
    parser.add_argument("--end", help="HH:MM[:SS] local, or ISO-8601")
    parser.add_argument("--start-offset", help="seconds from capture start, or MM:SS / HH:MM:SS")
    parser.add_argument("--end-offset", help="seconds from capture start, or MM:SS / HH:MM:SS")
    parser.add_argument("--approved-by", default="", help="who supplied the window")
    parser.add_argument("--evidence", default="", help="what was reviewed (quote or note)")
    parser.add_argument("--timezone", default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="replace a different existing window")
    parser.add_argument("--check", action="store_true", help="verify an existing window")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.check:
            result = check_window(args.capture_dir, out=args.out)
        else:
            result = record_window(
                args.capture_dir,
                start=args.start,
                end=args.end,
                start_offset=args.start_offset,
                end_offset=args.end_offset,
                approved_by=args.approved_by,
                evidence=args.evidence,
                timezone_name=args.timezone,
                out=args.out,
                force=args.force,
            )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
