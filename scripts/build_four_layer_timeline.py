#!/usr/bin/env python3
"""Build a read-only weekly timeline from the progress and timing ledgers.

Tracker state intervals are not execution measurements. The report keeps them
separate from accounting spans and from the synthetic Dev rehearsal spans.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import four_layer_measure, four_layer_progress, sermon_accounting


def iso(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def dependencies(steps: dict) -> dict[str, list[str]]:
    """Only formal gates and publication order, not guessed runtime scheduling."""
    result: dict[str, list[str]] = {}
    for key, state in steps.items():
        locale = state.get("locale")
        layer = state.get("layer")
        number = key.split("-", 1)[1].split("@", 1)[0]
        dep: list[str] = []
        if layer == 1 and number in {"02", "03"}:
            dep = ["L1-01"]
        elif layer == 1 and number == "04":
            dep = ["L1-01", "L1-02", "L1-03"]
        elif layer == 2 and number == "02":
            dep = ["L1-04", f"L2-01@{locale}"]
        elif layer == 2 and number == "03":
            dep = [f"L2-02@{locale}"]
        elif layer == 2 and number == "04":
            dep = [f"L2-03@{locale}"]
        elif layer == 3 and number == "01":
            dep = [f"L2-04@{locale}"]
        elif layer == 3 and number in {"02", "03", "04", "05", "06"}:
            dep = [f"L3-{int(number)-1:02d}@{locale}"]
        elif layer == 4 and number == "01":
            dep = [f"L2-04@{locale}", f"L3-06@{locale}"]
        elif layer == 4 and number in {"02", "03", "04"}:
            dep = [f"L4-{int(number)-1:02d}@{locale}"]
        result[key] = [item for item in dep if item in steps]
    return result


def production_data(ledger: dict, events: list[dict]) -> dict:
    audit = four_layer_measure.timing_audit(ledger, events)
    audited = {row["step"]: row for row in audit["rows"]}
    history = [event for event in ledger.get("history", [])
               if event.get("action") == "update" and event.get("step") in ledger["steps"]]
    history.sort(key=lambda event: event.get("at", ""))
    by_step: dict[str, list[dict]] = {key: [] for key in ledger["steps"]}
    for event in history:
        if iso(event.get("at")):
            by_step[event["step"]].append(event)
    rows = []
    for key, step in ledger["steps"].items():
        transitions = by_step[key]
        intervals = []
        marks = []
        for index, event in enumerate(transitions):
            start = iso(event["at"])
            status = event["status"]
            if index and transitions[index - 1]["status"] == status:
                continue
            next_event = next((other for other in transitions[index + 1:]
                               if other["status"] != status), None)
            if status in {"running", "waiting_review", "blocked"} and next_event:
                end = iso(next_event["at"])
                if end and seconds(start, end) >= 0:
                    intervals.append({"start": start, "end": end, "kind": status,
                                      "seconds": seconds(start, end)})
            if status == "complete":
                marks.append(start)
        attempts = []
        for item in audited[key]["attemptHistory"]:
            start, end = iso(item.get("startedAt")), iso(item.get("finishedAt"))
            if start and end and seconds(start, end) >= 0:
                attempts.append({"start": start, "end": end, "kind": "measured",
                                 "status": item["status"], "seconds": seconds(start, end)})
        rows.append({"id": key, "label": step["title"], "layer": step["layer"],
                     "locale": step.get("locale"), "status": step["status"],
                     "intervals": intervals, "attempts": attempts,
                     "completedAt": marks[-1] if marks else None})
    return {"label": "9/27 正式制作", "kind": "production", "pageId": ledger["pageId"],
            "rows": rows, "dependencies": dependencies(ledger["steps"]),
            "coverage": {"steps": len(rows), "measured": audit["measuredStepCount"],
                         "missingCompleted": audit["completedWithoutMeasuredExecutionCount"]},
            "note": "状态条表示账本在该段时间显示 running／等待审核／阻塞；只有实测执行条是程序耗时。完成点不反推开始时间。"}


def simulation_data(log: dict) -> dict:
    if log.get("schemaVersion") != "sermon-dev-four-layer-timing-log-v1":
        raise ValueError("unsupported simulation timing log")
    groups: dict[str, list[dict]] = {}
    for event in log.get("events", []):
        start, end = iso(event.get("startedAt")), iso(event.get("finishedAt"))
        if not start or not end or seconds(start, end) < 0:
            continue
        name = event.get("name")
        if not isinstance(name, str):
            continue
        locale = event.get("locale")
        # Nested unit/cue and parent stage spans are both shown, never summed.
        unit = event.get("unitId") or event.get("textGroupId")
        key = (name + ("@" + locale if isinstance(locale, str) else "")
               + ("#" + unit if isinstance(unit, str) else ""))
        groups.setdefault(key, []).append({"start": start, "end": end,
                                            "seconds": seconds(start, end),
                                            "unit": unit})
    rows = []
    for key, spans in groups.items():
        name = key.split("@", 1)[0].split("#", 1)[0]
        layer = int(name[5]) if name.startswith("layer") and name[5:6] in "1234" else 0
        rows.append({"id": key, "label": name + (" · " + key.split("#", 1)[1] if "#" in key else ""),
                     "layer": layer,
                     "locale": key.split("@", 1)[1].split("#", 1)[0] if "@" in key else None,
                     "status": "simulation_only", "intervals": [],
                     "attempts": [{**span, "kind": "measured", "status": "completed"}
                                  for span in spans], "completedAt": None})
    return {"label": "9/28 Dev 模拟片段", "kind": "simulation", "pageId": log.get("pageId"),
            "rows": rows, "dependencies": {},
            "coverage": {"events": len(log.get("events", [])), "groups": len(rows)},
            "note": "模拟复用已批准的片段与音频；这些毫秒数不代表整篇翻译、配音或人工审核的生产耗时。父阶段与单元子阶段重叠，不相加。"}


def build_report(ledger_path: Path, simulation_path: Path | None) -> dict:
    ledger = four_layer_progress.load(ledger_path)
    accounting_dir = ledger_path.parent / "accounting"
    events, damaged = sermon_accounting.read_events(accounting_dir) if (accounting_dir / "events.jsonl").exists() else ([], [])
    modes = [production_data(ledger, events)]
    if simulation_path:
        modes.append(simulation_data(json.loads(simulation_path.read_text())))
    return {"schemaVersion": "sermon-four-layer-timeline-v1", "modes": modes,
            "damagedAccountingRows": len(damaged),
            "source": {"ledger": str(ledger_path), "simulation": str(simulation_path) if simulation_path else None}}


def render_html(report: dict) -> str:
    payload = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    template = Path(__file__).with_name("four_layer_timeline_template.html").read_text()
    return template.replace("__TIMELINE_DATA__", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--simulation", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = build_report(args.ledger, args.simulation)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(report))
    print(json.dumps({"output": str(args.out), "modes": [mode["label"] for mode in report["modes"]],
                      "coverage": [mode["coverage"] for mode in report["modes"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
