"""tools/ops/drive_upload_watch.py: Saturday Drive folder watcher with Bark pushes (no network)."""
import datetime as dt
import json
from pathlib import Path
import plistlib
import shutil
import subprocess

import pytest

from tools.ops import drive_upload_watch as watch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/drive_upload_watch/folder_20261025.html"
TZ = watch.TZ
KEYS = {"bark-iphone": "IPHONEKEY", "bark-mac": "MACKEY"}


def pt(text):
    return dt.datetime.fromisoformat(text).replace(tzinfo=TZ)


def ms(text):
    return int(pt(text).timestamp() * 1000)


def drive_file(file_id, name, created, modified=None, size=900_000_000):
    return watch.DriveFile(id=file_id, name=name, mime="video/mp4", size=size,
                           earliest=pt(created), latest=pt(modified or created))


def encode_ivd(entries):
    """The folder page's escaping: JSON with brackets, quotes and slashes as \\x5b, \\x5d, \\x22, \\/."""
    rows = [[e["id"], [watch.FOLDER_ID], e["name"], "video/mp4", 0, None, 0, 0, 0,
             e["modified"], e["created"], None, None, e["size"]] for e in entries]
    text = json.dumps([rows]).replace("[", "\\x5b").replace("]", "\\x5d").replace('"', "\\x22").replace("/", "\\/")
    return f"<script>window['_DRIVE_ivd'] = '{text}';</script>"


class Clock:
    def __init__(self, start):
        self.now = pt(start)

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += dt.timedelta(seconds=seconds)


class Bark:
    """Records Bark POSTs; `fail` maps an account's key to how many calls fail first."""

    def __init__(self, fail=None):
        self.calls, self.fail = [], dict(fail or {})

    def __call__(self, url, payload):
        self.calls.append((url, payload))
        key = payload["device_key"]
        if self.fail.get(key, 0):
            self.fail[key] -= 1
            raise OSError("network down")
        return {"code": 200, "message": "success"}

    def titles(self, key="IPHONEKEY"):
        return [p["title"] for _, p in self.calls if p["device_key"] == key]


def make(tmp_path, clock, fetch, *, bark=None, keys=KEYS, local=None):
    bark = bark or Bark()
    local_calls = []
    notifier = watch.Notifier(dict(keys), post=bark, sleep=lambda s: None,
                              local=local or (lambda m: local_calls.append(m) or True))
    watcher = watch.Watcher(state_path=tmp_path / "state.json", notifier=notifier, fetch=fetch,
                            clock=clock, sleep=clock.sleep, jitter_seconds=0)
    return watcher, bark, local_calls


OLD = drive_file("old", "Saturday_400pm_Live__1080.mp4", "2026-10-24T19:37:03", "2026-10-24T19:46:10")


def test_real_page_fixture_parses_the_2026_10_24_upload():
    files = watch.parse_listing(FIXTURE.read_text(encoding="utf-8"))
    assert [f.name for f in files] == ["Saturday_400pm_Live__1080.mp4"]
    item = files[0]
    assert item.id == "1ha2OzzjtKUKHWn1h0YaDZpVYUSt7CwfO"
    assert item.size == 903_783_961
    assert item.earliest == pt("2026-10-24T19:37:03.321000")
    assert item.latest == pt("2026-10-24T19:46:10.253000")
    assert item.url == "https://drive.google.com/file/d/1ha2OzzjtKUKHWn1h0YaDZpVYUSt7CwfO/view"


def test_encoded_listing_round_trips_and_missing_listing_fails_loudly():
    page = encode_ivd([{"id": "a", "name": "20261101 BROADCAST MESSAGE.mp4", "size": 5,
                        "created": ms("2026-10-31T18:47:54"), "modified": ms("2026-10-31T18:50:01")}])
    [item] = watch.parse_listing(page)
    assert (item.name, item.earliest, item.latest) == (
        "20261101 BROADCAST MESSAGE.mp4", pt("2026-10-31T18:47:54"), pt("2026-10-31T18:50:01"))
    with pytest.raises(watch.ListingError, match="private or the page format changed"):
        watch.parse_listing("<html>Sign in</html>")
    with pytest.raises(watch.ListingError, match="could not be parsed"):
        watch.parse_listing("<script>window['_DRIVE_ivd'] = '\\x5b';</script>")


def test_window_dates_and_daylight_saving():
    sunday = pt("2026-10-25T09:00")
    window = watch.next_window(sunday)
    assert window.start == pt("2026-10-31T18:00") and window.start.utcoffset() == dt.timedelta(hours=-7)
    assert window.week_start == pt("2026-10-25T00:00")
    assert window.prefix == "20261101"
    after_dst = watch.next_window(pt("2026-11-01T09:00"))
    assert after_dst.end == pt("2026-11-07T22:00") and after_dst.end.utcoffset() == dt.timedelta(hours=-8)
    assert watch.next_window(pt("2026-10-31T22:30")).day == dt.date(2026, 11, 7)
    assert watch.window_on(pt("2026-10-31T12:00")).day == dt.date(2026, 10, 31)
    assert watch.window_on(pt("2026-10-30T19:00")) is None


def test_new_file_is_pushed_once_whatever_its_name_and_old_file_stays_silent(tmp_path):
    clock = Clock("2026-10-31T18:00")
    new = drive_file("new", "Saturday_400pm_Live__1080.mp4", "2026-10-31T19:37:03", "2026-10-31T19:46:10")
    fetch = lambda: [OLD, new] if clock.now >= pt("2026-10-31T19:40") else [OLD]
    watcher, bark, local_calls = make(tmp_path, clock, fetch)

    assert watcher.run() == 0
    assert clock.now >= pt("2026-10-31T22:00")
    assert bark.titles() == ["开始监控证道视频上传", "证道视频已上传"]
    assert bark.titles("MACKEY") == bark.titles()
    found = [p for _, p in bark.calls if p["title"] == "证道视频已上传" and p["device_key"] == "IPHONEKEY"][0]
    assert found["body"] == "Saturday_400pm_Live__1080.mp4 · 0.90 GB · 19:37 PT · 名称不含 20261101"
    assert (found["level"], found["group"], found["url"]) == (
        "timeSensitive", "sermon-upload", "https://drive.google.com/file/d/new/view")
    start = [p for _, p in bark.calls if p["title"] == "开始监控证道视频上传"][0]
    assert start["level"] == "passive" and "Bark: iphone, mac" in start["body"]
    assert local_calls == []  # the Mac's Bark push arrived
    state = json.loads((tmp_path / "state.json").read_text())
    assert set(state["notified"]) == {"new"} and set(state["baseline"]) == {"old"}
    assert state["windows"]["2026-10-31"]["found"] == ["new"]
    events = [json.loads(line)["event"] for line in (tmp_path / "observations.ndjson").read_text().splitlines()]
    assert events == ["found", "window_closed"]


def test_late_start_reports_a_file_uploaded_before_it_started(tmp_path):
    clock = Clock("2026-10-31T20:30")
    new = drive_file("new", "20261101 BROADCAST MESSAGE.mp4", "2026-10-31T18:47:54")
    watcher, bark, _ = make(tmp_path, clock, lambda: [OLD, new])
    watcher.run()
    found = [p["body"] for _, p in bark.calls if p["title"] == "证道视频已上传" and p["device_key"] == "IPHONEKEY"]
    assert found == ["20261101 BROADCAST MESSAGE.mp4 · 0.90 GB · 18:47 PT · 名称含 20261101"]


def test_this_weeks_file_uploaded_before_the_window_is_labelled(tmp_path):
    clock = Clock("2026-10-31T18:00")
    early = drive_file("early", "20261101 BROADCAST MESSAGE.mp4", "2026-10-31T17:30")
    watcher, bark, _ = make(tmp_path, clock, lambda: [early])
    watcher.poll(watch.Window(dt.date(2026, 10, 31)))
    assert bark.calls[0][1]["body"].endswith("17:30 PT · 名称含 20261101 · 窗口前已上传")


def test_restart_in_the_window_sends_nothing_again(tmp_path):
    new = drive_file("new", "x.mp4", "2026-10-31T19:00")
    clock = Clock("2026-10-31T19:30")
    first, bark, _ = make(tmp_path, clock, lambda: [OLD, new])
    first.poll(watch.Window(dt.date(2026, 10, 31)))
    first.start(watch.Window(dt.date(2026, 10, 31)), first.slot(watch.Window(dt.date(2026, 10, 31))))
    sent = len(bark.calls)
    second, bark2, _ = make(tmp_path, Clock("2026-10-31T21:59:30"), lambda: [OLD, new])
    second.run()
    assert sent == 4 and bark2.calls == []  # no second start, found or summary notice


def test_empty_window_sends_one_summary_and_a_catch_up_run_does_not_repeat_it(tmp_path):
    clock = Clock("2026-10-31T21:55")
    watcher, bark, _ = make(tmp_path, clock, lambda: [OLD])
    watcher.run()
    summary = [p for _, p in bark.calls if p["title"] == "本周未见新证道视频"]
    assert len(summary) == 2 and summary[0]["level"] == "active"
    assert summary[0]["body"] == "18:00–22:00 未见新文件。文件夹现有：Saturday_400pm_Live__1080.mp4"
    again, bark2, _ = make(tmp_path, Clock("2026-10-31T23:10"), lambda: [OLD])
    again.run()
    assert bark2.calls == []


def test_woken_after_the_window_reads_once_then_summarises(tmp_path):
    new = drive_file("new", "x.mp4", "2026-10-31T19:00")
    watcher, bark, _ = make(tmp_path, Clock("2026-10-31T22:40"), lambda: [OLD, new])
    watcher.run()
    assert bark.titles() == ["证道视频已上传"]


def test_outside_the_window_exits_without_reading(tmp_path):
    reads = []
    for start in ("2026-10-30T19:00", "2026-10-31T17:59", "2026-11-01T00:30"):
        watcher, bark, _ = make(tmp_path, Clock(start), lambda: reads.append(1) or [])
        assert watcher.run() == 0
        assert bark.calls == []
    assert reads == []


def test_three_failed_reads_push_one_error_then_one_recovery(tmp_path):
    clock = Clock("2026-10-31T18:00")
    outcomes = iter([watch.ListingError("folder private")] * 5 + [[OLD]] * 10)

    def fetch():
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value

    watcher, bark, _ = make(tmp_path, clock, fetch)
    window = watch.Window(dt.date(2026, 10, 31))
    for _ in range(8):
        watcher.poll(window)
    titles = bark.titles()
    assert titles == ["证道视频检查失败", "证道视频检查已恢复"]
    error = [p for _, p in bark.calls if p["title"] == "证道视频检查失败"][0]
    assert error["body"] == "连续 3 次读不到文件夹：folder private"


def test_bark_payload_retries_and_key_stays_out_of_the_url(tmp_path):
    bark = Bark(fail={"IPHONEKEY": 2})
    notifier = watch.Notifier(dict(KEYS), post=bark, sleep=lambda s: None, local=lambda m: True)
    results = notifier.send(watch.Message("t", "b", level="timeSensitive", url="https://drive.google.com/x", sound="bell"))
    assert results == {"bark-iphone": True, "bark-mac": True}
    assert len([c for c in bark.calls if c[1]["device_key"] == "IPHONEKEY"]) == 3
    url, payload = bark.calls[-1]
    assert url == "https://api.day.app/push" and "KEY" not in url
    assert payload == {"device_key": "MACKEY", "title": "t", "body": "b", "group": "sermon-upload",
                       "level": "timeSensitive", "isArchive": "1", "url": "https://drive.google.com/x",
                       "sound": "bell"}


def test_local_notification_only_when_the_mac_push_did_not_arrive():
    shown = []
    local = lambda m: shown.append(m.title) or True
    failing = watch.Notifier(dict(KEYS), post=Bark(fail={"MACKEY": 9}), sleep=lambda s: None, local=local)
    assert failing.send(watch.Message("a", "b")) == {"bark-iphone": True, "bark-mac": False, "local": True}
    iphone_only = watch.Notifier({"bark-iphone": "IPHONEKEY"}, post=Bark(), local=local)
    assert iphone_only.send(watch.Message("c", "d"))["local"] is True
    assert "local" not in iphone_only.send(watch.Message("quiet", "d", level="passive"))
    assert shown == ["a", "c"]


def test_undelivered_notice_is_retried_on_the_next_poll(tmp_path):
    new = drive_file("new", "x.mp4", "2026-10-31T19:00")
    bark = Bark(fail={"IPHONEKEY": 3})
    watcher, bark, _ = make(tmp_path, Clock("2026-10-31T19:30"), lambda: [new], bark=bark,
                            keys={"bark-iphone": "IPHONEKEY"}, local=lambda m: False)
    window = watch.Window(dt.date(2026, 10, 31))
    watcher.poll(window)
    assert watcher.state["notified"] == {}
    watcher.poll(window)
    assert set(watcher.state["notified"]) == {"new"}


def test_unknown_state_version_is_refused(tmp_path):
    path = tmp_path / "state.json"
    path.write_text('{"version": 99}')
    with pytest.raises(SystemExit, match="unsupported state version 99"):
        watch.load_state(path)


def test_launch_agent_starts_saturday_1800_awake_with_system_python(tmp_path):
    plist = plistlib.loads(plistlib.dumps(watch.plist_for(tmp_path / "copy.py", tmp_path)))
    assert plist["StartCalendarInterval"] == {"Weekday": 6, "Hour": 18, "Minute": 0}
    assert plist["RunAtLoad"] is True and "KeepAlive" not in plist
    assert plist["ProgramArguments"] == ["/usr/bin/caffeinate", "-i", "/usr/bin/python3", "-I",
                                         str(tmp_path / "copy.py"), "run"]


@pytest.mark.skipif(not Path(watch.SYSTEM_PYTHON).exists() or shutil.which("plutil") is None,
                    reason="macOS system Python and plutil only")
def test_installed_copy_runs_under_system_python_and_plist_lints(tmp_path):
    script = ROOT / "tools/ops/drive_upload_watch.py"
    result = subprocess.run([watch.SYSTEM_PYTHON, "-I", str(script), "--help"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plist = tmp_path / "agent.plist"
    plist.write_bytes(plistlib.dumps(watch.plist_for(tmp_path / "copy.py", tmp_path)))
    assert subprocess.run(["plutil", "-lint", str(plist)], capture_output=True).returncode == 0
