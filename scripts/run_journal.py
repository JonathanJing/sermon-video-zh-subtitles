#!/usr/bin/env python3
"""Append-only run journal: one JSON line per stage event, so a retrospective
reads one file instead of reconstructing the night from dispatch logs.

    python3 scripts/run_journal.py append --run-dir <run> --stage layer3.render.ko --event started
    python3 scripts/run_journal.py append --run-dir <run> --stage layer3.render.ko --event finished
    python3 scripts/run_journal.py append --run-dir <run> --stage audio-qc.ko --event waiting --waiting-on "human acceptance"
    python3 scripts/run_journal.py summary --run-dir <run>

Events: ``started``, ``finished``, ``failed``, ``waiting`` (blocked on something
outside the stage, named by ``--waiting-on``) and ``resumed``. A stage that starts
again after it finished or failed is rework. ``summary`` splits wall time into
compute (started → finished/failed, minus waiting), waiting (waiting → resumed/
finished/failed) and rework (compute spent in repeat starts), per stage and in
total, and names stages still open. The journal is plain text under the run's
ignored artifacts directory and is collected by export_run_digest.py.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

FILE_NAME = "journal.ndjson"
EVENTS = ("started", "finished", "failed", "waiting", "resumed")
STAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def append(run_dir: Path, stage: str, event: str, *, waiting_on: str | None = None, cost_microusd: int | None = None,
           note: str | None = None, refs=(), now=utc_now) -> dict:
    if not STAGE.fullmatch(stage or ""):
        raise ValueError("stage must be a short identifier such as layer3.render.ko")
    if event not in EVENTS:
        raise ValueError(f"event must be one of {', '.join(EVENTS)}")
    if event == "waiting" and not (waiting_on and waiting_on.strip()):
        raise ValueError("a waiting event names what it waits on (--waiting-on)")
    if cost_microusd is not None and (type(cost_microusd) is not int or cost_microusd < 0):
        raise ValueError("cost is a non-negative integer number of micro-USD")
    row = {"at": now(), "stage": stage, "event": event, "host": socket.gethostname(), "pid": os.getpid()}
    if waiting_on:
        row["waitingOn"] = waiting_on.strip()
    if cost_microusd is not None:
        row["costMicrousd"] = cost_microusd
    if note:
        row["note"] = note.strip()[:2000]
    if refs:
        row["refs"] = [str(ref) for ref in refs]
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    descriptor = os.open(run_dir / FILE_NAME, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)
    return row


def read(run_dir: Path) -> list[dict]:
    path = Path(run_dir) / FILE_NAME
    if not path.is_file():
        return []
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise ValueError(f"{path}:{number}: not JSON") from error
        if not isinstance(row, dict) or row.get("event") not in EVENTS or not isinstance(row.get("stage"), str):
            raise ValueError(f"{path}:{number}: not a journal event")
        rows.append(row)
    return rows


def _seconds(start: str, end: str) -> float:
    return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def summary(run_dir: Path) -> dict:
    rows = read(run_dir)
    stages: dict[str, dict] = {}
    for row in rows:
        stage = stages.setdefault(row["stage"], {"starts": 0, "computeSeconds": 0.0, "waitingSeconds": 0.0,
                                                 "reworkSeconds": 0.0, "costMicrousd": 0, "waitingOn": [],
                                                 "status": "never_started", "_open": None, "_wait": None, "_round": 0})
        at, event = row["at"], row["event"]
        stage["costMicrousd"] += row.get("costMicrousd", 0)
        if event == "started":
            if stage["_open"]:
                stage["status"] = "restarted_while_open"
            stage["starts"] += 1
            stage["_round"] = stage["starts"]
            stage["_open"], stage["_wait"] = at, None
            stage["status"] = "running"
        elif event == "waiting":
            if stage["_open"] and not stage["_wait"]:
                stage["_wait"] = at
            stage["status"] = "waiting"
            if row.get("waitingOn"):
                stage["waitingOn"].append(row["waitingOn"])
        elif event == "resumed":
            if stage["_wait"]:
                stage["waitingSeconds"] += _seconds(stage["_wait"], at)
                stage["_wait"] = None
            stage["status"] = "running"
        else:  # finished / failed
            if stage["_wait"]:
                stage["waitingSeconds"] += _seconds(stage["_wait"], at)
                stage["_wait"] = None
            if stage["_open"]:
                compute = _seconds(stage["_open"], at)
                stage["computeSeconds"] += compute
                if stage["_round"] > 1:
                    stage["reworkSeconds"] += compute
                stage["_open"] = None
            stage["status"] = event
    for stage in stages.values():
        # Waiting happened inside the open span; report compute net of it.
        stage["computeSeconds"] = round(max(0.0, stage["computeSeconds"] - stage["waitingSeconds"]), 3)
        stage["waitingSeconds"] = round(stage["waitingSeconds"], 3)
        stage["reworkSeconds"] = round(stage["reworkSeconds"], 3)
        stage["rework"] = max(0, stage["starts"] - 1)
        for key in ("_open", "_wait", "_round"):
            stage.pop(key)
    totals = {key: round(sum(stage[key] for stage in stages.values()), 3)
              for key in ("computeSeconds", "waitingSeconds", "reworkSeconds")}
    totals["costMicrousd"] = sum(stage["costMicrousd"] for stage in stages.values())
    totals["rework"] = sum(stage["rework"] for stage in stages.values())
    return {"schemaVersion": "sermon-run-journal-summary-v1", "events": len(rows),
            "firstAt": rows[0]["at"] if rows else None, "lastAt": rows[-1]["at"] if rows else None,
            "wallSeconds": round(_seconds(rows[0]["at"], rows[-1]["at"]), 3) if rows else 0.0,
            "stages": stages, "totals": totals,
            "openStages": sorted(name for name, stage in stages.items() if stage["status"] in ("running", "waiting"))}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("append", help="Append one stage event")
    add.add_argument("--run-dir", type=Path, required=True)
    add.add_argument("--stage", required=True)
    add.add_argument("--event", choices=EVENTS, required=True)
    add.add_argument("--waiting-on", help="What a waiting stage is blocked on (a person, a service, a credential)")
    add.add_argument("--cost-microusd", type=int, help="Paid cost this event settles, in micro-USD")
    add.add_argument("--note")
    add.add_argument("--ref", action="append", default=[], help="A receipt or log path this event points at; repeatable")
    show = commands.add_parser("summary", help="Compute, waiting and rework time per stage")
    show.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "append":
        row = append(args.run_dir, args.stage, args.event, waiting_on=args.waiting_on, cost_microusd=args.cost_microusd,
                     note=args.note, refs=args.ref)
        print(json.dumps(row, ensure_ascii=False))
    else:
        print(json.dumps(summary(args.run_dir), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
