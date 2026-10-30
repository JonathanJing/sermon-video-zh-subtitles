#!/usr/bin/env python3
"""Write one human-review sheet per finished locale run (CSV, UTF-8 with BOM for Excel/Numbers).

One row per sentence: speaker, time in the dub track, time in the source, English, the target text,
the spoken text when it differs, the back-transcription similarity, the review note, and the reason
to listen closely (back-transcription below 0.85, speaker agreement in doubt, a source doubt passed
with --doubt, or a revised translation). Run it as soon as a locale finishes, so the listener can
start on that track while the next locale renders.

  review_sheets.py --out <dir> --window-start 5.5 --run zh-Hans=<zh-run> --run ko=<ko-run> \\
      [--doubt doubts.json]   # {"s0043": "source may be an ASR error"}
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
from pathlib import Path
import unicodedata


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mmss(t: float) -> str:
    t = int(round(t))
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"


def norm(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", (text or "").lower()) if not unicodedata.combining(c))
    return "".join(c for c in text if not unicodedata.category(c).startswith(("P", "Z", "S")))


def quiet(note: str) -> bool:
    return note == "pass" or note.startswith("reused")


def sheet(run: Path, locale: str, out: Path, window_start: float, doubt: dict[str, str], names: dict[str, str]) -> dict:
    sent = rows(run / "sentences.jsonl")
    tr = {r["id"]: r for r in rows(run / "translations.jsonl")}
    sp = {r["id"]: r for r in rows(run / "speech.jsonl")}
    sched = {r["id"]: r for r in json.loads((run / "schedule.json").read_text())["sentences"]}
    heard = ({r["id"]: r["recognized"] for r in rows(run / "asr.jsonl")}
             if (run / "asr.jsonl").exists() else {})
    path = out / f"review-{locale}.csv"
    flagged = 0
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["句号", "讲员", "配音音轨时间", "原片时间", "English", "译文（字幕）", "口播稿（与译文不同时）",
                    "回转写相似度", "回转写文字（低于0.9时）", "翻译复核备注", "重点听", "结论（通过 / 问题：…）"])
        for s in sent:
            i, t, k = s["id"], tr[s["id"]], sp[s["id"]]
            sim = difflib.SequenceMatcher(None, norm(k["spokenText"]), norm(heard.get(i, "")), autojunk=False).ratio()
            note = t.get("reviewNote", "pass")
            reasons = [r for r, hit in (("回转写不一致", bool(heard) and sim < 0.85), ("讲员归属存疑", s.get("speakerReview") == "check"),
                                        (doubt.get(i, ""), i in doubt), ("复核改过或有备注", not quiet(note))) if hit]
            flagged += bool(reasons)
            w.writerow([i, names.get(s.get("speakerId", ""), s.get("speakerId", "")), mmss(sched[i]["actualStart"]),
                        mmss(s["start"] + window_start), s["english"], t["target"],
                        k["spokenText"] if k["spokenText"] != t["target"] else "", f"{sim:.2f}",
                        heard.get(i, "") if sim < 0.9 else "", "" if quiet(note) else note, "；".join(reasons), ""])
    return {"rows": len(sent), "flagged": flagged, "sheet": str(path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--run", action="append", required=True, metavar="LOCALE=RUN_DIR")
    parser.add_argument("--window-start", type=float, default=0.0, help="media seconds of the approved window start")
    parser.add_argument("--doubt", type=Path, help="json {sentenceId: reason} for doubtful source sentences")
    parser.add_argument("--name", action="append", default=["steve_bang_lee=Steve", "john_thomas=John"],
                        metavar="SPEAKERID=LABEL")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    doubt = json.loads(args.doubt.read_text(encoding="utf-8")) if args.doubt else {}
    names = dict(n.split("=", 1) for n in args.name)
    summary = {}
    for item in args.run:
        locale, run = item.split("=", 1)
        summary[locale] = sheet(Path(run), locale, args.out, args.window_start, doubt, names)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
