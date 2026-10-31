#!/usr/bin/env python3
"""Cut one source-audio WAV per sentence (experiment only).

Default method is in-process ``wave`` slicing: read the source WAV once and write each
slice as a byte range, instead of spawning one ffmpeg per sentence (the old loop decoded
the source from 0 for every slice and took ~142 s for 890 sentences). ``--method ffmpeg``
keeps a per-sentence ffmpeg fallback for WAVs that are not PCM16 mono.

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


def slice_bounds(rows: list[dict], index: int, total: float, pad: float) -> tuple[float, float]:
    """The old ffmpeg loop's boundaries: pad outward but never cross a neighbour or the clip."""
    row = rows[index]
    prev_end = rows[index - 1]["end"] if index else 0.0
    next_start = rows[index + 1]["start"] if index + 1 < len(rows) else total
    start = max(prev_end, row["start"] - pad, 0.0)
    end = min(next_start, row["end"] + pad, total)
    return start, end


def _slice_row(row: dict, start: float, end: float, seconds: float, target: Path) -> dict:
    return {"id": row["id"], "sliceStart": round(start, 3), "sliceEnd": round(end, 3),
            "speechSeconds": round(row["end"] - row["start"], 3),
            "sliceSeconds": round(seconds, 3),
            "budgetSeconds": round(row["end"] - row["start"] + row.get("pauseAfter", 0.0), 3),
            "path": str(target)}


def write_wave_slices(audio: Path, rows: list[dict], out: Path, pad: float) -> list[dict]:
    with wave.open(str(audio), "rb") as handle:
        channels, width, rate, frames = (handle.getnchannels(), handle.getsampwidth(),
                                         handle.getframerate(), handle.readframes(handle.getnframes()))
    if channels != 1 or width != 2:
        raise SystemExit(f"{audio}: wave slicing needs PCM16 mono, got channels={channels} width={width}; "
                         "use --method ffmpeg")
    total_frames = len(frames) // 2
    total = total_frames / rate
    report = []
    for index, row in enumerate(rows):
        start, end = slice_bounds(rows, index, total, pad)
        first, last = max(0, round(start * rate)), min(total_frames, round(end * rate))
        if last <= first:
            raise SystemExit(f"{row['id']}: empty slice after clamping ({start:.3f}-{end:.3f})")
        target = out / f"{row['id']}.wav"
        if not target.exists():
            with wave.open(str(target), "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(rate)
                handle.writeframes(frames[first * 2:last * 2])
        report.append(_slice_row(row, start, end, (last - first) / rate, target))
    return report


def write_ffmpeg_slices(audio: Path, rows: list[dict], out: Path, pad: float) -> list[dict]:
    total = wav_seconds(audio)
    report = []
    for index, row in enumerate(rows):
        start, end = slice_bounds(rows, index, total, pad)
        target = out / f"{row['id']}.wav"
        if not target.exists():
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}",
                            "-i", str(audio), "-t", f"{max(0.0, end - start):.3f}",
                            "-c:a", "pcm_s16le", str(target)], check=True)
        report.append(_slice_row(row, start, end, wav_seconds(target), target))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pad", type=float, default=0.08)
    parser.add_argument("--method", choices=("wave", "ffmpeg"), default="wave",
                        help="wave slices in-process once (default); ffmpeg spawns one encoder per sentence")
    args = parser.parse_args(argv)
    rows = read_sentences(args.sentences)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.method == "wave":
        report = write_wave_slices(args.audio, rows, args.out, args.pad)
    else:
        report = write_ffmpeg_slices(args.audio, rows, args.out, args.pad)
    (args.out / "slices.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({"slices": len(report), "out": str(args.out), "method": args.method}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
