"""Unit tests for the sentence-first P0 tools (SRT normalizer, preflight, review player, repair window)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import wave
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments" / "sentence-first-agent"


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EXPERIMENTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


SRT = """1
00:00:01,000 --> 00:00:03,000
right, check it out.

2
00:00:02,500 --> 00:00:05,000
right, check it out. I'm Eric.

3
00:00:05,500 --> 00:00:05,500
I'm Eric. Today we talk.

4
00:00:06,000 --> 00:00:07,000
Today we talk. Grace.
"""


def test_srt_normalize_dedupes_rolling_and_fixes_timing(tmp_path, capsys):
    mod = load("srt_normalize")
    srt = tmp_path / "episode.srt"
    srt.write_text(SRT, encoding="utf-8")
    out = tmp_path / "layer1"
    assert mod.main(["--srt", str(srt), "--out", str(out), "--media-duration", "10"]) == 0
    capsys.readouterr()
    report = json.loads((out / "srt-normalization-report.json").read_text(encoding="utf-8"))
    assert report["cues"] == 4
    assert report["rawIssues"]["zeroOrNegativeDuration"] == 1
    assert report["rawIssues"]["overlappingCues"] == 1
    assert report["issues"] == []
    manifest = json.loads((out / "anchor-manifest.json").read_text(encoding="utf-8"))
    units = manifest["sourceUnits"]
    assert len(units) == 4
    assert [u["english"] for u in units] == ["right, check it out.", "I'm Eric.", "Today we talk.", "Grace."]
    for i, unit in enumerate(units):
        assert unit["start"] < unit["end"]
        assert unit["end"] - unit["start"] >= 0.2 - 1e-6
        if i:
            assert unit["start"] >= units[i - 1]["end"] - 1e-6


def test_srt_normalize_validate_only_reports_raw_issues(tmp_path, capsys):
    mod = load("srt_normalize")
    srt = tmp_path / "episode.srt"
    srt.write_text(SRT, encoding="utf-8")
    assert mod.main(["--srt", str(srt), "--out", str(tmp_path / "unused"), "--validate-only"]) == 0
    out = capsys.readouterr().out
    assert "zeroOrNegativeDuration" in out
    assert not (tmp_path / "unused" / "anchor-manifest.json").exists()


def _make_run(root: Path, *, relative_ref: bool = False) -> tuple[Path, Path, Path, Path]:
    run = root / "run"
    run.mkdir()
    (run / "clip.json").write_text(json.dumps({"locale": "es"}), encoding="utf-8")
    sentences = [{"id": "s0001", "sourceUnitId": "u1", "speakerId": "eric_geiger", "english": "Hi.", "start": 0, "end": 1},
                 {"id": "s0002", "sourceUnitId": "u2", "speakerId": "eric_geiger", "english": "Bye.", "start": 1, "end": 2}]
    (run / "sentences.jsonl").write_text("\n".join(json.dumps(s) for s in sentences) + "\n", encoding="utf-8")
    (run / "translations.jsonl").write_text("\n".join(json.dumps({"id": s["id"], "target": "x"}) for s in sentences) + "\n", encoding="utf-8")
    (run / "review.json").write_text(json.dumps({"locale": "es", "speakers": {"eric_geiger": "eric_pilot"}}), encoding="utf-8")
    (run / "speech.jsonl").write_text("\n".join(json.dumps({"id": s["id"], "speaker": "eric_pilot", "language": "Spanish",
                                                             "spokenText": "x"}) for s in sentences) + "\n", encoding="utf-8")
    registry = root / "registry.json"
    registry.write_text(json.dumps({"speakers": [{
        "speakerId": "eric_geiger", "speakerKey": "eric_pilot",
        "authorization": {"status": "authorized", "purposes": ["multilingual_dubbing"]},
        "localeCapabilities": [{"targetLocale": "es", "status": "human_reviewed"}]}]}), encoding="utf-8")
    evidence = root / "evidence.json"
    evidence.write_text(json.dumps({"units": 2}), encoding="utf-8")
    ref_path = "artifacts/does-not-exist-evidence.json" if relative_ref else str(evidence)
    package = root / "english-source.json"
    package.write_text(json.dumps({
        "source": {"sourceUrl": "https://example.test/v"},
        "units": [{"sourceUnitId": "u1"}, {"sourceUnitId": "u2"}],
        "approvedWindow": {"evidence": {"path": ref_path, "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}},
    }), encoding="utf-8")
    return run, registry, package, evidence


def test_preflight_passes_and_resolves_absolute_evidence(tmp_path, capsys):
    mod = load("preflight")
    run, registry, package, _ = _make_run(tmp_path)
    out = tmp_path / "preflight.json"
    assert mod.main(["--run", str(run), "--registry", str(registry), "--english-package", str(package), "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "pass"
    assert not result["errors"]


def test_preflight_fails_on_unresolvable_relative_evidence(tmp_path, capsys):
    mod = load("preflight")
    run, registry, package, _ = _make_run(tmp_path, relative_ref=True)
    out = tmp_path / "preflight.json"
    assert mod.main(["--run", str(run), "--registry", str(registry), "--english-package", str(package), "--out", str(out)]) == 1
    result = json.loads(out.read_text(encoding="utf-8"))
    assert result["status"] == "fail"
    assert any("does-not-exist-evidence" in e["detail"] for e in result["errors"])


def _make_review_run(root: Path) -> Path:
    run = root / "review-run"
    run.mkdir()
    sentences = [{"id": "s0001", "speakerId": "eric_geiger", "english": "Hi.", "start": 0, "end": 1, "speakerReview": "check"},
                 {"id": "s0002", "speakerId": "steve_bang_lee", "english": "Bye.", "start": 1, "end": 2}]
    (run / "sentences.jsonl").write_text("\n".join(json.dumps(s) for s in sentences) + "\n", encoding="utf-8")
    (run / "translations.jsonl").write_text("\n".join(json.dumps({"id": s["id"], "target": "你好。"}) for s in sentences) + "\n", encoding="utf-8")
    (run / "review.json").write_text(json.dumps({"revisions": {"s0001": {"target": "嗨。"}}, "notes": {"s0002": "note: check"}}), encoding="utf-8")
    (run / "asr-report.json").write_text(json.dumps({"sentences": [{"id": "s0001", "similarity": 0.4, "recognized": "hi"}]}), encoding="utf-8")
    (run / "schedule.json").write_text(json.dumps({"sentences": [
        {"id": "s0001", "actualStart": 1.0, "dubSeconds": 1.5},
        {"id": "s0002", "actualStart": 3.0, "dubSeconds": 1.0}]}), encoding="utf-8")
    audio = run / "track.wav"
    with wave.open(str(audio), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 100)
    return run


def test_review_player_embeds_rows_flags_and_audio(tmp_path):
    mod = load("review_player")
    run = _make_review_run(tmp_path)
    out = tmp_path / "player" / "review-player.html"
    result = mod.build_player(run, out, title="测试听审")
    assert result["rows"] == 2
    assert result["flagged"] == 2
    html = out.read_text(encoding="utf-8")
    assert '"s0001"' in html and '"s0002"' in html
    assert "track.wav" in html
    assert "asr" in html and "speaker" in html and "revised" in html and "note" in html
    assert "测试听审" in html


def test_repair_window_for():
    mod = load("repair_sentence")
    batches = [{"batchIndex": 0, "ids": ["s0001", "s0002"], "batchSize": 2},
               {"batchIndex": 1, "ids": ["s0003"], "batchSize": 1}]
    assert mod.window_for(batches, "s0002")["batchIndex"] == 0
    try:
        mod.window_for(batches, "s9999")
    except SystemExit as exc:
        assert "not in tts/tts-batches.jsonl" in str(exc)
    else:
        raise AssertionError("missing window should fail")
