"""tools/ops/weekly_auto.py after the track reviews: the page configuration, the publish authorization,
the two guarded deployments, the gate and the confirmation.

sfa_publish.py, the fingerprint tool, the alignment tools and the publish gate are replaced; the driver,
the gate store and the page configuration run for real. Nothing here touches a network.
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ops"))
import weekly_auto  # noqa: E402
import weekly_auto_publish as wp  # noqa: E402
from test_weekly_auto import BASE, REVIEWER, Notifier, Opener, kickoff_payload, start, submit, trigger  # noqa: E402
from test_weekly_auto_tracks import NAME, TrackRun, approve_track, mark  # noqa: E402

PAGE = "revelation-jesus-will-return-20261122"
ORIGIN = "https://example.invalid"


class PublishRun(TrackRun):
    """Adds the publish tools. `fail` names steps that exit 1 (a `publish` that fails leaves an attempt that is not deployed)."""

    def __init__(self, fail=(), **options):
        super().__init__(**options)
        self.fail, self.order, self.env, self.commands = set(fail), [], {}, {}

    def __call__(self, command, **kwargs):
        script = Path(command[1]).name if len(command) > 1 else ""
        done = lambda code=0, out="", err="": subprocess.CompletedProcess(command, code, stdout=out, stderr=err)
        arg = lambda name: Path(command[command.index(name) + 1])
        line = lambda value: json.dumps(value) + "\n"
        if script == "sfa_publish.py":
            config = json.loads(arg("--config").read_text())
            action = command[4]
            self.order.append(action)
            self.commands[action] = [str(part) for part in command]
            self.env[action] = {key: value for key, value in (kwargs.get("env") or {}).items() if key in ("SFA_RUN_REPORT", "SFA_READING_PDF")}
            if action in self.fail:
                if action == "publish":
                    (arg("--snapshot") / "deployment-attempt-v2.json").write_text(json.dumps({"status": "started"}))
                return done(1, line({"ok": False, "error": "refused"}), f"sfa_publish: {action} refused")
            if action == "preflight":
                return done(out=line({"ok": True, "pageId": config["pageId"], "environment": config["environment"], "origin": ORIGIN,
                                      "locales": config["locales"], "englishSourceJsonSha256": "ab" * 32,
                                      "titleCheck": {"mode": config["titleCheck"]["mode"], "week": 11}, "warnings": []}))
            if action == "assets":
                out = arg("--out")
                for locale in config["locales"]:
                    (out / "releases").mkdir(parents=True, exist_ok=True)
                    (out / "releases" / f"{locale}.json").write_text(json.dumps({"pageId": config["pageId"], "targetLocale": locale}))
                    media = out / "public" / "media" / config["pageId"]
                    media.mkdir(parents=True, exist_ok=True)
                    (media / f"{locale}.mp3").write_bytes(f"mp3 {locale}".encode())
            if action in ("baseline", "stage1", "stage2"):
                out = arg("--out")
                (out / "public").mkdir(parents=True)
                (out / "seal-report.json").write_text(json.dumps({"snapshot": out.name, "sealed": action}))
            if action == "verify":
                arg("--out").write_text(json.dumps({"status": "pass"}))
            if action == "publish":
                (arg("--snapshot") / "deployment-attempt-v2.json").write_text(json.dumps({"status": "deployed"}))
                return done(out=line({"status": "deployed", "newVersion": f"v-{arg('--snapshot').name}", "baselineVersion": "v0", "catalogSha256": "cd" * 32}))
            return done(out=line({"ok": True, "action": action}))
        if command[0] == "node":
            out = arg("--out")
            assert not out.exists(), "the fingerprint tool refuses an existing output"
            mode = command[command.index("--mode") + 1]
            out.write_text(json.dumps({"mode": mode, "argv": [str(part) for part in command[2:]]}))
            self.order.append(f"fingerprint:{mode}")
            import hashlib
            return done(out=line({"path": str(out), "sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "bytes": 10, "landmarks": 5, "mode": mode}))
        if script == "build_alignment_sidecar.py":
            self.order.append("sidecar")
            self.sidecar = [str(part) for part in command]
            return done()
        if script == "run.py" and "delivery.published_alignment_catalog" in command:
            self.order.append("bind-catalogs")
            return done(out=line({"pageId": PAGE, "catalogs": []}))
        if script == "reseal_snapshot.py":
            self.order.append("reseal")
            (arg("--snapshot") / "seal-report.json").write_text(json.dumps({"sealed": "again"}))
            return done()
        if script == "sfa_publish_gate.py":
            self.order.append("gate")
            self.gate = [str(part) for part in command]
            failed = "gate" in self.fail
            arg("--json-out").write_text(json.dumps({"schemaVersion": "sentence-first-publish-gate-v1", "status": "fail" if failed else "pass",
                                                     "failed": ["zh-Hans.content.hash"] if failed else [], "checks": [
                {"check": "catalog.page", "ok": True, "required": True, "detail": ""},
                {"check": "zh-Hans.content.hash", "ok": not failed, "required": True, "detail": ""}]}))
            return done(1 if failed else 0, err="FAIL zh-Hans.content.hash" if failed else "")
        return super().__call__(command, **kwargs)


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("SFA_CLAUDE_BIN", str(ROOT / "tests" / "fake_claude.py"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.ndjson"))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")

    def build(through="publish", **run_options):
        config = json.loads((ROOT / "config" / "weekly-sermon-auto.json").read_text(encoding="utf-8"))
        config["source"]["minBytes"] = 1000
        config["automation"]["through"] = through
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))
        (tmp_path / "ckpt" / "checkpoint-75d28").mkdir(parents=True, exist_ok=True)
        driver = weekly_auto.Driver(tmp_path, config_path=path, local={"reviewBaseUrl": BASE, "ttsPython": "tts-python", "ttsRuntime": str(tmp_path / "ckpt")},
                                    run=PublishRun(**run_options), opener=Opener(), notifier=Notifier(), python=sys.executable,
                                    sleep=lambda seconds: None)
        driver.code_root = tmp_path
        return driver
    return build


def to_authorization(driver, rehearsal=False, **kickoff_changes):
    """Everything up to the point where the page waits for the reviewer's authorization."""
    if rehearsal:
        driver.start(trigger(), rehearsal=True, production=NAME)
        driver.advance(NAME)
    else:
        start(driver)
    payload = kickoff_payload(driver, NAME)
    payload["decisions"].update(kickoff_changes.pop("decisions", {}))
    payload.update(kickoff_changes)
    submit(driver, NAME, "l0.decisions", payload, key="a" * 20)
    submit(driver, NAME, "l1.english-review", {"edits": {}, "heardUnitIds": []}, key="b" * 20)
    driver.advance(NAME)
    for locale in ("zh-Hans", "ko", "es"):
        approve_track(driver, locale)
    return driver.advance(NAME)


def decide(driver, gate_id, payload, verdict="approved", key="p" * 20, checks=("metadata", "reviewed", "deployments", "otherPages")):
    gate = driver.store.descriptor(NAME, gate_id, REVIEWER)
    return driver.store.record_decision({
        "schemaVersion": "sermon-review-decision-v1", "gateId": gate_id, "kind": gate["kind"], "production": NAME, "locale": None,
        "revision": gate["revision"], "bindings": gate["bindings"], "verdict": verdict, "checks": {name: verdict == "approved" for name in checks},
        "payload": payload, "note": "" if verdict == "approved" else "先不发", "idempotencyKey": key,
        "client": {"submittedAt": "2026-11-22T07:00:00Z", "userAgent": "t"}}, REVIEWER)


def authorize(driver, **kwargs):
    data = driver.store.descriptor(NAME, "l4.publish.authorization", REVIEWER)["data"]
    return decide(driver, "l4.publish.authorization", {"intentId": data["intent"]["id"], "pageId": data["intent"]["pageId"],
                                                       "environment": data["intent"]["environment"],
                                                       "authorizedDeployments": [d["n"] for d in data["deployments"]]}, **kwargs)


def publish_calls(driver):
    return [name for name in driver.run_command.order if name == "publish"]


def test_after_the_track_reviews_the_page_is_prepared_and_nothing_is_deployed_before_the_authorization(make, tmp_path):
    driver = make()
    record = to_authorization(driver)
    stages = {name: s["state"] for name, s in record["stages"].items()}
    assert stages["gate.publish"] == "done" and stages["wait.publish"] == "waiting" and "l4.deploy1" not in stages
    run = driver.run_command
    assert run.order == ["validate", "preflight", "assets", "fingerprint:precompute", "fingerprint:bind", "fingerprint:bind", "fingerprint:bind",
                         "baseline", "stage1", "publish-check"] and publish_calls(driver) == []
    pub = tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-publish"
    page = json.loads((pub / "page-config.json").read_text())
    assert (page["pageId"], page["environment"], page["locales"], page["speakers"]) == (PAGE, "production", ["zh-Hans", "ko", "es"], "Eric Geiger")
    assert page["meta"]["ko"]["scripture"] == "요한계시록 19:11-21:8" and page["meta"]["zh-Hans"]["title"] == "耶稣必再来"
    assert page["runs"]["es"] == f"{NAME}-es" and page["verdict"].endswith(f"{NAME}-review/human-review-verdict.json")
    assert page["titleCheck"]["mode"] == "approved_exception" and REVIEWER["name"] in page["titleCheck"]["approvedBy"]
    assert page["sentences"] == 7 and page["source"]["window"]["end"] == 26.0
    intent = json.loads((pub / "publish-intent.json").read_text())
    assert [row["deliver"] for row in intent["deliverables"]] == [True, True, True, True, True, False, False]
    assert "还没有接到自动流程" in intent["deliverables"][5]["reason"] and "赞踩和收听统计不可用" in intent["deliverables"][6]["reason"]
    gate = driver.store.descriptor(NAME, "l4.publish.authorization", REVIEWER)
    assert gate["state"] == "open" and gate["kind"] == "publish"
    assert set(gate["bindings"]) == {"publishIntentId", "stage1SealSha256", "release.zh-Hans", "release.ko", "release.es", "humanReviewVerdictSha256"}
    data = gate["data"]
    assert data["intent"]["pageId"] == PAGE and data["intent"]["origin"] == ORIGIN and [d["n"] for d in data["deployments"]] == [1, 2]
    assert not data["deployments"][0]["touchesOtherPages"] and data["deployments"][1]["touchesOtherPages"]
    assert f"/alignment/{PAGE}.json" in data["deployments"][1]["changes"] and f"/english-reference/{PAGE}.json" in data["deployments"][1]["changes"]
    assert [item["ok"] for item in data["preconditions"]] == [True, True, None, True, True, None, None], "what was not checked says so"
    assert data["page"]["locales"][2]["url"] == f"{ORIGIN}/pages/{PAGE}/es/index.html"
    assert any("研读手册条目" in text for text in data["afterPublish"]) and any("统计目录" in text for text in data["afterPublish"])
    assert driver.notifier().titles()[-1] == "[同行] 待授权 · 发布"
    # the fingerprint binds the MP3 that will be published, on the exact window of the page
    bound = json.loads((pub / "alignment" / "index-ko.json").read_text())["argv"]
    assert bound[bound.index("--track") + 1].endswith(f"assets/public/media/{PAGE}/ko.mp3") and bound[bound.index("--end") + 1] == "26.0"


def test_an_authorization_makes_exactly_the_two_deployments_then_the_gate_then_the_confirmation(make, tmp_path):
    driver = make()
    to_authorization(driver)
    authorize(driver)
    record = driver.advance(NAME)
    run = driver.run_command
    after = run.order[run.order.index("publish-check") + 1:]
    assert after == ["publish", "verify", "stage2", "sidecar", "bind-catalogs", "reseal", "publish-check", "publish", "readback", "gate"], \
        "the seal is made again after the catalogs were bound, and before the second deployment"
    assert "--with-english" in run.commands["stage2"] and "--require-english-reference" in run.commands["publish-check"]
    assert "--require-alignment" in run.gate and run.gate[run.gate.index("--origin") + 1] == ORIGIN and "--require-guide" not in run.gate
    assert run.sidecar.count("--index") == 3 and "--write" in run.sidecar
    assert run.env["readback"] == {}, "a production readback keeps its report and reading-PDF export"
    pub = tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-publish"
    granted = json.loads((tmp_path / "artifacts" / "weekly-auto" / NAME / "publish-authorization.json").read_text())
    assert granted["humanApproval"] is True and granted["authorizedDeployments"] == [1, 2] and granted["authorizedBy"] == REVIEWER
    intent = json.loads((pub / "publish-intent.json").read_text())
    assert intent["deployments"]["1"]["newVersion"] == "v-stage1" and intent["deployments"]["2"]["snapshot"] == "stage2" and intent["gate"]["path"] == "publish-gate.json"
    assert record["stages"]["gate.confirm"]["state"] == "done" and record["stages"]["wait.confirm"]["state"] == "waiting"
    confirm = driver.store.descriptor(NAME, "l4.device-confirm", REVIEWER)
    assert confirm["state"] == "open" and confirm["data"]["pageId"] == PAGE and len(confirm["data"]["locales"]) == 3
    assert len(confirm["data"]["notDelivered"]) == 2 and "没有做浏览器冒烟" in confirm["data"]["published"]["smoke"]
    assert driver.notifier().titles()[-2:] == ["[同行] 已生效 · 发布", "[同行] 已发布 · 请在手机上确认"]
    # the reviewer looks at the page on a device: only then is the production complete
    decide(driver, "l4.device-confirm", {"pageId": PAGE, "locales": {}}, key="q" * 20, checks=("looked",))
    record = driver.advance(NAME)
    assert record["state"] == "published" and record["stages"]["handoff"]["state"] == "done"
    receipt = json.loads((tmp_path / "artifacts" / "weekly-auto" / NAME / "device-confirmation.json").read_text())
    assert receipt["humanApproval"] is True and "不是现场验收" in receipt["scope"]
    assert driver.notifier().titles()[-1] == "[同行] 完成 · 耶稣必再来" and publish_calls(driver) == ["publish", "publish"]
    driver.advance(NAME)
    assert publish_calls(driver) == ["publish", "publish"], "a later run deploys nothing again"


def test_not_now_deploys_nothing(make, tmp_path):
    driver = make()
    to_authorization(driver)
    authorize(driver, verdict="changes_requested")
    record = driver.advance(NAME)
    assert publish_calls(driver) == [] and record["stages"]["wait.publish"]["state"] == "waiting"
    assert not (tmp_path / "artifacts" / "weekly-auto" / NAME / "publish-authorization.json").exists()


def test_an_authorization_for_files_that_changed_since_is_thrown_out_and_asked_again(make, tmp_path):
    driver = make()
    to_authorization(driver)
    first = authorize(driver)
    pub = tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-publish"
    (pub / "stage1" / "seal-report.json").write_text(json.dumps({"sealed": "something else"}))
    record = driver.advance(NAME)
    assert driver.store.outcome(NAME, "l4.publish.authorization", first["decisionId"])["outcome"] == "rejected_stale"
    assert publish_calls(driver) == [] and driver.store.descriptor(NAME, "l4.publish.authorization", REVIEWER)["revision"] == 2
    assert record["stages"]["wait.publish"]["state"] == "waiting"


def test_a_deployment_that_did_not_end_as_deployed_is_never_tried_again(make, tmp_path):
    driver = make(fail={"publish"})
    to_authorization(driver)
    authorize(driver)
    record = driver.advance(NAME)
    assert record["stages"]["l4.deploy1"]["state"] == "failed" and record["state"] == "blocked" and publish_calls(driver) == ["publish"]
    driver.run_command.fail = set()
    record = driver.advance(NAME, retry=True)
    stage = record["stages"]["l4.deploy1"]
    assert stage["state"] == "failed" and stage["errorClass"] == "unknown_outcome" and "不要重试" in stage["message"]
    assert publish_calls(driver) == ["publish"], "the attempt on disk is for a person to reconcile"


def test_a_gate_that_fails_stops_before_the_confirmation_and_says_which_checks(make, tmp_path):
    driver = make(fail={"gate"})
    to_authorization(driver)
    authorize(driver)
    record = driver.advance(NAME)
    stage = record["stages"]["l4.gate"]
    assert stage["state"] == "failed" and stage["errorClass"] == "gate" and "zh-Hans.content.hash" in stage["message"]
    assert "gate.confirm" not in record["stages"] and driver.notifier().titles()[-1] == f"[同行] 发布门禁没过 · {PAGE}"


def test_a_rehearsal_never_reaches_the_publish_stages(make, tmp_path):
    driver = make()
    record = to_authorization(driver, rehearsal=True)
    assert record["state"] == "rehearsal_complete" and not any(name.startswith(("l4.", "gate.publish")) for name in record["stages"])
    assert driver.run_command.order == [] and not (tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-publish").exists()


def test_no_page_was_asked_for_so_none_is_prepared(make, tmp_path):
    driver = make()
    record = to_authorization(driver, decisions={"publish": "none"})
    assert record["state"] == "tracks_ready" and driver.run_command.order == []


def test_an_independent_track_or_an_unticked_alignment_publishes_without_alignment(make, tmp_path):
    driver = make()
    payload_change = [{"n": n, "deliver": n != 5, "reason": "本周不做现场对齐" if n == 5 else None} for n in range(1, 8)]
    to_authorization(driver, deliverables=payload_change)
    assert not [name for name in driver.run_command.order if name.startswith("fingerprint")]
    data = driver.store.descriptor(NAME, "l4.publish.authorization", REVIEWER)["data"]
    assert data["deliverables"][4] == {"n": 5, "label": data["deliverables"][4]["label"], "deliver": False, "state": "ready",
                                       "evidence": wp.EVIDENCE[5], "reason": "本周不做现场对齐"}
    assert not any("alignment" in change for change in data["deployments"][1]["changes"])
    authorize(driver)
    driver.advance(NAME)
    order = driver.run_command.order
    assert "sidecar" not in order and "reseal" not in order and "--require-alignment" not in driver.run_command.gate


def test_the_dev_site_gets_no_report_or_reading_pdf_export(make, tmp_path):
    driver = make()
    to_authorization(driver, decisions={"publish": "dev_review"})
    page = json.loads((tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-publish" / "page-config.json").read_text())
    assert page["environment"] == "dev"
    authorize(driver)
    driver.advance(NAME)
    assert driver.run_command.env["readback"] == {"SFA_RUN_REPORT": "0", "SFA_READING_PDF": "0"}


def test_a_week_the_title_table_does_not_know_stops_at_the_page_configuration(make, tmp_path):
    driver = make()
    start(driver)
    payload = kickoff_payload(driver, NAME)
    payload["title"]["english"] = "A message that is in no table"
    submit(driver, NAME, "l0.decisions", payload, key="a" * 20)
    submit(driver, NAME, "l1.english-review", {"edits": {}, "heardUnitIds": []}, key="b" * 20)
    driver.advance(NAME)
    for locale in ("zh-Hans", "ko", "es"):
        approve_track(driver, locale)
    record = driver.advance(NAME)
    stage = record["stages"]["l4.config"]
    assert stage["state"] == "failed" and stage["errorClass"] == "unsupported" and "标题表" in stage["message"]


@pytest.mark.parametrize("short, expected", [
    ("启 21:9–21", {"zh-Hans": "启示录 21:9–21", "ko": "요한계시록 21:9-21", "es": "Apocalipsis 21:9-21"}),
    ("启 14", {"zh-Hans": "启示录 14", "ko": "요한계시록 14", "es": "Apocalipsis 14"}),
    ("林前 13:1–13", {"zh-Hans": "哥林多前书 13:1–13", "ko": "고린도전서 13:1-13", "es": "1 Corintios 13:1-13"}),
])
def test_scripture_is_written_the_way_each_language_writes_it(short, expected):
    assert wp.scripture_names(short) == expected


def test_what_a_page_cannot_be_built_from_says_what_is_missing():
    assert len(wp.BOOKS) == 66 and len({book["es"] for book in wp.BOOKS.values()}) == 66
    with pytest.raises(wp.PageError, match="认不出书卷"):
        wp.scripture_names("某书 1:1")
    with pytest.raises(wp.PageError, match="认不出书卷"):
        wp.scripture_names(None)
    assert wp.page_id("revelation-comfort-and-hope", "Jesus will make all things new", "2026-11-29") == "revelation-jesus-will-make-all-things-new-20261129"
    assert wp.page_id(None, "Hope & Joy!", "2026-12-06") == "sermon-hope-joy-20261206"
    with pytest.raises(wp.PageError):
        wp.page_id("x", "", "2026-12-06")


def test_the_generated_page_configuration_is_what_was_written_by_hand_for_the_last_published_page():
    old = json.loads((ROOT / "experiments" / "sentence-first-agent" / "pages" / f"{PAGE}.json").read_text(encoding="utf-8"))
    table = (ROOT / "docs" / "series-sermon-titles.zh.md").read_text(encoding="utf-8")
    kickoff = {"decisions": {"locales": ["zh-Hans", "ko", "es"], "sync": "synced"}, "decisionId": "d-1",
               "title": {"english": "Jesus will return", "format": "title_only", "titles": {locale: old["meta"][locale]["title"] for locale in wp.LOCALES}}}
    new = wp.page_config(production="20261121-jesus-will-return", environment="production", kickoff=kickoff, section=wp.title_section(table, "Jesus will return"),
                         series={locale: old["meta"][locale]["series"] for locale in wp.LOCALES}, speaker="Eric Geiger", sunday="2026-11-22",
                         source_url=old["source"]["url"], window_end=old["source"]["window"]["end"], sentences=old["sentences"], reviewer="Jony",
                         basis="Claude Code CLI Opus 2.1.325 translation with an independent Opus audit")
    assert {key for key in set(old) | set(new) if old.get(key) != new.get(key)} == {"titleCheck"}
    assert new["titleCheck"]["publishedTitles"] == old["titleCheck"]["publishedTitles"] and new["titleCheck"]["seriesKey"] == "revelation-comfort-and-hope"
    import jsonschema
    jsonschema.validate(new, json.loads((ROOT / "experiments" / "sentence-first-agent" / "pages" / "page-config.schema.json").read_text(encoding="utf-8")))
    series_first = wp.page_config(production="p", environment="dev", kickoff={**kickoff, "title": {**kickoff["title"], "format": "series_dot_title"}},
                                  section=wp.title_section(table, "Jesus will return"), series={locale: old["meta"][locale]["series"] for locale in wp.LOCALES},
                                  speaker="Eric Geiger", sunday="2026-11-22", source_url=old["source"]["url"], window_end=10.0, sentences=3, reviewer="r", basis="b")
    assert series_first["titleCheck"] == {"englishTitle": "Jesus will return", "seriesKey": "revelation-comfort-and-hope", "mode": "table"}
    assert series_first["title"] == "启示录：耶稣带来的安慰与盼望 · 耶稣必再来"
