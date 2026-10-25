"""Tests for the sentence-first P1/P2 tools: consistency, ASR triage, runlog, TTS pool plan."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments" / "sentence-first-agent"
if str(EXPERIMENTS) not in sys.path:
    sys.path.insert(0, str(EXPERIMENTS))


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EXPERIMENTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _run(tmp_path: Path, locale: str = "ko") -> Path:
    run = tmp_path / "run"
    run.mkdir()
    rows = [{"id": "s1", "target": "여러분, 안녕하세요."}, {"id": "s2", "target": "당신은 괜찮습니까?"},
            {"id": "s3", "target": "에릭 가이어 목사님."}, {"id": "s4", "target": "19세기에"}]
    (run / "translations.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    (run / "review.json").write_text(json.dumps({"locale": locale, "revisions": {}, "notes": {}, "spokenForms": {}}), encoding="utf-8")
    (run / "sentences.jsonl").write_text("{}\n", encoding="utf-8")
    return run


def test_consistency_flags_address_terms_and_digits(tmp_path):
    mod = load("consistency_check")
    run = _run(tmp_path, "ko")
    report = mod.check(run, {"terms": [{"wrong": ["에릭 가이어"], "right": ["에릭 가이거"]}]})
    assert report["address"]["mixed"] == ["s2"] and report["address"]["forbiddenIds"] == 1
    assert report["address"]["share"] == 0.5
    assert report["address"]["status"] == "warn"
    assert report["terms"][0]["ids"] == ["s3"]
    assert report["numbers"]["digitIds"] == ["s4"]
    assert report["status"] == "warn"


def test_asr_triage_separates_variants_from_content():
    mod = load("asr_triage")
    assert mod.classify("阿们。", "阿门。", "zh-Hans") == "homophone"
    assert mod.classify("邦。", "帮。", "zh-Hans") == "homophone"
    assert mod.classify("十九世纪。", "19世纪。", "zh-Hans") == "number_form"
    assert mod.classify("Guau.", "Wow.", "es") == "variant"
    assert mod.classify("Sí.", "C.", "es") == "variant"
    assert mod.classify("Eric Geiger", "Eric Guyer", "ko") == "content"
    report = {"sentences": [{"id": "a", "similarity": 0.0, "expected": "阿们。", "recognized": "阿门。"},
                            {"id": "b", "similarity": 0.5, "expected": "Eric Geiger", "recognized": "Eric Guyer"}]}
    result = mod.triage(report, "zh-Hans")
    assert result["variantIds"] == ["a"] and result["contentIds"] == ["b"]


def test_runlog_writes_outcome_and_timings(tmp_path):
    mod = load("runlog")
    run = _run(tmp_path)
    mod.mark(run, "l1.test", "started")
    mod.mark(run, "l1.test", "finished")
    mod.write_outcome(run, status="track_ready_for_review", locale="ko")
    state = mod.write_timings(run)
    assert (run / "outcome.json").exists()
    assert (run / "timings.tsv").exists()
    assert state["stages"]["l1.test"]["status"] == "finished"
    assert json.loads((run / "outcome.json").read_text())["status"] == "track_ready_for_review"


def test_tts_pool_plan_splits_both_speakers():
    mod = load("tts_pool")
    rows = [{"id": f"e{i}", "speaker": "eric"} for i in range(10)] + [{"id": f"s{i}", "speaker": "steve"} for i in range(10)]
    plan = mod.plan_workers(rows, {"eric": "/eric", "steve": "/steve"}, 8, 8)
    assert plan["replicas"] == 8
    assert plan["bySpeaker"] == {"eric": 10, "steve": 10}
    assert len([w for w in plan["workers"] if w["speaker"] == "eric"]) == 4
    assert {i for w in plan["workers"] for i in w["ids"]} == {r["id"] for r in rows}
