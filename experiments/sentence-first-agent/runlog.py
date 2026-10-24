#!/usr/bin/env python3
"""Journal, outcome and timings helpers for the sentence-first scripts.

Wraps ``tools/development/run_journal.py`` (the repository's standard journal the run
report exporter already knows) and writes the ``outcome.json`` and ``timings.tsv`` the
exporter's retrospective reads. Stage names: ``l1.srt``, ``l1.preflight``,
``l2.consistency``, ``l3.tts.<speaker>.<locale>``, ``l3.asr.<locale>``, ``l3.finish``,
``l3.review.<locale>``, ``l4.assets``, ``l4.publish.<n>``.

The human review is journaled as ``waiting`` (``waiting_on="user track review"``) by the
agent when the track is sent and ``resumed`` when the user answers; nothing in the scripts
can infer that boundary.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "tools" / "development") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools" / "development"))
from run_journal import append, summary  # noqa: E402


def mark(run, stage: str, event: str, **extra) -> None:
    append(Path(run), stage, event, **extra)


def write_outcome(run, **fields) -> dict:
    data = {"schemaVersion": "sentence-first-outcome-v1",
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **fields}
    (Path(run) / "outcome.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


def write_timings(run) -> dict:
    state = summary(Path(run))
    rows = [["stage", "computeSeconds", "waitingSeconds", "reworkSeconds"]]
    for name, stage in state["stages"].items():
        rows.append([name, stage["computeSeconds"], stage["waitingSeconds"], stage["reworkSeconds"]])
    totals = state["totals"]
    rows.append(["total", totals["computeSeconds"], totals["waitingSeconds"], totals["reworkSeconds"]])
    (Path(run) / "timings.tsv").write_text("\n".join("\t".join(str(v) for v in row) for row in rows) + "\n",
                                           encoding="utf-8")
    return state
