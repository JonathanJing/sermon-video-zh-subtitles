#!/usr/bin/env python3
"""Trim leading/trailing silence from rendered sentence WAVs so dubbing does not drift.

Each Qwen3-TTS sentence WAV carries ~0.37 s of leading silence and ~0.07 s of trailing
silence; at 457 sentences that is ~200 s, more than the Chinese/English length difference.
Trimming edges (never inside a sentence) recovers both the drift and the late onset, without
deleting a single word. Original bytes are kept once in <tts>/../tts-raw-before-trim/.
"""
from __future__ import annotations

import argparse
import array
import json
import shutil
import wave
from pathlib import Path

LEAD_KEEP = 0.02
TAIL_KEEP = 0.05


def trim(path: Path, threshold_ratio: float) -> tuple[float, float, float]:
    with wave.open(str(path), "rb") as handle:
        rate, width, channels = handle.getframerate(), handle.getsampwidth(), handle.getnchannels()
        frames = handle.getnframes()
        pcm = array.array("h")
        pcm.frombytes(handle.readframes(frames))
    if width != 2 or channels != 1:
        raise SystemExit(f"{path}: need PCM16 mono")
    peak = max(1, max(abs(s) for s in pcm))
    threshold = peak * threshold_ratio
    first, last = None, None
    for i, value in enumerate(pcm):
        if abs(value) > threshold:
            first = i
            break
    if first is None:
        return 0.0, 0.0, frames / rate
    for i in range(len(pcm) - 1, -1, -1):
        if abs(pcm[i]) > threshold:
            last = i
            break
    keep_from = max(0, first - int(LEAD_KEEP * rate))
    keep_to = min(len(pcm), last + 1 + int(TAIL_KEEP * rate))
    original = frames / rate
    trimmed = (keep_to - keep_from) / rate
    if trimmed >= original - 1e-3:
        return 0.0, original, original
    backup = path.parent.parent / "tts-raw-before-trim"
    backup.mkdir(exist_ok=True)
    if not (backup / path.name).exists():
        shutil.copy2(path, backup / path.name)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm[keep_from:keep_to].tobytes())
    return original - trimmed, original, trimmed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--threshold-ratio", type=float, default=0.02)
    args = parser.parse_args()
    tts = args.run / "tts"
    entries, total = [], 0.0
    for path in sorted(tts.glob("*.wav")):
        saved, before, after = trim(path, args.threshold_ratio)
        total += saved
        entries.append({"id": path.stem, "savedSeconds": round(saved, 3),
                        "beforeSeconds": round(before, 3), "afterSeconds": round(after, 3)})
    report = {"schemaVersion": "sentence-first-tts-silence-trim-v1",
              "sentences": len(entries), "savedSeconds": round(total, 1),
              "leadKeepSeconds": LEAD_KEEP, "tailKeepSeconds": TAIL_KEEP,
              "entries": entries}
    (args.run / "tts-silence-trim.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"sentences": len(entries), "savedSeconds": round(total, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
