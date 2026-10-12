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
finished/failed) and rework (compute spent in repeat starts, net of their own
waiting), per stage and in total, and names stages still open. The journal is
plain text under the run's ignored artifacts directory and is collected by
export_run_digest.py, which publishes it; so a row names its host only by an
ID (``hostId``) keyed with a random per-run salt (``.journal-host-salt``, never exported),
which tells the Mac from Spark within one run without disclosing a machine name.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

FILE_NAME = "journal.ndjson"
SALT_NAME = ".journal-host-salt"
EVENTS = ("started", "finished", "failed", "waiting", "resumed")
STAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def host_id(run_dir: Path) -> str:
    """A per-run pseudonym for this machine: equal within a run, unlinkable to its name without the salt."""
    path = Path(run_dir) / SALT_NAME
    if not path.exists():
        # Write the salt whole under a private name, then link it into place: a concurrent
        # writer either wins the link or reads the complete salt the other one linked.
        draft = path.with_name(f"{SALT_NAME}.{os.getpid()}.{os.urandom(4).hex()}")
        draft.write_text(os.urandom(32).hex() + "\n", encoding="utf-8")
        try:
            os.link(draft, path)
        except FileExistsError:
            pass
        finally:
            draft.unlink()
    salt = bytes.fromhex(path.read_text(encoding="utf-8").strip())
    return "host-" + hmac.new(salt, socket.gethostname().encode("utf-8"), hashlib.sha256).hexdigest()[:12]


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
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    row = {"at": now(), "stage": stage, "event": event, "hostId": host_id(run_dir), "pid": os.getpid()}
    if waiting_on:
        row["waitingOn"] = waiting_on.strip()
    if cost_microusd is not None:
        row["costMicrousd"] = cost_microusd
    if note:
        row["note"] = note.strip()[:2000]
    if refs:
        row["refs"] = [str(ref) for ref in refs]
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


def _close_wait(stage: dict, at: str) -> None:
    if stage["_wait"]:
        waited = _seconds(stage["_wait"], at)
        stage["waitingSeconds"] += waited
        stage["_roundWait"] += waited
        stage["_wait"] = None


def summary(run_dir: Path) -> dict:
    rows = read(run_dir)
    stages: dict[str, dict] = {}
    for row in rows:
        stage = stages.setdefault(row["stage"], {"starts": 0, "computeSeconds": 0.0, "waitingSeconds": 0.0,
                                                 "reworkSeconds": 0.0, "costMicrousd": 0, "waitingOn": [],
                                                 "status": "never_started", "_open": None, "_wait": None, "_round": 0,
                                                 "_roundWait": 0.0})
        at, event = row["at"], row["event"]
        stage["costMicrousd"] += row.get("costMicrousd", 0)
        if event == "started":
            if stage["_open"]:
                stage["status"] = "restarted_while_open"
            stage["starts"] += 1
            stage["_round"] = stage["starts"]
            stage["_open"], stage["_wait"], stage["_roundWait"] = at, None, 0.0
            stage["status"] = "running"
        elif event == "waiting":
            if stage["_open"] and not stage["_wait"]:
                stage["_wait"] = at
            stage["status"] = "waiting"
            if row.get("waitingOn"):
                stage["waitingOn"].append(row["waitingOn"])
        elif event == "resumed":
            _close_wait(stage, at)
            stage["status"] = "running"
        else:  # finished / failed
            _close_wait(stage, at)
            if stage["_open"]:
                # Compute is this round's span less the waiting inside it; rework is that compute in a repeat round.
                compute = max(0.0, _seconds(stage["_open"], at) - stage["_roundWait"])
                stage["computeSeconds"] += compute
                if stage["_round"] > 1:
                    stage["reworkSeconds"] += compute
                stage["_open"] = None
            stage["status"] = event
    for stage in stages.values():
        stage["computeSeconds"] = round(stage["computeSeconds"], 3)
        stage["waitingSeconds"] = round(stage["waitingSeconds"], 3)
        stage["reworkSeconds"] = round(stage["reworkSeconds"], 3)
        stage["rework"] = max(0, stage["starts"] - 1)
        for key in ("_open", "_wait", "_round", "_roundWait"):
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
