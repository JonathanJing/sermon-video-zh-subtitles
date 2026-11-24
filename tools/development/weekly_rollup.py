#!/usr/bin/env python3
"""Weekly rollup: one reviewable summary of a week's run reports, with last week's actions checked.

A week leaves several run reports (the Sunday page, the podcast, hot fixes,
experiments), each with its own retrospective. Nobody reviews ten PRs, the
improvements written in them never reached the backlog, and nothing checked
next week whether a fix worked. This tool builds the weekly layer:

``build`` reads the run reports of one service week under
``docs/reports/runs/``, computes fixed metrics from their copied evidence
(journals, deploy attempts, gate results, retrospective tables), evaluates the
actions accepted in the previous rollup against this week's numbers, lists the
improvements the retrospectives proposed, and writes
``docs/reports/weekly/<YYYYMMDD>/weekly.json`` plus a ``WEEKLY.md`` skeleton.
The numbers are computed here; an agent or a person only writes the narrative.

``finalize`` reads the decisions a reviewer wrote into ``WEEKLY.md`` (accept,
reject or defer each candidate; mark each repeat as rework or change) and
stores them in ``weekly.json``, so next week's ``build`` can check them.

The rollup is machine-generated: ``humanApproval`` stays false until the
reviewed PR merges, and a merged rollup approves only the decisions written in
it. Every week is named by its Sunday (the service date) and covers the seven
days ending on it.

Usage (repo root):

    python3 tools/development/weekly_rollup.py build --week 20261115
    python3 tools/development/weekly_rollup.py finalize --week 20261115
    # private rollup with frontend numbers: built outside Git, kept in the private evidence store
    python3 tools/development/weekly_rollup.py build --week 20261115 --frontend artifacts/frontend/20261115/frontend-metrics.json \
        --weekly-root artifacts/weekly-private
    .venv/bin/python tools/ops/evidence_store.py put artifacts/weekly-private/20261115 --dest weekly/20261115

Frontend numbers are private operating data: pass ``--frontend`` only for the
private rollup unless the maintainer has decided the aggregated numbers may be
public. ``build`` and ``finalize`` need only the standard library.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.development import run_journal  # noqa: E402

SCHEMA = "sermon-weekly-rollup-v1"
REPORTS_ROOT = ROOT / "docs/reports/runs"
WEEKLY_ROOT = ROOT / "docs/reports/weekly"
REPORT_NAME = re.compile(r"(\d{8})-.+")
PLACEHOLDER = "待填写"
# Written by tools/ops/evidence_store.py index: which runs the private store holds (names and hashes only).
EVIDENCE_INDEX = "private-evidence-index.json"
PRODUCTION_STAGES = ("l3.", "l4.")
TIMINGS = (("preflight", "预检"), ("afterResources", "占用资源后"), ("afterPublish", "发布后"))
DECISIONS = {"接受": "accept", "accept": "accept", "拒绝": "reject", "reject": "reject", "推迟": "defer", "defer": "defer"}
REPEAT_KINDS = {"返工": "rework", "rework": "rework", "变更": "change", "change": "change"}
SIGNAL = re.compile(r"`?\s*([A-Za-z][A-Za-z0-9.]*)\s*(<=|>=|==|<|>)\s*(-?\d+(?:\.\d+)?)\s*`?")
RESULTS = {"effective": "生效", "no_effect": "无效", "regressed": "退步", "not_exercised": "本周没走到"}
CANDIDATE_HEADERS = ["编号", "来源", "类别", "改进", "依据", "决定", "backlog ID", "验证信号"]
REPEAT_HEADERS = ["报告", "阶段", "重跑次数", "重复轮次计算", "归类"]
METRIC_LABELS = {
    "reports.total": "运行报告数", "reports.production": "其中生产运行",
    "time.wallSeconds": "生产墙钟", "time.computeSeconds": "生产计算", "time.waitingSeconds": "生产等待",
    "time.reworkSeconds": "重复轮次计算", "time.reworkShare": "重复轮次占计算比",
    "publish.deployAttempts": "托管部署次数", "publish.maxDeployAttemptsPerReport": "单份报告最多部署次数",
    "publish.failedGateEvents": "发布阶段失败事件", "publish.gateFail": "发布门禁未通过份数",
    "errors.total": "复盘登记的错误", "errors.preflight": "预检发现", "errors.afterResources": "占用资源后发现",
    "errors.afterPublish": "发布后发现", "errors.lateShare": "晚发现占比",
    "collection.unstructuredReports": "无 manifest 的报告", "collection.reportsWithoutJournal": "缺 journal 的报告",
    "collection.retrospectiveUnfilled": "复盘未填完", "collection.withoutPrivateEvidence": "未上传私有证据",
    "cost.estimatedMicrousd": "估算费用（微美元）",
    "frontend.usage.sessions": "前端会话", "frontend.usage.playRateOfOpens": "打开后播放比例",
    "frontend.listening.qualifiedSessions": "满 30 秒收听会话", "frontend.listening.deviceDays": "收听设备日",
    "frontend.listening.completionRate": "收听完成率", "frontend.alignment.presses": "听声定位触发",
    "frontend.alignment.jumpRateOfRecorded": "听声定位成功率",
}
SECONDS_METRICS = {"time.wallSeconds", "time.computeSeconds", "time.waitingSeconds", "time.reworkSeconds"}
SHARE_METRICS = {"time.reworkShare", "errors.lateShare", "frontend.usage.playRateOfOpens",
                 "frontend.listening.completionRate", "frontend.alignment.jumpRateOfRecorded"}


# ---------------------------------------------------------------- reading run reports

def parse_week(value: str) -> date:
    day = datetime.strptime(value, "%Y%m%d").date()
    if day.weekday() != 6:
        raise ValueError(f"--week must be a Sunday (the service date): {value} is not")
    return day


def latest_sunday(today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    return (today - timedelta(days=(today.weekday() + 1) % 7)).strftime("%Y%m%d")


def reports_in_week(reports_root: Path, week: date) -> list[Path]:
    first = week - timedelta(days=6)
    found = []
    for path in sorted(Path(reports_root).iterdir()) if Path(reports_root).is_dir() else []:
        match = REPORT_NAME.fullmatch(path.name)
        if not match or not path.is_dir():
            continue
        try:
            day = datetime.strptime(match[1], "%Y%m%d").date()
        except ValueError:
            continue
        if first <= day <= week:
            found.append(path)
    return found


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def tables(markdown: str) -> dict[str, list[dict[str, str]]]:
    """Each ``## heading``'s first Markdown table as rows keyed by header cell."""
    result: dict[str, list[dict[str, str]]] = {}
    heading, header = None, None
    for line in markdown.splitlines():
        if line.startswith("## "):
            heading, header = line[3:].strip(), None
            continue
        stripped = line.strip()
        if heading is None or not stripped.startswith("|"):
            if stripped and header is not None and heading in result:
                header = "closed"
            continue
        if header == "closed":
            continue
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", stripped.strip("|"))]
        if header is None:
            header = cells
            result.setdefault(heading, [])
        elif all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells if cell):
            continue
        else:
            result[heading].append(dict(zip(header, cells + [""] * (len(header) - len(cells)))))
    return result


def _section(found: dict[str, list[dict]], *keywords: str) -> list[dict]:
    for heading, rows in found.items():
        if any(keyword in heading for keyword in keywords):
            return rows
    return []


def _timing(text: str) -> str:
    hits = [key for key, word in TIMINGS if word in text]
    return hits[0] if len(hits) == 1 else "unknown"


def retrospective(report: Path) -> dict:
    path = report / "RETROSPECTIVE.md"
    if not path.is_file():
        return {"status": "missing", "errors": [], "improvements": []}
    text = path.read_text(encoding="utf-8")
    found = tables(text)
    structured = any("错误" in heading for heading in found) and any("改进" in heading for heading in found)
    errors = [{"stage": row.get("层／阶段", ""), "symptom": row.get("现象", ""), "timing": _timing(row.get("发现时机", "")),
               "fix": row.get("提交或 PR", "")}
              for row in _section(found, "错误") if PLACEHOLDER not in "".join(list(row.values())[:2])]
    improvements = [{"category": row.get("类别", ""), "improvement": row.get("改进", ""),
                     "evidence": next((v for k, v in row.items() if k.startswith("依据")), ""),
                     "expectedGain": row.get("预期收益", ""), "tracking": row.get("跟踪", "")}
                    for row in _section(found, "改进") if PLACEHOLDER not in row.get("改进", PLACEHOLDER)]
    unfilled = text.count(PLACEHOLDER)
    status = "unstructured" if not structured else "template" if unfilled >= 6 else "partial" if unfilled else "filled"
    return {"status": status, "unfilled": unfilled, "errors": errors, "improvements": improvements}


def stored_bundles(report: Path, labels: list[str], index: dict | None) -> int:
    """How many private bundles of this report the evidence index lists (by run label or report-name prefix)."""
    names = {row.get("runName") for row in (index or {}).get("runs") or []}
    return sum(1 for name in names if name and (name in labels or name == report.name
                                                or name.startswith(report.name + "-")))


def report_metrics(report: Path, index: dict | None = None) -> dict:
    """Everything the rollup reads from one run report directory."""
    manifest = _json(report / "manifest.json")
    structured = isinstance(manifest, dict) and isinstance(manifest.get("runs"), list)
    row: dict = {"name": report.name, "structured": structured, "runs": []}
    # Link the page that exists: some reports carry only a RETROSPECTIVE.md,
    # and the docs gate rejects a WEEKLY.md with a broken local link.
    row["entry"] = next((name for name in ("INDEX.md", "RETROSPECTIVE.md") if (report / name).is_file()), "")
    first_at, last_at = [], []
    totals = Counter()
    failed = Counter()
    repeats = []
    stage_names: set[str] = set()
    journals = sorted(report.rglob(run_journal.FILE_NAME))
    for journal in journals:
        try:
            state = run_journal.summary(journal.parent)
            events = run_journal.read(journal.parent)
        except ValueError:
            row.setdefault("problems", []).append(f"{journal.relative_to(report)}: unreadable journal")
            continue
        if not state["events"]:
            continue
        first_at.append(state["firstAt"])
        last_at.append(state["lastAt"])
        for key in ("computeSeconds", "waitingSeconds", "reworkSeconds"):
            totals[key] += state["totals"][key]
        stage_names.update(state["stages"])
        for event in events:
            if event["event"] == "failed":
                failed[event["stage"]] += 1
        for name, stage in state["stages"].items():
            if stage["rework"]:
                repeats.append({"run": journal.parent.relative_to(report).as_posix(), "stage": name,
                                "repeats": stage["rework"], "seconds": stage["reworkSeconds"]})
        row["runs"].append({"run": journal.parent.relative_to(report).as_posix(), "events": state["events"],
                            "openStages": state["openStages"]})
    row["hasJournal"] = bool(first_at)
    row["production"] = any(name.startswith(PRODUCTION_STAGES) for name in stage_names)
    if first_at:
        start, end = min(map(datetime.fromisoformat, first_at)), max(map(datetime.fromisoformat, last_at))
        row["time"] = {"firstAt": start.isoformat(), "lastAt": end.isoformat(),
                       "wallSeconds": round((end - start).total_seconds(), 3),
                       **{key: round(totals[key], 3) for key in ("computeSeconds", "waitingSeconds", "reworkSeconds")}}
    row["failedEvents"] = dict(sorted(failed.items()))
    row["repeats"] = sorted(repeats, key=lambda item: -item["seconds"])
    attempts = [(_json(path) or {}).get("status", "unreadable") for path in sorted(report.rglob("deployment-attempt*.json"))]
    gates = [_json(path) or {} for path in sorted(report.rglob("publish-gate.json"))]
    smokes = [(_json(path) or {}).get("status", "unreadable") for path in sorted(report.rglob("smoke-*.json"))]
    row["publish"] = {"deployAttempts": len(attempts), "deployStatuses": dict(Counter(attempts)),
                      "gateStatuses": [gate.get("status", "unreadable") for gate in gates],
                      "gateFailedChecks": sum(len(gate.get("failed") or []) for gate in gates),
                      "smokeStatuses": dict(Counter(smokes))}
    row["outcomes"] = dict(Counter(str((_json(path) or {}).get("status", "unreadable"))
                                   for path in sorted(report.rglob("outcome.json"))))
    budgets = [_json(path) or {} for path in sorted(report.rglob("source-budget.settlement.json"))]
    row["cost"] = {"estimatedMicrousd": sum(b.get("estimatedMicrousd") or 0 for b in budgets),
                   "requests": sum(b.get("requests") or 0 for b in budgets), "ledgers": len(budgets)}
    evidence = _json(report / "private-evidence.json") or {}
    labels = [str(run.get("label")) for run in manifest["runs"] if isinstance(run, dict)] if structured else []
    bundles = max(len(evidence.get("bundles") or []), stored_bundles(report, labels, index))
    row["privateEvidence"] = {"uploaded": bool(evidence.get("uploaded")) or bundles > 0, "bundles": bundles}
    row["retrospective"] = retrospective(report)
    return row


# ---------------------------------------------------------------- week metrics and actions

def _number(value) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def week_metrics(reports: list[dict], frontend: dict | None) -> dict:
    production = [r for r in reports if r["production"]]
    metrics: dict = {"reports.total": len(reports), "reports.production": len(production)}
    timed = [r["time"] for r in production if r.get("time")]
    if timed:
        for key in ("wallSeconds", "computeSeconds", "waitingSeconds", "reworkSeconds"):
            metrics[f"time.{key}"] = round(sum(t[key] for t in timed), 3)
        if metrics["time.computeSeconds"]:
            metrics["time.reworkShare"] = round(metrics["time.reworkSeconds"] / metrics["time.computeSeconds"], 3)
    attempts = [r["publish"]["deployAttempts"] for r in reports]
    if any(attempts):
        metrics["publish.deployAttempts"] = sum(attempts)
        metrics["publish.maxDeployAttemptsPerReport"] = max(attempts)
    if any(r["hasJournal"] for r in production):
        metrics["publish.failedGateEvents"] = sum(count for r in production for stage, count in r["failedEvents"].items()
                                                  if stage.startswith("l4."))
    gates = [status for r in reports for status in r["publish"]["gateStatuses"]]
    if gates:
        metrics["publish.gateFail"] = sum(status != "pass" for status in gates)
    errors = [e for r in reports for e in r["retrospective"]["errors"]]
    if any(r["retrospective"]["status"] in ("filled", "partial") for r in reports):
        metrics["errors.total"] = len(errors)
        for key, _ in TIMINGS:
            metrics[f"errors.{key}"] = sum(e["timing"] == key for e in errors)
        if errors:
            metrics["errors.lateShare"] = round(
                (metrics["errors.afterResources"] + metrics["errors.afterPublish"]) / len(errors), 3)
    metrics["collection.unstructuredReports"] = sum(not r["structured"] for r in reports)
    metrics["collection.reportsWithoutJournal"] = sum(not r["hasJournal"] for r in reports)
    metrics["collection.retrospectiveUnfilled"] = sum(
        r["retrospective"]["status"] in ("missing", "template", "partial") for r in reports)
    metrics["collection.withoutPrivateEvidence"] = sum(not r["privateEvidence"]["uploaded"] for r in reports)
    if any(r["cost"]["ledgers"] for r in reports):
        metrics["cost.estimatedMicrousd"] = sum(r["cost"]["estimatedMicrousd"] for r in reports)
    for key, value in frontend_numbers(frontend).items():
        metrics[key] = value
    return metrics


def frontend_numbers(frontend: dict | None) -> dict:
    """The numeric frontend headline values; suppressed small counts ("<5") are left out."""
    reports = (frontend or {}).get("reports") or {}
    picks = {
        "frontend.usage.sessions": (reports.get("usage") or {}).get("totals", {}).get("sessions"),
        "frontend.usage.playRateOfOpens": (reports.get("usage") or {}).get("funnel", {}).get("playRateOfOpens"),
        "frontend.listening.qualifiedSessions": (reports.get("listening") or {}).get("totals", {}).get("qualifiedSessions"),
        "frontend.listening.deviceDays": (reports.get("listening") or {}).get("totals", {}).get("deviceDays"),
        "frontend.listening.completionRate": (reports.get("listening") or {}).get("totals", {}).get("completionRate"),
        "frontend.alignment.presses": (reports.get("alignment") or {}).get("totals", {}).get("presses"),
        "frontend.alignment.jumpRateOfRecorded": (reports.get("alignment") or {}).get("totals", {}).get("jumpRateOfRecorded"),
    }
    return {key: value for key, value in picks.items() if _number(value) is not None}


def parse_signal(text: str) -> dict | None:
    match = SIGNAL.fullmatch(text.strip())
    return {"metric": match[1], "op": match[2], "value": float(match[3])} if match else None


def _holds(value: float, op: str, target: float) -> bool:
    return {"<=": value <= target, ">=": value >= target, "==": value == target,
            "<": value < target, ">": value > target}[op]


def evaluate(action: dict, metrics: dict) -> dict:
    """Check one accepted action's signal against this week's metrics."""
    signal = action.get("signal") or {}
    value = _number(metrics.get(signal.get("metric")))
    if value is None:
        return {"result": "not_exercised", "value": None}
    if _holds(value, signal["op"], signal["value"]):
        return {"result": "effective", "value": value}
    baseline = _number(action.get("baseline"))
    lower_is_better = signal["op"] in ("<=", "<")
    worse = baseline is not None and signal["op"] != "==" and (value > baseline if lower_is_better else value < baseline)
    return {"result": "regressed" if worse else "no_effect", "value": value}


def previous_rollup(weekly_root: Path, week: str) -> dict | None:
    earlier = sorted(p for p in Path(weekly_root).glob("*/weekly.json") if p.parent.name < week) \
        if Path(weekly_root).is_dir() else []
    return _json(earlier[-1]) if earlier else None


def build(week: str, *, reports_root: Path = REPORTS_ROOT, weekly_root: Path = WEEKLY_ROOT,
          frontend_path: Path | None = None, now: str | None = None) -> dict:
    day = parse_week(week)
    index = _json(Path(weekly_root) / EVIDENCE_INDEX)
    reports = [report_metrics(path, index) for path in reports_in_week(reports_root, day)]
    frontend = _json(frontend_path) if frontend_path else None
    if frontend_path and not isinstance(frontend, dict):
        raise ValueError(f"{frontend_path} is not a frontend metrics file (tools/development/weekly_frontend.py)")
    metrics = week_metrics(reports, frontend)
    previous = previous_rollup(weekly_root, week)
    actions = []
    for action in (previous or {}).get("actions") or []:
        if action.get("status") == "closed":
            continue
        check = evaluate(action, metrics)
        actions.append({**action, "status": "open",
                        "history": [*(action.get("history") or []), {"week": week, **check}]})
    candidates = []
    for report in reports:
        for item in report["retrospective"]["improvements"]:
            candidates.append({"id": f"C{len(candidates) + 1}", "report": report["name"], **item, "decision": None})
    return {
        "schemaVersion": SCHEMA, "week": week, "window": {"from": (day - timedelta(days=6)).isoformat(), "to": day.isoformat()},
        "generatedAt": now or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generatedBy": "tools/development/weekly_rollup.py", "humanApproval": False, "finalized": False,
        "previousWeek": (previous or {}).get("week"),
        "metrics": metrics, "previousMetrics": (previous or {}).get("metrics") or {},
        "reports": reports, "actions": actions, "candidates": candidates,
        "frontend": frontend,
    }


# ---------------------------------------------------------------- rendering

def _duration(seconds) -> str:
    if _number(seconds) is None:
        return "—"
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}h{minutes:02d}m" if hours else f"{minutes}m{secs:02d}s"


def _show(key: str, value) -> str:
    if _number(value) is None:
        return "—"
    if key in SECONDS_METRICS:
        return _duration(value)
    if key in SHARE_METRICS:
        return f"{value * 100:.1f}%"
    return f"{value:g}"


def _delta(key: str, value, before) -> str:
    if _number(value) is None or _number(before) is None:
        return "—"
    change = value - before
    if not change:
        return "持平"
    if key in SECONDS_METRICS:
        return ("+" if change > 0 else "-") + _duration(abs(change))
    if key in SHARE_METRICS:
        return f"{change * 100:+.1f} 个百分点"
    return f"{change:+g}"


def _cell(text) -> str:
    return str(text if text not in (None, "") else "—").replace("|", "\\|").replace("\n", " ")


def _table(headers: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers),
            *("| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows)]


def _signal_text(signal: dict | None) -> str:
    return f"`{signal['metric']} {signal['op']} {signal['value']:g}`" if signal else "—"


def render(weekly: dict) -> str:
    metrics, before = weekly["metrics"], weekly["previousMetrics"]
    reports = weekly["reports"]
    out = [f"# 周汇总：{weekly['week']}", "",
           f"服务周 {weekly['window']['from']} 至 {weekly['window']['to']}。本页由 `tools/development/weekly_rollup.py` "
           "从本周已入库的运行报告生成，数值来自 `weekly.json`；**机器生成，`humanApproval=false`**。"
           "审核人在本页写结论和决定，合并本 PR 即批准这些决定，不批准任何内容产物。", "",
           "## 结论", "",
           "<!-- 三句话：本周是否按时交付、最贵的一处重做、下周只做哪几条。只引用下面表里的数值。 -->", PLACEHOLDER + "。", "",
           "## 本周运行", ""]
    rows = []
    for r in reports:
        time = r.get("time") or {}
        publish = r["publish"]
        entry = r.get("entry", "INDEX.md")
        link = f"../../runs/{r['name']}/{entry}" if entry else f"../../runs/{r['name']}/"
        rows.append([f"[{r['name']}]({link})", "生产" if r["production"] else "其他",
                     _duration(time.get("wallSeconds")), _duration(time.get("computeSeconds")),
                     _duration(time.get("waitingSeconds")), _duration(time.get("reworkSeconds")),
                     publish["deployAttempts"] or "—", "／".join(publish["gateStatuses"]) or "—",
                     {"filled": "已填", "partial": f"缺 {r['retrospective'].get('unfilled')} 处", "template": "未填",
                      "missing": "缺失", "unstructured": "非骨架格式"}[r["retrospective"]["status"]],
                     f"已上传 {r['privateEvidence']['bundles']}" if r["privateEvidence"]["uploaded"] else "未上传"])
    out += _table(["报告", "类型", "墙钟", "计算", "等待", "重复轮次", "部署", "门禁", "复盘", "私有证据"], rows) if rows \
        else ["本周没有运行报告。"]
    out += ["", "墙钟取该报告所有 journal 的最早到最晚事件；没有 journal 的报告显示「—」，不是零。"
            "「重复轮次」是同一阶段再次启动后的计算时间，包含返工和变更，下面由审核人区分。", "",
            "## 对比上周", ""]
    if weekly.get("previousWeek"):
        keys = [key for key in METRIC_LABELS if key in metrics or key in before]
        out += _table(["指标", f"本周 {weekly['week']}", f"上周 {weekly['previousWeek']}", "变化"],
                      [[METRIC_LABELS[key], _show(key, metrics.get(key)), _show(key, before.get(key)),
                        _delta(key, metrics.get(key), before.get(key))] for key in keys])
        out += ["", "两周的来源长度和运行数不同时，时间类指标不能直接算提速比。"]
    else:
        out += _table(["指标", f"本周 {weekly['week']}"],
                      [[METRIC_LABELS[key], _show(key, metrics[key])] for key in METRIC_LABELS if key in metrics])
        out += ["", "没有更早的周汇总，本周是基线。"]
    out += ["", "## 上周改进项结果", ""]
    if weekly["actions"]:
        out += _table(["ID", "backlog", "改进", "验证信号", "基线", "本周数值", "结果"],
                      [[a["id"], a.get("backlogId"), a.get("title"), _signal_text(a.get("signal")),
                        _show(a["signal"]["metric"], a.get("baseline")),
                        _show(a["signal"]["metric"], a["history"][-1]["value"]),
                        RESULTS[a["history"][-1]["result"]]] for a in weekly["actions"]])
        out += ["", "「生效」只说明本周数值满足信号；连续生效后由审核人在 backlog 里关闭该项。「本周没走到」表示本周没有产生该指标。"]
    else:
        out += ["没有待验证的改进项。"]
    errors = [(r["name"], e) for r in reports for e in r["retrospective"]["errors"]]
    out += ["", "## 错误与发现时机", ""]
    if errors:
        words = dict(TIMINGS)
        out += _table(["报告", "层／阶段", "现象", "发现时机", "提交或 PR"],
                      [[name, e["stage"], e["symptom"], words.get(e["timing"], "未标明"), e["fix"]] for name, e in errors])
    else:
        out += ["本周的复盘没有登记错误，或复盘还没按骨架填写。"]
    repeats = [(r["name"], item) for r in reports for item in r["repeats"]]
    out += ["", "## 重复轮次：返工还是变更", "",
            "<!-- 审核人在「归类」填 返工 或 变更。用户改主意、口径变化造成的重做是变更，不算返工。 -->"]
    if repeats:
        out += _table(REPEAT_HEADERS, [[name, item["stage"], item["repeats"], _duration(item["seconds"]), ""]
                                       for name, item in repeats[:20]])
    else:
        out += ["本周的 journal 里没有重复启动的阶段。"]
    out += ["", "## 候选改进", "",
            "<!-- 审核人填后三列：决定写 接受／拒绝／推迟；接受的必须有 backlog ID 和验证信号，"
            "信号写成 `指标 比较符 数值`，指标名见 weekly.json 的 metrics。每周最多接受 3 条。可以自己加行。 -->"]
    out += _table(CANDIDATE_HEADERS, [[c["id"], c["report"], c["category"], c["improvement"], c["evidence"], "", "", ""]
                                      for c in weekly["candidates"]] or [["N1", "", "", PLACEHOLDER, "", "", "", ""]])
    out += ["", "## 前端", ""]
    out += render_frontend(weekly.get("frontend"))
    gaps = collection_gaps(weekly)
    out += ["", "## 采集缺口", ""] + ([f"- {gap}" for gap in gaps] or ["本周没有采集缺口。"])
    out += ["", "## 证据边界", "",
            "- 本页只汇总已入库的运行报告；不在仓库里的运行不在本页。",
            "- 代码与测试、发布与 HTTP、浏览器渲染、设备播放、场地验收是分开的状态；本页的数值不证明后两者。",
            "- 私有证据（译文、审核表、听审结论、反馈正文）在私有证据库，本页只引用计数和哈希。", ""]
    return "\n".join(out)


def render_frontend(frontend: dict | None) -> list[str]:
    if not frontend:
        return ["前端数值是私有运营资料，不进本页（[使用统计](../../../sermon-app-usage.zh.md)规定不提交 Git）。"
                "本周三份报表在私有证据库 `frontend/<周>/`，带前端数值的私有周汇总在 `weekly/<周>/`。审核人在此只写结论：",
                "", PLACEHOLDER + "。"]
    window = frontend.get("range") or {}
    reports = frontend.get("reports") or {}
    out = [f"范围 {window.get('from')} 至 {window.get('to')}（洛杉矶日期）。{frontend.get('smallCountRule', '')}。"
           "只含开启匿名统计且成功送达的记录，不代表全部流量；浏览器日和设备日不是人数。", ""]
    usage, listening, alignment = reports.get("usage"), reports.get("listening"), reports.get("alignment")
    if usage:
        funnel = usage["funnel"]
        out += [f"- 使用：会话 {_cell(usage['totals'].get('sessions'))}，浏览器日 {_cell(usage['totals'].get('browserDays'))}；"
                f"打开 {_cell(funnel.get('appOpenSessions'))} → 播放 {_cell(funnel.get('playSessions'))} → "
                f"下载 {_cell(funnel.get('downloadSessions'))}（打开后播放 {_show('frontend.usage.playRateOfOpens', funnel.get('playRateOfOpens'))}）。"]
        top = [f"{row['key']}（{_cell(row.get('sessions'))}）" for row in usage.get("actions", [])[:8]]
        if top:
            out += ["- 按会话数最多的动作：" + "、".join(top) + "。"]
        hot = [f"{row['week']} 第 {row['minute']} 分钟（{row['events']} 次）"
               for row in (usage.get("positionHotspots") or {}).get("nudge", [])[:5]]
        out += ["- 同步微调集中的位置：" + ("、".join(hot) if hot else "没有达到 5 次的分钟。")]
        if usage["coverage"].get("truncated"):
            out += ["- **使用报表查询被截断，以上只是读取到的部分。**"]
    if listening:
        out += [""] + _table(["正文语言", "音轨语言", "平台", "满 30 秒会话", "设备日", "收听小时", "完成率"],
                             [[g.get("contentLocale"), g.get("audioLocale"), g.get("platform"), g.get("qualifiedSessions"),
                               g.get("deviceDays"), g.get("listenedHours"),
                               _show("frontend.listening.completionRate", g.get("completionRate"))]
                              for g in listening.get("groups", [])])
    if alignment:
        totals = alignment["totals"]
        out += ["", f"- 听声定位：触发 {_cell(totals.get('presses'))}，已录音 {_cell(totals.get('recorded'))}，"
                f"跳转 {_cell(totals.get('applied'))}，成功率 "
                f"{_show('frontend.alignment.jumpRateOfRecorded', totals.get('jumpRateOfRecorded'))}。"]
    missing = frontend.get("missing") or []
    if missing:
        out += ["", "- 缺少的报表：" + "、".join(missing) + "。"]
    return out


def collection_gaps(weekly: dict) -> list[str]:
    gaps = []
    for r in weekly["reports"]:
        problems = []
        if not r["structured"]:
            problems.append("不是导出器生成的（无 manifest），没有可比数值")
        elif r["production"] and not r["hasJournal"]:
            problems.append("生产运行缺 journal")
        if r["retrospective"]["status"] in ("missing", "template"):
            problems.append("复盘未填写")
        elif r["retrospective"]["status"] == "unstructured":
            problems.append("复盘不是八项骨架，错误和改进没有进表")
        if not r["privateEvidence"]["uploaded"]:
            problems.append("私有证据未上传")
        open_stages = sorted({stage for run in r["runs"] for stage in run["openStages"]})
        if open_stages:
            problems.append("journal 里未收尾的阶段：" + "、".join(open_stages[:6]))
        if problems:
            gaps.append(f"`{r['name']}`：" + "；".join(problems) + "。")
    return gaps


# ---------------------------------------------------------------- reviewer decisions

def finalize(week_dir: Path) -> dict:
    """Store the decisions written in WEEKLY.md into weekly.json; returns what changed."""
    weekly = _json(week_dir / "weekly.json")
    if not isinstance(weekly, dict) or weekly.get("schemaVersion") != SCHEMA:
        raise ValueError(f"{week_dir / 'weekly.json'} is not a weekly rollup")
    found = tables((week_dir / "WEEKLY.md").read_text(encoding="utf-8"))
    problems, accepted = [], []
    by_id = {c["id"]: c for c in weekly["candidates"]}
    for row in _section(found, "候选改进"):
        word = row.get("决定", "").strip().lower()
        if not word:
            continue
        decision = DECISIONS.get(word)
        identifier = row.get("编号", "").strip()
        if decision is None:
            problems.append(f"{identifier}: 决定只能写 接受／拒绝／推迟，不是「{row.get('决定')}」")
            continue
        candidate = by_id.get(identifier)
        if candidate is None:
            candidate = {"id": identifier, "report": row.get("来源", ""), "category": row.get("类别", ""),
                         "improvement": row.get("改进", ""), "evidence": row.get("依据", ""), "decision": None}
            weekly["candidates"].append(candidate)
            by_id[identifier] = candidate
        candidate["decision"] = decision
        if decision != "accept":
            continue
        signal = parse_signal(row.get("验证信号", ""))
        backlog = row.get("backlog ID", "").strip().strip("`")
        if not backlog or signal is None:
            problems.append(f"{identifier}: 接受的改进必须有 backlog ID 和形如 `指标 <= 数值` 的验证信号")
            continue
        accepted.append({"id": f"{weekly['week']}-{identifier}", "backlogId": backlog,
                         "title": candidate["improvement"], "signal": signal, "acceptedWeek": weekly["week"],
                         "baseline": _number(weekly["metrics"].get(signal["metric"])), "status": "open", "history": []})
    if len(accepted) > 3:
        problems.append(f"本周接受了 {len(accepted)} 条，上限是 3 条")
    change = 0.0
    kinds = {}
    for row in _section(found, "重复轮次"):
        kind = REPEAT_KINDS.get(row.get("归类", "").strip().lower())
        if kind:
            kinds[(row.get("报告", ""), row.get("阶段", ""))] = kind
    for report in weekly["reports"]:
        for item in report["repeats"]:
            item["kind"] = kinds.get((report["name"], item["stage"]))
            if item["kind"] == "change":
                change += item["seconds"]
    if problems:
        raise ValueError("; ".join(problems))
    carried = [a for a in weekly["actions"] if not a["id"].startswith(f"{weekly['week']}-")]
    weekly["actions"] = [*carried, *accepted]
    if "time.reworkSeconds" in weekly["metrics"]:
        weekly["metrics"]["time.changeSeconds"] = round(change, 3)
        weekly["metrics"]["time.reworkOnlySeconds"] = round(max(0.0, weekly["metrics"]["time.reworkSeconds"] - change), 3)
    weekly["finalized"] = True
    (week_dir / "weekly.json").write_text(json.dumps(weekly, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"accepted": [a["id"] for a in accepted], "changeSeconds": round(change, 3),
            "decided": sum(c["decision"] is not None for c in weekly["candidates"])}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "finalize"):
        p = sub.add_parser(name)
        p.add_argument("--week", default=None, help="the service Sunday, YYYYMMDD (default: the latest Sunday)")
        p.add_argument("--weekly-root", type=Path, default=WEEKLY_ROOT)
        if name == "build":
            p.add_argument("--reports-root", type=Path, default=REPORTS_ROOT)
            p.add_argument("--frontend", type=Path, help="frontend-metrics.json from weekly_frontend.py")
            p.add_argument("--force", action="store_true", help="overwrite an existing WEEKLY.md and a finalized weekly.json")
    args = parser.parse_args(argv)
    week = args.week or latest_sunday()
    week_dir = args.weekly_root / week
    try:
        if args.command == "finalize":
            print(json.dumps(finalize(week_dir), ensure_ascii=False))
            return 0
        existing = _json(week_dir / "weekly.json")
        if isinstance(existing, dict) and existing.get("finalized") and not args.force:
            raise ValueError(f"{week_dir} is finalized; rebuilding would drop its decisions (pass --force to do so)")
        weekly = build(week, reports_root=args.reports_root, weekly_root=args.weekly_root, frontend_path=args.frontend)
        week_dir.mkdir(parents=True, exist_ok=True)
        (week_dir / "weekly.json").write_text(json.dumps(weekly, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        page = week_dir / "WEEKLY.md"
        if page.exists() and not args.force:
            print(f"{page} exists and was left as it is; weekly.json was refreshed (pass --force to regenerate the page)")
        else:
            page.write_text(render(weekly), encoding="utf-8")
        print(f"{week_dir}: {len(weekly['reports'])} reports, {len(weekly['actions'])} actions checked, "
              f"{len(weekly['candidates'])} candidates")
        return 0
    except (OSError, ValueError) as error:
        print(f"weekly_rollup: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
