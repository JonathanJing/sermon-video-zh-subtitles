#!/usr/bin/env python3
"""Project the private frontend reports into numbers a public weekly report may carry.

``services/feedback/admin.mjs`` writes three private reports (``usage``,
``listening``, ``alignment``), each a ``summary.json``. They hold per-session
timelines and small counts about a small congregation, so they stay out of Git:
the reports go to the private evidence store, and only this projection goes
into the weekly rollup.

The projection keeps aggregates only and applies a small-count rule: a count
from 1 to 4 is written as ``"<5"``, a rate is written only when its denominator
is at least 5, and a time total only when at least 5 sessions stand behind it.
Session timelines, per-session rows and free text never leave the private
report. Coverage limits (truncated queries, dropped events, capped sessions)
are carried so a reader does not take the numbers for complete traffic.

Usage (repo root):

    # one step: export the three private reports for the service week (admin
    # credentials; writes under ignored artifacts/), keep them in the private
    # store as frontend/<week>/, and write the projection next to them
    (cd services/feedback && npm ci)
    .venv/bin/python tools/development/weekly_frontend.py export --week 20261115
    # or project reports that already exist (for example pulled from the store)
    .venv/bin/python tools/development/weekly_frontend.py project artifacts/frontend/20261115 --out frontend-metrics.json

``weekly_rollup.py build --frontend <frontend-metrics.json>`` reads the projection.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FEEDBACK = ROOT / "services" / "feedback"
# The feedback database's project (docs/sermon-app-usage.zh.md); not a secret.
DEFAULT_PROJECT = "ai-for-god-caption-dev"
SCHEMA = "sermon-weekly-frontend-metrics-v1"
SMALL = 5
REPORTS = {"usage": "sermon-private-usage-report-v1", "listening": "sermon-private-listening-report-v1",
           "alignment": "sermon-private-alignment-report-v1"}
# Player position actions: where listeners adjust the clock points at a sentence, not at a person.
POSITION_ACTIONS = {
    "nudge": {"nudge_back_1_click", "nudge_back_quarter_click", "nudge_forward_quarter_click", "nudge_forward_1_click"},
    "skip": {"back_5_click", "forward_5_click"},
}
POSITION_BIN_SECONDS = 60
TOP = 12


def small(value):
    """0 stays 0, 1–4 becomes "<5", larger counts stay; anything that is not a count becomes None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return 0
    return f"<{SMALL}" if value < SMALL else (int(value) if float(value).is_integer() else round(value, 3))


def rate(numerator, denominator):
    if not isinstance(numerator, (int, float)) or not isinstance(denominator, (int, float)) or denominator < SMALL:
        return None
    return round(numerator / denominator, 3)


def _coverage(report: dict, **extra) -> dict:
    query = report.get("query") or {}
    return {"truncated": bool(query.get("truncated")), "documentsRead": query.get("documentsRead"), **extra}


def usage_metrics(report: dict) -> dict:
    totals = report.get("totals") or {}
    funnel = report.get("funnel") or {}
    opens = funnel.get("appOpenSessions", 0)
    plays = funnel.get("appOpenAndPlaySessions", 0)
    downloads = funnel.get("appOpenAndPlayAndDownloadSessions", 0)
    positions: dict[str, Counter] = {group: Counter() for group in POSITION_ACTIONS}
    for session in report.get("sessions") or []:
        for event in session.get("events") or []:
            second = event.get("positionSeconds")
            if not isinstance(second, (int, float)) or not event.get("week"):
                continue
            for group, actions in POSITION_ACTIONS.items():
                if event.get("action") in actions:
                    positions[group][(event["week"], int(second // POSITION_BIN_SECONDS))] += 1
    hot = {group: [{"week": week, "minute": minute, "events": count}
                   for (week, minute), count in sorted(bins.items(), key=lambda item: (-item[1], item[0]))
                   if count >= SMALL][:TOP]
           for group, bins in positions.items()}
    return {
        "totals": {key: small(totals.get(key)) for key in ("sessions", "browserDays", "appOpens", "events")},
        "funnel": {"appOpenSessions": small(opens), "playSessions": small(plays), "downloadSessions": small(downloads),
                   "playRateOfOpens": rate(plays, opens), "downloadRateOfPlays": rate(downloads, plays)},
        "daily": [{"day": row.get("day"), "anonymousBrowsers": small(row.get("anonymousBrowsers")),
                   "sessions": small(row.get("sessions"))} for row in report.get("daily") or []],
        "peakHours": [{"hour": row.get("hour"), "activeSessionHours": small(row.get("activeSessionHours"))}
                      for row in sorted(report.get("hourly") or [], key=lambda r: -(r.get("activeSessionHours") or 0))[:3]
                      if (row.get("activeSessionHours") or 0) > 0],
        "actions": [{"key": row.get("key"), "sessions": small(row.get("sessions")), "events": small(row.get("events"))}
                    for row in (report.get("actions") or [])[:TOP * 2]],
        "voices": [{"key": row.get("key"), "sessions": small(row.get("sessions"))} for row in (report.get("voices") or [])[:TOP]],
        "positionHotspots": hot,
        "coverage": _coverage(report, sessionsWithDroppedEvents=small(totals.get("sessionsWithDroppedEvents")),
                              cappedSessions=small(totals.get("cappedSessions")),
                              sessionsWithoutBrowserId=small(totals.get("sessionsWithoutBrowserId"))),
    }


def _listening_row(row: dict) -> dict:
    qualified = row.get("qualifiedSessions") or 0
    seconds = row.get("listenedSeconds")
    return {"sessions": small(row.get("sessions")), "qualifiedSessions": small(qualified),
            "deviceDays": small(row.get("deviceDays")),
            "listenedHours": round(seconds / 3600, 2) if isinstance(seconds, (int, float)) and qualified >= SMALL else None,
            "completionRate": rate(row.get("completedSessions") or 0, qualified)}


def listening_metrics(report: dict) -> dict:
    keys = ("contentLocale", "audioLocale", "platform")
    return {
        "totals": _listening_row(report.get("totals") or {}),
        "groups": [{**{key: row.get(key) for key in keys}, **_listening_row(row)} for row in report.get("groups") or []],
        "pages": [{**{key: row.get(key) for key in ("week", "pageId", *keys)}, **_listening_row(row)}
                  for row in report.get("weeks") or []],
        "interfaceByContent": [{**{key: row.get(key) for key in ("interfaceLocale", *keys)}, **_listening_row(row)}
                               for row in report.get("crossTab") or []],
        "coverage": _coverage(report, ignoredRecords=small((report.get("totals") or {}).get("ignoredRecords"))),
    }


def _alignment_row(row: dict) -> dict:
    return {"presses": small(row.get("presses")), "recorded": small(row.get("recorded")),
            "matched": small(row.get("matched")), "applied": small(row.get("applied")),
            "devices": small(row.get("devices")),
            "jumpRateOfRecorded": rate(row.get("applied") or 0, row.get("recorded") or 0),
            "jumpRateOfPresses": rate(row.get("applied") or 0, row.get("presses") or 0)}


def alignment_metrics(report: dict) -> dict:
    totals = report.get("totals") or {}
    shadow = report.get("shadow") or {}
    timing = report.get("appliedTotalMs") or {}
    enough = (totals.get("applied") or 0) >= SMALL
    return {
        "totals": _alignment_row(totals),
        "outcomes": {key: small(value) for key, value in sorted((report.get("outcomes") or {}).items())},
        "noMatchReasons": {key: small(value) for key, value in sorted((report.get("reasons") or {}).items())},
        "fractionBands": {key: small(value) for key, value in sorted((report.get("fractionBands") or {}).items())},
        "errorCodes": {key: small(value) for key, value in sorted((report.get("errorCodes") or {}).items())},
        "byLocale": {key: _alignment_row(row) for key, row in sorted((report.get("byLocale") or {}).items())},
        "byPlatform": {key: _alignment_row(row) for key, row in sorted((report.get("byPlatform") or {}).items())},
        "byPage": {key: _alignment_row(row) for key, row in sorted((report.get("byPage") or {}).items())},
        "appliedTotalMs": {"p50": timing.get("p50") if enough else None, "p95": timing.get("p95") if enough else None},
        "shadow": {"evaluated": small(shadow.get("evaluated")), "rescued": small(shadow.get("rescued"))},
        "coverage": _coverage(report, ignoredRecords=small(report.get("ignoredRecords")),
                              ignoredAttempts=small(report.get("ignoredAttempts"))),
    }


PROJECTIONS = {"usage": usage_metrics, "listening": listening_metrics, "alignment": alignment_metrics}


def find_summary(directory: Path, kind: str) -> Path | None:
    """``<dir>/<kind>/summary.json``, or the newest ``<dir>/*<kind>*/summary.json``."""
    direct = directory / kind / "summary.json"
    if direct.is_file():
        return direct
    matches = sorted(p for p in directory.glob(f"*{kind}*/summary.json") if p.is_file())
    return matches[-1] if matches else None


def build(directory: Path) -> dict:
    """Read the private reports under ``directory`` and return the public-safe metrics."""
    result: dict = {"schemaVersion": SCHEMA, "smallCountRule": f"1 到 {SMALL - 1} 写成 <{SMALL}；分母不足 {SMALL} 不算比例",
                    "range": None, "reports": {}, "missing": []}
    for kind, schema in REPORTS.items():
        path = find_summary(Path(directory), kind)
        if path is None:
            result["missing"].append(kind)
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if report.get("schemaVersion") != schema:
            raise ValueError(f"{path} is not a {schema} report")
        window = report.get("range") or {}
        if result["range"] is None:
            result["range"] = {"from": window.get("from"), "to": window.get("to")}
        elif result["range"] != {"from": window.get("from"), "to": window.get("to")}:
            raise ValueError(f"{path} covers {window.get('from')}..{window.get('to')}, not {result['range']}")
        result["reports"][kind] = {"generatedAt": report.get("generatedAt"), **PROJECTIONS[kind](report)}
    return result


def export_week(week: str, *, out_root: Path, store_uri: str | None = None, store: bool = True,
                project: str | None = None, runner=subprocess.run) -> dict:
    """Run the three private exports for the service week, keep them in the private store, project them."""
    sunday = datetime.strptime(week, "%Y%m%d").date()
    first, last = (sunday - timedelta(days=6)).isoformat(), sunday.isoformat()
    target = Path(out_root) / week
    if target.exists():
        raise ValueError(f"{target} already exists; the private exporter only writes new directories")
    if not (FEEDBACK / "node_modules").is_dir():
        raise ValueError(f"install the report tool first: (cd {FEEDBACK.relative_to(ROOT)} && npm ci)")
    target.mkdir(parents=True)
    env = {**os.environ, "GOOGLE_CLOUD_PROJECT": project or os.environ.get("GOOGLE_CLOUD_PROJECT") or DEFAULT_PROJECT}
    for kind in REPORTS:
        done = runner(["node", str(FEEDBACK / "admin.mjs"), kind, "--from", first, "--to", last,
                       "--out", str(target / kind)], env=env, capture_output=True, text=True)
        if done.returncode != 0:
            raise ValueError(f"{kind} export failed: {(done.stderr or done.stdout).strip()[-300:]}")
    stored = None
    if store:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.ops import evidence_store
        target_store = evidence_store.open_store(store_uri)
        problems = target_store.check()
        if problems:
            raise ValueError(f"{target_store.uri} must not hold private evidence: " + "; ".join(problems))
        stored = evidence_store.put_directory(target_store, target, f"frontend/{week}")
    metrics = build(target)
    path = target / "frontend-metrics.json"
    path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"week": week, "range": metrics["range"], "metrics": str(path), "stored": (stored or {}).get("store"),
            "missing": metrics["missing"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("project", help="project existing private reports")
    p.add_argument("directory", type=Path, help="directory holding usage/, listening/ and alignment/ reports")
    p.add_argument("--out", type=Path, help="write the metrics here (default: stdout)")
    p = sub.add_parser("export", help="export the week's private reports, store them privately, project them")
    p.add_argument("--week", required=True, help="the service Sunday, YYYYMMDD")
    p.add_argument("--out-root", type=Path, default=ROOT / "artifacts/frontend")
    p.add_argument("--store", help="private evidence store (default: evidence_store.py's)")
    p.add_argument("--no-store", action="store_true", help="keep the private reports on this machine only")
    p.add_argument("--project", help=f"Firestore project (default: $GOOGLE_CLOUD_PROJECT or {DEFAULT_PROJECT})")
    args = parser.parse_args(argv)
    try:
        if args.command == "export":
            print(json.dumps(export_week(args.week, out_root=args.out_root, store_uri=args.store,
                                         store=not args.no_store, project=args.project), ensure_ascii=False))
            return 0
        metrics = build(args.directory)
    except (OSError, ValueError) as error:
        print(f"weekly_frontend: {error}", file=sys.stderr)
        return 1
    text = json.dumps(metrics, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"{args.out}: {', '.join(metrics['reports']) or 'no reports'}"
              + (f"; missing {', '.join(metrics['missing'])}" if metrics["missing"] else ""))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
