#!/usr/bin/env python3
"""Place sentence WAVs on the source timeline into one track (experiment only).

Each sentence starts at its English start; when the previous dub is still
playing it starts ``gap`` seconds after that dub ends instead. Nothing is
sped up, cut or stretched. Writes ``track.wav`` (PCM16 mono) and a schedule
with planned start, actual start and lag per sentence.
"""
from __future__ import annotations

import argparse
import array
import json
from pathlib import Path
import sys
import wave


def read_pcm(path: Path) -> tuple[array.array, int]:
    with wave.open(str(path), "rb") as handle:
        if handle.getsampwidth() != 2 or handle.getnchannels() != 1:
            raise SystemExit(f"{path}: need PCM16 mono")
        rate = handle.getframerate()
        pcm = array.array("h")
        pcm.frombytes(handle.readframes(handle.getnframes()))
    if sys.byteorder == "big":
        pcm.byteswap()
    return pcm, rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sentences", type=Path, required=True)
    parser.add_argument("--tts", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--schedule", type=Path, required=True)
    parser.add_argument("--gap", type=float, default=0.25)
    parser.add_argument("--allow-missing", action="store_true",
                        help="leave silence where a sentence has no WAV instead of stopping")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.sentences.read_text(encoding="utf-8").splitlines() if line.strip()]
    units, rate = [], None
    for row in rows:
        path = args.tts / f"{row['id']}.wav"
        if not path.exists():
            if args.allow_missing:
                units.append((row, None))
                continue
            raise SystemExit(f"missing dub: {path}")
        pcm, unit_rate = read_pcm(path)
        if rate is None:
            rate = unit_rate
        elif unit_rate != rate:
            raise SystemExit(f"{path}: sample rate {unit_rate} differs from {rate}")
        units.append((row, pcm))
    if rate is None:
        raise SystemExit("no dubbed sentences found")
    cursor, schedule, placed = 0.0, [], []
    for row, pcm in units:
        if pcm is None:
            schedule.append({"id": row["id"], "plannedStart": row["start"], "actualStart": None,
                             "lagSeconds": None, "dubSeconds": None, "missing": True})
            continue
        actual = max(row["start"], cursor)
        seconds = len(pcm) / rate
        schedule.append({"id": row["id"], "plannedStart": row["start"], "actualStart": round(actual, 3),
                         "lagSeconds": round(actual - row["start"], 3), "dubSeconds": round(seconds, 3),
                         "sourceSeconds": round(row["end"] - row["start"], 3)})
        placed.append((actual, pcm))
        cursor = actual + seconds + args.gap
    total_frames = max(int(round((start + len(pcm) / rate) * rate)) for start, pcm in placed)
    track = array.array("h", bytes(total_frames * 2))
    for start, pcm in placed:
        offset = int(round(start * rate))
        track[offset:offset + len(pcm)] = pcm
    if sys.byteorder == "big":
        track.byteswap()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(args.out), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(track.tobytes())
    lags = [s["lagSeconds"] for s in schedule if s.get("lagSeconds") is not None]
    summary = {"sentences": len(rows), "placed": len(placed), "trackSeconds": round(total_frames / rate, 3),
               "maxLagSeconds": round(max(lags), 3) if lags else 0.0,
               "sentencesOverLag8s": sum(1 for lag in lags if lag > 8.0), "gapSeconds": args.gap}
    args.schedule.write_text(json.dumps({"summary": summary, "sentences": schedule}, ensure_ascii=False, indent=2) + "\n",
                             encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
