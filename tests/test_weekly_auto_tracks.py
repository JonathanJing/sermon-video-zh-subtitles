"""tools/ops/weekly_auto.py after the English table: translation, dubbing, the Opus sync ladder, track reviews.

The Claude CLI, the TTS renderer, the merge and the route's deterministic helpers are replaced; the
driver, the gate store, translate_parts.py and opus_tasks.py run for real.
"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ops"))
import weekly_auto  # noqa: E402
from test_weekly_auto import BASE, REVIEWER, Notifier, Opener, Run, kickoff_payload, start, submit  # noqa: E402

NAME = "20261121-sermon"


class TrackRun(Run):
    """Adds the stages after Layer 1. `lags[locale]` is the max lag each successive merge reports."""

    def __init__(self, lags=None, memory=None):
        super().__init__()
        self.lags = {locale: list(values) for locale, values in (lags or {}).items()}
        self.memory = list(memory or [])
        self.count = {"tts": {}, "finish": {}}
        self.sfa = None

    def __call__(self, command, **kwargs):
        script = Path(command[1]).name if len(command) > 1 else ""
        done = lambda code=0, out="": subprocess.CompletedProcess(command, code, stdout=out, stderr="")
        arg = lambda name: command[command.index(name) + 1]
        if script == "sfa.py":
            self.calls.append("sfa.py")
            self.sfa = command
            anchor = json.loads(Path(arg("--anchor")).read_text())
            last = int(arg("--units").split(":")[1])
            names = [arg("--run")] + [command[i + 1].split("=")[1] for i, part in enumerate(command) if part == "--share-to"]
            for name in names:
                run = Path(kwargs["cwd"]) / "artifacts" / "sentence-first-agent" / name
                (run / "slices").mkdir(parents=True)
                units = anchor["sourceUnits"][: last + 1]
                rows = [{"id": f"s{i + 1:04d}", "english": u["english"], "start": u["start"], "end": u["end"], "sourceUnitId": u["sourceUnitId"]}
                        for i, u in enumerate(units)]
                (run / "sentences.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
                (run / "slices" / "slices.json").write_text(json.dumps([{"id": r["id"], "budgetSeconds": round(r["end"] - r["start"], 2)} for r in rows]))
                for r in rows:
                    (run / "slices" / f"{r['id']}.wav").write_bytes(b"src")
                (run / "clip.json").write_text("{}")
            (Path(kwargs["cwd"]) / "artifacts" / "sentence-first-agent" / names[0] / "setup.json").write_text("{}")
            return done()
        if script in ("consistency_check.py", "spoken_forms.py", "preflight.py"):
            self.calls.append(script)
            return done()
        if script == "build_speech.py":
            run = Path(arg("--run"))
            review = json.loads((run / "review.json").read_text())
            rows = [json.loads(line) for line in (run / "translations.jsonl").read_text().splitlines()]
            for row in rows:
                row["target"] = (review["revisions"].get(row["id"]) or {}).get("target") or row["target"]
            (run / "translations.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            budget = {b["id"]: b["budgetSeconds"] for b in json.loads((run / "slices" / "slices.json").read_text())}
            over = lambda row: review["locale"] == "ko" and row["id"] in ("s0001", "s0002")       # Korean runs long before any render
            (run / "speech.jsonl").write_text("".join(json.dumps({
                "id": r["id"], "spokenText": r["target"], "language": "x", "speaker": review["speaker"], "hint": "",
                "budgetSeconds": budget[r["id"]], "estimatedSeconds": budget[r["id"]] + (1.0 if over(r) else -0.2)}, ensure_ascii=False) + "\n" for r in rows))
            return done()
        if script == "tts_sentences.py":
            run = Path(arg("--speech")).parent
            if "--dry-run" in command:
                ok = self.memory.pop(0) if self.memory else True
                return done(0 if ok else 1, json.dumps({"memoryAdmission": {"device": "mps", "availableGiB": 20.0 if ok else 9.5, "requiredGiB": 15.0, "pass": ok}}) + "\n")
            self.tts = command
            self.count["tts"][run.name] = self.count["tts"].get(run.name, 0) + 1
            Path(arg("--out")).mkdir(parents=True, exist_ok=True)
            for line in (run / "speech.jsonl").read_text().splitlines():
                (Path(arg("--out")) / f"{json.loads(line)['id']}.wav").write_bytes(b"dub")
            return done(out='{"rendered": true}\n')
        if script == "finish_run.py":
            run = Path(arg("--run"))
            n = self.count["finish"][run.name] = self.count["finish"].get(run.name, 0) + 1
            locale = json.loads((run / "review.json").read_text())["locale"]
            lag = (self.lags.get(locale) or [2.0]).pop(0) if len(self.lags.get(locale) or []) > 1 else (self.lags.get(locale) or [2.0])[0]
            budget = {b["id"]: b["budgetSeconds"] for b in json.loads((run / "slices" / "slices.json").read_text())}
            rows, t = [], 0.5
            for line in (run / "speech.jsonl").read_text().splitlines():
                unit = json.loads(line)["id"]
                late = lag > 8 and unit in ("s0001", "s0005")
                rows.append({"id": unit, "plannedStart": t, "actualStart": t, "lagSeconds": lag if late else 0.2,
                             "dubSeconds": budget[unit] + (1.0 if late else 0.0), "sourceSeconds": budget[unit]})
                t += budget[unit] + 0.4
            (run / "schedule.json").write_text(json.dumps({"summary": {"sentences": len(rows), "trackSeconds": round(t, 1), "maxLagSeconds": lag,
                                                                       "sentencesOverLag8s": 2 if lag > 8 else 0, "gapSeconds": 0.05}, "sentences": rows}))
            (run / "track.wav").write_bytes(f"track {run.name} {n}".encode())
            (run / "review.mp3").write_bytes(f"mp3 {run.name} {n}".encode())
            (run / "dub-preview-640.mp4").write_bytes(b"mp4")
            self.finish = command
            return done()
        return super().__call__(command, **kwargs)


@pytest.fixture
def make(tmp_path, monkeypatch):
    monkeypatch.setenv("SFA_CLAUDE_BIN", str(ROOT / "tests" / "fake_claude.py"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.ndjson"))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")

    def build(**run_options):
        config = json.loads((ROOT / "config" / "weekly-sermon-auto.json").read_text(encoding="utf-8"))
        config["source"]["minBytes"] = 1000
        config["automation"]["through"] = "tracks"
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))
        (tmp_path / "ckpt" / "checkpoint-75d28").mkdir(parents=True, exist_ok=True)
        driver = weekly_auto.Driver(tmp_path, config_path=path, local={"reviewBaseUrl": BASE, "ttsPython": "tts-python", "ttsRuntime": str(tmp_path / "ckpt")},
                                    run=TrackRun(**run_options), opener=Opener(), notifier=Notifier(), python=sys.executable,
                                    sleep=lambda seconds: None)
        driver.code_root = tmp_path
        return driver
    return build


def approve_layer1(driver, name=NAME):
    submit(driver, name, "l0.decisions", kickoff_payload(driver, name), key="a" * 20)
    submit(driver, name, "l1.english-review", {"edits": {"drop": ["u0007"]}, "heardUnitIds": []}, key="b" * 20)
    return driver.advance(name)


def approve_track(driver, locale, name=NAME, verdict="approved", mode="whole_track", key=None, **payload):
    gate = driver.store.descriptor(name, f"l3.review.{locale}", REVIEWER)
    decision = {"schemaVersion": "sermon-review-decision-v1", "gateId": gate["gateId"], "kind": "track", "production": name, "locale": locale,
                "revision": gate["revision"], "bindings": gate["bindings"], "verdict": verdict,
                "checks": {"translation": verdict == "approved", "voice": verdict == "approved", "sync": verdict == "approved"},
                "payload": {"locale": locale, "rows": {}, "issueIds": [], "listening": {"mode": mode, "basis": "measured", "shareAt1x": 1.0}, **payload},
                "note": "", "idempotencyKey": key or (locale * 10)[:20].ljust(20, "x"), "client": {"submittedAt": "2026-11-22T06:00:00Z", "userAgent": "t"}}
    return driver.store.record_decision(decision, REVIEWER)


def test_after_the_english_table_the_run_goes_on_to_three_track_reviews(make, tmp_path):
    driver = make(lags={"zh-Hans": [12.0, 11.0, 2.0], "es": [12.0, 3.0]})
    start(driver)
    record = approve_layer1(driver)
    stages = {name: s["state"] for name, s in record["stages"].items()}
    assert stages["wait.tracks"] == "waiting" and all(stages[f"gate.track.{l}"] == "done" for l in ("zh-Hans", "ko", "es"))
    run = driver.run_command
    sfa = run.sfa
    assert sfa[sfa.index("--units") + 1] == "0:5" and "--sync" in sfa and "--publish" in sfa and "--english-package" in sfa
    assert [part for part in sfa if part.startswith(("ko=", "es="))] == [f"ko={NAME}-ko", f"es={NAME}-es"]
    tts = run.tts
    assert tts[0] == "tts-python" and tts[tts.index("--expect-checkpoint-sha256") + 1].startswith("75d28ce6")
    assert tts[tts.index("--batch-size") + 1] == "8" and tts[tts.index("--device") + 1] == "mps" and "--gap" in run.finish
    # the sync ladder: Chinese needed both rewrites, Spanish one, Korean was rewritten before its first render
    assert run.count["tts"] == {f"{NAME}-zh": 3, f"{NAME}-ko": 1, f"{NAME}-es": 2}
    assert record["sync"] == {"zh-Hans": ["colloquial", "condense"], "ko": ["colloquial"], "es": ["colloquial"]}
    runs = tmp_path / "artifacts" / "sentence-first-agent"
    assert json.loads((runs / f"{NAME}-ko" / "speech-ready.json").read_text())["colloquialBeforeRender"] == 1
    report = json.loads((runs / f"{NAME}-zh" / "lag-loop-report.json").read_text())
    assert report["gate"] == {"clean": True, "maxLagSeconds": 2.0, "sentencesOverLag8s": 0} and report["rewriteTiers"] == ["colloquial", "condense"]
    zh = json.loads((runs / f"{NAME}-zh" / "review.json").read_text())["revisions"]
    assert zh["s0002"]["note"].startswith("audit high") and "sync condense" in zh["s0005"]["note"] and "sync colloquial" in zh["s0001"]["note"]
    kinds = [json.loads(line)["kind"] for line in (tmp_path / "calls.ndjson").read_text().splitlines()]
    assert kinds.count("brief") == 1 and kinds.count("translate") == 9 and kinds.count("audit") == 3 and "condense" in kinds, "6 sentences make 3 parts per language"
    # each language's review step, with what the page needs
    gate = driver.store.descriptor(NAME, "l3.review.zh-Hans", REVIEWER)
    assert gate["kind"] == "track" and gate["locale"] == "zh-Hans" and gate["state"] == "open" and len(gate["data"]["rows"]) == 6
    assert set(gate["bindings"]) == {"trackWavSha256", "reviewMp3Sha256", "sentencesJsonlSha256", "translationsJsonlSha256"}
    rows = {row["id"]: row for row in gate["data"]["rows"]}
    assert rows["s0005"]["flags"][0] == "condensed" and rows["s0005"]["spoken"] and "revised" in rows["s0002"]["flags"]
    assert rows["s0003"]["dub"] == "tts/s0003.wav" and rows["s0003"]["source"] == "slices/s0003.wav"
    assert gate["data"]["sync"] == {"mode": "synced", "maxLagSeconds": 2.0, "over8s": 0} and gate["data"]["track"]["video"] == "dub-preview-640.mp4"
    assert driver.store.asset(NAME, "l3.review.zh-Hans", "tts/s0003.wav").read_bytes() == b"dub"
    titles = driver.notifier().titles()
    assert titles[-3:] == ["[同行] 可审 · 中文音轨", "[同行] 可审 · 韩语音轨", "[同行] 可审 · 西班牙语音轨"]
    assert driver.notifier().messages[-1].url == f"{BASE}/track.html?production={NAME}&gate=l3.review.es"
    journal = [json.loads(line) for line in (tmp_path / "artifacts/weekly-auto" / NAME / "journal.ndjson").read_text().splitlines()]
    assert sum(1 for row in journal if row["stage"] == "l3.tts.zh-Hans" and row["event"] == "started") == 3, "each new render is journalled as a new start"


def test_track_approvals_write_the_verdict_and_a_request_for_changes_waits(make, tmp_path):
    driver = make()
    start(driver)
    approve_layer1(driver)
    approve_track(driver, "zh-Hans", mode="whole_track")
    approve_track(driver, "ko", mode="flagged_only")
    approve_track(driver, "es", verdict="changes_requested", issueIds=["s0003"])
    record = driver.advance(NAME)
    assert record["stages"]["wait.tracks"]["state"] == "waiting" and driver.store.gate(NAME, "l3.review.es")["state"] == "changes_requested"
    assert sorted(driver.notifier().titles()[-3:]) == sorted(["[同行] 已生效 · 中文音轨", "[同行] 已生效 · 韩语音轨", "[同行] 已收到修改要求 · 西班牙语音轨"])
    zh = json.loads((tmp_path / "artifacts/weekly-auto" / NAME / "reviews" / "zh-Hans.json").read_text())
    assert zh["humanApproval"] is True and zh["reviewMode"] == "whole_track" and zh["reviewer"] == REVIEWER
    assert zh["trackWavSha256"] == weekly_auto.sha256_file(tmp_path / "artifacts/sentence-first-agent" / f"{NAME}-zh" / "track.wav")
    assert not (tmp_path / "artifacts/sentence-first-agent" / f"{NAME}-review").exists(), "no verdict until every language is approved"
    # the Spanish step is opened again by hand here (the automatic repair is not wired yet)
    driver.store.set_state(NAME, "l3.review.es", "open")
    approve_track(driver, "es", mode="flagged_only", key="e" * 20)
    record = driver.advance(NAME)
    assert record["state"] == "tracks_ready" and record["stages"]["l3.verdict"]["state"] == "done"
    verdict = json.loads((tmp_path / "artifacts/sentence-first-agent" / f"{NAME}-review" / "human-review-verdict.json").read_text())
    assert (verdict["schemaVersion"], verdict["verdict"], verdict["reviewMode"]) == ("sentence-first-human-review-verdict-v1", "approved", "flagged_only")
    assert set(verdict["locales"]) == {"zh-Hans", "ko", "es"} and verdict["locales"]["ko"]["reviewMode"] == "flagged_only"
    assert verdict["locales"]["zh-Hans"]["trackWavSha256"] == zh["trackWavSha256"] and verdict["reviewedAt"].endswith("+00:00")
    following = json.loads((tmp_path / "artifacts/weekly-auto" / NAME / "next-step.json").read_text())
    assert following["through"] == "tracks" and following["runs"]["ko"].endswith(f"{NAME}-ko") and following["verdict"].endswith("human-review-verdict.json")
    assert "发布还没有自动化" in following["note"]


def test_a_track_decision_about_a_track_that_changed_approves_nothing(make, tmp_path):
    driver = make()
    start(driver)
    approve_layer1(driver)
    approve_track(driver, "zh-Hans")
    (tmp_path / "artifacts/sentence-first-agent" / f"{NAME}-zh" / "track.wav").write_bytes(b"rendered again")
    driver.advance(NAME)
    assert driver.store.last_decision(NAME, "l3.review.zh-Hans")["outcome"] == "rejected_stale"
    assert not (tmp_path / "artifacts/weekly-auto" / NAME / "reviews").exists()
    assert driver.notifier().messages[-1].title == "[同行] 决定没有生效 · 中文音轨"


def test_a_track_that_still_lags_after_both_rewrites_stops_and_says_so(make):
    driver = make(lags={"zh-Hans": [12.0]})
    start(driver)
    record = approve_layer1(driver)
    assert record["state"] == "blocked" and record["stages"]["l3.sync.zh-Hans"]["errorClass"] == "sync"
    message = driver.notifier().messages[-1]
    assert message.title == "[同行] 失败 · 中文同步" and "口语化和精简之后配音仍然跟不上视频" in message.body and "12.0 秒" in message.body
    assert driver.run_command.count["tts"] == {f"{NAME}-zh": 3} and "l3.tts.ko" not in record["stages"]
    assert driver.store.gates(NAME)[-1]["kind"] == "english", "no track is offered for review while it lags"


def test_too_little_memory_waits_and_tries_again(make):
    driver = make(memory=[False, True])
    start(driver)
    record = approve_layer1(driver)
    assert record["stages"]["l3.tts.zh-Hans"]["state"] == "waiting" and record["state"] == "running"
    message = driver.notifier().messages[-1]
    assert message.title == "[同行] 配音没有开始 · 内存不够" and "9.5 GiB" in message.body and "15 GiB" in message.body
    record = driver.advance(NAME)
    assert record["stages"]["l3.tts.zh-Hans"]["state"] == "done" and record["stages"]["wait.tracks"]["state"] == "waiting"
    assert driver.notifier().titles().count("[同行] 配音没有开始 · 内存不够") == 1


def test_a_rehearsal_dubs_a_few_sentences_and_its_verdict_approves_nothing(make, tmp_path):
    driver = make()
    record = driver.start(__import__("test_weekly_auto").trigger(), rehearsal=True, production="rehearsal-x", limit_units=3)
    driver.advance("rehearsal-x")
    submit(driver, "rehearsal-x", "l0.decisions", kickoff_payload(driver, "rehearsal-x"), key="a" * 20)
    submit(driver, "rehearsal-x", "l1.english-review", {"edits": {}, "heardUnitIds": []}, key="b" * 20)
    driver.advance("rehearsal-x")
    sfa = driver.run_command.sfa
    assert sfa[sfa.index("--units") + 1] == "0:2" and "--no-publish" in sfa and "--english-package" not in sfa
    for locale in ("zh-Hans", "ko", "es"):
        approve_track(driver, locale, name="rehearsal-x")
    record = driver.advance("rehearsal-x")
    verdict = json.loads((tmp_path / "artifacts/sentence-first-agent" / "rehearsal-x-review" / "human-review-verdict.json").read_text())
    assert record["state"] == "rehearsal_complete" and verdict["verdict"] == "rehearsal" and "不能用于发布" in verdict["note"]
    assert json.loads((tmp_path / "artifacts/weekly-auto/rehearsal-x/reviews/ko.json").read_text())["humanApproval"] is False
    with pytest.raises(SystemExit):
        driver.start(__import__("test_weekly_auto").trigger(file_id="1cXDkbTESTfileid0000000000000000b"), production="real-x", limit_units=3)


def test_the_code_and_the_artifacts_must_share_a_checkout(make):
    driver = make()
    driver.code_root = ROOT
    start(driver)
    record = approve_layer1(driver)
    assert record["stages"]["l2.start"]["errorClass"] == "layout" and driver.run_command.sfa is None


def test_the_shipped_config_stops_after_layer_1_until_the_later_stretch_is_verified():
    config = json.loads((ROOT / "config" / "weekly-sermon-auto.json").read_text(encoding="utf-8"))
    assert config["automation"]["through"] == "layer1"
    assert config["authorizations"]["syncRewrite"]["statement"] == "应当调用Opus口语化译文，达不到效果，再用Opus精简译文。"


def test_a_quiet_rehearsal_records_its_notices_and_sends_none(make):
    driver = make()
    driver.start(__import__("test_weekly_auto").trigger(), rehearsal=True, production="rehearsal-q", quiet=True)
    record = driver.advance("rehearsal-q")
    assert driver.notifier().messages == [] and len(record["notices"]) == 3
    assert all(entry["quiet"] and not entry["delivered"] for entry in record["notices"].values()) and record.get("outbox", {}) == {}
    assert [entry["title"] for entry in record["notices"].values()][-1] == "[同行·演练] 待批准 · 英文表"
    with pytest.raises(SystemExit):
        driver.start(__import__("test_weekly_auto").trigger(file_id="1cXDkbTESTfileid0000000000000000c"), production="real-q", quiet=True)
