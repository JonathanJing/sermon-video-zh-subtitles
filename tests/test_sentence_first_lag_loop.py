"""Unit tests for lag_loop voice resolution (sync-run repair)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
EXPERIMENTS = HERE / "experiments" / "sentence-first-agent"


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    sys.path.insert(0, str(EXPERIMENTS))
    spec = importlib.util.spec_from_file_location(name, EXPERIMENTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules[name] = module
    return module


def test_explicit_voices_cover_every_speaker():
    lag = load("lag_loop")
    rows = [{"speaker": "john_thomas"}, {"speaker": "steve_bang_lee"}]
    voices = lag.resolve_voices(["john_thomas=/j", "steve_bang_lee=/s"], None, rows)
    assert voices == [("john_thomas", "/j"), ("steve_bang_lee", "/s")]


def test_missing_voice_is_rejected():
    lag = load("lag_loop")
    rows = [{"speaker": "john_thomas"}, {"speaker": "steve_bang_lee"}]
    try:
        lag.resolve_voices(["john_thomas=/j"], None, rows)
    except SystemExit as exc:
        assert "steve_bang_lee" in str(exc)
    else:
        raise AssertionError("missing speaker checkpoint must fail")


def test_legacy_checkpoint_covers_a_single_speaker_run():
    lag = load("lag_loop")
    rows = [{"speaker": "steve_bang_lee"}, {"speaker": "steve_bang_lee"}]
    assert lag.resolve_voices([], "/checkpoints/steve", rows) == [("steve_bang_lee", "/checkpoints/steve")]


def test_legacy_checkpoint_does_not_guess_for_two_speakers():
    lag = load("lag_loop")
    rows = [{"speaker": "john_thomas"}, {"speaker": "steve_bang_lee"}]
    try:
        lag.resolve_voices([], "/one", rows)
    except SystemExit:
        pass
    else:
        raise AssertionError("--checkpoint must not cover a two-speaker run")


def test_apply_revisions_updates_target_and_note(tmp_path):
    import json

    lag = load("lag_loop")
    path = tmp_path / "translations.jsonl"
    path.write_text(
        json.dumps({"id": "s0001", "locale": "zh-Hans", "target": "第一句很长", "reviewNote": "pass"}) + "\n"
        + json.dumps({"id": "s0002", "locale": "zh-Hans", "target": "第二句", "reviewNote": "pass"}) + "\n",
        encoding="utf-8")
    assert lag.apply_revisions(tmp_path, {"s0001": {"target": "第一句", "note": "revised: lag trim"}}) == 1
    data = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert data[0]["target"] == "第一句"
    assert data[0]["reviewNote"] == "revised: lag trim"
    assert data[1] == {"id": "s0002", "locale": "zh-Hans", "target": "第二句", "reviewNote": "pass"}


def test_apply_revisions_leaves_untouched_rows_byte_identical(tmp_path):
    import json

    lag = load("lag_loop")
    path = tmp_path / "translations.jsonl"
    original = json.dumps({"id": "s0001", "locale": "ko", "target": "한 문장", "reviewNote": "pass"},
                          ensure_ascii=False)
    path.write_text(original + "\n", encoding="utf-8")
    assert lag.apply_revisions(tmp_path, {}) == 0
    assert path.read_text(encoding="utf-8").strip() == original


def _write_report(run, name, payload):
    import json

    (run / name).write_text(json.dumps(payload), encoding="utf-8")


def test_lag_loop_refuses_text_cuts_before_the_cheaper_levers(tmp_path):
    lag = load("lag_loop")
    try:
        lag.require_levers(tmp_path, skip=False)
    except SystemExit as exc:
        assert "silence" in str(exc)
    else:
        raise AssertionError("text trimming must wait for silence trim / speed fit")


def test_lag_loop_accepts_after_silence_trim(tmp_path):
    lag = load("lag_loop")
    _write_report(tmp_path, "tts-silence-trim.json", {"savedSeconds": 170.0})
    found = lag.require_levers(tmp_path, skip=False)
    assert "silenceTrim" in found


def test_lag_loop_accepts_after_speed_fit(tmp_path):
    lag = load("lag_loop")
    _write_report(tmp_path, "speed-fit.json", {"summary": {"adjusted": 124}})
    found = lag.require_levers(tmp_path, skip=False)
    assert "speedFit" in found


def test_lag_loop_skip_flag_bypasses_the_gate(tmp_path):
    lag = load("lag_loop")
    assert lag.require_levers(tmp_path, skip=True) == {}


def test_orphan_spoken_forms_are_pruned(tmp_path):
    lag = load("lag_loop")
    path = tmp_path / "review.json"
    path.write_text(__import__("json").dumps({"spokenForms": {"1980 年": "一九八零年", "第 146 页": "第一百四十六页"}}),
                    encoding="utf-8")
    orphans = lag.prune_orphan_spoken_forms(path, ["然后在 1980 年，天花消灭了。"])
    assert orphans == ["第 146 页"]
    remaining = __import__("json").loads(path.read_text(encoding="utf-8"))["spokenForms"]
    assert remaining == {"1980 年": "一九八零年"}


def test_no_orphans_leaves_the_file_byte_identical(tmp_path):
    lag = load("lag_loop")
    path = tmp_path / "review.json"
    original = "{\"spokenForms\": {\"2024 年\": \"二零二四年\"}}"
    path.write_text(original, encoding="utf-8")
    assert lag.prune_orphan_spoken_forms(path, ["他在 2024 年退役。"]) == []
    assert path.read_text(encoding="utf-8") == original
