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
        self.count = {"tts": {}, "finish": {}, "repair": {}}
        self.opus = []
        self.sfa = None

    def __call__(self, command, **kwargs):
        script = Path(command[1]).name if len(command) > 1 else ""
        done = lambda code=0, out="": subprocess.CompletedProcess(command, code, stdout=out, stderr="")
        arg = lambda name: command[command.index(name) + 1]
        if script == "opus_tasks.py":                       # runs for real below; kept to look at its arguments
            self.opus.append(command)
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
                if ok == "busy":                              # render_lock.py refuses before anything else is looked at
                    return subprocess.CompletedProcess(command, 1, stdout="", stderr="another TTS renderer is running (pid 4242, out /x/tts); the laptop allows one model copy.")
                return done(0 if ok else 1, json.dumps({"memoryAdmission": {"device": "mps", "availableGiB": 20.0 if ok else 9.5, "requiredGiB": 15.0, "pass": ok}}) + "\n")
            self.tts = command
            self.count["tts"][run.name] = self.count["tts"].get(run.name, 0) + 1
            Path(arg("--out")).mkdir(parents=True, exist_ok=True)
            ids = [json.loads(line)["id"] for line in (run / "speech.jsonl").read_text().splitlines()]
            for unit in ids:
                (Path(arg("--out")) / f"{unit}.wav").write_bytes(b"dub")
            with (Path(arg("--out")) / "tts-batches.jsonl").open("a") as handle:      # windows of four, as the renderer records them
                for index in range(0, len(ids), 4):
                    handle.write(json.dumps({"batchIndex": index // 4, "ids": ids[index:index + 4], "seed": 7, "batchSize": 4}) + "\n")
            return done(out='{"rendered": true}\n')
        if script == "repair_sentence.py":
            run = Path(arg("--run"))
            self.repair = command
            window = next(json.loads(line)["ids"] for line in (run / "tts" / "tts-batches.jsonl").read_text().splitlines() if arg("--id") in line)
            self.count["repair"].setdefault(run.name, []).append(window)
            spoken = {json.loads(line)["id"]: json.loads(line)["spokenText"] for line in (run / "speech.jsonl").read_text().splitlines()}
            for unit in window:
                (run / "tts" / f"{unit}.wav").write_bytes(f"again {spoken[unit]}".encode())
            return done(out='{"repaired": true}\n')
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
    before_render = next(c for c in run.opus if "rewrite" in c and "estimate" in c)
    assert before_render[before_render.index("--limit") + 1] == "1000", "every sentence estimated not to fit, not the worst 160"
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


def test_track_approvals_write_the_verdict_and_a_request_without_marked_sentences_waits(make, tmp_path):
    driver = make()
    start(driver)
    approve_layer1(driver)
    approve_track(driver, "zh-Hans", mode="whole_track")
    approve_track(driver, "ko", mode="flagged_only")
    approve_track(driver, "es", verdict="changes_requested", issueIds=[])
    record = driver.advance(NAME)
    assert record["stages"]["wait.tracks"]["state"] == "waiting" and driver.store.gate(NAME, "l3.review.es")["state"] == "changes_requested"
    assert "repairs" not in record and driver.run_command.count["repair"] == {}
    assert sorted(driver.notifier().titles()[-3:]) == sorted(["[同行] 已生效 · 中文音轨", "[同行] 已生效 · 韩语音轨", "[同行] 已收到修改要求 · 西班牙语音轨"])
    zh = json.loads((tmp_path / "artifacts/weekly-auto" / NAME / "reviews" / "zh-Hans.json").read_text())
    assert zh["humanApproval"] is True and zh["reviewMode"] == "whole_track" and zh["reviewer"] == REVIEWER
    assert zh["trackWavSha256"] == weekly_auto.sha256_file(tmp_path / "artifacts/sentence-first-agent" / f"{NAME}-zh" / "track.wav")
    assert not (tmp_path / "artifacts/sentence-first-agent" / f"{NAME}-review").exists(), "no verdict until every language is approved"
    # a request with only a note names no sentence to repair: a person handles it and opens the step again
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


def test_the_shipped_config_runs_through_the_track_reviews_and_names_the_sync_decision():
    config = json.loads((ROOT / "config" / "weekly-sermon-auto.json").read_text(encoding="utf-8"))
    assert config["automation"]["through"] == "tracks"
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


def mark(note, *tags):
    return {"verdict": "issue", "tags": list(tags), "note": note}


def to_track_reviews(make, **options):
    driver = make(**options)
    start(driver)
    approve_layer1(driver)
    return driver


def test_a_track_sent_back_is_reworded_rendered_again_and_shown_again(make, tmp_path):
    driver = to_track_reviews(make)
    run = tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-zh"
    (run / "tts-raw-before-trim").mkdir()                    # what the first merge kept: s0001 and s0006 were trimmed
    for unit in ("s0001", "s0006"):
        (run / "tts-raw-before-trim" / f"{unit}.wav").write_bytes(f"raw {unit}".encode())
    (run / "speed-fit.json").write_text("{}")
    first = driver.store.descriptor(NAME, "l3.review.zh-Hans", REVIEWER)
    approve_track(driver, "zh-Hans", verdict="changes_requested", key="c" * 20, issueIds=["s0002", "s0006"],
                  rows={"s0002": mark("这句不对，改成 那城有神的荣耀", "translation"), "s0006": mark("有杂音", "audio"), "s0001": {"verdict": "pass", "tags": [], "note": ""}})
    record = driver.advance(NAME)
    assert record["stages"]["l3.repair.zh-Hans"]["state"] == "done" and record["stages"]["wait.tracks"]["state"] == "waiting"
    repair = record["repairs"]["zh-Hans"][0]
    assert repair["state"] == "done" and repair["round"] == "r1" and repair["worded"]["retranslate"] == ["s0002"] and repair["worded"]["rerender"] == ["s0006"]
    calls = driver.run_command
    assert calls.count["repair"] == {f"{NAME}-zh": [["s0001", "s0002", "s0003", "s0004"], ["s0005", "s0006"]]}, "each batch once, whole batches"
    assert calls.repair[0] == "tts-python" and calls.repair[calls.repair.index("--voice") + 1].startswith("eric_") and "--apply" in calls.repair
    assert calls.count["tts"][f"{NAME}-zh"] == 1 and calls.count["finish"][f"{NAME}-zh"] == 2, "no full render; one more merge"
    # the merge starts from what the renderer wrote: nothing trimmed or sped up twice
    assert not list((run / "tts-raw-before-trim").glob("*.wav")) and not (run / "speed-fit.json").exists()
    assert (run / "tts" / "s0002.wav").read_bytes() == "again 那城有神的荣耀".encode()
    revision = json.loads((run / "review.json").read_text())["revisions"]["s0002"]
    assert revision["target"] == "那城有神的荣耀" and "review fix r1: 这句不对" in revision["note"] and revision["note"].startswith("audit high")
    report = json.loads((run / "repair" / "repair-r1-report.json").read_text())
    assert report["applied"] is True and [row["action"] for row in report["rows"]] == ["retranslate", "rerender"]
    issues = json.loads((run / "repair" / "issues-r1.json").read_text())
    assert issues["trackHashes"] == first["bindings"] and issues["listening"]["mode"] == "whole_track" and issues["reviewer"]["login"] == REVIEWER["login"]
    # the next version of the review step says what was done to which sentence
    gate = driver.store.descriptor(NAME, "l3.review.zh-Hans", REVIEWER)
    assert gate["revision"] == 2 and gate["state"] == "open" and gate["bindings"] != first["bindings"]
    rows = {row["id"]: row for row in gate["data"]["rows"]}
    assert rows["s0002"]["flags"][0] == "fixed" and rows["s0002"]["target"] == "那城有神的荣耀"
    assert rows["s0002"]["fix"] == {"asked": "这句不对，改成 那城有神的荣耀", "tags": ["译文"], "did": "照听审人写的改", "action": "retranslate",
                                    "before": rows["s0002"]["fix"]["before"]} and rows["s0002"]["fix"]["before"] != "那城有神的荣耀"
    assert rows["s0006"]["flags"][0] == "rerendered" and rows["s0006"]["fix"]["before"] is None and rows["s0001"]["flags"][0] == "rerendered" and "fix" not in rows["s0001"]
    assert gate["data"]["previous"] == {"revision": 1, "issues": 2, "listeningMode": "whole_track", "fixed": ["s0002"],
                                        "rerendered": ["s0001", "s0003", "s0004", "s0005", "s0006"], "unclear": []}
    titles = driver.notifier().titles()
    assert titles[-2:] == ["[同行] 已收到修改要求 · 中文音轨", "[同行] 可审 · 中文音轨"]
    # approving the second version: the receipt keeps how the first one was heard
    # only what changed was heard this time; the earlier version was heard in full, and the receipt says both
    for locale, mode in (("zh-Hans", "changed_only"), ("ko", "whole_track"), ("es", "whole_track")):
        approve_track(driver, locale, mode=mode)
    record = driver.advance(NAME)
    assert record["state"] == "tracks_ready"
    receipt = json.loads((tmp_path / "artifacts" / "weekly-auto" / NAME / "reviews" / "zh-Hans.json").read_text())
    assert receipt["reviewMode"] == "whole_track" and receipt["listening"]["mode"] == "changed_only"
    assert receipt["earlierRounds"][0]["listening"]["mode"] == "whole_track" and receipt["earlierRounds"][0]["round"] == "r1"
    verdict = json.loads((tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-review" / "human-review-verdict.json").read_text())
    assert verdict["reviewMode"] == "whole_track" and verdict["locales"]["zh-Hans"]["trackWavSha256"] == receipt["trackWavSha256"]
    assert receipt["earlierRounds"][0]["rerenderedIds"] == ["s0001", "s0002", "s0003", "s0004", "s0005", "s0006"]


def test_a_sentence_the_model_does_not_understand_changes_nothing_and_is_shown_as_such(make, tmp_path):
    driver = to_track_reviews(make)
    first = driver.store.descriptor(NAME, "l3.review.es", REVIEWER)
    approve_track(driver, "es", verdict="changes_requested", key="d" * 20, issueIds=["s0003"], rows={"s0003": mark("？？", "other")})
    record = driver.advance(NAME)
    assert record["repairs"]["es"][0]["worded"]["unclear"] == ["s0003"] and driver.run_command.count["repair"] == {}
    gate = driver.store.descriptor(NAME, "l3.review.es", REVIEWER)
    assert gate["revision"] == 2 and gate["data"]["previous"]["unclear"] == ["s0003"] and gate["data"]["previous"]["fixed"] == []
    row = next(row for row in gate["data"]["rows"] if row["id"] == "s0003")
    assert row["flags"][0] == "unclear" and row["fix"]["did"] == "看不出要改哪里"
    assert gate["bindings"]["translationsJsonlSha256"] == first["bindings"]["translationsJsonlSha256"]


def test_a_repair_that_leaves_the_track_behind_stops_instead_of_rewriting_the_rest(make, tmp_path):
    driver = to_track_reviews(make, lags={"zh-Hans": [2.0, 12.0]})
    approve_track(driver, "zh-Hans", verdict="changes_requested", key="e" * 20, issueIds=["s0002"], rows={"s0002": mark("太书面", "translation")})
    record = driver.advance(NAME)
    stage = record["stages"]["l3.sync.zh-Hans"]
    assert stage["state"] == "failed" and stage["errorClass"] == "sync" and "按听审意见改句之后" in stage["message"] and record["state"] == "blocked"
    assert driver.run_command.count["tts"][f"{NAME}-zh"] == 1, "the rest of the track is not rendered again"
    kinds = [json.loads(line)["kind"] for line in (tmp_path / "calls.ndjson").read_text().splitlines()]
    assert kinds.count("repair") == 1 and "condense" not in kinds
    assert driver.store.descriptor(NAME, "l3.review.zh-Hans", REVIEWER)["state"] == "changes_requested"


def test_a_repair_the_model_did_not_answer_fails_its_stage_and_resumes_on_retry(make, tmp_path, monkeypatch):
    driver = to_track_reviews(make)
    run = tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-ko"
    before = (run / "review.json").read_text()
    approve_track(driver, "ko", verdict="changes_requested", key="f" * 20, issueIds=["s0004"], rows={"s0004": mark("改成 새 문장", "translation")})
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail_repair")
    record = driver.advance(NAME)
    assert record["stages"]["l3.repair.ko"]["state"] == "failed" and (run / "review.json").read_text() == before
    assert driver.run_command.count["repair"] == {} and driver.notifier().titles()[-1].startswith("[同行] 失败")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    assert driver.advance(NAME)["stages"]["l3.repair.ko"]["state"] == "failed", "the timer does not retry a failed stage"
    record = driver.advance(NAME, retry=True)
    assert record["stages"]["l3.repair.ko"]["state"] == "done" and driver.store.descriptor(NAME, "l3.review.ko", REVIEWER)["revision"] == 2
    assert json.loads((run / "review.json").read_text())["revisions"]["s0004"]["target"] == "새 문장"


def test_a_repair_waits_for_memory_and_does_not_touch_the_audio_meanwhile(make, tmp_path):
    driver = to_track_reviews(make, memory=[True, True, True, False, True])
    run = tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-zh"
    approve_track(driver, "zh-Hans", verdict="changes_requested", key="g" * 20, issueIds=["s0005"], rows={"s0005": mark("有杂音", "audio")})
    record = driver.advance(NAME)
    assert record["stages"]["l3.repair.zh-Hans"]["state"] == "waiting" and (run / "tts" / "s0005.wav").read_bytes() == b"dub"
    assert driver.notifier().titles()[-1] == "[同行] 配音没有开始 · 内存不够"
    record = driver.advance(NAME)
    assert record["stages"]["l3.repair.zh-Hans"]["state"] == "done" and driver.run_command.count["repair"] == {f"{NAME}-zh": [["s0005", "s0006"]]}
    assert driver.store.descriptor(NAME, "l3.review.zh-Hans", REVIEWER)["revision"] == 2


def test_a_request_for_changes_about_another_version_of_the_track_repairs_nothing(make, tmp_path):
    driver = to_track_reviews(make)
    run = tmp_path / "artifacts" / "sentence-first-agent" / f"{NAME}-es"
    approve_track(driver, "es", verdict="changes_requested", key="h" * 20, issueIds=["s0001"], rows={"s0001": mark("改成 otra frase", "translation")})
    (run / "track.wav").write_bytes(b"another track")
    record = driver.advance(NAME)
    assert "repairs" not in record and driver.run_command.count["repair"] == {}
    assert driver.store.pending(NAME) == [] and driver.notifier().titles()[-1] == "[同行] 决定没有生效 · 西班牙语音轨"


def test_before_a_new_merge_every_sentence_is_the_audio_the_renderer_wrote(make, tmp_path):
    driver, run = make(), tmp_path / "run"
    for name in ("tts", "tts-raw-before-trim", "tts-before-speed"):
        (run / name).mkdir(parents=True)
    for unit, state in (("s0001", "trimmed and fast"), ("s0002", "fast"), ("s0003", "as rendered"), ("s0004", "trimmed")):
        (run / "tts" / f"{unit}.wav").write_bytes(state.encode())
    (run / "tts-raw-before-trim" / "s0001.wav").write_bytes(b"raw 1")          # trimmed, then sped up
    (run / "tts-before-speed" / "s0001.wav").write_bytes(b"trimmed 1")
    (run / "tts-before-speed" / "s0002.wav").write_bytes(b"raw 2")             # only sped up
    (run / "tts-raw-before-trim" / "s0004.wav").write_bytes(b"raw 4")          # only trimmed
    (run / "tts-raw-before-trim" / "s0009.wav").write_bytes(b"no such sentence any more")
    for name in ("speed-fit.json", "tts-silence-trim.json"):
        (run / name).write_text("{}")
    driver.restore_raw(run)
    assert {p.name: p.read_bytes() for p in sorted((run / "tts").glob("*.wav"))} == {
        "s0001.wav": b"raw 1", "s0002.wav": b"raw 2", "s0003.wav": b"as rendered", "s0004.wav": b"raw 4"}
    assert not list((run / "tts-raw-before-trim").iterdir()) and not list((run / "tts-before-speed").iterdir())
    assert not (run / "speed-fit.json").exists() and not (run / "tts-silence-trim.json").exists()
    driver.restore_raw(run)                                                      # again: nothing left to do, nothing breaks


def test_another_render_on_the_machine_makes_dubbing_wait_not_fail(make, tmp_path):
    driver = make(memory=["busy", True])
    start(driver)
    record = approve_layer1(driver)
    assert record["stages"]["l3.tts.zh-Hans"]["state"] == "waiting" and record["state"] != "blocked"
    assert record["worker"]["detail"].startswith("这台机器上另一条配音还在跑") and driver.run_command.count["tts"] == {}
    assert not [title for title in driver.notifier().titles() if "失败" in title or "内存" in title], "it ends by itself: nobody is called"
    record = driver.advance(NAME)
    assert record["stages"]["l3.tts.zh-Hans"]["state"] == "done" and record["stages"]["wait.tracks"]["state"] == "waiting"


def test_hearing_only_the_changes_counts_only_when_the_earlier_version_was_heard_properly(make, tmp_path):
    driver = to_track_reviews(make)
    approve_track(driver, "ko", verdict="changes_requested", mode="partial", key="k" * 20, issueIds=["s0001"], rows={"s0001": mark("有杂音", "audio")})
    driver.advance(NAME)
    gate = driver.store.descriptor(NAME, "l3.review.ko", REVIEWER)
    assert gate["revision"] == 2 and gate["data"]["previous"]["listeningMode"] == "partial"
    approve_track(driver, "ko", mode="changed_only", key="l" * 20)      # a page would not offer this; the driver does not take its word
    driver.advance(NAME)
    receipt = json.loads((tmp_path / "artifacts" / "weekly-auto" / NAME / "reviews" / "ko.json").read_text())
    assert receipt["reviewMode"] == "partial" and receipt["listening"]["mode"] == "changed_only"


def test_a_version_opened_again_gets_its_own_reminder(make, tmp_path, monkeypatch):
    driver = to_track_reviews(make)
    monkeypatch.setattr(weekly_auto.notices, "reminder_due", lambda kind, at, now, sent: kind == "track" and sent == 0)
    driver.advance(NAME)                                    # the first versions of all three have waited long enough
    approve_track(driver, "es", verdict="changes_requested", key="m" * 20, issueIds=["s0002"], rows={"s0002": mark("改成 otra", "translation")})
    record = driver.advance(NAME)
    record = driver.advance(NAME)
    reminders = [title for title in driver.notifier().titles() if title == "[同行] 还在等你 · 西班牙语音轨"]
    assert len(reminders) == 2 and record["reminders"]["l3.review.es"] == 1 and record["reminders"]["l3.review.es#r2"] == 1
