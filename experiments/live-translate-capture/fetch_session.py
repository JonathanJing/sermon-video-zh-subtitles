#!/usr/bin/env python3
"""Fetch the translated session transcript that the service keeps after a live capture.

The live WebSocket gives us text as it is spoken, but the captions arrive
without provider timestamps.  The public session log (``/api/rooms/<room>/
sessions``) keeps the finalized lines for the whole broadcast with exact
``ts`` values, for the source (English) and every opened language (``zh``).
Reading that log after the service is the timing source of record; the live
capture remains the resilience copy and the only copy of the Mandarin audio.

The fetch is read-only and filters the payload to the capture window.  It
deliberately drops listener telemetry and the raw ingest URL so the saved
artifact contains no listener identifiers or internal endpoints.

Usage
-----
  .venv/bin/python experiments/live-translate-capture/fetch_session.py \
      --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15

  # ad hoc, without a capture manifest
  ... --room mariners-north-irvine --start-at 10:00 --stop-at 11:20
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

SCHEMA = "live-translate-session/v1"
DEFAULT_BASE_URL = "https://translate.pastors.ai"
DEFAULT_TIMEZONE = "America/Los_Angeles"
SUMMARY_KEEP = (
    "sessionId",
    "room",
    "provider",
    "providerModel",
    "startedAt",
    "endedAt",
    "durationMs",
    "complete",
    "peakListeners",
    "languagesOpened",
    "captionLines",
    "captionWords",
    "providerErrors",
    "providerReconnects",
    "providerEventTypes",
    "sessionMinutes",
    "languageOutput",
)


def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def parse_when(value: str, tz: ZoneInfo, *, now: datetime | None = None) -> datetime:
    text = value.strip()
    moment = (now or datetime.now(tz)).astimezone(tz)
    if text.lower() == "now":
        return moment.astimezone(timezone.utc)
    if re.fullmatch(r"\d{1,2}:\d{2}", text):
        hour, minute = (int(part) for part in text.split(":"))
        return datetime.combine(moment.date(), datetime.min.time().replace(hour=hour, minute=minute), tz).astimezone(
            timezone.utc
        )
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(timezone.utc)


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_json(url: str, *, timeout: float = 20.0, attempts: int = 3) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=timeout, headers={"accept": "application/json"})
            response.raise_for_status()
            return response.json()
        except Exception as exc:  # noqa: BLE001 - operator tool: report and retry
            last_error = exc
            if attempt < attempts:
                time.sleep(2.0 * attempt)
    raise RuntimeError(f"GET {url} failed after {attempts} attempts: {last_error}")


def session_span(session: dict[str, Any], now: datetime) -> tuple[datetime, datetime]:
    started = parse_ts(session["startedAt"])
    ended = parse_ts(session["endedAt"]) if session.get("endedAt") else now
    return started, ended


def choose_session(
    sessions: list[dict[str, Any]],
    start: datetime,
    stop: datetime,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    current = now or datetime.now(timezone.utc)
    search_start = start - timedelta(minutes=10)
    search_stop = stop + timedelta(minutes=10)
    best: dict[str, Any] | None = None
    best_overlap = 0.0
    for session in sessions:
        if not session.get("startedAt"):
            continue
        session_start, session_end = session_span(session, current)
        overlap = (min(session_end, search_stop) - max(session_start, search_start)).total_seconds()
        if overlap > best_overlap:
            best = session
            best_overlap = overlap
    return best


def redact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    redacted = {key: summary[key] for key in SUMMARY_KEEP if key in summary}
    if "source" in summary:
        redacted["source"] = "ingest:rtmp (redacted)"
    return redacted


def load_capture(capture_dir: Path) -> dict[str, Any]:
    manifest_path = capture_dir / "capture.json"
    if not manifest_path.exists():
        raise SystemExit(f"no capture manifest at {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    window = manifest.get("window") or {}
    actual_start = window.get("actual_start")
    actual_stop = window.get("actual_stop")
    if not actual_start or not actual_stop:
        raise SystemExit("capture manifest has no actual_start/actual_stop")
    return {
        "room": manifest["room"],
        "start": parse_ts(actual_start),
        "stop": parse_ts(actual_stop),
        "base_url": (manifest.get("source") or {}).get("base_ws", "").replace("wss://", "https://").replace(
            "ws://", "http://"
        )
        or DEFAULT_BASE_URL,
        "manifest": manifest,
    }


def filter_lines(
    lines: list[dict[str, Any]],
    start: datetime,
    stop: datetime,
    *,
    pre_roll_s: int,
    post_roll_s: int,
) -> list[dict[str, str]]:
    lower = start - timedelta(seconds=pre_roll_s)
    upper = stop + timedelta(seconds=post_roll_s)
    selected: list[dict[str, str]] = []
    for line in lines:
        timestamp = line.get("ts")
        text = str(line.get("text") or "").strip()
        if not timestamp or not text:
            continue
        moment = parse_ts(timestamp)
        if lower <= moment <= upper:
            selected.append({"ts": iso_utc(moment), "text": text})
    return selected


def write_lines(path: Path, lines: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def write_text(path: Path, lines: list[dict[str, str]]) -> None:
    path.write_text("\n".join(line["text"] for line in lines) + ("\n" if lines else ""), encoding="utf-8")


def compare_with_live(capture_dir: Path, session_lines: list[dict[str, str]]) -> dict[str, Any]:
    live_path = capture_dir / "english.finals.jsonl"
    if not live_path.exists():
        return {"live_english_finals": 0, "exact_normalised_matches": 0}
    live: list[str] = []
    with live_path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                live.append(normalise(json.loads(line).get("text", "")))
            except json.JSONDecodeError:
                continue
    session = {normalise(line["text"]) for line in session_lines}
    matches = sum(1 for text in live if text and text in session)
    return {
        "live_english_finals": len(live),
        "session_source_lines": len(session_lines),
        "exact_normalised_matches": matches,
        "match_fraction": round(matches / len(live), 3) if live else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch the translated session log for a capture window.")
    parser.add_argument("--capture-dir", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--room", default=None)
    parser.add_argument("--start-at", default=None, help="only with --room; HH:MM or ISO-8601")
    parser.add_argument("--stop-at", default=None, help="only with --room; HH:MM or ISO-8601")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--pre-roll-s", type=int, default=120)
    parser.add_argument("--post-roll-s", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args(argv)

    capture_dir = args.capture_dir
    if capture_dir is not None:
        info = load_capture(capture_dir)
        room = info["room"]
        start = info["start"]
        stop = info["stop"]
        base_url = args.base_url or info["base_url"]
    else:
        if not args.room or not args.start_at or not args.stop_at:
            raise SystemExit("pass --capture-dir, or --room with --start-at and --stop-at")
        tz = ZoneInfo(args.timezone)
        room = args.room
        start = parse_when(args.start_at, tz)
        stop = parse_when(args.stop_at, tz)
        base_url = args.base_url or DEFAULT_BASE_URL
    out_dir = args.out if args.out is not None else capture_dir
    if out_dir is None:
        raise SystemExit("pass --out or --capture-dir")
    out_dir.mkdir(parents=True, exist_ok=True)
    base_url = base_url.rstrip("/")

    sessions_url = f"{base_url}/api/rooms/{quote(room, safe='')}/sessions"
    sessions = get_json(sessions_url, timeout=args.timeout)
    if isinstance(sessions, dict):
        sessions = sessions.get("sessions", [])
    if not isinstance(sessions, list):
        raise SystemExit(f"unexpected sessions payload from {sessions_url}")
    chosen = choose_session(sessions, start, stop)
    if chosen is None:
        raise SystemExit(f"no session overlaps {iso_utc(start)} .. {iso_utc(stop)} in room {room}")

    session_id = chosen.get("sessionId")
    detail_url = f"{sessions_url}/{quote(str(session_id), safe='')}"
    detail = get_json(detail_url, timeout=args.timeout)
    summary = detail.get("summary") or {}
    captions = detail.get("captions") or {}
    source_lines = filter_lines(
        captions.get("source") or [],
        start,
        stop,
        pre_roll_s=args.pre_roll_s,
        post_roll_s=args.post_roll_s,
    )
    mandarin_lines = filter_lines(
        captions.get("zh") or [],
        start,
        stop,
        pre_roll_s=args.pre_roll_s,
        post_roll_s=args.post_roll_s,
    )

    english_jsonl = out_dir / "session.english.jsonl"
    mandarin_jsonl = out_dir / "session.mandarin.jsonl"
    english_txt = out_dir / "session.english.txt"
    mandarin_txt = out_dir / "session.mandarin.txt"
    write_lines(english_jsonl, source_lines)
    write_lines(mandarin_jsonl, mandarin_lines)
    write_text(english_txt, source_lines)
    write_text(mandarin_txt, mandarin_lines)

    comparison = (
        compare_with_live(capture_dir, source_lines) if capture_dir is not None else None
    )
    payload = {
        "schema": SCHEMA,
        "fetched_at": iso_utc(datetime.now(timezone.utc)),
        "room": room,
        "window": {
            "capture_start": iso_utc(start),
            "capture_stop": iso_utc(stop),
            "pre_roll_s": args.pre_roll_s,
            "post_roll_s": args.post_roll_s,
        },
        "session": redact_summary(summary),
        "session_id": session_id,
        "sources": {"sessions": sessions_url, "detail": detail_url},
        "captions": {
            "english": {
                "lines": len(source_lines),
                "first_ts": source_lines[0]["ts"] if source_lines else None,
                "last_ts": source_lines[-1]["ts"] if source_lines else None,
                "file": str(english_jsonl),
                "text_file": str(english_txt),
                "sha256": sha256_file(english_jsonl),
            },
            "mandarin": {
                "lines": len(mandarin_lines),
                "first_ts": mandarin_lines[0]["ts"] if mandarin_lines else None,
                "last_ts": mandarin_lines[-1]["ts"] if mandarin_lines else None,
                "file": str(mandarin_jsonl),
                "text_file": str(mandarin_txt),
                "sha256": sha256_file(mandarin_jsonl),
            },
        },
        "comparison_with_live": comparison,
        "redactions": [
            "summary.listenerTelemetry",
            "summary.listenerSocket",
            "timeline",
            "summary.source (ingest URL)",
        ],
        "note": (
            "Provider session log: finalized caption lines with provider timestamps. "
            "Prefer these timestamps for alignment; the live capture remains the copy of "
            "what our listener actually received and the only copy of the Mandarin audio."
        ),
    }
    write_json(out_dir / "session.json", payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
