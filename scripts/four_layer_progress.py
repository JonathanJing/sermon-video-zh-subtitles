#!/usr/bin/env python3
"""Operator-maintained progress ledger for one four-layer multilingual release.

This ledger reports work progress. It never grants a production gate or approval.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


SCHEMA = "sermon-four-layer-progress-v1"
STATUSES = {"pending", "running", "waiting_review", "blocked", "complete"}
STEPS = {
    1: (
        ("01", "来源媒体、身份与人工范围"),
        ("02", "冻结英文文本与词级对齐"),
        ("03", "句界、停顿和锚点核验"),
        ("04", "英文人工审核与正式 Source Package"),
    ),
    2: (
        ("01", "目标语言策略与经文版本"),
        ("02", "逐单元翻译与覆盖"),
        ("03", "独立机器复核与语言检查"),
        ("04", "人工文字审核与 Candidate"),
    ),
    3: (
        ("01", "授权音色、能力与 Speech Job"),
        ("02", "逐单元合成"),
        ("03", "解码、哈希与回转写筛查"),
        ("04", "排程、字幕与完整音轨"),
        ("05", "人工全文听审"),
        ("06", "同视频同步审核与 Audio Package"),
    ),
    4: (
        ("01", "同语言 Release Package 与文件清单"),
        ("02", "构建与上传"),
        ("03", "线上 HTTP、哈希与音频 Range 核验"),
        ("04", "客户端文字、语言与播放核验"),
    ),
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp() -> str:
    return now().isoformat(timespec="seconds")


def step_id(layer: int, number: str, locale: str | None = None) -> str:
    return f"L{layer}-{number}" + (f"@{locale}" if locale else "")


def new_ledger(page_id: str, locales: list[str], *, target: str = "dev") -> dict:
    if not page_id.strip():
        raise ValueError("page ID is required")
    if (not locales or len(set(locales)) != len(locales)
            or any(not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", locale)
                   for locale in locales)):
        raise ValueError("locales must be unique BCP 47 language tags")
    if target not in {"dev", "production"}:
        raise ValueError("target must be dev or production")
    steps = {}
    for layer, definitions in STEPS.items():
        for locale in ([None] if layer == 1 else locales):
            for number, title in definitions:
                key = step_id(layer, number, locale)
                steps[key] = {
                    "layer": layer,
                    "locale": locale,
                    "title": title,
                    "status": "pending",
                    "evidence": [],
                    "estimateMinutes": None,
                    "elapsedMinutes": 0.0,
                    "doneUnits": None,
                    "totalUnits": None,
                }
    return {
        "schemaVersion": SCHEMA,
        "pageId": page_id,
        "target": target,
        "locales": locales,
        "createdAt": timestamp(),
        "updatedAt": timestamp(),
        "steps": steps,
        "acceptance": {
            locale: {kind: {"status": "not_run", "evidence": []}
                     for kind in ("device", "venue")}
            for locale in locales
        },
        "history": [],
    }


def load(path: Path) -> dict:
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if ledger.get("schemaVersion") != SCHEMA or not isinstance(ledger.get("steps"), dict):
        raise ValueError("unsupported or invalid progress ledger")
    # Early v1 local drafts stored placeholder acceptance statuses globally.
    if isinstance(ledger.get("acceptance", {}).get("device"), str):
        ledger["acceptance"] = {
            locale: {kind: {"status": "not_run", "evidence": []}
                     for kind in ("device", "venue")}
            for locale in ledger["locales"]
        }
    return ledger


def save(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(ledger, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def update_step(ledger: dict, key: str, status: str, *, evidence: str | None = None,
                reason: str | None = None, estimate_minutes: float | None = None,
                elapsed_minutes: float | None = None, done_units: int | None = None,
                total_units: int | None = None) -> None:
    if key not in ledger["steps"]:
        raise ValueError(f"unknown step: {key}")
    if status not in STATUSES:
        raise ValueError(f"unsupported status: {status}")
    step = ledger["steps"][key]
    if step["status"] == "complete" and status != "complete":
        raise ValueError("completed step can only reopen through invalidate")
    if status == "complete" and not (step["evidence"] or evidence):
        raise ValueError("completion requires an evidence reference")
    if status in {"blocked", "waiting_review"} and not reason:
        raise ValueError("blocked and waiting_review require a reason")
    if estimate_minutes is not None and estimate_minutes <= 0:
        raise ValueError("estimate must be positive")
    if elapsed_minutes is not None and elapsed_minutes < 0:
        raise ValueError("elapsed time cannot be negative")
    new_total = total_units if total_units is not None else step["totalUnits"]
    new_done = done_units if done_units is not None else step["doneUnits"]
    if new_total is not None and (new_total <= 0 or new_done is not None and new_done > new_total):
        raise ValueError("invalid unit totals")
    if new_done is not None and (new_done < 0 or new_total is None):
        raise ValueError("done units require a valid total")
    if status == "complete" and new_total is not None and new_done != new_total:
        raise ValueError("all units must be done before completion")
    step["status"] = status
    if evidence and evidence not in step["evidence"]:
        step["evidence"].append(evidence)
    step["reason"] = reason if status in {"blocked", "waiting_review"} else None
    if estimate_minutes is not None:
        step["estimateMinutes"] = round(estimate_minutes, 2)
    if elapsed_minutes is not None:
        step["elapsedMinutes"] = round(elapsed_minutes, 2)
    step["doneUnits"], step["totalUnits"] = new_done, new_total
    step["updatedAt"] = timestamp()
    ledger["updatedAt"] = timestamp()
    ledger["history"].append({"at": timestamp(), "action": "update", "step": key, "status": status})


def invalidate(ledger: dict, layer: int, locale: str | None, reason: str) -> list[str]:
    if layer not in STEPS or not reason.strip():
        raise ValueError("valid layer and reason required")
    if layer != 1 and locale not in ledger["locales"]:
        raise ValueError("Layer 2-4 invalidation requires a tracked locale")
    if layer == 1 and locale is not None:
        raise ValueError("Layer 1 is shared and must not specify a locale")
    changed = []
    previous = {}
    for key, step in ledger["steps"].items():
        if step["layer"] < layer or layer > 1 and step["locale"] != locale:
            continue
        previous[key] = {"status": step["status"], "evidence": list(step["evidence"])}
        step["status"] = "pending"
        step["evidence"] = []
        step["reason"] = f"上游失效：{reason}"
        step["elapsedMinutes"] = 0.0
        step["doneUnits"] = None
        step["totalUnits"] = None
        step["updatedAt"] = timestamp()
        changed.append(key)
    ledger["updatedAt"] = timestamp()
    affected_locales = ledger["locales"] if layer == 1 else [locale]
    previous_acceptance = {affected_locale: json.loads(json.dumps(ledger["acceptance"][affected_locale]))
                           for affected_locale in affected_locales}
    for affected_locale in affected_locales:
        for kind in ("device", "venue"):
            ledger["acceptance"][affected_locale][kind] = {"status": "not_run", "evidence": []}
    ledger["history"].append({"at": timestamp(), "action": "invalidate", "layer": layer,
                              "locale": locale, "reason": reason, "steps": changed,
                              "previous": previous, "previousAcceptance": previous_acceptance})
    return changed


def update_acceptance(ledger: dict, locale: str, kind: str, status: str,
                      *, evidence: str | None = None, reason: str | None = None) -> None:
    if locale not in ledger["locales"] or kind not in {"device", "venue"}:
        raise ValueError("unknown locale or acceptance kind")
    if status not in {"not_run", "pending", "passed", "failed", "blocked"}:
        raise ValueError("unsupported acceptance status")
    record = ledger["acceptance"][locale][kind]
    previous = json.loads(json.dumps(record))
    if status in {"passed", "failed"} and not evidence:
        raise ValueError("acceptance result requires evidence")
    if status == "blocked" and not reason:
        raise ValueError("blocked acceptance requires a reason")
    if status == "not_run":
        record["evidence"] = []
    elif evidence and evidence not in record["evidence"]:
        record["evidence"].append(evidence)
    record["status"] = status
    record["reason"] = reason if status in {"blocked", "failed"} else None
    record["updatedAt"] = timestamp()
    ledger["updatedAt"] = timestamp()
    ledger["history"].append({"at": timestamp(), "action": "acceptance", "locale": locale,
                              "kind": kind, "status": status, "previous": previous})


def remaining_minutes(step: dict) -> float | None:
    if step["status"] == "complete":
        return 0.0
    done, total, elapsed = step["doneUnits"], step["totalUnits"], step["elapsedMinutes"]
    if done and total and elapsed > 0:
        return round((elapsed / done) * (total - done), 1)
    estimate = step["estimateMinutes"]
    if estimate is None:
        return None
    return round(max(0.0, estimate - elapsed), 1)


def summary(ledger: dict, *, at: datetime | None = None) -> dict:
    clock = at or now()
    rows = []
    for layer in STEPS:
        for locale in ([None] if layer == 1 else ledger["locales"]):
            steps = [s for s in ledger["steps"].values()
                     if s["layer"] == layer and s["locale"] == locale]
            complete = sum(s["status"] == "complete" for s in steps)
            blocked = [s["title"] + ": " + str(s.get("reason")) for s in steps
                       if s["status"] in {"blocked", "waiting_review"}]
            remaining = [remaining_minutes(s) for s in steps if s["status"] != "complete"]
            unknown = sum(value is None for value in remaining)
            rows.append({"layer": layer, "locale": locale, "complete": complete,
                         "total": len(steps), "percent": round(100 * complete / len(steps)),
                         "blockers": blocked, "unknownEstimates": unknown,
                         "remainingMinutes": None if unknown else round(sum(remaining), 1)})
    all_steps = list(ledger["steps"].values())
    blockers = [f"{key}: {s.get('reason')}" for key, s in ledger["steps"].items()
                if s["status"] in {"blocked", "waiting_review"}]
    unknown = [key for key, s in ledger["steps"].items()
               if s["status"] != "complete" and remaining_minutes(s) is None]
    active_units = [{"step": key, "done": s["doneUnits"], "total": s["totalUnits"],
                     "percent": round(100 * s["doneUnits"] / s["totalUnits"])}
                    for key, s in ledger["steps"].items()
                    if s["status"] == "running" and s["doneUnits"] is not None
                    and s["totalUnits"] is not None]
    remaining = None if unknown else round(sum(remaining_minutes(s) for s in all_steps), 1)
    eta = None if blockers or unknown else (clock + timedelta(minutes=remaining)).isoformat(timespec="minutes")
    return {"pageId": ledger["pageId"], "target": ledger["target"],
            "complete": sum(s["status"] == "complete" for s in all_steps), "total": len(all_steps),
            "rows": rows, "blockers": blockers, "missingEstimates": unknown,
            "activeUnits": active_units,
            "remainingSerialMinutes": remaining, "earliestContinuousEta": eta,
            "acceptance": ledger["acceptance"], "updatedAt": ledger["updatedAt"]}


def render(report: dict) -> str:
    lines = [f"{report['pageId']} · {report['target']} · 检查点 {report['complete']}/{report['total']}",
             "层 / 语言       完成       剩余串行工时"]
    for row in report["rows"]:
        name = f"L{row['layer']} {row['locale'] or 'shared'}"
        minutes = row["remainingMinutes"]
        lines.append(f"{name:<16} {row['complete']}/{row['total']} ({row['percent']}%)  "
                     + (f"{minutes:g} 分钟" if minutes is not None else "未知"))
    eta = report["earliestContinuousEta"]
    local_eta = (datetime.fromisoformat(eta).astimezone(ZoneInfo("America/Los_Angeles"))
                 .strftime("%Y-%m-%d %H:%M %Z")) if eta else "未知"
    lines.append("ETA（连续串行、无审核等待）: " + local_eta)
    for item in report["activeUnits"]:
        lines.append(f"进行中 {item['step']}: {item['done']}/{item['total']} 单元 ({item['percent']}%)")
    if report["blockers"]:
        lines.append("待审核／阻塞: " + "; ".join(report["blockers"]))
    if report["missingEstimates"]:
        missing = report["missingEstimates"]
        lines.append(f"缺估时 {len(missing)} 项: " + ", ".join(missing[:6])
                     + (" …" if len(missing) > 6 else ""))
    for locale, acceptance in report["acceptance"].items():
        lines.append(f"独立验收 {locale}: 设备={acceptance['device']['status']}，"
                     f"现场={acceptance['venue']['status']}")
    lines.append("注意：进度账本不授予 Layer 门禁、发布或验收状态。")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="Ignored run-local JSON path")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--page-id", required=True)
    init.add_argument("--locales", nargs="+", required=True)
    init.add_argument("--target", choices=("dev", "production"), default="dev")
    update = commands.add_parser("update")
    update.add_argument("--step", required=True)
    update.add_argument("--status", required=True, choices=sorted(STATUSES))
    update.add_argument("--evidence")
    update.add_argument("--reason")
    update.add_argument("--estimate-minutes", type=float)
    update.add_argument("--elapsed-minutes", type=float)
    update.add_argument("--done-units", type=int)
    update.add_argument("--total-units", type=int)
    invalid = commands.add_parser("invalidate")
    invalid.add_argument("--layer", type=int, required=True, choices=sorted(STEPS))
    invalid.add_argument("--locale")
    invalid.add_argument("--reason", required=True)
    acceptance = commands.add_parser("acceptance")
    acceptance.add_argument("--locale", required=True)
    acceptance.add_argument("--kind", choices=("device", "venue"), required=True)
    acceptance.add_argument("--status", choices=("not_run", "pending", "passed", "failed", "blocked"), required=True)
    acceptance.add_argument("--evidence")
    acceptance.add_argument("--reason")
    show = commands.add_parser("show")
    show.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "init":
            if args.ledger.exists():
                raise ValueError("ledger already exists; refusing to overwrite")
            ledger = new_ledger(args.page_id, args.locales, target=args.target)
            save(args.ledger, ledger)
        else:
            ledger = load(args.ledger)
            if args.command == "update":
                update_step(ledger, args.step, args.status, evidence=args.evidence,
                            reason=args.reason, estimate_minutes=args.estimate_minutes,
                            elapsed_minutes=args.elapsed_minutes, done_units=args.done_units,
                            total_units=args.total_units)
                save(args.ledger, ledger)
            elif args.command == "invalidate":
                invalidate(ledger, args.layer, args.locale, args.reason)
                save(args.ledger, ledger)
            elif args.command == "acceptance":
                update_acceptance(ledger, args.locale, args.kind, args.status,
                                  evidence=args.evidence, reason=args.reason)
                save(args.ledger, ledger)
        report = summary(ledger)
        print(json.dumps(report, ensure_ascii=False, indent=2) if getattr(args, "json", False)
              else render(report))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
