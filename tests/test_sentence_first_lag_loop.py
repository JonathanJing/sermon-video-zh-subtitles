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
