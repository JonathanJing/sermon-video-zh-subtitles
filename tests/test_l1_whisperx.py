"""l1_whisperx.py: replace whisper-1 word times before the English review."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from weekly_auto_helpers import make_raw, write_wav  # noqa: E402

SCRIPT = ROOT / "experiments" / "sentence-first-agent" / "l1_whisperx.py"
ANCHOR = ROOT / "experiments" / "sentence-first-agent" / "l1_anchor.py"


def fake_adapter(root: Path, *, mismatch: bool = False) -> Path:
    path = root / "fake_adapter.py"
    path.write_text(f'''import argparse, json
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--request", type=Path); p.add_argument("--out", type=Path)
p.add_argument("--device"); p.add_argument("--language")
a = p.parse_args()
request = json.loads(a.request.read_text())
chunks = []
for chunk in request["chunks"]:
    tokens = chunk["text"].split()
    if {mismatch!r}:
        tokens = tokens[:-1]
    words = []
    for index, token in enumerate(tokens):
        start = chunk["start"] + index * 0.1
        words.append({{"text": token, "start": round(start, 3), "end": round(start + 0.08, 3)}})
    chunks.append({{"id": chunk["id"], "start": chunk["start"], "end": chunk["end"], "words": words}})
a.out.write_text(json.dumps({{"schemaVersion": "sermon-whisperx-alignment-result-v1",
    "model": {{"whisperxVersion": "fake"}}, "elapsedSeconds": 0.01, "attemptCounts": {{"chunk_exact": len(chunks)}},
    "chunks": chunks}}))
''', encoding="utf-8")
    return path


def test_whisperx_raw_feeds_the_anchor_builder(tmp_path):
    raw = make_raw()
    raw_path = tmp_path / "raw-whisper.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    audio = tmp_path / "source.wav"
    write_wav(audio, raw["duration"])
    out = tmp_path / "raw-whisperx.json"
    words = tmp_path / "words.json"
    command = [sys.executable, str(SCRIPT), "--raw-whisper", str(raw_path), "--audio", str(audio),
               "--out", str(out), "--words-out", str(words), "--runtime-python", sys.executable,
               "--adapter", str(fake_adapter(tmp_path))]
    subprocess.run(command, check=True, capture_output=True, text=True)
    aligned = json.loads(out.read_text())
    assert aligned["timingQuality"] == "whisperx_wav2vec2_forced_alignment"
    assert len(aligned["words"]) == len(raw["words"])
    assert len(json.loads(words.read_text())) == len(raw["words"])
    anchor = tmp_path / "anchor"
    subprocess.run([sys.executable, str(ANCHOR), "build", "--raw", str(out),
                    "--media-sha256", "a" * 64, "--media-duration", repr(raw["duration"]),
                    "--out", str(anchor), "--source-url", "https://example.test/source",
                    "--date", "2026-11-22", "--speaker-source", "test",
                    "--timing-basis", "WhisperX test", "--timing-source", "raw-whisperx.json"],
                   check=True, capture_output=True, text=True)
    manifest = json.loads((anchor / "anchor-manifest.json").read_text())
    assert manifest["policy"]["timingBasis"] == "WhisperX test"
    assert manifest["input"]["source"] == "raw-whisperx.json"


def test_a_token_mismatch_stops_the_stage(tmp_path):
    raw = make_raw()
    raw_path = tmp_path / "raw-whisper.json"
    raw_path.write_text(json.dumps(raw), encoding="utf-8")
    audio = tmp_path / "source.wav"
    write_wav(audio, raw["duration"])
    proc = subprocess.run([sys.executable, str(SCRIPT), "--raw-whisper", str(raw_path), "--audio", str(audio),
                           "--out", str(tmp_path / "raw-whisperx.json"),
                           "--runtime-python", sys.executable,
                           "--adapter", str(fake_adapter(tmp_path, mismatch=True))],
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "token_sequence_mismatch" in (proc.stderr or "")
