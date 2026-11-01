#!/usr/bin/env python3
"""Observable run status for the sentence-first agent route (P0).

This module is the *display* sidecar for the sentence-first weekly runbook
(``experiments/sentence-first-agent/AGENTS.md``). It never gates production:
a failure to write status or build a snapshot must not change a production
command's exit code. The authoritative evidence remains the run's artifacts,
review receipts, publish preflight/gate and HTTP readback.

What it writes (all under the run's ignored ``artifacts/`` directory):

  status/events.ndjson     progress, heartbeats, attention, evidence markers
  status/status.json       snapshot derived from journal + status events + state files
  status/notify-sent.ndjson dedupe ledger for Bark notifications (P2)
  status/status-check.json optional consistency report from ``check``
  .status-index.json       production -> locale run directory index (at status root)

Stage transitions are still written to the existing ``journal.ndjson`` via
``run_journal.py``; the status events carry the higher-frequency detail the
journal intentionally does not store. A snapshot is always derived, never
hand-edited.

Typical use:

  python3 experiments/sentence-first-agent/run_status.py status --run RUN --watch 2
  python3 experiments/sentence-first-agent/run_status.py handoff --run RUN \\
      --stage l3.review.zh-Hans --waiting-on "user track review" --url http://127.0.0.1:8765/review-player.html
  python3 experiments/sentence-first-agent/run_status.py resume --run RUN --stage l3.review.zh-Hans
  python3 experiments/sentence-first-agent/run_status.py wrap --run RUN --stage l3.finish -- python3 finish_run.py ...
  python3 experiments/sentence-first-agent/run_status.py notify --run RUN [--execute]  # Bark (P2)

Start/register and the TTS queue call the same helpers; see ``sfa.py`` and
``spark_queue.py``. The snapshot's ``evidenceLevel`` is E0-E6 and is explicitly
``null`` when the evidence is not known; it is never inferred from a file name.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
TOOLS_DEVELOPMENT = ROOT / "tools" / "development"
TOOLS_OPS = ROOT / "tools" / "ops"
for _entry in (str(TOOLS_DEVELOPMENT), str(TOOLS_OPS)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
import run_journal  # noqa: E402
try:  # notification transport is optional until P2 is used
    import notify as notify_transport
except Exception:  # noqa: BLE001
    notify_transport = None

SCHEMA_EVENT = "sentence-first-status-event-v1"
SCHEMA_SNAPSHOT = "sentence-first-run-status-v1"
SCHEMA_INDEX = "sentence-first-status-index-v1"
STATUS_DIR = "status"
EVENTS_FILE = "events.ndjson"
SNAPSHOT_FILE = "status.json"
CHECK_FILE = "status-check.json"
AGENT_FILE = "agent.json"
NOTIFY_SENT_FILE = "notify-sent.ndjson"
INDEX_FILE = ".status-index.json"
MISSING_GRACE_SECONDS = 600
STATUS_ROOT = ROOT / "artifacts" / "sentence-first-agent"
EVIDENCE_LEVELS = ("E0", "E1", "E2", "E3", "E4", "E5", "E6")
JOURNAL_EVENTS = ("started", "finished", "failed", "waiting", "resumed")
STATUS_TYPES = (
    "run.planned", "run.started", "run.finished", "run.failed", "run.cancelled",
    "stage.started", "stage.progress", "stage.heartbeat", "stage.waiting",
    "stage.resumed", "stage.finished", "stage.failed", "stage.skipped", "stage.rework",
    "evidence.recorded", "attention.open", "attention.close",
)
STATUS_TO_JOURNAL = {
    "stage.started": "started", "stage.finished": "finished", "stage.failed": "failed",
    "stage.waiting": "waiting", "stage.resumed": "resumed",
}
JOURNAL_TO_STATUS = {value: key for key, value in STATUS_TO_JOURNAL.items()}
DEFAULT_LOCALES = ("zh-Hans", "ko", "es", "vi")
LOCALE_TOKEN = re.compile(r"^(?:[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?)$")
SEVERITY_RANK = {"critical": 0, "timeSensitive": 1, "attention": 2, "info": 3}


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value)


def utc_now(now: Callable[[], Any] | None = None) -> str:
    """ISO-8601 UTC; microseconds keep same-second status events ordered."""
    if now is not None:
        return _iso(now())
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def parse_time(value: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def age_seconds(then: str, now: Callable[[], Any] | None = None) -> float:
    return max(0.0, (parse_time(utc_now(now)) - parse_time(then)).total_seconds())


def status_dir(run: Path) -> Path:
    return Path(run) / STATUS_DIR


def status_path(run: Path) -> Path:
    return status_dir(run) / SNAPSHOT_FILE


def events_path(run: Path) -> Path:
    return status_dir(run) / EVENTS_FILE


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    draft = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    draft.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(draft, path)


def _append_line(path: Path, row: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False) + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(descriptor, line.encode("utf-8"))
    finally:
        os.close(descriptor)


def _validate_stage(stage: str) -> None:
    if not isinstance(stage, str) or not run_journal.STAGE.fullmatch(stage):
        raise ValueError(f"stage must be a short identifier such as l3.tts.john_thomas.zh-Hans: {stage!r}")


def _validate_evidence(level: str | None) -> str | None:
    if level is None:
        return None
    if level not in EVIDENCE_LEVELS:
        raise ValueError(f"evidence level must be one of {', '.join(EVIDENCE_LEVELS)}")
    return level


def phase_for(stage: str) -> str:
    if stage.startswith("l3.review."):
        return "P4"
    if stage.startswith("l1."):
        return "P1"
    if stage.startswith("l2."):
        return "P2"
    if stage.startswith("l3."):
        return "P3"
    if stage.startswith("l4."):
        return "P5"
    if stage.startswith("l5."):
        return "P6"
    return "PX"


def lane_for(stage: str, locales: set[str] | None = None) -> str | None:
    known = set(locales or ()) | set(DEFAULT_LOCALES)
    parts = stage.split(".")
    for part in reversed(parts[1:]):
        if part in known:
            return part
        if LOCALE_TOKEN.fullmatch(part) and part not in {"tts", "review", "finish", "speech", "audit"}:
            return part
    return None


def expected_heartbeat_seconds(stage: str) -> int:
    if stage.startswith("l3.tts"):
        return 180
    # finish_run/lag_loop journal only started/finished today; a 60 s expectation would
    # flag their normal 4-8 min run as stalled. P1 adds sub-step progress; until then use
    # a conservative threshold and let the journal start act as the heartbeat.
    if stage.startswith(("l3.finish", "l3.lag-loop")):
        return 300
    if stage.startswith("l2."):
        return 120
    return 120


def infer_locale(run: Path, decisions: dict | None = None) -> str | None:
    decisions = decisions or {}
    locales = decisions.get("locales") or []
    name = Path(run).name
    for locale in reversed(sorted(locales, key=len)):
        if name.endswith("-" + locale) or name.endswith("_" + locale):
            return locale
    aliases = {"zh": "zh-Hans", "zh-hans": "zh-Hans", "zh-hant": "zh-Hant",
               "ko": "ko", "es": "es", "vi": "vi"}
    for alias, locale in aliases.items():
        if name.endswith("-" + alias) or name.endswith("_" + alias):
            return locale
    for locale in sorted(DEFAULT_LOCALES, key=len, reverse=True):
        if name.endswith("-" + locale) or name.endswith("_" + locale):
            return locale
    return None


def default_index(run: Path | None = None) -> Path:
    if run is not None:
        run = Path(run).resolve()
        try:
            run.relative_to(STATUS_ROOT.resolve())
            return STATUS_ROOT / INDEX_FILE
        except ValueError:
            return run.parent / INDEX_FILE
    return STATUS_ROOT / INDEX_FILE


def resolve_index(value: str | Path | None, run: Path | None = None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return default_index(run)


def _run_ref(run: Path, index: Path) -> str:
    try:
        return str(Path(run).resolve().relative_to(Path(index).resolve().parent))
    except ValueError:
        return str(Path(run).resolve())


def _resolve_ref(ref: str, index: Path) -> Path:
    path = Path(ref)
    if path.is_absolute():
        return path
    return (Path(index).resolve().parent / path).resolve()


def load_index(index: Path | None = None) -> dict:
    path = Path(index) if index else default_index()
    value = _read_json(path)
    if value.get("schemaVersion") != SCHEMA_INDEX:
        value = {"schemaVersion": SCHEMA_INDEX, "updatedAt": utc_now(), "productions": {}}
    value.setdefault("productions", {})
    return value


def save_index(value: dict, index: Path | None = None) -> Path:
    path = Path(index) if index else default_index()
    value = dict(value)
    value["schemaVersion"] = SCHEMA_INDEX
    value["updatedAt"] = utc_now()
    _write_json(path, value)
    return path


def register_run(run: Path, *, production: str | None = None, page_id: str | None = None,
                 locale: str | None = None, form: str | None = None, sync: bool | None = None,
                 publish: bool | None = None, title: str | None = None, locales: list[str] | None = None,
                 index: Path | None = None, now: Callable[[], Any] | None = None) -> dict:
    """Register a run for one production in the status index (idempotent)."""
    run = Path(run).resolve()
    index_path = resolve_index(index, run)
    decisions = _read_json(run / "decisions.json")
    locale = locale or infer_locale(run, decisions)
    production = production or page_id or decisions.get("pageId") or run.name
    if page_id is None:
        page_id = decisions.get("pageId")
    if form is None:
        form = decisions.get("form")
    if sync is None:
        sync = decisions.get("sync")
    if publish is None:
        publish = decisions.get("publish")
    if title is None:
        title = decisions.get("title") or ""
    all_locales = list(dict.fromkeys([*(locales or decisions.get("locales") or []),
                                      *([locale] if locale else [])]))
    data = load_index(index_path)
    productions = data.setdefault("productions", {})
    entry = productions.get(production) or {
        "productionId": production,
        "schemaVersion": SCHEMA_INDEX,
        "runs": {},
        "registeredAt": utc_now(now),
    }
    if page_id:
        entry["pageId"] = page_id
    entry["title"] = title or entry.get("title") or ""
    if form:
        entry["form"] = form
    if sync is not None:
        entry["sync"] = bool(sync)
    if publish is not None:
        entry["publish"] = bool(publish)
    entry["locales"] = sorted(set(entry.get("locales") or []) | set(all_locales))
    runs = entry.setdefault("runs", {})
    runs[locale or "default"] = _run_ref(run, index_path)
    entry["active"] = True
    entry["updatedAt"] = utc_now(now)
    productions[production] = entry
    save_index(data, index_path)
    append_status_event(run, "run.planned", stage="run", source="register", now=now,
                        message=f"production={production} locale={locale or 'default'}")
    return entry


def find_run_for_locale(locale: str, index: Path | None = None) -> Path | None:
    data = load_index(index)
    entries = sorted(data.get("productions", {}).values(),
                     key=lambda entry: (bool(entry.get("active")), entry.get("updatedAt") or ""),
                     reverse=True)
    for entry in entries:
        ref = (entry.get("runs") or {}).get(locale)
        if ref:
            path = _resolve_ref(ref, Path(index) if index else default_index())
            if path.exists():
                return path
    return None


def entry_for_run(run: Path, index: Path | None = None) -> tuple[dict | None, str | None, Path]:
    run = Path(run).resolve()
    index_path = resolve_index(index, run)
    data = load_index(index_path)
    for production, entry in data.get("productions", {}).items():
        for locale, ref in (entry.get("runs") or {}).items():
            if _resolve_ref(ref, index_path) == run:
                return entry, locale if locale != "default" else None, index_path
    return None, None, index_path


def next_attempt(run: Path, stage: str) -> int:
    try:
        rows = run_journal.read(Path(run))
    except (OSError, ValueError):
        return 1
    starts = sum(1 for row in rows if row.get("stage") == stage and row.get("event") == "started")
    return starts + 1


def append_status_event(run: Path, event_type: str, *, stage: str, source: str = "cli",
                        attempt: int | None = None, lane: str | None = None,
                        progress: dict | None = None, eta_seconds: float | None = None,
                        message: str | None = None, waiting_on: str | None = None,
                        kind: str | None = None, action_url: str | None = None,
                        expected_minutes: str | None = None, evidence_level: str | None = None,
                        error_class: str | None = None, resume: str | None = None,
                        heartbeat_expected_seconds: int | None = None,
                        now: Callable[[], Any] | None = None, **extra: Any) -> dict:
    _validate_stage(stage)
    if event_type not in STATUS_TYPES:
        raise ValueError(f"unknown status event type: {event_type}")
    event = {
        "schemaVersion": SCHEMA_EVENT,
        "eventId": f"{Path(run).name}:{uuid.uuid4().hex[:12]}",
        "at": utc_now(now),
        "runId": Path(run).name,
        "type": event_type,
        "stage": stage,
        "source": source,
    }
    optional = {
        "attempt": attempt, "lane": lane, "progress": progress, "etaSeconds": eta_seconds,
        "message": message, "waitingOn": waiting_on, "kind": kind, "actionUrl": action_url,
        "expectedMinutes": expected_minutes, "evidenceLevel": _validate_evidence(evidence_level),
        "errorClass": error_class, "resume": resume,
        "heartbeatExpectedSeconds": heartbeat_expected_seconds,
    }
    for key, value in optional.items():
        if value is not None:
            event[key] = value
    for key, value in extra.items():
        if value is not None:
            event[key] = value
    _append_line(events_path(run), event)
    return event


def mark_event(run: Path, stage: str, event: str, *, attempt: int | None = None,
               unit: str | None = None, done: int | None = None, total: int | None = None,
               eta_seconds: float | None = None, message: str | None = None,
               waiting_on: str | None = None, kind: str | None = None,
               source: str = "cli", evidence_level: str | None = None,
               error_class: str | None = None, resume: str | None = None,
               action_url: str | None = None, expected_minutes: str | None = None,
               heartbeat_expected_seconds: int | None = None,
               now: Callable[[], Any] | None = None) -> dict:
    """Write a stage event to the journal (transitions) and the status sidecar."""
    _validate_stage(stage)
    run = Path(run)
    if event not in (*JOURNAL_EVENTS, "progress", "heartbeat", "skipped"):
        raise ValueError(f"event must be one of {', '.join((*JOURNAL_EVENTS, 'progress', 'heartbeat', 'skipped'))}")
    if event == "waiting" and not (waiting_on and waiting_on.strip()):
        raise ValueError("waiting requires --waiting-on")
    if event == "progress" and not (unit or done is not None or total is not None or eta_seconds is not None):
        raise ValueError("progress requires --unit/--done/--total or --eta-seconds")
    if attempt is None and event in JOURNAL_EVENTS:
        attempt = next_attempt(run, stage)
    if event in JOURNAL_EVENTS:
        clock = (lambda: utc_now(now))
        run_journal.append(run, stage, event, waiting_on=waiting_on, note=message, now=clock)
    status_type = {
        "started": "stage.started", "finished": "stage.finished", "failed": "stage.failed",
        "waiting": "stage.waiting", "resumed": "stage.resumed",
        "progress": "stage.progress", "heartbeat": "stage.heartbeat", "skipped": "stage.skipped",
    }[event]
    progress = None
    if unit is not None or done is not None or total is not None:
        progress = {"unit": unit or "units", "done": done, "total": total}
    return append_status_event(
        run, status_type, stage=stage, source=source, attempt=attempt,
        progress=progress, eta_seconds=eta_seconds, message=message, waiting_on=waiting_on,
        kind=kind or ("human" if event == "waiting" and (waiting_on or "") and
                      any(word in waiting_on.lower() for word in ("user", "review", "authoriz", "approv"))
                      else ("external" if event == "waiting" else None)),
        action_url=action_url, expected_minutes=expected_minutes,
        evidence_level=evidence_level, error_class=error_class, resume=resume,
        heartbeat_expected_seconds=heartbeat_expected_seconds, now=now,
    )


def safe_mark(run: Path, stage: str, event: str, **kwargs: Any) -> dict | None:
    """Fail-open wrapper for production scripts; never raises."""
    try:
        return mark_event(run, stage, event, **kwargs)
    except Exception as exc:  # noqa: BLE001 - status must not break production
        print(f"run_status: could not mark {stage} {event}: {exc}", file=sys.stderr)
        return None


def safe_register(run: Path, **kwargs: Any) -> dict | None:
    try:
        return register_run(run, **kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"run_status: could not register {run}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- derivation

def _journal_events(run: Path) -> tuple[list[dict], list[str]]:
    try:
        rows = run_journal.read(Path(run))
    except (OSError, ValueError) as exc:
        return [], [f"journal: {exc}"]
    events = []
    for row in rows:
        event = {
            "at": row["at"], "type": JOURNAL_TO_STATUS[row["event"]], "stage": row["stage"],
            "source": "journal", "eventId": f"journal:{row['at']}:{row.get('pid')}:{row['stage']}",
        }
        if row.get("waitingOn"):
            event["waitingOn"] = row["waitingOn"]
            event["kind"] = "human" if any(word in row["waitingOn"].lower()
                                           for word in ("user", "review", "authoriz", "approv")) else "external"
        if row.get("costMicrousd") is not None:
            event["costMicrousd"] = row["costMicrousd"]
        events.append(event)
    return events, []


def _status_events(run: Path) -> tuple[list[dict], list[str]]:
    path = events_path(run)
    if not path.is_file():
        return [], []
    events, issues = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or row.get("type") not in STATUS_TYPES:
                raise ValueError("not a status event")
            _validate_stage(row.get("stage", ""))
            if not row.get("at"):
                raise ValueError("missing at")
        except (ValueError, TypeError) as exc:
            issues.append(f"status:{number}: {exc}")
            continue
        row.setdefault("source", "status")
        events.append(row)
    return events, issues


def _infer_waiting_kind(waiting_on: str | None) -> str | None:
    if not waiting_on:
        return None
    lowered = waiting_on.lower()
    return "human" if any(word in lowered for word in ("user", "review", "authoriz", "approv")) else "external"


def _new_stage(stage: str, locales: set[str]) -> dict:
    return {
        "id": stage, "phase": phase_for(stage), "lane": lane_for(stage, locales),
        "state": "pending", "attempt": 0, "startedAt": None, "finishedAt": None,
        "waitingSince": None, "waitingOn": None, "waitingKind": None, "actionUrl": None,
        "expectedMinutes": None, "progress": None, "heartbeatAt": None,
        "heartbeatExpectedSeconds": expected_heartbeat_seconds(stage),
        "etaSeconds": None, "etaSource": None, "evidenceLevel": None,
        "errorClass": None, "errorMessage": None, "resume": None,
        "source": "derived", "stalled": False, "stalledSeconds": None,
        "waitingAgeSeconds": None, "_progress_history": [],
    }


def _apply_event(stages: dict[str, dict], event: dict, locales: set[str]) -> None:
    typ = event["type"]
    if typ.startswith(("run.", "evidence.", "attention.")):
        return
    stage_id = event["stage"]
    stage = stages.setdefault(stage_id, _new_stage(stage_id, locales))
    at = event["at"]
    attempt = event.get("attempt")
    if attempt is not None:
        # An event from an older attempt must never reopen or overwrite the current one.
        if int(attempt) < stage["attempt"]:
            return
        stage["attempt"] = int(attempt)
    if event.get("source"):
        stage["source"] = event["source"]
    if event.get("heartbeatExpectedSeconds") is not None:
        stage["heartbeatExpectedSeconds"] = int(event["heartbeatExpectedSeconds"])
    if typ in ("stage.started", "stage.rework"):
        if typ == "stage.rework" or (attempt is None and stage["state"] in
                                     ("running", "succeeded", "failed", "skipped")):
            if stage["state"] != "pending":
                stage["attempt"] = max(stage["attempt"] + 1, int(attempt or 0))
        stage["state"] = "running"
        stage["startedAt"] = at
        stage["finishedAt"] = None
        stage["waitingSince"] = None
        stage["waitingOn"] = None
        stage["waitingKind"] = None
        stage["heartbeatAt"] = at
        stage["progress"] = None
        stage["etaSeconds"] = None
        stage["etaSource"] = None
        stage["errorClass"] = None
        stage["errorMessage"] = None
        stage["resume"] = None
        stage["_progress_history"] = []
        stage["attempt"] = max(1, stage["attempt"])
    elif typ == "stage.progress":
        if stage["state"] in ("succeeded", "failed", "skipped"):
            return
        if stage["state"] == "pending":
            stage["state"] = "running"
            stage["startedAt"] = at
        stage["progress"] = dict(event.get("progress") or {})
        values = stage["progress"]
        if values.get("done") is not None and values.get("total"):
            stage["_progress_history"].append((at, values.get("done"), values.get("total")))
            stage["_progress_history"] = stage["_progress_history"][-32:]
        stage["heartbeatAt"] = at
        if event.get("etaSeconds") is not None:
            stage["etaSeconds"] = event["etaSeconds"]
            stage["etaSource"] = "event"
    elif typ == "stage.heartbeat":
        if stage["state"] == "running":
            stage["heartbeatAt"] = at
    elif typ == "stage.waiting":
        stage["state"] = "waiting"
        stage["waitingSince"] = at
        stage["waitingOn"] = event.get("waitingOn")
        stage["waitingKind"] = event.get("kind") or _infer_waiting_kind(event.get("waitingOn"))
        stage["actionUrl"] = event.get("actionUrl")
        stage["expectedMinutes"] = event.get("expectedMinutes")
    elif typ == "stage.resumed":
        stage["state"] = "running"
        stage["waitingSince"] = None
        stage["waitingOn"] = None
        stage["waitingKind"] = None
        stage["heartbeatAt"] = at
    elif typ == "stage.finished":
        stage["state"] = "succeeded"
        stage["finishedAt"] = at
        stage["heartbeatAt"] = at
        stage["waitingSince"] = None
        stage["waitingOn"] = None
        stage["waitingKind"] = None
        if event.get("evidenceLevel"):
            stage["evidenceLevel"] = event["evidenceLevel"]
    elif typ == "stage.failed":
        stage["state"] = "failed"
        stage["finishedAt"] = at
        stage["errorClass"] = event.get("errorClass") or "unknown"
        stage["errorMessage"] = (event.get("message") or "")[:500]
        stage["resume"] = event.get("resume")
        stage["waitingSince"] = None
        stage["waitingOn"] = None
        stage["waitingKind"] = None
    elif typ == "stage.skipped":
        stage["state"] = "skipped"
        stage["finishedAt"] = at


def _finish_stage(stage: dict, now: Callable[[], Any] | None) -> None:
    history = stage.pop("_progress_history", [])
    if stage["state"] == "running":
        heartbeat = stage["heartbeatAt"] or stage["startedAt"]
        expected = int(stage.get("heartbeatExpectedSeconds") or expected_heartbeat_seconds(stage["id"]))
        age = age_seconds(heartbeat, now) if heartbeat else None
        stage["heartbeatAgeSeconds"] = round(age, 1) if age is not None else None
        threshold = max(3 * expected, 120)
        stage["stalled"] = bool(age is not None and age > threshold)
        stage["stalledSeconds"] = round(age - threshold, 1) if stage["stalled"] else None
    if stage["state"] == "waiting" and stage["waitingSince"]:
        stage["waitingAgeSeconds"] = round(age_seconds(stage["waitingSince"], now), 1)
    if stage["state"] == "running" and stage["etaSeconds"] is None and len(history) >= 2:
        first_at, first_done, total = history[0]
        last_at, last_done, last_total = history[-1]
        if total == last_total and last_done is not None and first_done is not None and last_done > first_done:
            elapsed = (parse_time(last_at) - parse_time(first_at)).total_seconds()
            if elapsed > 0:
                rate = (last_done - first_done) / elapsed
                remaining = max(0, int(total) - int(last_done))
                if rate > 0:
                    stage["etaSeconds"] = int(round(remaining / rate))
                    stage["etaSource"] = "observed"


def _read_speakers(run: Path) -> list[str]:
    path = Path(run) / "speech.jsonl"
    if not path.is_file():
        return []
    speakers = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            speaker = row.get("speaker")
            if speaker and speaker not in speakers:
                speakers.append(speaker)
    except (OSError, ValueError):
        return []
    return speakers


def _line_count(path: Path) -> int:
    try:
        return sum(1 for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _mtime_at(path: Path) -> str:
    return datetime.fromtimestamp(Path(path).stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def _fill_stage(stages: dict[str, dict], stage_id: str, locales: set[str], *, state: str,
                evidence_level: str, source: str, path: Path | None = None,
                progress: dict | None = None, error_class: str | None = None,
                message: str | None = None, resume: str | None = None) -> None:
    stage = stages.setdefault(stage_id, _new_stage(stage_id, locales))
    if stage["state"] != "pending":
        return
    at = _mtime_at(path) if path and path.exists() else utc_now()
    stage["state"] = state
    stage["startedAt"] = at
    stage["heartbeatAt"] = at
    if state in ("succeeded", "failed", "skipped"):
        stage["finishedAt"] = at
    stage["evidenceLevel"] = evidence_level
    stage["source"] = source
    if progress:
        stage["progress"] = progress
    if error_class:
        stage["errorClass"] = error_class
        stage["errorMessage"] = message
        stage["resume"] = resume


def _derive_artifacts(run: Path, stages: dict[str, dict], locale: str | None,
                      locales: set[str], speakers: list[str]) -> list[str]:
    """Fill stages that old/manual runs proved with products but never journaled."""
    if not locale:
        return []
    derived = []

    def note(name: str) -> None:
        if name not in derived:
            derived.append(name)

    translations = run / "translations.jsonl"
    translated_rows = _line_count(translations) if translations.is_file() else 0
    if translated_rows:
        _fill_stage(stages, f"l2.translate.{locale}", locales, state="succeeded",
                    evidence_level="E1", source="derived:translations.jsonl", path=translations)
        note("translations.jsonl")
    else:
        # The subagent route writes translate/output-<k>.jsonl and only merges later.
        inputs = sorted((run / "translate").glob("input-*.jsonl"))
        outputs = sorted((run / "translate").glob("output-*.jsonl"))
        total = sum(_line_count(path) for path in inputs)
        done = sum(_line_count(path) for path in outputs)
        if total:
            path = outputs[-1] if outputs else inputs[-1]
            _fill_stage(stages, f"l2.translate.{locale}", locales, state="running",
                        evidence_level="E0", source="derived:translate/", path=path,
                        progress={"unit": "rows", "done": done, "total": total})
            note("translate/")
    consistency = run / f"consistency-{locale}.json"
    if not consistency.is_file():
        consistency = run / "consistency.json"
    if consistency.is_file():
        _fill_stage(stages, "l2.consistency", locales, state="succeeded", evidence_level="E1",
                    source=f"derived:{consistency.name}", path=consistency)
        note(consistency.name)
    audit_files = sorted((run / "audit").glob(f"revisions-{locale}.jsonl"))
    if not audit_files:
        audit_files = sorted((run / "audit").glob(f"raw-{locale}.txt"))
    if audit_files and _line_count(audit_files[0]):
        _fill_stage(stages, f"l2.audit.{locale}", locales, state="succeeded", evidence_level="E1",
                    source=f"derived:audit/{audit_files[0].name}", path=audit_files[0])
        note(f"audit/{audit_files[0].name}")
    speech = run / "speech.jsonl"
    if speech.is_file() and _line_count(speech):
        _fill_stage(stages, f"l3.speech.{locale}", locales, state="succeeded", evidence_level="E1",
                    source="derived:speech.jsonl", path=speech)
        note("speech.jsonl")
    track = run / "track.wav"
    if track.is_file():
        tts = [f"l3.tts.{speaker}.{locale}" for speaker in speakers] or [f"l3.tts.{locale}"]
        for name in tts:
            _fill_stage(stages, name, locales, state="succeeded", evidence_level="E1",
                        source="derived:track.wav", path=track)
        _fill_stage(stages, "l3.finish", locales, state="succeeded", evidence_level="E1",
                    source="derived:track.wav", path=track)
        note("track.wav")
    elif speakers:
        # Partial TTS is visible from the per-sentence WAVs; do not call it finished.
        wavs = list((run / "tts").glob("*.wav")) if (run / "tts").is_dir() else []
        sentences = _line_count(run / "sentences.jsonl")
        if wavs and sentences:
            for speaker in speakers:
                name = f"l3.tts.{speaker}.{locale}"
                _fill_stage(stages, name, locales, state="running", evidence_level="E0",
                            source="derived:tts/", path=run / "tts",
                            progress={"unit": "sentences", "done": len(wavs), "total": sentences})
            note("tts/")
    lag_report = run / "lag-loop-report.json"
    if lag_report.is_file():
        report = _read_json(lag_report)
        gate = report.get("gate") or {}
        clean = gate.get("clean") if isinstance(gate, dict) else None
        if clean is True:
            _fill_stage(stages, f"l3.lag-loop.{locale}", locales, state="succeeded",
                        evidence_level="E2", source="derived:lag-loop-report.json", path=lag_report)
        elif clean is False:
            _fill_stage(stages, f"l3.lag-loop.{locale}", locales, state="failed",
                        evidence_level="E1", source="derived:lag-loop-report.json", path=lag_report,
                        error_class="lag_gate", message="lag-loop gate.clean is false",
                        resume="lag_loop.py --check-only --require-clean")
        note("lag-loop-report.json")
    for verdict in sorted(run.glob("*verdict*.json")):
        receipt = _read_json(verdict)
        if receipt.get("verdict") == "approved":
            _fill_stage(stages, f"l3.review.{locale}", locales, state="succeeded",
                        evidence_level="E3", source=f"derived:{verdict.name}", path=verdict)
            note(verdict.name)
    return derived


def _derive_deepseek_states(run: Path, stages: dict[str, dict], locale: str | None,
                            locales: set[str], now: Callable[[], Any] | None) -> list[str]:
    derived = []
    if not locale:
        return derived
    mapping = {
        "translate": (f"l2.translate.{locale}", "windows"),
        "audit": (f"l2.audit.{locale}", "windows"),
        "trim": (f"l3.lag-loop.{locale}", "windows"),
    }
    for path in sorted(Path(run).glob("state-*.json")):
        state = _read_json(path)
        label = state.get("label") or path.stem.removeprefix("state-")
        target = mapping.get(label)
        if not target:
            continue
        stage_id, unit = target
        stage = stages.get(stage_id)
        if stage is not None and stage.get("progress"):
            continue
        if stage is None:
            stage = stages.setdefault(stage_id, _new_stage(stage_id, locales))
        status_word = state.get("status")
        if status_word in ("running", "finished", "failed"):
            stage["state"] = {"running": "running", "finished": "succeeded", "failed": "failed"}[status_word]
        window_done = state.get("windowsDone")
        window_total = state.get("total")
        values = {"unit": unit, "done": window_done,
                  "total": window_total if isinstance(window_total, int) and window_total > 0 else None}
        if values["done"] is not None or values["total"] is not None:
            stage["progress"] = values
        if state.get("unitsDone") is not None:
            stage.setdefault("unitsDone", state.get("unitsDone"))
        started = state.get("startedAt")
        updated = state.get("updatedAt")
        if started:
            stage["startedAt"] = started
        if updated:
            stage["heartbeatAt"] = updated
        stage["source"] = f"derived:{path.name}"
        if stage["state"] == "failed" and state.get("lastError"):
            stage["errorClass"] = stage.get("errorClass") or "deepseek"
            stage["errorMessage"] = str(state["lastError"])[:500]
        derived.append(path.name)
        _finish_stage(stage, now)
    return derived


def _domain_variants(value: str, suffixes: tuple[str, ...]) -> list[str]:
    return [value] + [value + suffix for suffix in suffixes]


def _required_stages(run: Path, stages: dict[str, dict], locale: str | None,
                     locales: set[str], decisions: dict, speakers: list[str]) -> dict:
    required: list[dict] = []
    suffixes = tuple(f".{loc}" for loc in sorted(locales))
    sync = bool(decisions.get("sync"))
    publish = bool(decisions.get("publish"))

    def add(stage_id: str, prerequisites: list[str] | None = None, human: bool = False) -> None:
        required.append({"id": stage_id, "prerequisites": prerequisites or [], "human": human})

    def succeeded(stage_id: str) -> bool:
        for name in _domain_variants(stage_id, suffixes):
            if stages.get(name, {}).get("state") in ("succeeded", "skipped"):
                return True
        return False

    def present(stage_id: str) -> bool:
        for name in _domain_variants(stage_id, suffixes):
            if stages.get(name, {}).get("state") in ("running", "waiting", "failed", "succeeded", "skipped"):
                return True
        return False

    add("l1.start")
    add("l1.preflight", ["l1.start"])
    if locale:
        translate = f"l2.translate.{locale}"
        consistency = "l2.consistency"
        speech = f"l3.speech.{locale}"
        finish = "l3.finish"
        translate_prereqs = ["l1.preflight", "l1.start"]
        if publish:
            translate_prereqs.append("l1.english-review")
        add(translate, translate_prereqs)
        add(f"l2.audit.{locale}", [translate])
        add(consistency, [translate])
        add(speech, [consistency, translate])
        tts = [f"l3.tts.{speaker}.{locale}" for speaker in speakers]
        if not tts:
            tts = [f"l3.tts.{locale}"]
        for name in tts:
            add(name, [speech])
        add(finish, tts)
        if sync:
            add(f"l3.lag-loop.{locale}", [finish])
        if publish:
            add("l1.english-review", ["l1.start"], human=True)
            add(f"l3.review.{locale}", [*( [f"l3.lag-loop.{locale}"] if sync else [finish])], human=True)
    due, missing, not_due, human = [], [], [], []
    for item in required:
        stage_id = item["id"]
        if item["human"]:
            human.append(item)
            continue
        is_due = all(succeeded(prereq) for prereq in item["prerequisites"])
        item["due"] = is_due
        if not is_due:
            not_due.append(item)
            continue
        due.append(item)
        # "Missing" means there is no record for a stage that is due. A running,
        # waiting or failed stage has its own state/attention and is not missing.
        if not succeeded(stage_id) and not present(stage_id):
            missing.append(item["id"])
    return {"all": required, "due": due, "missing": missing, "notDue": not_due, "human": human}


def _attention_items(run: Path, stages: dict[str, dict], missing: list[str],
                     now: Callable[[], Any] | None, required_all: list[dict] | None = None) -> list[dict]:
    items = []
    required_by_id = {item["id"]: item for item in (required_all or [])}
    now_iso = utc_now(now)
    for stage in stages.values():
        state = stage["state"]
        if state == "waiting":
            kind = "human_review" if stage.get("waitingKind") == "human" or stage["id"].startswith("l3.review") else "external"
            items.append({
                "id": f"att-{stage['id']}-{kind}", "kind": kind,
                "severity": "attention" if kind == "human_review" else "info",
                "stage": stage["id"], "since": stage.get("waitingSince"),
                "ageSeconds": stage.get("waitingAgeSeconds"),
                "waitingOn": stage.get("waitingOn"), "actionUrl": stage.get("actionUrl"),
                "expectedMinutes": stage.get("expectedMinutes"), "state": "open",
            })
        if state == "failed":
            items.append({
                "id": f"att-{stage['id']}-failed", "kind": "failed", "severity": "timeSensitive",
                "stage": stage["id"], "since": stage.get("finishedAt"),
                "ageSeconds": round(age_seconds(stage["finishedAt"], now), 1) if stage.get("finishedAt") else None,
                "errorClass": stage.get("errorClass"), "message": stage.get("errorMessage"),
                "resume": stage.get("resume"), "state": "open",
            })
        if stage.get("stalled"):
            items.append({
                "id": f"att-{stage['id']}-stalled", "kind": "stalled", "severity": "timeSensitive",
                "stage": stage["id"], "since": stage.get("heartbeatAt"),
                "ageSeconds": stage.get("heartbeatAgeSeconds"),
                "heartbeatExpectedSeconds": stage.get("heartbeatExpectedSeconds"),
                "stalledSeconds": stage.get("stalledSeconds"), "state": "open",
            })
    for stage_id in missing:
        if stage_id != "l1.start":
            item = required_by_id.get(stage_id) or {}
            due_times = []
            for prerequisite in item.get("prerequisites") or []:
                for key, stage in stages.items():
                    if key == prerequisite or key.startswith(prerequisite + "."):
                        if stage.get("finishedAt"):
                            due_times.append(stage["finishedAt"])
            if due_times:
                due_since = max(due_times, key=parse_time)
                if (parse_time(now_iso) - parse_time(due_since)).total_seconds() < MISSING_GRACE_SECONDS:
                    continue
        items.append({
            "id": f"att-{stage_id}-missing", "kind": "missing_required",
            "severity": "info" if stage_id == "l1.start" else "attention",
            "stage": stage_id, "since": now_iso, "ageSeconds": 0, "state": "open",
        })
    items.sort(key=lambda item: (SEVERITY_RANK.get(item.get("severity"), 9), item.get("since") or ""))
    return items


def _run_state(stages: dict[str, dict], attention: list[dict], required: dict,
               publish: bool) -> str:
    if not stages:
        return "planned"
    active = [stage for stage in stages.values() if stage["state"] in ("running", "waiting")]
    if any(item.get("severity") in ("attention", "timeSensitive", "critical") for item in attention):
        return "attention_required"
    if active:
        return "attention_required" if any(stage["state"] == "waiting" for stage in active) else "active"
    machine = [item for item in required.get("all", []) if not item.get("human")]

    def done(stage_id: str) -> bool:
        return any(stages.get(key, {}).get("state") in ("succeeded", "skipped")
                   for key in stages if key == stage_id or key.startswith(stage_id + "."))

    if all(done(item["id"]) for item in machine):
        if not publish:
            return "completed"
        review_stages = [stage for name, stage in stages.items() if name.startswith("l3.review.")]
        if review_stages and all(stage["state"] == "succeeded" for stage in review_stages):
            return "completed"
        return "active"
    return "active"


def _deliverables(run: Path) -> list[dict]:
    rows = []

    def add(item_id: str, level: str, ref: str, path: Path, **extra: Any) -> None:
        rows.append({
            "id": item_id, "evidenceLevel": level, "ref": ref,
            "evidenceAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
            **extra,
        })

    checks = [
        ("track.wav", "track", "E1", None),
        ("review.mp3", "review_audio", "E1", None),
        ("review-player.html", "review_player", "E1", None),
        ("translations.jsonl", "translations", "E1", None),
        ("speech.jsonl", "speech", "E1", None),
        ("decisions.json", "decisions", "E1", None),
    ]
    for name, item_id, level, extra in checks:
        path = Path(run) / name
        if path.is_file():
            add(item_id, level, name, path)
    lag = _read_json(Path(run) / "lag-loop-report.json")
    if lag:
        gate = lag.get("gate") or {}
        clean = gate.get("clean") if isinstance(gate, dict) else None
        add("lag_gate", "E2" if clean is True else "E1", "lag-loop-report.json",
            Path(run) / "lag-loop-report.json", clean=clean)
    state_check = _read_json(Path(run) / "state-check.json")
    if state_check:
        add("state_check", "E2" if state_check.get("consistent") is True else "E1",
            "state-check.json", Path(run) / "state-check.json", consistent=state_check.get("consistent"))
    intent = _read_json(Path(run) / "publish-intent.json")
    if intent:
        add("publish_intent", "E1", "publish-intent.json", Path(run) / "publish-intent.json")
    live_gate = _read_json(Path(run) / "gate" / "live-gate.json")
    if live_gate:
        add("live_gate", "E2" if live_gate.get("status") == "pass" else "E1",
            "gate/live-gate.json", Path(run) / "gate" / "live-gate.json", status=live_gate.get("status"))
    verification = _read_json(Path(run) / "http-verification.json")
    if verification:
        add("http_verification", "E5" if verification.get("ok") is True else "E1",
            "http-verification.json", Path(run) / "http-verification.json", ok=verification.get("ok"))
    return rows


def _agent_state(run: Path) -> dict | None:
    data = _read_json(status_dir(run) / AGENT_FILE)
    if not data:
        return None
    fields = ("state", "tool", "updatedAt", "lastEventAt", "message")
    return {key: data[key] for key in fields if key in data}


def derive_snapshot(run: Path, *, index: Path | None = None, entry: dict | None = None,
                    locale: str | None = None, now: Callable[[], Any] | None = None) -> dict:
    """Pure-ish derivation; reads files only, never writes the snapshot."""
    started = time.monotonic()
    now_value = utc_now(now)
    clock = (lambda: now_value)
    run = Path(run).resolve()
    if entry is None:
        entry, entry_locale, index_path = entry_for_run(run, index)
        locale = locale or entry_locale
    else:
        index_path = resolve_index(index, run)
    decisions = _read_json(run / "decisions.json")
    locale = locale or infer_locale(run, decisions)
    locales = set((entry or {}).get("locales") or decisions.get("locales") or [])
    if locale:
        locales.add(locale)
    all_locales = locales | set(DEFAULT_LOCALES)
    journal_events, journal_issues = _journal_events(run)
    status_events, status_issues = _status_events(run)
    issues = journal_issues + status_issues
    combined = journal_events + status_events
    # Stable ordering: journal transitions first, then status events in append order.
    # Real callers use microsecond timestamps, but tests and fast scripts can emit
    # several events inside one second; random event ids must not reorder them.
    for order, event in enumerate(journal_events):
        event["_order"] = order
    for order, event in enumerate(status_events):
        event["_order"] = order
    combined.sort(key=lambda event: (parse_time(event["at"]),
                                     0 if event["source"] == "journal" else 1,
                                     int(event.get("_order", 0))))
    stages: dict[str, dict] = {}
    for event in combined:
        _apply_event(stages, event, all_locales)
    speakers = _read_speakers(run)
    derived = _derive_artifacts(run, stages, locale, all_locales, speakers)
    derived += _derive_deepseek_states(run, stages, locale, all_locales, clock)
    for stage in stages.values():
        _finish_stage(stage, clock)
    required = _required_stages(run, stages, locale, all_locales, decisions, speakers)
    attention = _attention_items(run, stages, required["missing"], clock, required["all"])
    publish = bool(decisions.get("publish"))
    run_state = _run_state(stages, attention, required, publish)
    last_at = max((event["at"] for event in combined), default=None)
    last_age = round(age_seconds(last_at, clock), 1) if last_at else None
    heartbeat_ages = [stage.get("heartbeatAgeSeconds") for stage in stages.values()
                      if stage["state"] == "running" and stage.get("heartbeatAgeSeconds") is not None]
    snapshot = {
        "schemaVersion": SCHEMA_SNAPSHOT,
        "productionId": (entry or {}).get("productionId") or run.name,
        "runId": run.name,
        "locale": locale,
        "generatedAt": now_value,
        "startedAt": combined[0]["at"] if combined else None,
        "runState": run_state,
        "stalled": any(stage.get("stalled") for stage in stages.values()),
        "freshness": {
            "ageSeconds": last_age,
            "heartbeatAgeSeconds": round(min(heartbeat_ages), 1) if heartbeat_ages else last_age,
            "state": ("unknown" if last_age is None else "fresh" if last_age <= 120 else "stale"),
        },
        "source": {
            "journalEvents": len(journal_events),
            "statusEvents": len(status_events),
            "derived": derived,
            "index": str(index_path),
        },
        "decisions": {
            key: decisions.get(key) for key in ("form", "sync", "publish", "title", "locales")
            if decisions.get(key) is not None
        },
        "stages": sorted(stages.values(), key=lambda stage: (stage["phase"], stage["id"])),
        "attention": attention,
        "required": required,
        "deliverables": _deliverables(run),
        "agent": _agent_state(run),
        "recent": [
            {key: event[key] for key in ("at", "type", "stage", "source", "progress", "message",
                                         "waitingOn", "evidenceLevel", "errorClass")
             if event.get(key) is not None}
            for event in combined[-20:]
        ],
        "issues": issues,
        "projection": {"rebuildSeconds": round(time.monotonic() - started, 3), "redacted": False},
    }
    return snapshot


def rebuild_run(run: Path, *, index: Path | None = None, now: Callable[[], Any] | None = None) -> dict:
    snapshot = derive_snapshot(run, index=index, now=now)
    _write_json(status_path(run), snapshot)
    return snapshot


def build_production(production: str | None = None, *, index: Path | None = None,
                     now: Callable[[], Any] | None = None) -> dict:
    index_path = resolve_index(index)
    data = load_index(index_path)
    productions = data.get("productions", {})
    if production is None:
        if len(productions) != 1:
            raise ValueError("multiple productions in the index; pass --production")
        production = next(iter(productions))
    entry = productions.get(production)
    if not entry:
        raise ValueError(f"unknown production: {production}")
    runs = []
    for locale, ref in (entry.get("runs") or {}).items():
        run = _resolve_ref(ref, index_path)
        if not run.exists():
            continue
        snapshot = derive_snapshot(run, index=index_path, entry=entry, locale=locale if locale != "default" else None, now=now)
        runs.append(snapshot)
    stages, attention, deliverables, missing = [], [], [], []
    for snapshot in runs:
        for stage in snapshot["stages"]:
            stages.append({**stage, "runId": snapshot["runId"], "locale": snapshot.get("locale")})
        for item in snapshot["attention"]:
            attention.append({**item, "runId": snapshot["runId"]})
        for item in snapshot["deliverables"]:
            deliverables.append({**item, "runId": snapshot["runId"]})
        for item in snapshot["required"].get("missing", []):
            missing.append(f"{snapshot['runId']}:{item}")
    if any(item.get("severity") in ("attention", "timeSensitive", "critical") for item in attention):
        run_state = "attention_required"
    elif any(snapshot["runState"] in ("active", "attention_required") for snapshot in runs):
        run_state = "active"
    elif runs and all(snapshot["runState"] == "completed" for snapshot in runs):
        run_state = "completed"
    else:
        run_state = "planned"
    ages = [snapshot["freshness"]["ageSeconds"] for snapshot in runs
            if snapshot["freshness"].get("ageSeconds") is not None]
    snapshot = {
        "schemaVersion": SCHEMA_SNAPSHOT,
        "kind": "production",
        "productionId": production,
        "generatedAt": utc_now(now),
        "runState": run_state,
        "stalled": any(snapshot.get("stalled") for snapshot in runs),
        "freshness": {
            "ageSeconds": round(max(ages), 1) if ages else None,
            "state": ("unknown" if not ages else "fresh" if max(ages) <= 120 else "stale"),
        },
        "entry": {key: entry.get(key) for key in ("pageId", "title", "form", "sync", "publish", "locales")},
        "runs": [
            {
                "runId": snapshot["runId"], "locale": snapshot.get("locale"),
                "runState": snapshot["runState"], "stalled": snapshot.get("stalled"),
                "activeStage": next((stage["id"] for stage in snapshot["stages"]
                                     if stage["state"] in ("running", "waiting")), None),
                "heartbeatAgeSeconds": snapshot["freshness"].get("heartbeatAgeSeconds"),
                "attentionCount": len(snapshot.get("attention") or []),
            }
            for snapshot in runs
        ],
        "stages": sorted(stages, key=lambda stage: (stage.get("locale") or "", stage["phase"], stage["id"])),
        "attention": attention,
        "required": {"missing": missing},
        "deliverables": deliverables,
        "issues": [issue for snapshot in runs for issue in snapshot.get("issues", [])],
        "projection": {"runs": len(runs), "redacted": False},
    }
    _write_json(index_path.parent / ".status" / f"{production}.json", snapshot)
    return snapshot


def check_snapshot(run: Path, *, index: Path | None = None,
                   now: Callable[[], Any] | None = None) -> dict:
    on_disk = _read_json(status_path(run))
    # Replay at the snapshot's own generation time: ages/stall are derived from the clock,
    # so comparing them against "now" would make every check drift. The event facts must match.
    replay_now = (lambda: on_disk["generatedAt"]) if on_disk.get("generatedAt") else now
    rebuilt = derive_snapshot(run, index=index, now=replay_now)
    keys = ("runState", "stalled", "stages", "attention", "required", "deliverables")
    consistent = bool(on_disk) and all(
        json.dumps(on_disk.get(key), sort_keys=True, ensure_ascii=False) ==
        json.dumps(rebuilt.get(key), sort_keys=True, ensure_ascii=False) for key in keys)
    report = {
        "schemaVersion": "sentence-first-status-check-v1",
        "run": on_disk.get("runId") or Path(run).name,
        "consistent": consistent,
        "checkedAt": utc_now(now),
        "keys": list(keys),
        "onDiskGeneratedAt": on_disk.get("generatedAt"),
        "rebuiltGeneratedAt": rebuilt.get("generatedAt"),
    }
    if not consistent and on_disk:
        report["mismatches"] = [key for key in keys
                                if json.dumps(on_disk.get(key), sort_keys=True, ensure_ascii=False) !=
                                json.dumps(rebuilt.get(key), sort_keys=True, ensure_ascii=False)]
    return report


def _fmt_progress(progress: dict | None) -> str:
    if not progress:
        return ""
    done, total = progress.get("done"), progress.get("total")
    unit = progress.get("unit") or "units"
    if total:
        return f"{done}/{total} {unit}"
    return f"{done if done is not None else '?'} {unit} (total unknown)"


def render_run(snapshot: dict) -> str:
    lines = [
        f"{snapshot.get('runId')}  state={snapshot.get('runState')}"
        f"  stalled={'yes' if snapshot.get('stalled') else 'no'}"
        f"  fresh={snapshot.get('freshness', {}).get('state')}"
        f"  age={snapshot.get('freshness', {}).get('ageSeconds')}s"
        f"  locale={snapshot.get('locale') or '?'}",
    ]
    for stage in snapshot.get("stages", []):
        if stage["state"] == "pending":
            continue
        bits = [f"{stage['phase']} {stage['id']}", stage["state"]]
        progress = _fmt_progress(stage.get("progress"))
        if progress:
            bits.append(progress)
        if stage.get("unitsDone") is not None:
            bits.append(f"unitsDone={stage['unitsDone']}")
        if stage.get("heartbeatAgeSeconds") is not None:
            bits.append(f"hb={stage['heartbeatAgeSeconds']}s")
        if stage.get("stalled"):
            bits.append(f"STALLED+{stage.get('stalledSeconds')}s")
        if stage.get("etaSeconds") is not None:
            bits.append(f"eta={stage['etaSeconds']}s/{stage.get('etaSource') or '?'}")
        if stage.get("waitingAgeSeconds") is not None:
            bits.append(f"waiting={stage['waitingAgeSeconds']}s")
        if stage.get("evidenceLevel"):
            bits.append(stage["evidenceLevel"])
        if stage.get("source"):
            bits.append(f"[{stage['source']}]")
        lines.append("  " + "  ".join(str(bit) for bit in bits))
    if snapshot.get("attention"):
        lines.append("attention:")
        for item in snapshot["attention"]:
            detail = "  ".join(str(item[key]) for key in ("kind", "stage", "severity", "ageSeconds")
                               if item.get(key) is not None)
            if item.get("waitingOn"):
                detail += f"  waitingOn={item['waitingOn']}"
            if item.get("resume"):
                detail += f"  resume={item['resume']}"
            lines.append("  " + detail)
    missing = snapshot.get("required", {}).get("missing") or []
    if missing:
        lines.append("missing required: " + ", ".join(missing))
    if snapshot.get("deliverables"):
        lines.append("deliverables: " + "  ".join(
            f"{item['id']}={item['evidenceLevel']}" for item in snapshot["deliverables"]))
    return "\n".join(lines)


def render_production(snapshot: dict) -> str:
    lines = [f"production {snapshot.get('productionId')}  state={snapshot.get('runState')}"
             f"  fresh={snapshot.get('freshness', {}).get('state')}"
             f"  stalled={'yes' if snapshot.get('stalled') else 'no'}"]
    for run in snapshot.get("runs", []):
        lines.append(f"  {run.get('locale') or '?'}  {run.get('runId')}  {run.get('runState')}"
                     f"  active={run.get('activeStage') or '-'}"
                     f"  hb={run.get('heartbeatAgeSeconds')}s  attention={run.get('attentionCount')}")
    if snapshot.get("attention"):
        lines.append("attention:")
        for item in snapshot["attention"]:
            lines.append("  " + "  ".join(str(item[key]) for key in
                                           ("runId", "kind", "stage", "severity", "ageSeconds")
                                           if item.get(key) is not None))
    return "\n".join(lines)


def wrap_command(run: Path, stage: str, command: list[str], *, heartbeat_seconds: float = 15.0,
                 evidence_level: str | None = None, message: str | None = None,
                 error_class: str = "process") -> int:
    """Run a command while emitting started/heartbeat/finished or failed."""
    if not command:
        raise ValueError("wrap needs a command after --")
    attempt = next_attempt(run, stage)
    safe_mark(run, stage, "started", attempt=attempt, source="wrap", message=message)
    stop = threading.Event()

    interval = max(1.0, float(heartbeat_seconds))

    def heartbeat() -> None:
        while not stop.wait(interval):
            safe_mark(run, stage, "heartbeat", attempt=attempt, source="wrap", message=message)

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        process = subprocess.Popen(command)
    except OSError as exc:
        stop.set()
        thread.join(timeout=1)
        safe_mark(run, stage, "failed", attempt=attempt, source="wrap",
                  error_class="process", message=f"could not start command: {exc}",
                  resume=" ".join(command))
        return 127
    try:
        code = process.wait()
    except KeyboardInterrupt:
        process.terminate()
        try:
            code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            code = -15
        stop.set()
        thread.join(timeout=1)
        safe_mark(run, stage, "failed", attempt=attempt, source="wrap",
                  error_class="interrupted", message="interrupted", resume=" ".join(command))
        return 130
    stop.set()
    thread.join(timeout=1)
    if code == 0:
        safe_mark(run, stage, "finished", attempt=attempt, source="wrap",
                  evidence_level=evidence_level, message=message)
    else:
        safe_mark(run, stage, "failed", attempt=attempt, source="wrap",
                  error_class=error_class, message=f"exit {code}", resume=" ".join(command))
    return int(code)




# ---------------------------------------------------------------- notifications (P2)

def _safe_text(value: Any, limit: int = 300) -> str:
    """Sanitize a local message before it leaves the Mac for Bark."""
    text = str(value or "").strip()
    text = re.sub(r"(?:/Users|/home|/private|/var/folders)/[^\s,;]+", "<path>", text)
    text = re.sub(r"artifacts/[^\s,;]+", "<artifact>", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{6,}", "<key>", text)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _safe_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text.startswith(("http://", "https://")):
        return None
    host = (urlsplit(text).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return None
    return text


def _duration(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        return "未知"
    minutes, sec = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h{minutes:02d}m"
    return f"{minutes}m{sec:02d}s"


def _human_review_copy(stage: str, waiting_on: str | None, expected: str | None,
                       age_seconds: Any) -> tuple[str, str]:
    """Stage-specific copy; not every human handoff is a track listening review."""
    waiting = waiting_on or "等待用户"
    expected_text = f"预计 {expected}" if expected else "预计时间见计划"
    body = f"{waiting} · 已等 {_duration(age_seconds)} · {expected_text}"
    if stage.startswith("l3.review."):
        locale = stage.split(".")[-1] if "." in stage else ""
        return f"[同行] 可审 · {locale} 轨" if locale else "[同行] 可审 · 整轨", body + "；回到电脑打开播放器"
    if stage == "l1.english-review":
        return "[同行] 待批准 · 英文来源", body + "；打开英文审核表"
    if stage == "l1.speakers":
        return "[同行] 待确认 · 讲员映射", body + "；核对低一致度句子"
    if stage.startswith("l4.publish"):
        return "[同行] 待授权 · 页面发布", body + "；在对话里确认后继续"
    if stage.startswith("l4.study"):
        return "[同行] 待批准 · 学习内容", body + "；审阅大纲与默想"
    return f"[同行] 需你处理 · {stage}", body


def _candidate(key: str, kind: str, level: str, title: str, body: str,
               *, url: str | None = None, since: str | None = None,
               cooldown_seconds: float | None = None) -> dict:
    return {"key": key, "kind": kind, "level": level, "title": title,
            "body": _safe_text(body, 500), "url": _safe_url(url),
            "since": since, "cooldownSeconds": cooldown_seconds}


def notification_candidates(snapshot: dict) -> list[dict]:
    """Policy: start, human-review handoff, failure, stall, missing step, completion."""
    run_id = snapshot.get("runId") or "run"
    production = snapshot.get("productionId") or run_id
    decisions = snapshot.get("decisions") or {}
    candidates: list[dict] = []
    started_at = snapshot.get("startedAt")
    run_state = snapshot.get("runState")
    if started_at and run_state in ("planned", "active", "attention_required"):
        title = decisions.get("title") or production
        locales = "/".join(decisions.get("locales") or []) or "?"
        mode_parts = []
        if decisions.get("form"):
            mode_parts.append(str(decisions["form"]))
        if decisions.get("sync") is not None:
            mode_parts.append("sync" if decisions.get("sync") else "no-sync")
        if decisions.get("publish") is not None:
            mode_parts.append("publish" if decisions.get("publish") else "no-publish")
        mode = "/".join(mode_parts)
        candidates.append(_candidate(
            f"start:{run_id}", "started", "passive",
            f"[同行] 开工 · {title}",
            f"{run_id} · {locales} · {mode or '形态未记录'}；状态页：run_status.py status",
            since=started_at))
    for item in snapshot.get("attention") or []:
        kind = item.get("kind")
        severity = item.get("severity")
        if severity not in ("attention", "timeSensitive", "critical"):
            continue
        stage = item.get("stage") or "?"
        if kind == "human_review":
            title, body = _human_review_copy(stage, item.get("waitingOn"),
                                             item.get("expectedMinutes"), item.get("ageSeconds"))
            candidates.append(_candidate(
                f"review:{run_id}:{stage}:{item.get('since')}", "human_review", "active",
                title, body, url=item.get("actionUrl"), since=item.get("since")))
        elif kind == "failed":
            unknown = item.get("errorClass") == "unknown_outcome"
            body = f"{item.get('errorClass') or 'failed'}"
            if item.get("message"):
                body += f" · {item['message']}"
            if item.get("resume"):
                body += f" · 续跑：{item['resume']}"
            candidates.append(_candidate(
                f"failed:{run_id}:{stage}:{item.get('since')}", "failed",
                "critical" if unknown else "timeSensitive",
                f"[同行] 失败 · {stage}", body, since=item.get("since")))
        elif kind == "stalled":
            candidates.append(_candidate(
                f"stalled:{run_id}:{stage}", "stalled", "timeSensitive",
                f"[同行] 可能卡住 · {stage}",
                f"最后心跳 {_duration(item.get('ageSeconds'))} 前 · 期望 {_duration(item.get('heartbeatExpectedSeconds'))}"
                "；先查进程/SSH/GPU，不要自动重启整条队列",
                since=item.get("since"), cooldown_seconds=900))
        elif kind == "missing_required":
            candidates.append(_candidate(
                f"missing:{run_id}:{stage}", "missing_required", "active",
                f"[同行] 缺步骤 · {stage}", f"{stage} 已到期但没有记录；补跑或确认是否被静默跳过",
                since=item.get("since")))
    if run_state == "completed":
        evidence = ", ".join(f"{item.get('id')}={item.get('evidenceLevel')}"
                             for item in (snapshot.get("deliverables") or [])[:8])
        candidates.append(_candidate(
            f"complete:{run_id}", "completed", "active",
            f"[同行] 完成 · {run_id}",
            "已到完成状态；证据级别：" + (evidence or "见 status.json") + "。设备/现场验收仍单独记录。",
            since=snapshot.get("generatedAt")))
    return candidates


def _sent_ledger(run: Path) -> dict[str, dict]:
    path = status_dir(run) / NOTIFY_SENT_FILE
    if not path.is_file():
        return {}
    ledger = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("key"):
            ledger[row["key"]] = row
    return ledger


def _record_sent(run: Path, candidate: dict, now: Callable[[], Any] | None) -> None:
    _append_line(status_dir(run) / NOTIFY_SENT_FILE, {
        "schemaVersion": "sentence-first-notify-sent-v1",
        "at": utc_now(now), "key": candidate["key"], "kind": candidate["kind"],
        "level": candidate["level"], "title": candidate["title"],
    })


def notify_run(run: Path, *, notifier=None, execute: bool = False,
               index: Path | None = None, now: Callable[[], Any] | None = None,
               cooldown_seconds: float = 900) -> dict:
    """Plan (dry-run) or send the notifications for one run; returns a redacted plan."""
    run = Path(run)
    snapshot = derive_snapshot(run, index=index, now=now)
    candidates = notification_candidates(snapshot)
    ledger = _sent_ledger(run)
    plan, sent, skipped, failed = [], [], [], []
    now_value = utc_now(now)
    for candidate in candidates:
        key = candidate["key"]
        previous = ledger.get(key)
        if previous:
            if candidate.get("cooldownSeconds"):
                try:
                    last = parse_time(previous["at"])
                    if (parse_time(now_value) - last).total_seconds() < float(candidate["cooldownSeconds"]):
                        skipped.append({**candidate, "reason": "cooldown"})
                        continue
                except (KeyError, ValueError):
                    pass
            else:
                skipped.append({**candidate, "reason": "already-sent"})
                continue
        plan.append(candidate)
        if not execute:
            continue
        if notifier is None:
            failed.append({**candidate, "reason": "no-notifier"})
            continue
        message = notify_transport.Message(
            candidate["title"], candidate["body"], candidate["level"], candidate.get("url"))
        results = notifier.send(message)
        if notify_transport.delivered(results):
            sent.append({**candidate, "results": results})
            try:
                _record_sent(run, candidate, now)
            except OSError as exc:
                print(f"run_status: could not record notification dedupe: {exc}", file=sys.stderr)
        else:
            failed.append({**candidate, "results": results})
    return {"run": run.name, "plan": plan, "sent": sent, "skipped": skipped, "failed": failed}


def notify_production(production: str, *, notifier=None, execute: bool = False,
                      index: Path | None = None, now: Callable[[], Any] | None = None,
                      cooldown_seconds: float = 900) -> dict:
    index_path = resolve_index(index)
    data = load_index(index_path)
    entry = (data.get("productions") or {}).get(production)
    if not entry:
        raise ValueError(f"unknown production: {production}")
    results = []
    for locale, ref in (entry.get("runs") or {}).items():
        run = _resolve_ref(ref, index_path)
        if run.exists():
            results.append(notify_run(run, notifier=notifier, execute=execute, index=index_path,
                                      now=now, cooldown_seconds=cooldown_seconds))
    return {"production": production, "runs": results}


def _default_notifier(*, service: str | None = None, group: str | None = None,
                      bark_url: str | None = None, accounts: list[str] | None = None,
                      push: bool = True):
    if notify_transport is None:
        raise ValueError("tools/ops/notify.py is unavailable")
    keys = notify_transport.keychain_keys(tuple(accounts or notify_transport.ACCOUNTS),
                                          service=service or notify_transport.SERVICE)
    return notify_transport.Notifier(
        keys, bark_url=bark_url or notify_transport.BARK_URL,
        group=group or notify_transport.GROUP, push=push)


def _render_notify_plan(result: dict) -> str:
    lines = []
    for run in result.get("runs", [result]):
        lines.append(f"{run.get('run') or run.get('production')}: "
                     f"plan={len(run.get('plan') or [])} sent={len(run.get('sent') or [])} "
                     f"skipped={len(run.get('skipped') or [])} failed={len(run.get('failed') or [])}")
        for item in run.get("plan") or []:
            lines.append(f"  [{item['level']}] {item['title']} — {item['body']}")
        for item in run.get("failed") or []:
            lines.append(f"  FAILED {item['title']}: {item.get('reason') or item.get('results')}")
    return "\n".join(lines)
# ---------------------------------------------------------------- CLI

def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--index", type=Path, help="status index path (default: artifacts/sentence-first-agent/.status-index.json)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register", help="register a run in the production index")
    register.add_argument("--run", type=Path, required=True)
    register.add_argument("--production")
    register.add_argument("--page-id")
    register.add_argument("--locale")
    register.add_argument("--locales", nargs="*")
    register.add_argument("--form", choices=("full", "clip"))
    register.add_argument("--title")
    group = register.add_mutually_exclusive_group()
    group.add_argument("--sync", action="store_true", default=None)
    group.add_argument("--no-sync", action="store_true", default=None)
    pub = register.add_mutually_exclusive_group()
    pub.add_argument("--publish", action="store_true", default=None)
    pub.add_argument("--no-publish", action="store_true", default=None)
    _common(register)

    mark = commands.add_parser("mark", help="append one stage event")
    mark.add_argument("--run", type=Path, required=True)
    mark.add_argument("--stage", required=True)
    mark.add_argument("--event", required=True,
                      choices=(*JOURNAL_EVENTS, "progress", "heartbeat", "skipped"))
    mark.add_argument("--attempt", type=int)
    mark.add_argument("--unit")
    mark.add_argument("--done", type=int)
    mark.add_argument("--total", type=int)
    mark.add_argument("--eta-seconds", type=float)
    mark.add_argument("--message")
    mark.add_argument("--waiting-on")
    mark.add_argument("--kind", choices=("human", "external"))
    mark.add_argument("--source", default="cli")
    mark.add_argument("--evidence-level", choices=EVIDENCE_LEVELS)
    mark.add_argument("--error-class")
    mark.add_argument("--resume")
    mark.add_argument("--action-url")
    mark.add_argument("--expected-minutes")
    mark.add_argument("--heartbeat-expected-seconds", type=int)

    wrap = commands.add_parser("wrap", help="run a command with started/heartbeat/finished status")
    wrap.add_argument("--run", type=Path, required=True)
    wrap.add_argument("--stage", required=True)
    wrap.add_argument("--heartbeat-seconds", type=float, default=15.0)
    wrap.add_argument("--evidence-level", choices=EVIDENCE_LEVELS)
    wrap.add_argument("--message")
    wrap.add_argument("--error-class", default="process")
    wrap.add_argument("wrapped_command", nargs=argparse.REMAINDER)

    handoff = commands.add_parser("handoff", help="record that a stage was handed to the user")
    handoff.add_argument("--run", type=Path, required=True)
    handoff.add_argument("--stage", required=True)
    handoff.add_argument("--waiting-on", required=True)
    handoff.add_argument("--url")
    handoff.add_argument("--expected-minutes")
    handoff.add_argument("--kind", choices=("human", "external"), default="human")

    resume = commands.add_parser("resume", help="close a waiting stage")
    resume.add_argument("--run", type=Path, required=True)
    resume.add_argument("--stage", required=True)
    resume.add_argument("--message")

    rebuild = commands.add_parser("rebuild", help="rebuild status/status.json")
    rebuild.add_argument("--run", type=Path, required=True)
    rebuild.add_argument("--json", action="store_true")
    _common(rebuild)

    status = commands.add_parser("status", help="show a run or production snapshot")
    status.add_argument("--run", type=Path)
    status.add_argument("--production")
    status.add_argument("--watch", type=float, metavar="SECONDS")
    status.add_argument("--json", action="store_true")
    _common(status)

    production = commands.add_parser("production", help="build and write a production snapshot")
    production.add_argument("--production")
    production.add_argument("--json", action="store_true")
    _common(production)

    check = commands.add_parser("check", help="compare the on-disk snapshot with a replay")
    check.add_argument("--run", type=Path, required=True)
    check.add_argument("--record", action="store_true", help="write status/status-check.json")
    check.add_argument("--json", action="store_true")
    _common(check)

    notify = commands.add_parser("notify", help="plan or send Bark notifications for a run/production")
    notify.add_argument("--run", type=Path)
    notify.add_argument("--production")
    notify.add_argument("--execute", action="store_true", help="send; default is a dry run")
    notify.add_argument("--watch", type=float, metavar="SECONDS")
    notify.add_argument("--cooldown-seconds", type=float, default=900)
    notify.add_argument("--keychain-service")
    notify.add_argument("--group")
    notify.add_argument("--bark-url")
    notify.add_argument("--account", action="append", dest="accounts")
    notify.add_argument("--no-push", action="store_true", help="print instead of sending")
    notify.add_argument("--test", action="store_true", help="send one test message")
    notify.add_argument("--json", action="store_true")
    _common(notify)
    return parser


def _latest_input_mtime(run: Path) -> float:
    run = Path(run)
    paths = [run / "journal.ndjson", status_dir(run) / EVENTS_FILE, run / "decisions.json",
             status_dir(run) / AGENT_FILE]
    for pattern in ("state-*.json", "speech.jsonl", "translations.jsonl", "review.mp3",
                    "review-player.html", "track.wav", "lag-loop-report.json", "state-check.json",
                    "publish-intent.json", "gate/live-gate.json", "http-verification.json"):
        paths.extend(run.glob(pattern))
    return max((path.stat().st_mtime for path in paths if path.is_file()), default=0.0)


def _snapshot_or_build(run: Path, index: Path | None, now: Callable[[], Any] | None = None) -> dict:
    path = status_path(run)
    now_value = utc_now(now)
    if path.is_file():
        snapshot = _read_json(path)
        generated = snapshot.get("generatedAt")
        fresh_enough = bool(generated) and age_seconds(generated, lambda: now_value) <= 30
        if fresh_enough and path.stat().st_mtime >= _latest_input_mtime(run):
            return snapshot
    return rebuild_run(run, index=index, now=(lambda: now_value))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "register":
            if args.sync and args.no_sync:
                raise ValueError("--sync and --no-sync are mutually exclusive")
            if args.publish and args.no_publish:
                raise ValueError("--publish and --no-publish are mutually exclusive")
            entry = register_run(
                args.run, production=args.production, page_id=args.page_id, locale=args.locale,
                form=args.form, title=args.title, locales=args.locales,
                sync=True if args.sync else False if args.no_sync else None,
                publish=True if args.publish else False if args.no_publish else None,
                index=args.index,
            )
            print(json.dumps(entry, ensure_ascii=False, indent=1))
            return 0
        if args.command == "mark":
            event = mark_event(
                args.run, args.stage, args.event, attempt=args.attempt, unit=args.unit,
                done=args.done, total=args.total, eta_seconds=args.eta_seconds,
                message=args.message, waiting_on=args.waiting_on, kind=args.kind,
                source=args.source, evidence_level=args.evidence_level,
                error_class=args.error_class, resume=args.resume,
                action_url=args.action_url, expected_minutes=args.expected_minutes,
                heartbeat_expected_seconds=args.heartbeat_expected_seconds,
            )
            print(json.dumps(event, ensure_ascii=False))
            return 0
        if args.command == "wrap":
            command = list(args.wrapped_command)
            if command and command[0] == "--":
                command = command[1:]
            return wrap_command(args.run, args.stage, command,
                                heartbeat_seconds=args.heartbeat_seconds,
                                evidence_level=args.evidence_level, message=args.message,
                                error_class=args.error_class)
        if args.command == "handoff":
            event = mark_event(args.run, args.stage, "waiting", waiting_on=args.waiting_on,
                               kind=args.kind, action_url=args.url, expected_minutes=args.expected_minutes,
                               source="agent")
            print(json.dumps(event, ensure_ascii=False))
            return 0
        if args.command == "resume":
            event = mark_event(args.run, args.stage, "resumed", message=args.message, source="agent")
            print(json.dumps(event, ensure_ascii=False))
            return 0
        if args.command == "rebuild":
            snapshot = rebuild_run(args.run, index=args.index)
            print(json.dumps(snapshot, ensure_ascii=False, indent=1) if args.json else
                  f"{status_path(args.run)}  state={snapshot['runState']}")
            return 0
        if args.command == "status":
            if args.watch:
                try:
                    while True:
                        snapshot = (_snapshot_or_build(args.run, args.index) if args.run
                                    else build_production(args.production, index=args.index))
                        print("\033[2J\033[H" + (json.dumps(snapshot, ensure_ascii=False, indent=1) if args.json
                                                  else render_production(snapshot) if snapshot.get("kind") == "production"
                                                  else render_run(snapshot)), flush=True)
                        time.sleep(max(1.0, args.watch))
                except KeyboardInterrupt:
                    return 0
            if args.run:
                snapshot = _snapshot_or_build(args.run, args.index)
                print(json.dumps(snapshot, ensure_ascii=False, indent=1) if args.json else render_run(snapshot))
                return 0
            if args.production:
                snapshot = build_production(args.production, index=args.index)
                print(json.dumps(snapshot, ensure_ascii=False, indent=1) if args.json else render_production(snapshot))
                return 0
            data = load_index(args.index)
            for name, entry in sorted(data.get("productions", {}).items()):
                print(f"{name}  locales={','.join(entry.get('locales') or [])}  active={entry.get('active')}")
            return 0
        if args.command == "production":
            snapshot = build_production(args.production, index=args.index)
            print(json.dumps(snapshot, ensure_ascii=False, indent=1) if args.json else
                  f"state={snapshot['runState']}  runs={len(snapshot['runs'])}")
            return 0
        if args.command == "check":
            report = check_snapshot(args.run, index=args.index)
            if args.record:
                _write_json(status_dir(args.run) / CHECK_FILE, report)
            print(json.dumps(report, ensure_ascii=False, indent=1) if args.json else
                  ("consistent" if report["consistent"] else "MISMATCH: " + ", ".join(report.get("mismatches", []))))
            return 0 if report["consistent"] else 1
        if args.command == "notify":
            notifier = _default_notifier(service=args.keychain_service, group=args.group,
                                         bark_url=args.bark_url, accounts=args.accounts,
                                         push=not args.no_push)
            execute = bool(args.execute and not args.no_push)
            if args.test:
                if notify_transport is None:
                    raise ValueError("tools/ops/notify.py is unavailable")
                message = notify_transport.Message("[同行] 测试通知", "production progress notification test",
                                                   "active")
                if not args.execute:
                    print(f"test notification would be sent to {sorted(notifier.keys)}; pass --execute")
                    return 0
                results = notifier.send(message)
                print(json.dumps(results, ensure_ascii=False, indent=1) if args.json else
                      f"test notification: {results}")
                if args.no_push:
                    return 0
                return 0 if notify_transport.delivered(results) else 1
            if not (args.run or args.production):
                raise ValueError("notify needs --run or --production")
            def once():
                if args.run:
                    return notify_run(args.run, notifier=notifier, execute=execute,
                                      index=args.index, cooldown_seconds=args.cooldown_seconds)
                return notify_production(args.production, notifier=notifier, execute=execute,
                                         index=args.index, cooldown_seconds=args.cooldown_seconds)
            if args.watch:
                try:
                    while True:
                        result = once()
                        print(_render_notify_plan(result) if not args.json else
                              json.dumps(result, ensure_ascii=False, indent=1), flush=True)
                        time.sleep(max(5.0, args.watch))
                except KeyboardInterrupt:
                    return 0
            result = once()
            print(json.dumps(result, ensure_ascii=False, indent=1) if args.json else _render_notify_plan(result))
            failed = (result.get("failed") or []) if "failed" in result else [
                item for run in result.get("runs", []) for item in run.get("failed", [])]
            return 0 if not failed else 1
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"run_status: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
