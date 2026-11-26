#!/usr/bin/env python3
"""What the English review page shows for one candidate sentence table.

Cuts one 16 kHz mono WAV per unit from source.wav (stdlib wave, exact sample boundaries) and
writes rows.json: per unit the text, the times, and the reasons to look at it:

  edited     a machine fix changed the text (the page shows the text before the fix)
  disagree   the two transcription passes read this unit differently (the page shows the other reading)
  number     the text has a number or a chapter/verse reference
  long       longer than --long-seconds

The output directory is the review step's asset directory: rows.json and slices/<unit>.wav.
This is the 2026-11-21 week-11 review page builder without the page: the page is
apps/review-web/english.html, and this script only prepares its data.
"""
from __future__ import annotations

import argparse
import json
import re
import wave
from pathlib import Path

NUMBER = re.compile(r"\b\d[\d,.:]*\b")
SCRIPTURE = re.compile(r"\b(?:chapter|verse|chapters|verses)\s+\w+", re.I)


def slice_wav(source: wave.Wave_read, start: float, end: float, target: Path) -> None:
    rate = source.getframerate()
    first = max(0, int(start * rate))
    last = min(source.getnframes(), int(end * rate))
    source.setpos(first)
    data = source.readframes(max(0, last - first))
    with wave.open(str(target), "wb") as out:
        out.setnchannels(source.getnchannels())
        out.setsampwidth(source.getsampwidth())
        out.setframerate(rate)
        out.writeframes(data)


def build_rows(manifest: dict, *, fixes: dict | None = None, crosscheck: dict | None = None, long_seconds: float = 12.0) -> list[dict]:
    edited: dict[str, dict] = {}
    for item in (fixes or {}).get("fixes", []):
        edited.setdefault(item["after"], item)
    checked = (crosscheck or {}).get("units", {})
    rows = []
    for unit in manifest["sourceUnits"]:
        text, unit_id = unit["english"], unit["sourceUnitId"]
        flags = []
        if text in edited:
            flags.append("edited")
        second = checked.get(unit_id)
        if second and not second["agrees"]:
            flags.append("disagree")
        if NUMBER.search(text) or SCRIPTURE.search(text):
            flags.append("number")
        if unit["end"] - unit["start"] > long_seconds:
            flags.append("long")
        rows.append({"id": unit_id, "start": unit["start"], "end": unit["end"],
                     "seconds": round(unit["end"] - unit["start"], 2), "english": text, "flags": flags,
                     "before": edited[text]["before"] if text in edited else None,
                     "secondPass": second["secondPass"] if second and not second["agrees"] else None,
                     "audio": f"slices/{unit_id}.wav"})
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--manifest", type=Path, required=True, help="candidate anchor-manifest.json")
    parser.add_argument("--audio", type=Path, required=True, help="source.wav (PCM)")
    parser.add_argument("--out", type=Path, required=True, help="asset directory for the review step")
    parser.add_argument("--fixes-applied", type=Path, help="english-fixes-applied.json")
    parser.add_argument("--crosscheck", type=Path, help="english-crosscheck.json")
    parser.add_argument("--file-name", default="")
    parser.add_argument("--transcription", default="whisper-1 给词级时间，gpt-4o-transcribe 做第二遍文字核对；不是 MFA 对齐")
    parser.add_argument("--long-seconds", type=float, default=12.0)
    args = parser.parse_args(argv)

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    load = lambda path: json.loads(path.read_text(encoding="utf-8")) if path and path.exists() else None
    rows = build_rows(manifest, fixes=load(args.fixes_applied), crosscheck=load(args.crosscheck), long_seconds=args.long_seconds)
    slices = args.out / "slices"
    slices.mkdir(parents=True, exist_ok=True)
    wanted = {f"{row['id']}.wav" for row in rows}
    for stale in slices.glob("*.wav"):                       # a rebuilt candidate renumbers its units
        if stale.name not in wanted:
            stale.unlink()
    with wave.open(str(args.audio), "rb") as source:
        for row in rows:
            slice_wav(source, row["start"], row["end"], slices / f"{row['id']}.wav")
    duration = manifest["input"]["mediaDurationSeconds"]
    data = {"summary": {"fileName": args.file_name, "durationSeconds": duration, "window": {"start": 0.0, "end": duration},
                        "transcription": args.transcription},
            "rows": rows}
    (args.out / "rows.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "flagged": sum(1 for row in rows if row["flags"]),
                      "counts": {name: sum(1 for row in rows if name in row["flags"]) for name in ("edited", "disagree", "number", "long")},
                      "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
