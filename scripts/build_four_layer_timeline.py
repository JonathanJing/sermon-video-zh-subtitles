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

# These are measurement lanes within existing checkpoints, not new production
# layers or approval gates. Prefixes match current accounting.stage names where
# implemented; the others are explicit future instrumentation slots.
SUBSTEPS = {
    "L1-02": [
        ("transcribe", "英文转写", "可按音频段并行", "layer1.transcribe"),
        ("align", "词级对齐", "按已冻结段并行", "layer1.align"),
        ("freeze", "文本与对齐轴冻结", "汇合后串行", "layer1.freeze"),
    ],
    "L1-03": [
        ("anchors", "分句与锚点", "按父句并行", "layer1.anchors"),
        ("boundary_check", "停顿与边界检查", "按风险片段并行", "layer1.boundary_check"),
    ],
    "L2-02": [
        ("group", "翻译组整体", "不同组可并行", "layer2.group."),
        ("translator", "Astra 初译", "不同组可并行", "layer2.translator."),
        ("reviewer", "Sol 独立复核", "同组依赖初译；不同组可并行", "layer2.reviewer."),
        ("repair", "失败组修订与重试", "仅受影响组", "layer2.repair."),
    ],
    "L2-03": [
        ("coverage", "覆盖与结构检查", "按组并行", "layer2.coverage"),
        ("language", "语言／经文检查", "按组并行", "layer2.language_check"),
        ("admission", "候选准入", "汇合后串行", "layer2.admission"),
    ],
    "L3-02": [
        ("inputs", "输入物化与验证", "各语言独立", "layer3.materialize_inputs"),
        ("validate", "身份／策略验证", "各语言独立", "layer3.validate_inputs"),
        ("model_load", "音色模型加载", "每个运行资源池计一次", "layer3.model_load."),
        ("render_units", "单元渲染整体", "包含单元子跨度，不能相加", "layer3.render_units"),
        ("unit", "逐单元合成／复用", "先实测 GPU 资源后定并发数", "layer3.unit."),
        ("assemble", "音轨组装", "本语言单元汇合后", "layer3.assemble"),
    ],
    "L3-03": [
        ("decode", "逐单元完整解码", "按单元并行", "layer3.decode."),
        ("hash", "音频哈希与收据", "按单元并行", "layer3.hash."),
        ("asr", "回转写筛查", "按单元并行", "layer3.asr."),
    ],
    "L3-04": [
        ("schedule", "时间排程与偏差", "本语言单元汇合后", "layer3.schedule"),
        ("captions", "字幕 cue", "排程后", "layer3.captions"),
        ("mix", "完整音轨编码", "排程后", "layer3.mix"),
    ],
    "L4-02": [
        ("build", "清单与资产构建", "各语言独立", "layer4.build"),
        ("upload", "资产上传", "逐文件可并行；限制并发", "layer4.upload."),
    ],
    "L4-03": [
        ("get", "逐资产 GET／哈希", "逐文件可并行", "layer4.http_get."),
        ("range", "音频／视频 Range", "逐语言可并行", "layer4.http_range."),
    ],
}

SUBSTEP_DEPENDENCIES = {
    "L1-02": {"align": ["transcribe"], "freeze": ["align"]},
    "L1-03": {"boundary_check": ["anchors"]},
    "L2-02": {"reviewer": ["translator"], "repair": ["reviewer"]},
    "L2-03": {"admission": ["coverage", "language"]},
    "L3-02": {"validate": ["inputs"], "model_load": ["validate"],
               "unit": ["model_load"], "assemble": ["unit"]},
    "L3-03": {"hash": ["decode"], "asr": ["decode"]},
    "L3-04": {"captions": ["schedule"], "mix": ["schedule"]},
    "L4-02": {"upload": ["build"]},
}

def iso(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.isoformat() if parsed.tzinfo else None
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


def nested_spans(audit: dict, events: list[dict]) -> dict[str, list[dict]]:
    """Return complete child spans linked to a same-identity measured step.

    The audit supplies trusted root IDs. A same-name stage from another ledger,
    or a stage merely close in time, never gets attached to this release.
    """
    roots = {attempt["spanId"]: row["step"] for row in audit["rows"]
             for attempt in row["attemptHistory"] if isinstance(attempt.get("spanId"), str)}
    starts: dict[str, dict] = {}
    duplicate_starts: set[str] = set()
    finishes: dict[str, list[dict]] = {}
    for event in events:
        span_id = event.get("spanId")
        if not isinstance(span_id, str):
            continue
        if event.get("event") == "stage_started":
            if span_id in starts:
                duplicate_starts.add(span_id)
            else:
                starts[span_id] = event
        elif event.get("event") == "stage_finished":
            finishes.setdefault(span_id, []).append(event)

    def root_for(span_id: str) -> str | None:
        seen = set()
        current = span_id
        while current and current not in seen:
            seen.add(current)
            if current in roots:
                return roots[current]
            current = starts.get(current, {}).get("parentSpanId")
        return None

    result: dict[str, list[dict]] = {}
    for span_id, start_event in starts.items():
        if span_id in roots or span_id in duplicate_starts or len(finishes.get(span_id, [])) != 1:
            continue
        step = root_for(span_id)
        finish = finishes[span_id][0]
        start, end = iso(start_event.get("startedAt")), iso(finish.get("recordedAt"))
        if (step is None or not start or not end or seconds(start, end) < 0
                or start_event.get("stage") != finish.get("stage")
                or finish.get("status") not in {"completed", "failed"}):
            continue
        result.setdefault(step, []).append({"stage": start_event["stage"],
                                            "start": start, "end": end,
                                            "seconds": seconds(start, end),
                                            "status": finish["status"],
                                            "cacheHit": bool(start_event.get("cacheHit"))})
    return result


def substep_rows(step_id: str, spans: list[dict]) -> list[dict]:
    template = step_id.split("@", 1)[0]
    definitions = SUBSTEPS.get(template, [])
    rows = []
    matched: set[int] = set()
    for code, label, parallel, prefix in definitions:
        selected = []
        for index, span in enumerate(spans):
            if index not in matched and span["stage"].startswith(prefix):
                selected.append(span)
                matched.add(index)
        rows.append({"id": f"{step_id}/{code}", "label": label, "parallel": parallel,
                     "dependsOn": [f"{step_id}/{item}" for item in
                                   SUBSTEP_DEPENDENCIES.get(template, {}).get(code, [])],
                     "attempts": [{**span, "kind": "measured"} for span in selected]})
    for index, span in enumerate(spans):
        if index not in matched:
            rows.append({"id": f"{step_id}/other-{index}", "label": span["stage"],
                         "parallel": "未分类，须检查实际资源与依赖",
                         "dependsOn": [],
                         "attempts": [{**span, "kind": "measured"}]})
    return rows


def production_data(ledger: dict, events: list[dict]) -> dict:
    audit = four_layer_measure.timing_audit(ledger, events)
    audited = {row["step"]: row for row in audit["rows"]}
    children = nested_spans(audit, events)
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
                     "completedAt": marks[-1] if marks else None,
                     "substeps": substep_rows(key, children.get(key, []))})
    planned_substeps = sum(len(row["substeps"]) for row in rows)
    measured_substeps = sum(bool(item["attempts"]) for row in rows for item in row["substeps"])
    return {"label": "正式制作", "kind": "production", "pageId": ledger["pageId"],
            "rows": rows, "dependencies": dependencies(ledger["steps"]),
            "coverage": {"steps": len(rows), "measured": audit["measuredStepCount"],
                         "missingCompleted": audit["completedWithoutMeasuredExecutionCount"],
                         "plannedSubsteps": planned_substeps, "measuredSubsteps": measured_substeps},
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
    return {"label": "Dev 模拟片段", "kind": "simulation", "pageId": log.get("pageId"),
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
