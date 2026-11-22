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
