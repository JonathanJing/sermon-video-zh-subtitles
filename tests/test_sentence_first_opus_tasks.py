"""experiments/sentence-first-agent/opus_tasks.py with a stand-in for the Claude CLI (no model call)."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "sentence-first-agent"
sys.path.insert(0, str(EXP))
import opus_tasks  # noqa: E402
from weekly_auto_helpers import SENTENCES  # noqa: E402

EPISODE = {"speaker": "Eric Geiger", "englishTitle": "A sample title",
           "titles": {"zh-Hans": "示例讲题", "ko": "예시 제목", "es": "Título de ejemplo"}, "series": {"zh-Hans": "示例系列"}}


@pytest.fixture
def run(tmp_path, monkeypatch):
    monkeypatch.setenv("SFA_CLAUDE_BIN", str(ROOT / "tests" / "fake_claude.py"))
    monkeypatch.setenv("FAKE_CLAUDE_LOG", str(tmp_path / "calls.ndjson"))
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "ok")
    folder = tmp_path / "run"
    folder.mkdir()
    rows = [{"id": f"s{i + 1:04d}", "english": text, "start": i * 4.0, "end": i * 4.0 + 3.0, "sourceUnitId": f"u{i + 1:04d}"}
            for i, text in enumerate(SENTENCES)]
    (folder / "sentences.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (tmp_path / "episode.json").write_text(json.dumps(EPISODE, ensure_ascii=False))
    subprocess.run([sys.executable, str(EXP / "translate_parts.py"), "split", "--run", str(folder), "--parts", "2"], check=True, capture_output=True)
    return folder


def calls(tmp_path):
    path = tmp_path / "calls.ndjson"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def go(*argv):
    return opus_tasks.main([str(a) for a in argv])


def translate(run, tmp_path, locale="zh-Hans"):
    return go("translate", "--run", run, "--locale", locale, "--episode", tmp_path / "episode.json", "--brief", tmp_path / "brief.json", "--workers", 2)


def test_the_cli_is_called_the_way_the_model_stack_fixes_it(run, tmp_path):
    assert go("brief", "--run", run, "--episode", tmp_path / "episode.json", "--out", tmp_path / "brief.json") == 0
    argv = calls(tmp_path)[0]["argv"]
    assert argv == ["-p", "--model", "opus", "--permission-mode", "acceptEdits"]
    brief = json.loads((tmp_path / "brief.json").read_text())
    assert brief["schemaVersion"] == "sentence-first-episode-brief-v1" and len(brief["terminologySha256"]) == 64
    assert len(brief["establishedTermsSha256"]) == 64 and brief["correctedToEstablished"] == []
    established = {row["english"]: row for row in json.loads(opus_tasks.ESTABLISHED.read_text(encoding="utf-8"))["terms"]}
    assert established["Mariners Church"]["zh-Hans"] == "水手教会" and established["Eric"] == {"english": "Eric", "zh-Hans": "埃里克", "ko": "에릭", "es": "Eric"}
    assert "{established}" in opus_tasks.BRIEF_PROMPT and "必须照用" in opus_tasks.BRIEF_PROMPT
    assert opus_tasks.terms_text(brief, "ko") == "- 书卷与出处：chapter 21 = 21장\n- 术语：the city = 그 성\n- 人名与机构：Eric = 에릭"


def test_a_brief_that_departs_from_a_published_rendering_is_put_back_and_says_so(run, tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "brief_differs")
    assert go("brief", "--run", run, "--episode", tmp_path / "episode.json", "--out", tmp_path / "brief.json") == 0
    brief = json.loads((tmp_path / "brief.json").read_text())
    assert brief["correctedToEstablished"] == [{"english": "Eric", "locale": "zh-Hans", "was": "艾瑞克", "now": "埃里克"}]
    assert brief["names"][0]["zh-Hans"] == "埃里克" and "Eric = 埃里克" in opus_tasks.terms_text(brief, "zh-Hans")


def test_translation_parts_are_checked_and_only_the_bad_part_is_sent_again(run, tmp_path, monkeypatch, capsys):
    go("brief", "--run", run, "--episode", tmp_path / "episode.json", "--out", tmp_path / "brief.json")
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "drop_row_once")
    assert translate(run, tmp_path) == 0
    kinds = [c["out"].rsplit("/", 1)[1] for c in calls(tmp_path) if c["kind"] == "translate"]
    assert sorted(kinds) == ["output-1.jsonl", "output-1.jsonl", "output-2.jsonl", "output-2.jsonl"], "both parts were short once, then passed"
    record = json.loads((run / "translate-dispatch.json").read_text())
    assert [r["attempt"] for r in record] == [1, 1, 2, 2] and record[0]["problems"] and not record[-1]["problems"]
    subprocess.run([sys.executable, str(EXP / "translate_parts.py"), "merge", "--run", str(run), "--locale", "zh-Hans"], check=True, capture_output=True)
    targets = [json.loads(line)["target"] for line in (run / "translations.jsonl").read_text().splitlines()]
    assert targets == [f"[zh-Hans] {text}" for text in SENTENCES]
    before = len(calls(tmp_path))
    assert translate(run, tmp_path) == 0 and len(calls(tmp_path)) == before, "parts that pass the check are not sent again"


def test_a_part_that_stays_bad_is_reported_after_one_more_try(run, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "drop_row")
    assert translate(run, tmp_path) == 1
    assert len([c for c in calls(tmp_path) if c["kind"] == "translate"]) == 4
    assert '"bad": [1, 2]' in capsys.readouterr().out
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    assert translate(run, tmp_path, "ko") == 1


def prepare_review(run, tmp_path):
    translate(run, tmp_path)
    subprocess.run([sys.executable, str(EXP / "translate_parts.py"), "merge", "--run", str(run), "--locale", "zh-Hans"], check=True, capture_output=True)
    (run / "review.json").write_text(json.dumps({"locale": "zh-Hans", "speaker": "eric_pilot", "revisions": {}, "notes": {}, "spokenForms": {}}))


def test_audit_findings_become_revisions_or_notes_and_the_translation_it_read_is_frozen(run, tmp_path):
    prepare_review(run, tmp_path)
    assert go("audit", "--run", run, "--locale", "zh-Hans", "--episode", tmp_path / "episode.json", "--apply") == 0
    review = json.loads((run / "review.json").read_text())
    assert review["revisions"] == {"s0002": {"target": "AUDITED " + SENTENCES[1], "note": "audit high: 数字：漏了章节"}}
    assert review["notes"] == {"s0003": "audit low: 偏移：不确定"}
    assert (run / "audit" / "translations.audit.jsonl").read_bytes() == (run / "translations.jsonl").read_bytes()
    applied = json.loads((run / "audit" / "audit-zh-Hans.applied.json").read_text())
    assert applied == {"adoptedAsRevisions": ["s0002"], "notedOnly": ["s0003"]}
    before = len(calls(tmp_path))
    assert go("audit", "--run", run, "--locale", "zh-Hans", "--episode", tmp_path / "episode.json", "--apply") == 0
    assert len(calls(tmp_path)) == before, "a finished audit is not paid for twice"


def test_an_audit_with_no_output_passes_only_when_it_says_there_is_nothing(run, tmp_path, monkeypatch):
    prepare_review(run, tmp_path)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "no_output")
    assert go("audit", "--run", run, "--locale", "zh-Hans", "--episode", tmp_path / "episode.json", "--apply") == 0
    assert json.loads((run / "review.json").read_text())["revisions"] == {}
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    assert go("audit", "--run", run, "--locale", "zh-Hans", "--episode", tmp_path / "episode.json", "--apply", "--force") == 1


def write_speech(run, over):
    rows = [json.loads(line) for line in (run / "translations.jsonl").read_text().splitlines()]
    (run / "speech.jsonl").write_text("".join(json.dumps({"id": r["id"], "spokenText": r["target"], "budgetSeconds": 3.0,
                                                          "estimatedSeconds": 4.5 if r["id"] in over else 2.5}) + "\n" for r in rows))


def test_colloquial_rewrite_takes_only_sentences_that_do_not_fit_and_keeps_numbers(run, tmp_path, monkeypatch):
    prepare_review(run, tmp_path)
    write_speech(run, over={"s0001", "s0002"})
    assert go("rewrite", "--run", run, "--locale", "zh-Hans", "--mode", "colloquial", "--select", "estimate") == 0
    report = json.loads((run / "sync" / "colloquial-estimate-report.json").read_text())
    assert (report["selected"], report["accepted"], report["rejected"]) == (2, ["s0001"], [])
    review = json.loads((run / "review.json").read_text())
    assert review["revisions"]["s0001"] == {"target": "[zh-Hans] Good evening, welcome.", "note": "sync colloquial: colloquial"}
    sent = [json.loads(line) for line in (run / "sync" / "colloquial-estimate-input-1.jsonl").read_text().splitlines()]
    assert [row["id"] for row in sent] == ["s0001", "s0002"] and sent[0]["before"] is None and sent[0]["after"].startswith("[zh-Hans] We are")
    assert sent[0]["sourceSeconds"] == 3.0 and sent[0]["dubSeconds"] == 4.5


def test_condensing_uses_the_measured_schedule_and_refuses_changed_numbers(run, tmp_path, monkeypatch):
    prepare_review(run, tmp_path)
    schedule = {"sentences": [{"id": f"s{i + 1:04d}", "sourceSeconds": 3.0, "dubSeconds": 3.0 + (1.2 if i in (1, 2) else 0.0),
                               "lagSeconds": 9.5 if i == 5 else 0.0} for i in range(len(SENTENCES))]}
    (run / "schedule.json").write_text(json.dumps(schedule))
    assert go("rewrite", "--run", run, "--locale", "zh-Hans", "--mode", "condense", "--select", "measured") == 0
    report = json.loads((run / "sync" / "condense-measured-report.json").read_text())
    # the stand-in cuts the last third of each sentence: s0002 loses "21" and s0003 loses "12", so both are refused
    assert report["selected"] == 3 and report["rejected"] == [{"id": "s0002", "why": "numbers changed"}, {"id": "s0003", "why": "numbers changed"}]
    assert report["accepted"] == ["s0006"], "the sentence that only lags (its own length fits) is selected too"
    revisions = json.loads((run / "review.json").read_text())["revisions"]
    assert revisions["s0006"]["note"].startswith("sync condense") and len(revisions["s0006"]["target"]) < len("[zh-Hans] " + SENTENCES[5])
    assert "s0002" not in revisions and "s0003" not in revisions


def test_nothing_to_rewrite_calls_nothing(run, tmp_path):
    prepare_review(run, tmp_path)
    write_speech(run, over=set())
    before = len(calls(tmp_path))
    assert go("rewrite", "--run", run, "--locale", "zh-Hans", "--mode", "colloquial", "--select", "estimate") == 0
    assert len(calls(tmp_path)) == before and json.loads((run / "sync" / "colloquial-estimate-report.json").read_text())["selected"] == 0


@pytest.mark.parametrize("mode, before, after, why", [
    ("condense", "one two three four five six", "one two three four five six seven", "longer than before"),
    ("condense", "one two three four five six seven eight nine ten", "one", "cut by more than half"),
    ("colloquial", "chapter 21 has 12 gates", "chapter 21 has gates", "numbers changed"),
    ("colloquial", "some words", "  ", "empty"),
    ("colloquial", "some words here", "some words", None),
])
def test_rewrite_checks(mode, before, after, why):
    assert opus_tasks.check_rewrite(mode, {"target": before}, {"target": after}) == why


def ask_repair(run, tmp_path, rows, name="issues-r1.json", apply=True):
    if not (run / "review.json").exists():
        prepare_review(run, tmp_path)
    write_speech(run, over=set())
    (run / "repair").mkdir(exist_ok=True)
    (run / "repair" / name).write_text(json.dumps({"decisionId": "d1", "rows": rows}, ensure_ascii=False))
    return go("repair", "--run", run, "--locale", "zh-Hans", "--issues", run / "repair" / name, "--episode", tmp_path / "episode.json",
              "--brief", tmp_path / "brief.json", *(["--apply"] if apply else []))


def test_a_reviewers_marked_sentences_get_the_wording_they_asked_for_or_a_new_render(run, tmp_path, capsys):
    rows = {"s0003": {"tags": ["translation"], "note": "太书面，改成 那城有 12 个门"}, "s0005": {"tags": ["audio"], "note": "有杂音"},
            "s0002": {"tags": ["other"], "note": "？？"}}
    assert ask_repair(run, tmp_path, rows) == 0
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary == {"locale": "zh-Hans", "issues": 3, "retranslate": ["s0003"], "rerender": ["s0005"], "unclear": ["s0002"], "failed": []}
    sent = [json.loads(line) for line in (run / "repair" / "repair-r1-input-1.jsonl").read_text().splitlines()]
    assert [row["id"] for row in sent] == ["s0002", "s0003", "s0005"], "in sentence order"
    assert sent[1]["tags"] == ["译文"] and sent[1]["note"].startswith("太书面") and sent[1]["english"] == SENTENCES[2]
    assert sent[1]["before"].startswith("[zh-Hans]") and sent[1]["after"].startswith("[zh-Hans]") and sent[1]["spoken"]
    revisions = json.loads((run / "review.json").read_text())["revisions"]
    assert revisions["s0003"] == {"target": "那城有 12 个门", "note": "review fix r1: 太书面，改成 那城有 12 个门"}
    assert "s0005" not in revisions and "s0002" not in revisions, "only a new wording becomes a revision"
    report = json.loads((run / "repair" / "repair-r1-report.json").read_text())
    assert report["applied"] is True and report["decisionId"] == "d1" and report["rows"][1]["before"].startswith("[zh-Hans]")
    assert [(row["id"], row["action"]) for row in report["rows"]] == [("s0002", "unclear"), ("s0003", "retranslate"), ("s0005", "rerender")]
    assert len([c for c in calls(tmp_path) if c["kind"] == "repair"]) == 1


def test_a_repair_keeps_the_note_of_an_earlier_revision_and_without_apply_changes_nothing(run, tmp_path):
    prepare_review(run, tmp_path)
    review = json.loads((run / "review.json").read_text())
    review.setdefault("revisions", {})["s0004"] = {"target": "earlier wording", "note": "audit high: 漏译"}
    (run / "review.json").write_text(json.dumps(review, ensure_ascii=False))
    before = (run / "review.json").read_text()
    assert ask_repair(run, tmp_path, {"s0004": {"tags": ["translation"], "note": ""}}, apply=False) == 0
    assert (run / "review.json").read_text() == before and "applied" not in json.loads((run / "repair" / "repair-r1-report.json").read_text())
    assert ask_repair(run, tmp_path, {"s0004": {"tags": ["translation"], "note": ""}}, name="issues-r2.json") == 0
    revision = json.loads((run / "review.json").read_text())["revisions"]["s0004"]
    assert revision == {"target": "FIXED earlier wording", "note": "audit high: 漏译; review fix r2: 译文"}, "the tag stands in for an empty note"


def test_a_sentence_left_out_is_asked_for_once_more_and_a_bad_answer_applies_nothing(run, tmp_path, monkeypatch, capsys):
    rows = {"s0003": {"tags": ["translation"], "note": "改成 新的一句"}, "s0004": {"tags": ["audio"], "note": ""}}
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "repair_drop_once")
    assert ask_repair(run, tmp_path, rows) == 0
    report = json.loads((run / "repair" / "repair-r1-report.json").read_text())
    assert [a["missing"] for a in report["attempts"]] == [["s0004"], []] and len([c for c in calls(tmp_path) if c["kind"] == "repair"]) == 2
    second = [json.loads(line)["id"] for line in (run / "repair" / "repair-r1-input-2.jsonl").read_text().splitlines()]
    assert second == ["s0004"], "only the sentence without a usable answer goes out again"
    # a "render again" that quietly changed the words is refused twice: the round fails and nothing is written
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "repair_silent_change")
    before = (run / "review.json").read_text()
    capsys.readouterr()
    assert ask_repair(run, tmp_path, {"s0004": rows["s0004"], "s0006": {"tags": ["translation"], "note": "改成 另一句"}}, name="issues-r2.json") == 1
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["repair"] == "failed" and summary["failed"] == ["s0004"] and summary["retranslate"] == ["s0006"] and (run / "review.json").read_text() == before
    report = json.loads((run / "repair" / "repair-r2-report.json").read_text())
    assert report["attempts"][0]["refused"] == {"s0004": "wording changed without saying so"} and "applied" not in report


def test_a_repair_for_a_sentence_that_is_not_in_the_run_asks_nothing(run, tmp_path, capsys):
    assert ask_repair(run, tmp_path, {"s0999": {"tags": [], "note": "x"}}) == 1
    assert "unknown ids" in capsys.readouterr().out and not [c for c in calls(tmp_path) if c["kind"] == "repair"]


@pytest.mark.parametrize("action, before, after, why", [
    ("retranslate", "some words", "other words", None),
    ("rerender", "some words", "some words", None),
    ("unclear", "some words", "some words", None),
    ("rerender", "some words", "other words", "wording changed without saying so"),
    ("retranslate", "some words", "some words", "says retranslate but the wording is the same"),
    ("retranslate", "some words", " ", "empty"),
    ("rewrite", "some words", "other words", "unknown action"),
    ("retranslate", "short", "x" * 40, "much longer than before"),
])
def test_repair_checks(action, before, after, why):
    assert opus_tasks.check_repair({"target": before}, {"action": action, "target": after}) == why
