#!/usr/bin/env python3
"""Observe the public Resi event UUID on a sparse weekend schedule.

This collector reads the Mariners page and Resi's latest-event metadata only.
It never requests a media manifest or segment.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import html.parser
import json
import os
import pathlib
import plistlib
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from zoneinfo import ZoneInfo


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ROOT / "artifacts" / "resi-uuid-inventory"
PAGE_URL = "https://www.marinerschurch.org/weekendlive/"
LATEST_URL = "https://webevents.resi.io/api/v1/eventprofiles/latest/"
TIMEZONE = ZoneInfo("America/Los_Angeles")
AGENT_LABEL = "org.sermonvideo.resi-uuid-inventory"
USER_AGENT = "sermon-video-zh-subtitles-resi-uuid-inventory/1.0"
TIMEOUT_SECONDS = 20

SATURDAY_SLOTS = ((16, 0, "sat-1600"), (17, 30, "sat-1730"))
SUNDAY_SLOTS = (
    (7, 0, "sun-0700"),
    (8, 30, "sun-0830"),
    (10, 0, "sun-1000"),
    (11, 30, "sun-1130"),
)


class EmbedIdParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.embed_id: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id") == "resi-video-player":
            self.embed_id = values.get("data-embed-id")


def local_window(now: dt.datetime) -> tuple[str, str] | None:
    """Return weekend date and observation window, not a claimed event identity."""
    local = now.astimezone(TIMEZONE)
    minute = local.hour * 60 + local.minute
    if local.weekday() == 5 and 15 * 60 + 45 <= minute < 19 * 60:
        slots = SATURDAY_SLOTS
        weekend = local.date()
    elif local.weekday() == 6 and 6 * 60 + 45 <= minute < 13 * 60:
        slots = SUNDAY_SLOTS
        weekend = local.date() - dt.timedelta(days=1)
    else:
        return None
    window = "pre-service"
    for hour, slot_minute, label in slots:
        if minute >= hour * 60 + slot_minute:
            window = label
    return weekend.isoformat(), window


def fetch_text(url: str, max_bytes: int) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html, application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise ValueError("response_too_large")
    return body.decode("utf-8")


def fetch_embed_id() -> str:
    parser = EmbedIdParser()
    parser.feed(fetch_text(PAGE_URL, 5_000_000))
    if not parser.embed_id:
        raise ValueError("embed_id_missing")
    return str(uuid.UUID(parser.embed_id))


def fetch_event(embed_id: str) -> tuple[str, str]:
    data = json.loads(fetch_text(LATEST_URL + embed_id, 100_000))
    if not isinstance(data, dict):
        raise ValueError("event_response_invalid")
    event_id = str(uuid.UUID(data["uuid"]))
    name = data.get("name")
    return event_id, name[:200] if isinstance(name, str) else ""


def atomic_json(path: pathlib.Path, value: dict[str, str]) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
        json.dump(value, file, ensure_ascii=False, sort_keys=True)
        file.write("\n")
        temporary = pathlib.Path(file.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def error_code(error: Exception) -> str:
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    if isinstance(error, urllib.error.URLError):
        return "network_error"
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(error, (KeyError, TypeError, AttributeError)):
        return "event_response_invalid"
    if isinstance(error, ValueError):
        return str(error) if str(error) in {
            "response_too_large", "embed_id_missing", "event_response_invalid"
        } else "invalid_uuid"
    return "unexpected_error"


def collect_once(data_dir: pathlib.Path, now: dt.datetime, *, force: bool = False) -> dict[str, str]:
    window = local_window(now)
    if window is None and not force:
        return {"status": "outside_window"}
    local = now.astimezone(TIMEZONE)
    weekend, label = window or ("manual", "manual")
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state_path = data_dir / "state.json"
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            state = {}
        record = {
            "schemaVersion": "resi-event-uuid-observation-v1",
            "observedAtUtc": now.astimezone(dt.timezone.utc).isoformat(),
            "observedAtLocal": local.isoformat(),
            "weekendDate": weekend,
            "scheduledWindow": label,
            "status": "observed",
        }
        try:
            # Refresh the page once per local day; its embed ID is a channel ID,
            # while the API response UUID identifies the current event.
            if state.get("checkedLocalDate") != local.date().isoformat():
                embed_id = fetch_embed_id()
                atomic_json(state_path, {
                    "checkedLocalDate": local.date().isoformat(),
                    "embedId": embed_id,
                })
            else:
                embed_id = str(uuid.UUID(state["embedId"]))
            event_id, name = fetch_event(embed_id)
            record.update({"embedId": embed_id, "uuid": event_id, "name": name})
        except Exception as error:
            record.update({"status": "error", "errorCode": error_code(error)})
        with (data_dir / "observations.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            file.flush()
            os.fsync(file.fileno())
        return record


def summarize(data_dir: pathlib.Path, weekend: str | None) -> dict[str, object]:
    path = data_dir / "observations.jsonl"
    if not path.exists():
        return {"status": "no_observations", "dataPath": str(path)}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if weekend is None:
        dates = sorted({row["weekendDate"] for row in rows if row["weekendDate"] != "manual"})
        weekend = dates[-1] if dates else "manual"
    selected = [row for row in rows if row["weekendDate"] == weekend]
    windows: dict[str, dict[str, object]] = {}
    for row in selected:
        label = row["scheduledWindow"]
        group = windows.setdefault(label, {"polls": 0, "uuids": [], "errors": 0})
        group["polls"] += 1
        if row["status"] == "observed":
            if row["uuid"] not in group["uuids"]:
                group["uuids"].append(row["uuid"])
        else:
            group["errors"] += 1
    return {"weekendDate": weekend, "observations": len(selected), "windows": windows}


def launchd_calendar() -> list[dict[str, int]]:
    # launchd Weekday: Sunday=0, Saturday=6. Local system TZ must be Los Angeles.
    result = [{"Weekday": 6, "Hour": 15, "Minute": 50}]
    result += [{"Weekday": 6, "Hour": hour, "Minute": minute}
               for hour in range(16, 19) for minute in (10, 30, 50)]
    result += [{"Weekday": 0, "Hour": 6, "Minute": 50}]
    result += [{"Weekday": 0, "Hour": hour, "Minute": minute}
               for hour in range(7, 13) for minute in (10, 30, 50)]
    return result


def launchd_plist(data_dir: pathlib.Path, script_path: pathlib.Path | None = None) -> bytes:
    script_path = script_path or pathlib.Path(__file__).resolve()
    return plistlib.dumps({
        "Label": AGENT_LABEL,
        "ProgramArguments": [sys.executable, str(script_path),
                             "--data-dir", str(data_dir)],
        "StartCalendarInterval": launchd_calendar(),
        "WorkingDirectory": str(ROOT),
        "StandardOutPath": str(data_dir / "launchd.stdout.log"),
        "StandardErrorPath": str(data_dir / "launchd.stderr.log"),
    })


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=pathlib.Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--force", action="store_true", help="One manual poll outside weekend hours.")
    parser.add_argument("--report", nargs="?", const="latest", metavar="SATURDAY_DATE")
    parser.add_argument("--print-launchd-plist", action="store_true")
    parser.add_argument("--script-path", type=pathlib.Path,
                        help="Stable deployed copy of this script for launchd.")
    args = parser.parse_args()
    if args.print_launchd_plist:
        sys.stdout.buffer.write(launchd_plist(args.data_dir.resolve(),
                                              args.script_path.resolve() if args.script_path else None))
        return 0
    if args.report:
        report = summarize(args.data_dir, None if args.report == "latest" else args.report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    result = collect_once(args.data_dir, dt.datetime.now(dt.timezone.utc), force=args.force)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result["status"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
