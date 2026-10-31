"""Unit tests for preview encoder selection and the no-video fallback (``finish_run.py``)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile

HERE = Path(__file__).resolve().parents[1]
EXPERIMENTS = HERE / "experiments" / "sentence-first-agent"


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    sys.path.insert(0, str(EXPERIMENTS))  # finish_run imports runlog from its own directory
    spec = importlib.util.spec_from_file_location(name, EXPERIMENTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    sys.modules[name] = module
    return module


def test_auto_prefers_hardware_on_macos_and_fast_elsewhere():
    mod = load("finish_run")
    assert mod.choose_preview_encoder("auto", "darwin", True) == "hardware"
    assert mod.choose_preview_encoder("auto", "darwin", False) == "fast"
    assert mod.choose_preview_encoder("auto", "linux", True) == "fast"
    assert mod.choose_preview_encoder("quality", "darwin", True) == "quality"
    assert mod.choose_preview_encoder("fast", "linux", True) == "fast"
    assert mod.choose_preview_encoder("hardware", "linux", True) == "hardware"


def test_encoder_flags_keep_the_historical_quality_path():
    mod = load("finish_run")
    assert mod.PREVIEW_ENCODER_FLAGS["quality"] == ["-c:v", "libx264", "-preset", "veryfast", "-crf", "30"]
    assert mod.PREVIEW_ENCODER_FLAGS["fast"][2:] == ["-preset", "ultrafast", "-crf", "30"]
    assert mod.PREVIEW_ENCODER_FLAGS["hardware"][:2] == ["-c:v", "h264_videotoolbox"]


def test_build_preview_falls_back_to_quality_when_the_hardware_file_has_no_video(tmp_path, monkeypatch):
    mod = load("finish_run")
    run = tmp_path
    (run / "dub.mp4").write_bytes(b"not a real video")
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return Result()

    seen = {"count": 0}

    def fake_has_video(path):
        seen["count"] += 1
        return seen["count"] > 1  # the first (hardware) attempt reports no video stream

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "preview_has_video", fake_has_video)
    encoder = mod.build_preview(run, "hardware")
    assert encoder == "quality"
    assert len(calls) == 2
    assert "h264_videotoolbox" in calls[0]
    assert "-preset" in calls[1] and "veryfast" in calls[1]
