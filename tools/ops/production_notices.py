#!/usr/bin/env python3
"""Every notice the weekly sermon flow sends, in one place: when, which channel, what it says.

    python3 tools/ops/production_notices.py list [--json]        # the whole table
    python3 tools/ops/production_notices.py preview gate.opened --kind english \\
        --url https://<mac>.<tailnet>.ts.net:8444/english.html --field units=457 --field flagged=41 --field minutes=15
    python3 tools/ops/production_notices.py send <event> ... [--no-push]

One event has one level and one wording. Bark carries the level; email follows the Drive
watcher's rule: everything that is not ``passive`` also goes out by email, as a second path
and a record. A notice that asks for a person links to the review page for that step
(apps/review-web); a local address is never sent to a phone. Texts carry no file path, no
key and no sermon text.

Levels (docs/design/progress-and-status-display.zh.md, 4.2):
  passive        something happened, nothing to do
  active         a step is ready for you, or the run finished
  timeSensitive  a failure, a stall, or a decision that did not take effect
  critical       a paid request with an unknown outcome (needs the phone's Critical Alerts permission)

The Drive watcher (tools/ops/drive_upload_watch.py) keeps its own copy of its five notices,
because its installed copy must run with the system Python and no imports from this checkout;
they are listed here with ``sender: watcher`` so the table is complete, and a test keeps the
two in step.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import notify  # noqa: E402

TZ = ZoneInfo("America/Los_Angeles")
PREFIX = "[同行]"
REHEARSAL_PREFIX = "[同行·演练]"
QUIET_START = dt.time(22, 30)   # no reminders from here ...
QUIET_END = dt.time(7, 30)      # ... until here; a reminder that falls inside waits for the morning
LOCALE_NAMES = {"zh-Hans": "中文", "ko": "韩语", "es": "西班牙语", "en": "英文"}

# The steps that wait for a person. Each one has a review page; `stage` is the run_status stage
# the handoff is recorded under. `remind` is minutes of waiting before the single reminder.
GATES = {
    "decisions": {"stage": "l0.decisions", "page": "decisions.html", "name": "开工决定", "remind": 30,
                  "opened": ("待确认 · 开工决定", "{summary}。确认之前不会开始翻译。"),
                  "waiting": "没有确认就不会开始翻译"},
    "english": {"stage": "l1.english-review", "page": "english.html", "name": "英文表", "remind": 30,
                "opened": ("待批准 · 英文表", "{units} 句，其中 {flagged} 句要重点看，大约 {minutes} 分钟。批准后开始三种语言的翻译。"),
                "waiting": "没有批准就不会开始翻译"},
    "speakers": {"stage": "l1.speakers", "page": "speakers.html", "name": "讲员", "remind": 30,
                 "opened": ("待确认 · 讲员", "{toCheck} 句机器拿不准是谁说的，大约 5 分钟。确认后才开始翻译和配音。"),
                 "waiting": "没有确认就不会开始配音"},
    "track": {"stage": "l3.review.{locale}", "page": "track.html", "name": "{localeName}音轨", "remind": 180,
              "opened": ("可审 · {localeName}音轨", "{trackMinutes} 分钟，{flagged} 句有标记，最大落后 {maxLag} 秒。下一种语言还在配，不用等。"),
              "waiting": "这条音轨没有结论就不能发布"},
    "study": {"stage": "l4.study", "page": "study.html", "name": "大纲与默想", "remind": 120,
              "opened": ("待批准 · 大纲与默想", "{locales} 的草稿已备好。不批准，页面就不带学习内容。"),
              "waiting": "没有批准，页面就不带学习内容"},
    "publish": {"stage": "l4.publish.authorization", "page": "publish.html", "name": "发布", "remind": 60,
                "opened": ("待授权 · 发布", "{pageId}：{deployments} 次部署，发布前的机器核对全部通过。授权之前不会部署。"),
                "waiting": "没有授权就不会部署"},
    "confirm": {"stage": "l4.device-confirm", "page": "confirm.html", "name": "发布后确认", "remind": 120,
                "opened": ("已发布 · 请在手机上确认", "{pageId} 已上线并通过发布门禁。请把三种语言各打开看一遍。"),
                "waiting": "没有你的确认，这一期不记为完成"},
}

# event -> (sender, level, link, title, body). `link`: gate | index | drive | none.
# gate.opened takes its title and body from GATES.
EVENTS = {
    # Saturday Drive watcher (its own process; wording lives in drive_upload_watch.py)
    "watch.started": ("watcher", "passive", "none", "开始监控证道视频上传", "18:00–22:00 每 60s 查一次 Broadcast Message Files"),
    "watch.found": ("watcher", "critical", "drive", "证道视频已上传", "文件名 · 大小 · 上传时间 · 名称标签"),
    "watch.none": ("watcher", "active", "none", "本周未见新证道视频", "18:00–22:00 未见新文件，并列出文件夹现有文件"),
    "watch.error": ("watcher", "timeSensitive", "none", "证道视频检查失败", "连续 3 次读不到文件夹"),
    "watch.recovered": ("watcher", "passive", "none", "证道视频检查已恢复", "文件夹又能读取了"),
    # Automatic start
    "production.started": ("driver", "passive", "index", "已自动开工 · {sunday}", "{fileName}，{sizeGb} GB。正在下载和转写，英文表预计 {eta} 可审。"),
    "source.rejected": ("driver", "timeSensitive", "index", "新文件没有开工", "{fileName}：{reason}。没有下载，也没有任何付费请求。请看一下是不是本周的文件。"),
    "source.download_failed": ("driver", "timeSensitive", "index", "下载失败", "{fileName}：{reason}。试了 {attempts} 次，没有开始转写。"),
    "budget.blocked": ("driver", "timeSensitive", "index", "转写没有开始 · 预算上限",
                       "本周已用约 {spent} 美元，这一次要预留 {reserve} 美元，超过每周 {cap} 美元的上限。没有发出付费请求。"),
    "paid.unknown_outcome": ("driver", "critical", "index", "付费请求结果未知 · {stageName}",
                             "一次付费请求没有确认结果。已经停止新的付费请求，等你核对之后才继续。"),
    # Steps that wait for a person
    "gate.opened": ("driver", "active", "gate", None, None),
    "gate.reminder": ("driver", "active", "gate", "还在等你 · {gateName}", "已经等了 {waited}。{waiting}。"),
    "gate.superseded": ("driver", "active", "gate", "审核版本已更新 · {gateName}", "文件变了，之前那一版作废。请打开新版本。"),
    # What became of a decision
    "decision.applied": ("driver", "passive", "index", "已生效 · {gateName}", "{verdict}，提交人 {reviewer}。生产机已核对哈希并生成收据。下一步：{next}。"),
    "decision.changes_requested": ("driver", "passive", "index", "已收到修改要求 · {gateName}", "{count} 处要改。改完会出新版本，再请你审。"),
    "decision.rejected_stale": ("driver", "timeSensitive", "gate", "决定没有生效 · {gateName}",
                                "提交时文件已经变了，这一版作废，没有产生批准。请打开新版本重新审。"),
    "decision.failed": ("driver", "timeSensitive", "index", "决定没能应用 · {gateName}", "{reason}。决定已经保存，不用重新提交。"),
    # Machine stages
    "stage.failed": ("driver", "timeSensitive", "index", "失败 · {stageName}", "{errorClass}：{message}。已停在这一步，不会自动重试。"),
    "stage.stalled": ("driver", "timeSensitive", "index", "可能卡住 · {stageName}", "最后一次进展是 {age} 前。先查进程，不要重启整条流程。"),
    "resource.blocked": ("driver", "timeSensitive", "index", "配音没有开始 · 内存不够",
                         "可用 {available} GiB，需要 {required} GiB。关掉占内存的应用后会自动再试。"),
    # Publishing and the end
    "publish.gate_failed": ("driver", "timeSensitive", "index", "发布门禁没过 · {pageId}", "{failed} 项不一致。已停止收尾，这一期不记为已发布。"),
    "production.completed": ("driver", "active", "index", "完成 · {title}", "三种语言已发布，并经你在设备上确认。全程 {wall}，其中等你 {waiting}。现场验收没有做。"),
}

EMAIL_LEVELS = ("active", "timeSensitive", "critical")
_PATH = re.compile(r"(?:/Users|/home|/private|/var/folders)/[^\s,;，。]+|artifacts/[^\s,;，。]+")
_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{6,}")


def safe_text(value, limit: int = 300) -> str:
    """What may leave the Mac: no path, no key, one line."""
    text = _KEY.sub("<key>", _PATH.sub("<path>", str(value if value is not None else "")))
    return re.sub(r"\s+", " ", text).strip()[:limit]


def safe_url(value) -> str | None:
    """A link a phone can open: http(s), and not this Mac's own loopback or .local name."""
    text = str(value or "").strip()
    if not text.startswith(("http://", "https://")):
        return None
    host = (urlsplit(text).hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return None
    return text


class _Fields(dict):
    def __missing__(self, key):
        raise KeyError(f"field {key!r} is required for this notice")


def build(event: str, *, production: str, kind: str | None = None, locale: str | None = None,
          url: str | None = None, rehearsal: bool = False, **fields) -> dict:
    """One notice, ready for notify.Message: key, level, email, title, body, url.

    A rehearsal says so in its title, so a test run is never read as the real thing."""
    if event not in EVENTS:
        raise KeyError(f"unknown event {event!r}")
    sender, level, link, title, body = EVENTS[event]
    values = _Fields({name: safe_text(value) for name, value in fields.items()})
    stage = None
    if kind is not None:
        if kind not in GATES:
            raise KeyError(f"unknown gate kind {kind!r}")
        gate = GATES[kind]
        if kind == "track" and not locale:
            raise KeyError("a track notice needs --locale")
        values["localeName"] = LOCALE_NAMES.get(locale or "", locale or "")
        values.setdefault("locale", locale or "")
        values["gateName"] = gate["name"].format_map(values)
        values["waiting"] = gate["waiting"]
        stage = gate["stage"].format_map(values)
        if event == "gate.opened":
            title, body = gate["opened"]
    elif link == "gate" or event.startswith(("gate.", "decision.")):
        raise KeyError(f"{event} needs a gate kind")
    link_url = safe_url(url)
    key = ":".join(str(part) for part in (event, production, stage or "-", fields.get("revision", "-")) if part)
    return {"event": event, "sender": sender, "key": key, "level": level, "email": level in EMAIL_LEVELS,
            "title": f"{REHEARSAL_PREFIX if rehearsal else PREFIX} {title.format_map(values)}", "body": body.format_map(values),
            "url": link_url if link != "none" else None, "stage": stage,
            "linkMissing": link in ("gate", "drive") and link_url is None}


def reminder_due(kind: str, opened_at: dt.datetime, now: dt.datetime, already_sent: int) -> bool:
    """One reminder per waiting step, after the step's waiting time, never in the quiet hours."""
    if already_sent >= 1:
        return False
    if now - opened_at < dt.timedelta(minutes=GATES[kind]["remind"]):
        return False
    local = now.astimezone(TZ).time()
    return not (local >= QUIET_START or local < QUIET_END)


def to_message(notice: dict) -> notify.Message:
    critical = notice["level"] == "critical"
    return notify.Message(notice["title"], notice["body"], notice["level"], notice["url"],
                          sound="bell" if critical else None, volume="0" if critical else None)


def table() -> list[dict]:
    rows = []
    for event, (sender, level, link, title, body) in EVENTS.items():
        if event == "gate.opened":
            for kind, gate in GATES.items():
                rows.append({"event": f"gate.opened[{kind}]", "sender": sender, "level": level, "bark": True,
                             "email": level in EMAIL_LEVELS, "link": link, "page": gate["page"], "stage": gate["stage"],
                             "title": f"{PREFIX} {gate['opened'][0]}", "body": gate["opened"][1],
                             "remindAfterMinutes": gate["remind"]})
            continue
        rows.append({"event": event, "sender": sender, "level": level, "bark": True, "email": level in EMAIL_LEVELS,
                     "link": link, "title": title if sender == "watcher" else f"{PREFIX} {title}", "body": body})
    return rows


def _parse_fields(pairs: list[str]) -> dict:
    fields = {}
    for pair in pairs:
        name, sep, value = pair.partition("=")
        if not sep or not name:
            raise SystemExit(f"--field wants name=value, got {pair!r}")
        fields[name] = value
    return fields


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="print every notice: level, channels, link, wording")
    listing.add_argument("--json", action="store_true")
    for name in ("preview", "send"):
        command = commands.add_parser(name, help="build one notice" + (" and send it" if name == "send" else ""))
        command.add_argument("event", choices=[event for event, spec in EVENTS.items() if spec[0] != "watcher"])
        command.add_argument("--production", default="demo")
        command.add_argument("--kind", choices=sorted(GATES))
        command.add_argument("--locale")
        command.add_argument("--url", help="the review page for this step (tailnet HTTPS address)")
        command.add_argument("--field", action="append", default=[], metavar="NAME=VALUE")
        if name == "send":
            command.add_argument("--no-push", action="store_true", help="print instead of sending")
            command.add_argument("--no-email", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "list":
        rows = table()
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for row in rows:
                channels = "Bark+邮件" if row["email"] else "Bark"
                print(f"{row['event']:<28} {row['level']:<13} {channels:<9} {row['link']:<5} {row['title']} — {row['body']}")
        return 0
    try:
        notice = build(args.event, production=args.production, kind=args.kind, locale=args.locale, url=args.url,
                       **_parse_fields(args.field))
    except KeyError as exc:
        raise SystemExit(str(exc.args[0])) from exc
    if args.command == "preview":
        print(json.dumps(notice, ensure_ascii=False, indent=1))
        return 0
    if notice["linkMissing"]:
        raise SystemExit("this notice asks for a person and needs --url with an address a phone can open")
    keys = {} if args.no_push else notify.keychain_keys()
    mail = None if (args.no_push or args.no_email) else notify.configured_mail()
    results = notify.Notifier(keys, push=not args.no_push, mail=mail).send(to_message(notice))
    print(json.dumps({"key": notice["key"], "level": notice["level"], "results": results}, ensure_ascii=False))
    return 0 if args.no_push or notify.delivered(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
