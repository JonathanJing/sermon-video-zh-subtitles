"""tools/ops/weekly_auto.py: from a Drive trigger to an approved English table, offline.

ffmpeg, ffprobe, the Drive download and the paid transcription are replaced; the Layer 1 scripts
and the gate store run for real, so the test covers what the files on disk end up saying.
"""
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ops"))
import review_gates  # noqa: E402
import weekly_auto  # noqa: E402
from weekly_auto_helpers import SENTENCES, write_transcript, write_wav  # noqa: E402

FOLDER = "1PsAKaZhYCXsNfzYFkFBTng66N1tPw1sF"
MEDIA = b"\x00\x00\x00 ftypmp42" + b"v" * 5000
REVIEWER = {"login": "me@example.com", "name": "Me", "source": "tailscale"}
BASE = "https://mac.tailnet-name.ts.net:8444"


def trigger(size=len(MEDIA), mime="video/mp4", file_id="1cXDkbTESTfileid0000000000000000a", folder=FOLDER):
    return {"schemaVersion": "sermon-drive-upload-trigger-v1", "folderId": folder, "folderUrl": f"https://drive.google.com/drive/folders/{folder}",
            "file": {"id": file_id, "name": "Saturday_400pm_Live__1080.mp4", "mime": mime, "sizeBytes": size,
                     "earliestTimePT": "2026-11-21T19:20:00-08:00", "latestTimePT": "2026-11-21T19:22:27-08:00",
                     "url": f"https://drive.google.com/file/d/{file_id}/view"},
            "window": "2026-11-21", "sunday": "2026-11-22", "firstSeenPT": "2026-11-21T19:22:40-08:00"}


class Notifier:
    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return {"bark-iphone": True, "email": message.level != "passive"}

    def titles(self):
        return [message.title for message in self.messages]


class Response:
    def __init__(self, body, status=200, content_type="video/mp4"):
        self.body, self.status, self.headers, self.offset = body, status, {"Content-Type": content_type}, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        block = self.body[self.offset:self.offset + size] if size > 0 else self.body[self.offset:]
        self.offset += len(block)
        return block


class Opener:
    def __init__(self, responder=None):
        self.requests, self.responder = [], responder or (lambda request: Response(MEDIA))

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return self.responder(request)


class Run:
    """ffmpeg/ffprobe/transcription are faked; every other step runs for real."""

    def __init__(self, transcribe_exit=0):
        self.calls, self.transcribe_exit, self.duration = [], transcribe_exit, 26.0

    def __call__(self, command, **kwargs):
        name = Path(command[0]).name
        done = lambda code=0, out="", err="": subprocess.CompletedProcess(command, code, stdout=out, stderr=err)
        if name == "ffprobe":
            self.calls.append("ffprobe")
            return done(out=f"{self.duration}\n")
        if name == "ffmpeg":
            self.calls.append("ffmpeg")
            target = Path(command[-1])
            write_wav(target, self.duration) if target.suffix == ".wav" else target.write_bytes(b"mp3")
            return done()
        if any("run_with_openai_environment.py" in part for part in command):
            self.calls.append("transcribe")
            self.launcher = command
            if self.transcribe_exit:
                return done(self.transcribe_exit, err="APIConnectionError: timed out")
            write_transcript(Path(command[command.index("--out") + 1]))
            return done()
        self.calls.append(Path(command[1]).name + ":" + command[2] if command[2] in ("build", "revise") else Path(command[1]).name)
        kwargs.pop("env", None)
        return subprocess.run(command, **kwargs)


@pytest.fixture
def driver(tmp_path):
    config = json.loads((ROOT / "config" / "weekly-sermon-auto.json").read_text(encoding="utf-8"))
    config["source"]["minBytes"] = 1000
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    (tmp_path / "artifacts" / "model-routing" / "macbook-tts" / "checkpoint-75d28").mkdir(parents=True)
    return weekly_auto.Driver(tmp_path, config_path=path, local={"reviewBaseUrl": BASE}, run=Run(), opener=Opener(),
                              notifier=Notifier(), python=sys.executable, sleep=lambda seconds: None,
                              today=lambda: dt.date(2026, 11, 25))


def start(driver, **kwargs):
    record = driver.start(trigger(**{k: v for k, v in kwargs.items() if k in ("size", "mime", "folder")}),
                          rehearsal=kwargs.get("rehearsal", False))
    return driver.advance(record["production"])


def submit(driver, production, gate_id, payload, *, verdict="approved", key="k" * 20, checks=None, note=""):
    gate = driver.store.descriptor(production, gate_id, REVIEWER)
    names = {"decisions": ("speaker", "workload", "frozen"),
             "english": ("sourceIdentity", "transcriptCompleteness", "wordAlignment", "sentenceAndPauseBoundaries", "window")}[gate["kind"]]
    decision = {"schemaVersion": "sermon-review-decision-v1", "gateId": gate_id, "kind": gate["kind"], "production": production,
                "locale": None, "revision": gate["revision"], "bindings": gate["bindings"], "verdict": verdict,
                "checks": checks or {name: verdict == "approved" for name in names}, "payload": payload, "note": note,
                "idempotencyKey": key, "client": {"submittedAt": "2026-11-22T04:00:00Z", "userAgent": "test"}}
    return driver.store.record_decision(decision, REVIEWER)


def kickoff_payload(driver, production, **changes):
    data = driver.store.descriptor(production, "l0.decisions", REVIEWER)["data"]
    payload = {"decisions": {choice["key"]: choice["value"] for choice in data["choices"]},
               "title": {"basis": data["title"]["basis"], "english": data["title"]["english"], "format": "title_only", "titles": data["title"]["titles"]},
               "window": {"start": data["window"]["start"], "end": data["window"]["end"]},
               "deliverables": [{"n": d["n"], "deliver": True, "reason": None} for d in data["deliverables"]], "changedFromDefaults": []}
    payload.update(changes)
    return payload


def test_a_new_file_runs_by_itself_up_to_the_two_review_steps(driver, tmp_path):
    record = start(driver)
    assert record["production"] == "20261121-sermon" and record["state"] == "running"
    assert {name: s["state"] for name, s in record["stages"].items()} == {
        **{name: "done" for name in weekly_auto.STAGES[:9]}, "wait.review": "waiting"}
    run = tmp_path / "artifacts" / "sentence-first-agent" / "20261121-sermon-source"
    identity = json.loads((run / "source" / "source.json").read_text())
    assert identity["sizeBytes"] == len(MEDIA) and identity["sha256"] == weekly_auto.sha256_file(run / "source" / "episode.mp4")
    assert identity["authorization"]["statement"] == "自动下载的来源授权，默认是周日的正式播放版，自动开始生产"
    request = driver.opener.requests[0]
    assert "id=1cXDkbTESTfileid0000000000000000a" in request.full_url and request.get_header("Range") is None
    gates = {gate["gateId"]: gate for gate in driver.store.gates("20261121-sermon")}
    assert list(gates) == ["l0.decisions", "l1.english-review"] and all(gate["state"] == "open" for gate in gates.values())
    kickoff = driver.store.descriptor("20261121-sermon", "l0.decisions", REVIEWER)
    assert kickoff["data"]["title"]["english"] == "Jesus will return" and kickoff["data"]["title"]["basis"] == "title_table"
    speaker = next(c for c in kickoff["data"]["choices"] if c["key"] == "speakerId")
    assert speaker["value"] == "eric_geiger" and next(o for o in speaker["options"] if o["value"] == "eric_geiger")["checkpointReady"]
    assert (run / "review" / "decisions" / "window" / "head.mp3").is_file()
    english = driver.store.descriptor("20261121-sermon", "l1.english-review", REVIEWER)
    assert [row["english"] for row in english["data"]["rows"]] == SENTENCES
    assert english["bindings"]["sourceMediaSha256"] == identity["sha256"] and (run / "review" / "english" / "slices" / "u0007.wav").is_file()
    titles = driver.notifier().titles()
    assert titles == ["[同行] 已自动开工 · 2026-11-22", "[同行] 待确认 · 开工决定", "[同行] 待批准 · 英文表"]
    opened = driver.notifier().messages[2]
    assert opened.url == f"{BASE}/english.html?production=20261121-sermon&gate=l1.english-review" and opened.level == "active"
    assert "7 句" in opened.body and "/Users" not in opened.body
    assert json.loads((tmp_path / "artifacts/weekly-auto/20261121-sermon/production.json").read_text())["worker"]["state"] == "等待"
    assert driver.advance("20261121-sermon")["stages"]["wait.review"]["state"] == "waiting" and driver.notifier().titles() == titles


def test_transcription_is_reserved_settled_and_goes_through_the_launcher(driver, tmp_path):
    start(driver)
    ledgers = sorted(path.name for path in (tmp_path / "artifacts/weekly-auto/budget").iterdir())
    assert ledgers == ["openai-2026-W48.json"], "the week the money is spent in (2026-11-25), not the sermon's week (W47)"
    ledger = json.loads((tmp_path / "artifacts/weekly-auto/budget/openai-2026-W48.json").read_text())
    entry = ledger["entries"][0]
    assert (entry["state"], entry["stage"], ledger["capUsd"]) == ("settled", "l1.transcribe", 50)
    assert entry["reservedUsd"] == round(26.0 / 60 * 0.006 * 4, 4) and 0 < entry["actualUsd"] < entry["reservedUsd"]
    launcher = driver.run_command.launcher
    assert launcher[launcher.index("--environment") + 1] == "prod" and launcher[launcher.index("--env-file") + 1] == str(tmp_path / ".env.openai")
    assert "--prompt-file" in launcher and not any(part.startswith("sk-") for part in launcher)
    assert 'Episode: "Jesus will return".' in (tmp_path / "artifacts/sentence-first-agent/20261121-sermon-source/layer1/prompt.txt").read_text()
    assert driver.run_command.calls.count("transcribe") == 1


def test_page_decisions_produce_the_kickoff_record_and_an_approved_english_package(driver, tmp_path, monkeypatch):
    start(driver)
    name = "20261121-sermon"
    submit(driver, name, "l0.decisions", kickoff_payload(driver, name), key="a" * 20)
    submit(driver, name, "l1.english-review", {"edits": {"replace": {"u0003": "The writer says the city had twelve gates."}, "drop": ["u0007"]},
                                               "heardUnitIds": ["u0003", "u0004"]}, key="b" * 20)
    record = driver.advance(name)
    assert record["state"] == "layer1_ready" and record["stages"]["handoff"]["state"] == "done"
    assert [g["state"] for g in driver.store.gates(name)] == ["applied", "applied"]
    folder = tmp_path / "artifacts/weekly-auto" / name
    kickoff = json.loads((folder / "kickoff.json").read_text())
    assert kickoff["humanApproval"] is True and kickoff["decidedBy"] == REVIEWER and kickoff["decisions"]["locales"] == ["zh-Hans", "ko", "es"]
    assert kickoff["authority"]["statement"] == "页面上的提交算正式结论"
    layer1 = tmp_path / "artifacts/sentence-first-agent" / f"{name}-source" / "layer1"
    package = json.loads((layer1 / "english-source.json").read_text())
    assert (package["status"], package["translationEligible"], package["review"]["humanApproval"]) == ("ready_for_translation", True, True)
    assert [u["english"] for u in package["units"]] == [*SENTENCES[:2], "The writer says the city had twelve gates.", *SENTENCES[3:6]]
    assert package["review"]["reviewer"] == "Me (tailscale, review page)"
    candidate = json.loads((layer1 / "candidate" / "anchor-manifest.json").read_text())
    assert package["review"]["decision"]["candidateAnchorManifestJsonSha256"] == weekly_auto.json_sha(candidate)
    assert package["anchors"]["artifact"]["jsonSha256"] != weekly_auto.json_sha(candidate), "the receipt binds the revised table"
    last = driver.store.last_decision(name, "l1.english-review")
    assert last["outcome"] == "applied" and last["receiptSha256"] == weekly_auto.sha256_file(layer1 / "english-approval-receipt.json")
    assert "还没有自动化" in last["nextStage"]
    sys.path.insert(0, str(ROOT / "experiments" / "sentence-first-agent"))
    import preflight
    report = preflight.Report()
    preflight.check_english_package(layer1 / "english-source.json", {"sentences": [{"sourceUnitId": u["sourceUnitId"]} for u in package["units"]]}, report, tmp_path)
    assert report.result()["status"] == "pass", report.result()["errors"]
    following = json.loads((folder / "next-step.json").read_text())
    assert following["sfaStart"] == {"locales": ["zh-Hans", "ko", "es"], "units": "0:5", "windowStart": 0.0, "sync": True, "publish": True}
    assert driver.notifier().titles()[3:] == ["[同行] 已生效 · 开工决定", "[同行] 已生效 · 英文表"]
    assert all(m.level == "passive" for m in driver.notifier().messages[3:])
    events = [json.loads(line)["event"] for line in (folder / "events.ndjson").read_text().splitlines()]
    assert events.count("decision.handled") == 2
    journal = [(row["stage"], row["event"]) for row in map(json.loads, (folder / "journal.ndjson").read_text().splitlines())]
    assert journal[:2] == [("source.accept", "started"), ("source.accept", "finished")]
    assert [event for stage, event in journal if stage == "wait.review"] == ["started", "waiting", "finished"], "waiting for a person is journalled once"
    assert journal[-1] == ("handoff", "finished") and len(journal) == 2 * len(weekly_auto.STAGES) + 1
    outcome = json.loads((folder / "outcome.json").read_text())
    assert (outcome["status"], outcome["exitCode"], outcome["humanApproval"], outcome["rehearsal"]) == ("layer1_ready", 0, True, False)


def test_a_rehearsal_goes_all_the_way_and_approves_nothing(driver, tmp_path):
    record = start(driver, rehearsal=True)
    name = record["production"]
    assert name.startswith("rehearsal-") and all(title.startswith("[同行·演练] ") for title in driver.notifier().titles())
    submit(driver, name, "l0.decisions", kickoff_payload(driver, name), key="a" * 20)
    submit(driver, name, "l1.english-review", {"edits": {}, "heardUnitIds": []}, key="b" * 20)
    record = driver.advance(name)
    assert record["state"] == "rehearsal_complete"
    package = json.loads((tmp_path / "artifacts/sentence-first-agent" / f"{name}-source" / "layer1" / "english-source.json").read_text())
    assert (package["status"], package["translationEligible"], package["review"]["humanApproval"]) == ("rehearsal_not_for_translation", False, False)
    assert json.loads((tmp_path / "artifacts/weekly-auto" / name / "kickoff.json").read_text())["humanApproval"] is False
    assert "不能用于翻译或发布" in json.loads((tmp_path / "artifacts/weekly-auto" / name / "next-step.json").read_text())["note"]
    outcome = json.loads((tmp_path / "artifacts/weekly-auto" / name / "outcome.json").read_text())
    assert (outcome["status"], outcome["humanApproval"], outcome["deliveryType"]) == ("rehearsal_complete", False, "test (rehearsal)")


def test_a_decision_about_a_table_that_changed_is_rejected_and_approves_nothing(driver, tmp_path):
    start(driver)
    name = "20261121-sermon"
    submit(driver, name, "l1.english-review", {"edits": {}}, key="b" * 20)
    candidate = tmp_path / "artifacts/sentence-first-agent" / f"{name}-source" / "layer1" / "candidate" / "anchor-manifest.json"
    manifest = json.loads(candidate.read_text())
    manifest["sourceUnits"][0]["english"] = "Changed after the reviewer saw it."
    candidate.write_text(json.dumps(manifest))
    record = driver.advance(name)
    last = driver.store.last_decision(name, "l1.english-review")
    assert last["outcome"] == "rejected_stale" and last["receiptSha256"] is None
    assert driver.store.gate(name, "l1.english-review")["state"] == "stale" and record["stages"]["wait.review"]["state"] == "waiting"
    assert not (candidate.parent.parent / "english-source.json").exists()
    assert driver.notifier().messages[-1].title == "[同行] 决定没有生效 · 英文表" and driver.notifier().messages[-1].level == "timeSensitive"


def test_kickoff_choices_the_driver_cannot_carry_out_are_reported_not_approved(driver, tmp_path):
    start(driver)
    name = "20261121-sermon"
    submit(driver, name, "l0.decisions", kickoff_payload(driver, name, window={"start": 30.0, "end": 26.0}), key="a" * 20)
    driver.advance(name)
    outcome = driver.store.last_decision(name, "l0.decisions")
    assert outcome["outcome"] == "failed" and "整段媒体" in outcome["message"]
    assert not (tmp_path / "artifacts/weekly-auto" / name / "kickoff.json").exists()
    assert driver.notifier().messages[-1].title == "[同行] 决定没能应用 · 开工决定"


def test_a_request_for_changes_waits_and_a_rebuild_opens_a_new_revision(driver, tmp_path):
    start(driver)
    name = "20261121-sermon"
    submit(driver, name, "l1.english-review", {"edits": {"drop": ["u0005"]}}, verdict="changes_requested", note="第 5 句是掌声", key="b" * 20)
    driver.advance(name)
    assert driver.store.gate(name, "l1.english-review")["state"] == "changes_requested"
    assert driver.notifier().messages[-1].title == "[同行] 已收到修改要求 · 英文表"
    fixes = tmp_path / "fixes.json"
    fixes.write_text(json.dumps({"drop": ["u0005"]}))
    assert weekly_auto.main(["--work-root", str(tmp_path), "--config", str(driver.config_path), "--no-push", "status"]) == 0
    layer1 = tmp_path / "artifacts/sentence-first-agent" / f"{name}-source" / "layer1"
    (layer1 / "english-fixes.json").write_text(fixes.read_text())
    record = driver.store.production(name)
    import shutil
    shutil.rmtree(layer1 / "candidate")
    for stage in ("l1.anchor", "l1.rows", "gate.english", "wait.review"):
        record["stages"].pop(stage)
    driver.save(record)
    driver.advance(name)
    gate = driver.store.descriptor(name, "l1.english-review", REVIEWER)
    assert (gate["revision"], gate["state"], len(gate["data"]["rows"])) == (2, "open", 6)
    assert driver.notifier().titles().count("[同行] 待批准 · 英文表") == 2, "a new revision is announced again"


@pytest.mark.parametrize("kwargs, reason", [({"mime": "application/pdf"}, "不是视频文件"), ({"size": 10}, "不像一场证道"),
                                            ({"folder": "anotherFolderId000000000000000000"}, "不在授权的来源文件夹里")])
def test_a_file_that_is_not_this_weeks_sermon_is_not_downloaded(driver, kwargs, reason):
    record = start(driver, **kwargs)
    assert record["state"] == "blocked" and record["stages"]["source.accept"]["state"] == "failed"
    assert driver.opener.requests == [] and driver.run_command.calls == []
    message = driver.notifier().messages[-1]
    assert message.title == "[同行] 新文件没有开工" and reason in message.body and message.level == "timeSensitive"
    assert driver.advance(record["production"])["stages"]["source.accept"]["state"] == "failed" and len(driver.notifier().messages) == 1


def test_over_the_weekly_cap_nothing_is_sent(driver, tmp_path):
    driver.config["budget"]["weeklyCapUsd"] = 0.001
    record = start(driver)
    assert record["stages"]["l1.transcribe"]["state"] == "failed" and "transcribe" not in driver.run_command.calls
    message = driver.notifier().messages[-1]
    assert message.title == "[同行] 转写没有开始 · 预算上限" and "0.001" in message.body and "没有发出付费请求" in message.body
    assert list((tmp_path / "artifacts/weekly-auto").glob("budget/*.json")) == [], "nothing was reserved"


def test_an_unclear_paid_result_stops_paid_work_until_it_is_reconciled(driver, tmp_path):
    driver.run_command.transcribe_exit = 1
    record = start(driver)
    name = record["production"]
    assert record["stages"]["l1.transcribe"]["errorClass"] == "unknown_outcome"
    message = driver.notifier().messages[-1]
    assert (message.title, message.level, message.volume) == ("[同行] 付费请求结果未知 · 英文转写", "critical", "0")
    driver.run_command.transcribe_exit = 0
    again = driver.advance(name, retry=True)
    assert again["stages"]["l1.transcribe"]["state"] == "failed" and driver.run_command.calls.count("transcribe") == 1, "still unknown: nothing new is sent"
    outcome = json.loads((tmp_path / "artifacts/weekly-auto" / name / "outcome.json").read_text())
    assert (outcome["status"], outcome["exitCode"], outcome["failedStages"]) == ("blocked", 1, {"l1.transcribe": "unknown_outcome"})
    assert weekly_auto.main(["--work-root", str(tmp_path), "--config", str(driver.config_path), "--no-push",
                             "reconcile", "--production", name, "--outcome", "not_charged"]) == 0
    done = driver.advance(name, retry=True)
    assert done["stages"]["l1.transcribe"]["state"] == "done" and driver.run_command.calls.count("transcribe") == 2
    states = [e["state"] for e in json.loads(next((tmp_path / "artifacts/weekly-auto/budget").glob("*.json")).read_text())["entries"]]
    assert states == ["released", "settled"]


def test_download_resumes_and_refuses_a_page_or_a_short_file(driver, tmp_path):
    record = driver.start(trigger())
    target = tmp_path / "episode.mp4"
    target.with_name("episode.mp4.part").write_bytes(MEDIA[:2000])
    driver.opener = Opener(lambda request: Response(MEDIA[2000:], status=206))
    driver.download(record, target)
    assert target.read_bytes() == MEDIA and driver.opener.requests[0].get_header("Range") == "bytes=2000-"
    for responder, text in ((lambda request: Response(b"<html>quota</html>", content_type="text/html; charset=utf-8"), "网页"),
                            (lambda request: Response(MEDIA[:100]), "大小")):
        target.unlink(missing_ok=True)
        target.with_name("episode.mp4.part").unlink(missing_ok=True)
        driver.opener = Opener(responder)
        with pytest.raises(weekly_auto.StageError) as failure:
            driver.download(record, target)
        assert failure.value.event == "source.download_failed" and text in failure.value.fields["reason"] and not target.exists()


def test_one_reminder_after_the_waiting_time(driver, monkeypatch):
    start(driver)
    name = "20261121-sermon"
    gate = driver.store.gate(name, "l1.english-review")
    opened = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=45)
    driver.store.set_state(name, "l1.english-review", "open", openedAt=opened.isoformat(timespec="seconds"))
    monkeypatch.setattr(weekly_auto.notices, "reminder_due", lambda kind, at, now, sent: kind == "english" and sent == 0)
    driver.advance(name)
    driver.advance(name)
    reminders = [m for m in driver.notifier().messages if m.title == "[同行] 还在等你 · 英文表"]
    assert len(reminders) == 1 and "45 分钟" in reminders[0].body and reminders[0].url.endswith("gate=l1.english-review")
    assert gate["revision"] == 1


def test_a_notice_no_channel_took_is_sent_again_on_the_next_run(driver):
    class Flaky(Notifier):
        fail = 2

        def send(self, message):
            self.messages.append(message)
            if Flaky.fail:
                Flaky.fail -= 1
                return {"bark-iphone": False, "email": False}
            return {"bark-iphone": True}

    driver._notifier = Flaky()
    record = start(driver)                       # started + kickoff notice both fail, the English one is delivered
    assert sorted(record["outbox"]) == ["gate.opened:20261121-sermon:l0.decisions:-", "production.started:20261121-sermon:-:-"]
    assert record["notices"]["gate.opened:20261121-sermon:l1.english-review:1"]["delivered"] is True
    again = driver.advance("20261121-sermon")
    assert again["outbox"] == {} and len(driver.notifier().messages) == 5
    kickoff = again["notices"]["gate.opened:20261121-sermon:l0.decisions:-"]
    assert (kickoff["delivered"], kickoff["attempts"]) == (True, 2)
    assert len(driver.advance("20261121-sermon")["notices"]) == 3 and len(driver.notifier().messages) == 5


def test_pending_starts_each_trigger_once(driver, tmp_path, capsys):
    folder = tmp_path / "triggers"
    folder.mkdir()
    (folder / "1cXDkbTESTfileid0000000000000000a.json").write_text(json.dumps(trigger()))
    (folder / "notes.json").write_text(json.dumps({"schemaVersion": "something-else"}))
    args = weekly_auto.build_parser().parse_args(["pending", "--triggers", str(folder)])
    assert weekly_auto.cmd_pending(driver, args) == 0 and weekly_auto.cmd_pending(driver, args) == 0
    assert driver.store.productions() == ["20261121-sermon"] and driver.opener.requests and len(driver.opener.requests) == 1
    assert driver.run_command.calls.count("transcribe") == 1


def test_launch_agents_run_the_service_and_the_driver_from_this_checkout(driver, tmp_path):
    plists = weekly_auto.agent_plists(tmp_path, 8444, "/venv/bin/python", "mac.tailnet-name.ts.net")
    review, drive = plists[weekly_auto.LABEL_REVIEW], plists[weekly_auto.LABEL_DRIVER]
    assert review["KeepAlive"] is True and review["ProgramArguments"][1].endswith("tools/ops/review_gate_server.py")
    assert review["ProgramArguments"][2:] == ["serve", "--work-root", str(tmp_path), "--port", "8444", "--allow-host", "mac.tailnet-name.ts.net"]
    assert "--allow-host" not in weekly_auto.agent_plists(tmp_path, 8444, "/venv/bin/python")[weekly_auto.LABEL_REVIEW]["ProgramArguments"]
    assert drive["WatchPaths"] == [str(weekly_auto.TRIGGERS)] and drive["StartInterval"] == 300
    assert drive["ProgramArguments"][:2] == ["/usr/bin/caffeinate", "-i"] and drive["ProgramArguments"][-1] == "pending"
    assert "/opt/homebrew/bin" in drive["EnvironmentVariables"]["PATH"]
    import plistlib
    for plist in plists.values():
        assert plistlib.loads(plistlib.dumps(plist)) == plist


def test_title_table_and_speaker_registry_are_read_for_the_kickoff_page(driver):
    row = driver.title_row("2026-11-22")
    assert (row["week"], row["english"], row["speaker"], row["titles"]["zh-Hans"]) == (11, "Jesus will return", "Eric Geiger", "耶稣必再来")
    assert row["series"].startswith("启示录") and driver.title_row("2031-01-05") is None
    options = {option["value"]: option for option in driver.speaker_options()}
    assert options["eric_geiger"]["locales"] == ["zh-Hans", "ko", "es"] and options["eric_geiger"]["checkpointReady"] is True
    assert driver.page_url({"production": "p"}) == f"{BASE}/index.html?production=p"
