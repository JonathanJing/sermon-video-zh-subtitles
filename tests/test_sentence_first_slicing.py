"""Unit tests for in-process WAV slicing (``slice_sentences.py``)."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
import sys
import wave

HERE = Path(__file__).resolve().parents[1]
EXPERIMENTS = HERE / "experiments" / "sentence-first-agent"


def load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, EXPERIMENTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_wav(path: Path, *, seconds: float = 6.0, rate: int = 16000, channels: int = 1) -> list[int]:
    samples = [((index * 37) % 4000) - 2000 for index in range(round(seconds * rate))]
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        frames = [sample for sample in samples for _ in range(channels)]
        handle.writeframes(b"".join(sample.to_bytes(2, "little", signed=True) for sample in frames))
    return samples


def write_sentences(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def three_sentences() -> list[dict]:
    return [{"id": "s0001", "start": 0.5, "end": 1.5, "pauseAfter": 0.2},
            {"id": "s0002", "start": 2.0, "end": 3.0, "pauseAfter": 0.0},
            {"id": "s0003", "start": 4.0, "end": 5.5, "pauseAfter": 0.0}]


def test_wave_slicing_writes_pcm16_mono_slices_with_the_loop_bounds(tmp_path):
    mod = load("slice_sentences")
    audio = tmp_path / "clip.wav"
    samples = write_wav(audio)
    sentences = tmp_path / "sentences.jsonl"
    write_sentences(sentences, three_sentences())
    out = tmp_path / "slices"
    assert mod.main(["--audio", str(audio), "--sentences", str(sentences), "--out", str(out)]) == 0
    report = json.loads((out / "slices.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in report] == ["s0001", "s0002", "s0003"]
    first = report[0]
    # pad 0.08, clamped by the neighbour on the right only (s0002 starts at 2.0)
    assert first["sliceStart"] == 0.42
    assert first["sliceEnd"] == 1.58
    assert first["budgetSeconds"] == 1.2
    assert abs(first["sliceSeconds"] - 1.16) <= 0.001
    with wave.open(str(out / "s0001.wav"), "rb") as handle:
        assert (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) == (1, 2, 16000)
        frames = handle.readframes(handle.getnframes())
    expected = samples[round(0.42 * 16000):round(1.58 * 16000)]
    assert frames == b"".join(sample.to_bytes(2, "little", signed=True) for sample in expected)
    # the first slice is clamped at zero, the last one at the clip end
    assert report[0]["sliceStart"] >= 0
    assert report[-1]["sliceEnd"] <= 6.0


def test_existing_slices_are_kept(tmp_path):
    mod = load("slice_sentences")
    audio = tmp_path / "clip.wav"
    write_wav(audio)
    sentences = tmp_path / "sentences.jsonl"
    write_sentences(sentences, three_sentences())
    out = tmp_path / "slices"
    assert mod.main(["--audio", str(audio), "--sentences", str(sentences), "--out", str(out)]) == 0
    marker = b"do-not-touch"
    (out / "s0002.wav").write_bytes(marker)
    assert mod.main(["--audio", str(audio), "--sentences", str(sentences), "--out", str(out)]) == 0
    assert (out / "s0002.wav").read_bytes() == marker


def test_wave_mode_rejects_non_pcm16_mono(tmp_path, capsys):
    mod = load("slice_sentences")
    audio = tmp_path / "clip.wav"
    write_wav(audio, channels=2)
    sentences = tmp_path / "sentences.jsonl"
    write_sentences(sentences, three_sentences())
    try:
        mod.main(["--audio", str(audio), "--sentences", str(sentences), "--out", str(tmp_path / "slices")])
    except SystemExit as exc:
        assert "PCM16 mono" in str(exc)
    else:
        raise AssertionError("stereo input should be rejected")


def test_ffmpeg_method_produces_the_same_slice_boundaries(tmp_path):
    mod = load("slice_sentences")
    if not shutil.which("ffmpeg"):
        return
    audio = tmp_path / "clip.wav"
    write_wav(audio)
    sentences = tmp_path / "sentences.jsonl"
    write_sentences(sentences, three_sentences())
    wave_out = tmp_path / "wave"
    ffmpeg_out = tmp_path / "ffmpeg"
    assert mod.main(["--audio", str(audio), "--sentences", str(sentences), "--out", str(wave_out)]) == 0
    assert mod.main(["--audio", str(audio), "--sentences", str(sentences), "--out", str(ffmpeg_out),
                     "--method", "ffmpeg"]) == 0
    wave_report = json.loads((wave_out / "slices.json").read_text(encoding="utf-8"))
    ffmpeg_report = json.loads((ffmpeg_out / "slices.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in wave_report] == [row["id"] for row in ffmpeg_report]
    for left, right in zip(wave_report, ffmpeg_report):
        assert right["sliceStart"] == left["sliceStart"]
        assert right["sliceEnd"] == left["sliceEnd"]
        assert abs(right["sliceSeconds"] - left["sliceSeconds"]) <= 0.02
