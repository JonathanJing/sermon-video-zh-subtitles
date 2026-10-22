#!/usr/bin/env python3
"""Cut one source-audio WAV per sentence with ffmpeg (experiment only).

Each slice runs from ``start - pad`` to ``end + pad`` without crossing the
neighbouring sentences. Writes ``<out>/<id>.wav`` and ``<out>/slices.json``
with each slice's measured duration. Existing slices are kept.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import wave


def read_sentences(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit("sentences: empty")
    return rows


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pad", type=float, default=0.08)
    args = parser.parse_args()
    rows = read_sentences(args.sentences)
    args.out.mkdir(parents=True, exist_ok=True)
    total = wav_seconds(args.audio)
    report = []
    for i, row in enumerate(rows):
        prev_end = rows[i - 1]["end"] if i else 0.0
        next_start = rows[i + 1]["start"] if i + 1 < len(rows) else total
        start = max(prev_end, row["start"] - args.pad, 0.0)
        end = min(next_start, row["end"] + args.pad, total)
        target = args.out / f"{row['id']}.wav"
        if not target.exists():
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(args.audio),
                            "-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-c:a", "pcm_s16le",
                            str(target)], check=True)
        report.append({"id": row["id"], "sliceStart": round(start, 3), "sliceEnd": round(end, 3),
                       "speechSeconds": round(row["end"] - row["start"], 3),
                       "sliceSeconds": round(wav_seconds(target), 3),
                       "budgetSeconds": round(row["end"] - row["start"] + row.get("pauseAfter", 0.0), 3),
                       "path": str(target)})
    (args.out / "slices.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({"slices": len(report), "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
