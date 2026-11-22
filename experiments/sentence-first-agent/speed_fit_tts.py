#!/usr/bin/env python3
"""Per-sentence dynamic speed fit for sync runs (atempo, max 1.15 by default).

The sync budget per sentence is its English source slot. After the edge-silence trim a few
sentences still read longer than their slot; instead of cutting words, each *lagging* sentence
is time-compressed by the smallest amount that clears its own accumulated lag, never more than
``--max-speed``. Sentences that are not behind are left untouched, so the change stays local:
the catch-up is consumed sentence by sentence and stops as soon as lag is back under threshold.

Time compression uses ffmpeg ``atempo`` (pitch preserved). Originals are kept once in
``<run>/tts-before-speed/`` and the per-sentence factors are written to ``<run>/speed-fit.json``.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import wave
from pathlib import Path


def read_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def plan_speed_fit(rows: list[dict], durations: dict[str, float], *, gap: float = 0.05,
                   threshold: float = 0.3, max_speed: float = 1.15,
                   min_speed: float = 1.005) -> tuple[list[dict], dict]:
    """Decide one factor per sentence from its own English slot (no cross-sentence coupling).

    ``rows`` needs ``id``, ``slotSeconds`` (English start of the next sentence minus this start,
    or this sentence's own source span for the last one) and ``start``. A sentence whose dub is
    longer than its slot by more than ``threshold`` is compressed to fit the slot (minus the gap),
    capped at ``max_speed``. Sentences that already fit are left byte-identical.
    """
    plan: list[dict] = []
    worst_slot_overrun = 0.0
    for row in rows:
        identifier = row["id"]
        dub = durations.get(identifier)
        slot = float(row["slotSeconds"]) - gap
        if dub is None or slot <= 0.2:
            continue
        overrun = dub - slot
        worst_slot_overrun = max(worst_slot_overrun, overrun)
        if overrun <= threshold:
            continue
        factor = min(max_speed, dub / slot)
        if factor < min_speed:
            continue
        played = dub / factor
        plan.append({"id": identifier, "factor": round(factor, 4),
                     "slotSeconds": round(slot, 3), "dubSeconds": round(dub, 3),
                     "overrunSeconds": round(overrun, 3), "playedSeconds": round(played, 3),
                     "savedSeconds": round(dub - played, 3)})
    summary = {"sentences": len(rows), "adjusted": len(plan),
               "savedSeconds": round(sum(item["savedSeconds"] for item in plan), 2),
               "worstSlotOverrunSeconds": round(worst_slot_overrun, 3),
               "maxFactor": max([item["factor"] for item in plan], default=1.0)}
    return plan, summary


def plan_lag_fit(rows: list[dict], durations: dict[str, float], *, threshold: float = 0.5,
                 max_speed: float = 1.15, min_speed: float = 1.005) -> tuple[list[dict], dict]:
    """Speed up only the sentences that are actually behind, to re-align them at their time point.

    ``rows`` needs ``id``, ``lagSeconds`` (from schedule.json) and ``dubSeconds``. The factor is
    ``dub / (dub - lag)``: exactly what is needed for this sentence to end where its English
    source ends, capped at max_speed. Sentences inside the threshold are left untouched.
    """
    plan: list[dict] = []
    for row in rows:
        identifier = row["id"]
        dub = durations.get(identifier)
        lag = float(row.get("lagSeconds") or 0.0)
        if dub is None or lag <= threshold or dub <= 0.2:
            continue
        factor = min(max_speed, dub / max(0.2, dub - lag))
        if factor < min_speed:
            continue
        played = dub / factor
        plan.append({"id": identifier, "factor": round(factor, 4), "lagSeconds": round(lag, 3),
                     "dubSeconds": round(dub, 3), "playedSeconds": round(played, 3),
                     "savedSeconds": round(dub - played, 3)})
    summary = {"mode": "lag", "sentences": len(rows), "adjusted": len(plan),
               "savedSeconds": round(sum(item["savedSeconds"] for item in plan), 2),
               "maxLagAdjusted": max([item["lagSeconds"] for item in plan], default=0.0),
               "maxFactor": max([item["factor"] for item in plan], default=1.0)}
    return plan, summary


def stretch(path: Path, factor: float, rate: int) -> None:
    tmp = path.with_suffix(".speed.tmp.wav")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path),
                    "-filter:a", f"atempo={factor:.6f}", "-ac", "1", "-ar", str(rate),
                    "-c:a", "pcm_s16le", str(tmp)], check=True)
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--max-speed", type=float, default=1.15)
    parser.add_argument("--threshold", type=float, default=0.3)
    parser.add_argument("--gap", type=float, default=0.05)
    parser.add_argument("--mode", choices=("slot", "lag"), default="slot",
                        help="slot: fit each sentence to its English slot (first pass); "
                             "lag: only speed up sentences measured behind in schedule.json")
    parser.add_argument("--from-schedule", type=Path, help="schedule.json for --mode lag (default <run>/schedule.json)")
    parser.add_argument("--force", action="store_true", help="re-plan even if speed-fit.json exists")
    args = parser.parse_args()
    run = args.run
    report = run / "speed-fit.json"
    if report.exists() and not args.force:
        print(json.dumps({"skipped": "speed-fit.json exists", **json.loads(report.read_text())["summary"]}))
        return 0
    sentences = [json.loads(line) for line in
                 (run / "sentences.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    for index, row in enumerate(sentences):
        if index + 1 < len(sentences):
            slot = sentences[index + 1]["start"] - row["start"]
        else:
            slot = row["end"] - row["start"]
        rows.append({"id": row["id"], "start": row["start"], "slotSeconds": slot})
    wavs = {path.stem: path for path in (run / "tts").glob("*.wav")}
    durations = {identifier: read_duration(path) for identifier, path in wavs.items()}
    if args.mode == "lag":
        schedule_path = args.from_schedule or (run / "schedule.json")
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        srows = {row["id"]: row for row in schedule["sentences"]}
        rows = [{"id": row["id"], "lagSeconds": float(srows[row["id"]]["lagSeconds"]),
                 "dubSeconds": float(srows[row["id"]]["dubSeconds"])}
                for row in sentences if row["id"] in srows]
        plan, summary = plan_lag_fit(rows, durations, threshold=args.threshold,
                                     max_speed=args.max_speed)
    else:
        plan, summary = plan_speed_fit(rows, durations, gap=args.gap,
                                       threshold=args.threshold, max_speed=args.max_speed)
    backup = run / "tts-before-speed"
    if plan:
        backup.mkdir(exist_ok=True)
    with wave.open(str(next(iter(wavs.values()))), "rb") as probe:
        rate = probe.getframerate()
    for item in plan:
        path = wavs[item["id"]]
        if not (backup / path.name).exists():
            shutil.copy2(path, backup / path.name)
        stretch(path, item["factor"], rate)
        item["afterSeconds"] = round(read_duration(path), 3)
    report.write_text(json.dumps({"schemaVersion": "sentence-first-speed-fit-v1",
                                  "maxSpeed": args.max_speed, "threshold": args.threshold,
                                  "summary": summary, "sentences": plan},
                                 ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
