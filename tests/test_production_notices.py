"""tools/ops/production_notices.py: one wording and one level per event, for Bark and email."""
import datetime as dt
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ops"))
import production_notices as notices  # noqa: E402

URL = "https://mac.tailnet-name.ts.net:8791/english.html?production=p&gate=l1.english-review"
FIELDS = dict(sunday="2026-11-29", fileName="Saturday_530pm_Live__1080.mp4", sizeGb="1.00", eta="20:05", reason="不是视频文件",
              attempts="3", spent="1.20", reserve="0.90", cap="50", stageName="英文转写", summary="整期 · 三语 · 同步 · 正式页",
              units="457", flagged="41", minutes="15", toCheck="21", trackMinutes="36", maxLag="4.9", locales="中文、韩语、西班牙语",
              pageId="page-20261129", deployments="3", waited="45 分钟", verdict="批准", reviewer="reviewer@example.com", next="翻译",
              count="3", errorClass="process", message="退出码 1", age="16 分钟", available="11.2", required="15", failed="2",
              title="示例讲题", wall="3 小时 5 分", waiting="1 小时 40 分")
DRIVER_EVENTS = [event for event, spec in notices.EVENTS.items() if spec[0] == "driver" and event != "gate.opened"]


def needs_kind(event):
    return event.startswith(("gate.", "decision."))


@pytest.mark.parametrize("event", DRIVER_EVENTS)
def test_every_event_builds_complete_text(event):
    notice = notices.build(event, production="p", kind="english" if needs_kind(event) else None, url=URL, **FIELDS)
    assert notice["title"].startswith("[同行] ") and "{" not in notice["title"] + notice["body"]
    assert notice["level"] in ("passive", "active", "timeSensitive", "critical")
    assert notice["email"] == (notice["level"] != "passive"), "everything that is not passive also goes by email"


@pytest.mark.parametrize("kind", sorted(notices.GATES))
def test_a_step_that_waits_for_a_person_is_active_and_links_to_its_page(kind):
    notice = notices.build("gate.opened", production="p", kind=kind, locale="ko", url=URL, **FIELDS)
    assert (notice["level"], notice["email"], notice["url"], notice["linkMissing"]) == ("active", True, URL, False)
    assert "{" not in notice["title"] + notice["body"]
    assert notice["stage"] == notices.GATES[kind]["stage"].replace("{locale}", "ko")
    assert "对话" not in notice["body"] and "回到电脑" not in notice["body"], "the decision is made on the page"


def test_track_notice_names_the_language_and_needs_one():
    notice = notices.build("gate.opened", production="p", kind="track", locale="es", url=URL, **FIELDS)
    assert notice["title"] == "[同行] 可审 · 西班牙语音轨" and notice["stage"] == "l3.review.es"
    assert notice["key"] == "gate.opened:p:l3.review.es:-"
    with pytest.raises(KeyError):
        notices.build("gate.opened", production="p", kind="track", url=URL, **FIELDS)


def test_levels_follow_the_policy():
    level = lambda event: notices.EVENTS[event][1]
    assert level("paid.unknown_outcome") == "critical"
    for event in ("stage.failed", "stage.stalled", "decision.rejected_stale", "decision.failed", "budget.blocked",
                  "source.rejected", "source.download_failed", "resource.blocked", "publish.gate_failed"):
        assert level(event) == "timeSensitive", event
    for event in ("production.started", "decision.applied", "decision.changes_requested"):
        assert level(event) == "passive", event
    assert level("gate.reminder") == level("production.completed") == "active"


def test_a_local_address_is_never_sent_and_is_reported_as_missing():
    for local in ("http://127.0.0.1:8791/english.html", "http://localhost:8765/review-player.html", "http://mbp.local:8765/x", "file:///tmp/x"):
        notice = notices.build("gate.opened", production="p", kind="english", url=local, **FIELDS)
        assert notice["url"] is None and notice["linkMissing"] is True
    assert notices.build("production.started", production="p", **FIELDS)["linkMissing"] is False


def test_text_carries_no_path_and_no_key():
    notice = notices.build("stage.failed", production="p", stageName="配音", errorClass="process",
                           message="see /Users/someone/dev/repo/artifacts/run/tts.log and artifacts/run/x.json key sk-abcdef123456")
    assert "/Users" not in notice["body"] and "artifacts/" not in notice["body"] and "sk-abcdef" not in notice["body"]
    assert "<path>" in notice["body"] and "<key>" in notice["body"]


def test_a_missing_field_is_an_error_not_a_blank():
    with pytest.raises(KeyError):
        notices.build("budget.blocked", production="p", spent="1", reserve="1")
    with pytest.raises(KeyError):
        notices.build("decision.applied", production="p", **FIELDS)   # no gate kind
    with pytest.raises(KeyError):
        notices.build("no.such.event", production="p")


def test_one_reminder_after_the_waiting_time_and_never_in_quiet_hours():
    at = lambda text: dt.datetime.fromisoformat(text).replace(tzinfo=notices.TZ)
    opened = at("2026-11-28T20:05")
    assert notices.reminder_due("english", opened, at("2026-11-28T20:30"), 0) is False
    assert notices.reminder_due("english", opened, at("2026-11-28T20:36"), 0) is True
    assert notices.reminder_due("english", opened, at("2026-11-28T21:30"), 1) is False, "only one reminder"
    assert notices.reminder_due("track", opened, at("2026-11-28T22:00"), 0) is False, "a track takes time to hear"
    assert notices.reminder_due("track", opened, at("2026-11-28T23:30"), 0) is False, "quiet hours"
    assert notices.reminder_due("track", opened, at("2026-11-29T07:00"), 0) is False
    assert notices.reminder_due("track", opened, at("2026-11-29T07:31"), 0) is True


def test_critical_message_is_silent_but_breaks_through():
    message = notices.to_message(notices.build("paid.unknown_outcome", production="p", stageName="英文转写"))
    assert (message.level, message.volume, message.sound) == ("critical", "0", "bell")
    assert notices.to_message(notices.build("production.started", production="p", **FIELDS)).volume is None


def test_watcher_rows_match_the_watcher_itself():
    source = (ROOT / "tools" / "ops" / "drive_upload_watch.py").read_text(encoding="utf-8")
    for event, (sender, level, _link, title, _body) in notices.EVENTS.items():
        if sender != "watcher":
            continue
        assert f'"{title}"' in source, f"{event}: the watcher no longer sends {title!r}"
    assert 'level="critical", url=item.url' in source and notices.EVENTS["watch.found"][1] == "critical"


def test_table_lists_every_event_and_every_gate():
    rows = notices.table()
    events = [row["event"] for row in rows]
    assert len(events) == len(set(events)) == len(notices.EVENTS) - 1 + len(notices.GATES)
    assert all(row["bark"] for row in rows)
    assert [row for row in rows if row["level"] == "passive" and row["email"]] == []
    assert notices.main(["list", "--json"]) == 0


def test_send_refuses_a_notice_whose_link_a_phone_cannot_open(capsys):
    with pytest.raises(SystemExit):
        notices.main(["send", "gate.opened", "--kind", "english", "--url", "http://127.0.0.1:8791/english.html",
                      "--field", "units=1", "--field", "flagged=0", "--field", "minutes=1", "--no-push"])
    assert notices.main(["send", "gate.opened", "--kind", "english", "--url", URL,
                         "--field", "units=1", "--field", "flagged=0", "--field", "minutes=1", "--no-push"]) == 0
    assert '"printed": true' in capsys.readouterr().out
