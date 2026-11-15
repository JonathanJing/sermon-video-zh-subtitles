#!/usr/bin/env python3
"""Prepare and score a blinded quality comparison of two Chinese translations.

Inputs are the captured service and one production reading run:

  capture/session.english.jsonl     provider English finals with ts
  capture/session.mandarin.jsonl    pastors.ai Mandarin finals with ts
  ours/segments_timed_zh.json       our Layer 2 Chinese (--ours layer2)
  ours/reading-edition-v2/...       our reading-edition Chinese (--ours reading)

`prepare` builds English anchor units, aligns both candidates by time,
writes the full alignment, samples a stratified blinded subset, and creates
the rater CSV templates and a blind review packet.  `score` reads the filled
CSVs, unblinds, runs deterministic coverage hints, and aggregates human
ratings with bootstrap confidence intervals.

No model, network or paid call is used.  Human ratings are the primary
evidence; the deterministic checks are advisory.

Usage
-----
  .venv/bin/python experiments/translation-quality-comparison/compare.py prepare \
      --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15 \
      --ours-dir artifacts/live-reading-tests/20261115-north-irvine \
      --ours layer2 \
      --outdir artifacts/translation-comparison/20261115-north-irvine \
      --sample-size 30 --seed 20261115

  ... compare.py score --outdir artifacts/translation-comparison/20261115-north-irvine
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

PREPARE_SCHEMA = "translation-quality-comparison-prepare/v1"
SCORE_SCHEMA = "translation-quality-comparison-score/v1"
RATING_COLUMNS = [
    "unit_id",
    "a_adequacy",
    "a_fluency",
    "b_adequacy",
    "b_fluency",
    "preference",
    "critical_a",
    "major_a",
    "minor_a",
    "critical_b",
    "major_b",
    "minor_b",
    "notes",
]
SENTENCE_END = re.compile(r"[.!?][\"')\]]*$")
SCRIPTURE = re.compile(r"\b\d+:\d+\b")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
SRT_TIME = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{number}: {exc}") from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def sentence_end(text: str) -> bool:
    return bool(SENTENCE_END.search(text.strip()))


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_capture(capture_dir: Path) -> tuple[dict[str, Any], dict[str, Any], datetime, datetime]:
    capture = read_json(capture_dir / "capture.json", "capture manifest")
    window_path = capture_dir / "sermon.window.json"
    if not window_path.exists():
        raise ValueError(f"no sermon window at {window_path}; run mark_window.py first")
    window_payload = read_json(window_path, "sermon window")
    bound = (window_payload.get("capture") or {}).get("manifest_sha256")
    if bound != sha256_file(capture_dir / "capture.json"):
        raise ValueError("sermon.window.json is not bound to this capture.json")
    window = window_payload.get("sermon_window") or {}
    start = parse_ts(window["start"])
    end = parse_ts(window["end"])
    actual_start = parse_ts(capture["window"]["actual_start"])
    actual_stop = parse_ts(capture["window"]["actual_stop"])
    if start < actual_start or end > actual_stop:
        raise ValueError("sermon window is outside the capture window")
    return capture, window_payload, start, end


def load_candidate_rows(path: Path, kind: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if kind == "layer2":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"expected a list in {path}")
        for item in data:
            if not isinstance(item, dict):
                raise ValueError(f"expected objects in {path}")
            text = clean_text(item.get("zh"))
            if text:
                rows.append({"id": item.get("id"), "start": float(item["start"]), "end": float(item["end"]), "zh": text})
    elif kind == "reading":
        json_path = path / "reading-edition-v2" / "reading_blocks.final.json"
        srt_path = path / "reading-edition-v2" / "sermon_zh_reading_revised.srt"
        if json_path.exists():
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                raise ValueError(f"expected a list in {json_path}")
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError(f"expected objects in {json_path}")
                text = clean_text(item.get("zh") or item.get("draftZh"))
                if text:
                    rows.append(
                        {
                            "id": item.get("id"),
                            "start": float(item["start"]),
                            "end": float(item["end"]),
                            "zh": text,
                        }
                    )
        elif srt_path.exists():
            chunks = re.split(r"\n\s*\n", srt_path.read_text(encoding="utf-8").strip())
            for index, chunk in enumerate(chunks):
                lines = [line for line in chunk.splitlines() if line.strip()]
                if len(lines) < 2:
                    continue
                match = SRT_TIME.search(lines[1] if not SRT_TIME.search(lines[0]) else lines[0])
                if not match:
                    continue
                text_lines = lines[2:] if not SRT_TIME.search(lines[0]) else lines[1:]
                text = clean_text(" ".join(text_lines))
                if not text:
                    continue
                start = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + int(match.group(4)) / 1000
                end = int(match.group(5)) * 3600 + int(match.group(6)) * 60 + int(match.group(7)) + int(match.group(8)) / 1000
                rows.append({"id": index, "start": start, "end": end, "zh": text})
        else:
            raise ValueError(f"no reading-edition output under {path}")
    else:
        raise ValueError(f"unknown candidate kind: {kind}")
    rows.sort(key=lambda item: item["start"])
    return rows


def build_units(
    english: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    unit_seconds: float,
    unit_max_chars: int,
) -> list[dict[str, Any]]:
    selected = []
    for row in english:
        ts = row.get("ts")
        text = clean_text(row.get("text"))
        if not ts or not text:
            continue
        moment = parse_ts(ts)
        if window_start <= moment <= window_end:
            selected.append({"ts": moment, "text": text})
    selected.sort(key=lambda item: item["ts"])
    if not selected:
        raise ValueError("no English lines inside the sermon window")

    units: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        start = current[0]["ts"]
        end = current[-1]["ts"]
        if end <= start:
            end = start + timedelta(seconds=1)
        units.append(
            {
                "unit_id": f"u{len(units) + 1:04d}",
                "start": start,
                "end": end,
                "english": " ".join(item["text"] for item in current),
            }
        )
        current.clear()

    for row in selected:
        if current and (
            row["ts"] - current[0]["ts"] >= timedelta(seconds=unit_seconds)
            or sum(len(item["text"]) for item in current) + len(row["text"]) > unit_max_chars
        ):
            flush()
        current.append(row)
        if current and sentence_end(row["text"]) and (
            row["ts"] - current[0]["ts"] >= timedelta(seconds=unit_seconds * 0.6)
        ):
            flush()
    flush()
    return units


def assign_pastors(units: list[dict[str, Any]], pastors: list[dict[str, Any]]) -> None:
    for unit in units:
        unit["pastors_ts"] = []
        unit["pastors_zh"] = ""
    for row in pastors:
        moment = parse_ts(row["ts"])
        text = clean_text(row.get("text"))
        if not text:
            continue
        best = None
        best_distance = None
        for unit in units:
            if unit["start"] <= moment <= unit["end"]:
                distance = 0.0
            else:
                center = unit["start"] + (unit["end"] - unit["start"]) / 2
                distance = abs((moment - center).total_seconds())
            if best_distance is None or distance < best_distance:
                best = unit
                best_distance = distance
        if best is not None and best_distance is not None and best_distance <= 45:
            best["pastors_ts"].append(iso(moment))
            best["pastors_zh"] = clean_text(best["pastors_zh"] + " " + text)


def assign_ours(units: list[dict[str, Any]], ours: list[dict[str, Any]], window_start: datetime) -> None:
    for unit in units:
        unit["ours_zh"] = ""
        unit["ours_ids"] = []
        unit["ours_overlap_s"] = 0.0
        unit["multi_unit"] = False
    absolute = []
    for row in ours:
        absolute.append(
            {
                "id": row.get("id"),
                "start": window_start + timedelta(seconds=float(row["start"])),
                "end": window_start + timedelta(seconds=float(row["end"])),
                "zh": clean_text(row["zh"]),
            }
        )
    for row in absolute:
        overlaps = []
        for unit in units:
            left = max(row["start"], unit["start"])
            right = min(row["end"], unit["end"])
            seconds = max(0.0, (right - left).total_seconds())
            if seconds > 0:
                overlaps.append((seconds, unit))
        if not overlaps:
            continue
        overlaps.sort(key=lambda item: item[0], reverse=True)
        seconds, best = overlaps[0]
        row_duration = max(0.001, (row["end"] - row["start"]).total_seconds())
        if seconds / row_duration < 0.2:
            continue
        best["ours_zh"] = clean_text(best["ours_zh"] + " " + row["zh"])
        best["ours_ids"].append(row["id"])
        best["ours_overlap_s"] += seconds
        significant = [unit for seconds, unit in overlaps if seconds / row_duration >= 0.2]
        if len(significant) > 1:
            for unit in significant:
                unit["multi_unit"] = True


def classify_units(
    units: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
) -> None:
    total = max(0.001, (window_end - window_start).total_seconds())
    for unit in units:
        duration = max(0.001, (unit["end"] - unit["start"]).total_seconds())
        english_chars = len(unit["english"])
        pastors_chars = len(unit["pastors_zh"])
        ours_chars = len(unit["ours_zh"])
        coverage = min(1.0, unit["ours_overlap_s"] / duration)
        flags = []
        if not unit["pastors_zh"]:
            flags.append("missing_pastors")
        if not unit["ours_zh"]:
            flags.append("missing_ours")
        if pastors_chars and pastors_chars < max(20, 0.12 * english_chars):
            flags.append("short_pastors")
        if ours_chars and ours_chars < max(10, 0.15 * english_chars):
            flags.append("short_ours")
        if coverage < 0.3:
            flags.append("low_ours_coverage")
        elif coverage < 0.6:
            flags.append("medium_ours_coverage")
        if unit.get("multi_unit"):
            flags.append("multi_unit_ours")
        if duration < 8:
            flags.append("short_unit")
        if "missing_pastors" in flags or "missing_ours" in flags or "low_ours_coverage" in flags or "short_pastors" in flags:
            confidence = "low"
        elif flags:
            confidence = "medium"
        else:
            confidence = "high"
        unit.update(
            {
                "english_chars": english_chars,
                "pastors_chars": pastors_chars,
                "ours_chars": ours_chars,
                "ours_coverage": round(coverage, 3),
                "duration_s": round(duration, 3),
                "flags": flags,
                "confidence": confidence,
                "position": min(2, max(0, int(((unit["start"] - window_start).total_seconds() / total) * 3))),
            }
        )
        content = "general"
        if SCRIPTURE.search(unit["english"]):
            content = "scripture"
        elif NUMBER.search(unit["english"]):
            content = "numbers"
        unit["content"] = content
        unit["stratum"] = f"{['beginning', 'middle', 'end'][unit['position']]}:{content}"


def eligible_units(units: list[dict[str, Any]], allow_medium: bool) -> list[dict[str, Any]]:
    allowed = {"high"} | ({"medium"} if allow_medium else set())
    return [
        unit
        for unit in units
        if unit["confidence"] in allowed and unit["pastors_zh"] and unit["ours_zh"]
    ]


def sample_units(candidates: list[dict[str, Any]], sample_size: int, seed: int) -> list[dict[str, Any]]:
    if not candidates:
        return []
    groups: dict[str, list[dict[str, Any]]] = {}
    for unit in candidates:
        groups.setdefault(unit["stratum"], []).append(unit)
    for stratum, items in groups.items():
        random.Random(f"{seed}:{stratum}").shuffle(items)
    sampled: list[dict[str, Any]] = []
    keys = sorted(groups)
    index = 0
    while len(sampled) < min(sample_size, len(candidates)):
        progressed = False
        for stratum in keys:
            if index < len(groups[stratum]) and len(sampled) < sample_size:
                sampled.append(groups[stratum][index])
                progressed = True
        if not progressed:
            break
        index += 1
    sampled.sort(key=lambda unit: unit["start"])
    result = []
    for unit in sampled:
        order = "pastors_first" if random.Random(f"{seed}:{unit['unit_id']}:order").random() < 0.5 else "ours_first"
        result.append(
            {
                "unit_id": unit["unit_id"],
                "stratum": unit["stratum"],
                "order": order,
            }
        )
    return result


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    capture_dir = args.capture_dir.resolve()
    ours_dir = args.ours_dir.resolve()
    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    _, window_payload, window_start, window_end = load_capture(capture_dir)
    english = read_jsonl(capture_dir / "session.english.jsonl")
    pastors = read_jsonl(capture_dir / "session.mandarin.jsonl") if (capture_dir / "session.mandarin.jsonl").exists() else []
    if not pastors:
        raise ValueError("no session.mandarin.jsonl; capture the Mandarin feed or choose another comparison")

    if args.ours == "layer2":
        candidate_path = ours_dir / "segments_timed_zh.json"
        ours_input = sha256_file(candidate_path)
    else:
        candidate_path = ours_dir
        ours_input = {
            f"reading-edition-v2/{name}": sha256_file(ours_dir / "reading-edition-v2" / name)
            for name in ("reading_blocks.final.json", "sermon_zh_reading_revised.srt")
            if (ours_dir / "reading-edition-v2" / name).exists()
        }
    ours = load_candidate_rows(candidate_path, args.ours)
    if not ours:
        raise ValueError(f"no Chinese candidate rows in {candidate_path}")

    units = build_units(english, window_start, window_end, args.unit_seconds, args.unit_max_chars)
    assign_pastors(units, pastors)
    assign_ours(units, ours, window_start)
    classify_units(units, window_start, window_end)

    alignment_rows = []
    for unit in units:
        alignment_rows.append(
            {
                "unit_id": unit["unit_id"],
                "start": iso(unit["start"]),
                "end": iso(unit["end"]),
                "duration_s": unit["duration_s"],
                "position": ["beginning", "middle", "end"][unit["position"]],
                "content": unit["content"],
                "stratum": unit["stratum"],
                "english": unit["english"],
                "english_chars": unit["english_chars"],
                "pastors_zh": unit["pastors_zh"],
                "pastors_chars": unit["pastors_chars"],
                "ours_zh": unit["ours_zh"],
                "ours_chars": unit["ours_chars"],
                "pastors_ts": unit["pastors_ts"],
                "ours_ids": unit["ours_ids"],
                "ours_coverage": unit["ours_coverage"],
                "confidence": unit["confidence"],
                "flags": unit["flags"],
            }
        )
    write_jsonl(outdir / "alignment.jsonl", alignment_rows)

    candidates = eligible_units(units, args.allow_medium)
    if not candidates:
        raise ValueError("no eligible units for sampling; inspect alignment.jsonl")
    sample = sample_units(candidates, args.sample_size, args.seed)
    if not sample:
        raise ValueError("sampling returned no units")
    warning = None
    if len(sample) < args.sample_size:
        warning = (
            f"requested {args.sample_size} units but only {len(sample)} eligible; "
            "inspect alignment.jsonl and the pastors.ai final line count before rating"
        )
    write_json(
        outdir / "sample.json",
        {
            "schema": PREPARE_SCHEMA,
            "seed": args.seed,
            "requested": args.sample_size,
            "sample_size": len(sample),
            "eligible": len(candidates),
            "allow_medium": args.allow_medium,
            "warning": warning,
            "units": sample,
            "strata": {
                stratum: sum(1 for unit in sample if unit["stratum"] == stratum)
                for stratum in sorted({unit["stratum"] for unit in sample})
            },
        },
    )

    for rater in range(1, args.raters + 1):
        path = outdir / f"ratings.rater{rater}.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=RATING_COLUMNS)
            writer.writeheader()
            for item in sample:
                writer.writerow({"unit_id": item["unit_id"]})

    packet = [
        "# Blind translation comparison",
        "",
        "评分单元已随机标为 A/B。不要猜测来源；先独立评分，评分后再解盲。",
        "分数 1–5；preference 填 A、B 或 tie；错误数为非负整数，没有就填 0。",
        "",
    ]
    by_id = {unit["unit_id"]: unit for unit in units}
    for item in sample:
        unit = by_id[item["unit_id"]]
        first = unit["pastors_zh"] if item["order"] == "pastors_first" else unit["ours_zh"]
        second = unit["ours_zh"] if item["order"] == "pastors_first" else unit["pastors_zh"]
        packet.extend(
            [
                f"## {unit['unit_id']}",
                "",
                f"**English**: {unit['english']}",
                "",
                f"**A**: {first}",
                "",
                f"**B**: {second}",
                "",
            ]
        )
    (outdir / "review.packet.md").write_text("\n".join(packet), encoding="utf-8")

    manifest = {
        "schema": PREPARE_SCHEMA,
        "generated_at": iso(now_utc()),
        "capture_dir": str(capture_dir),
        "ours_dir": str(ours_dir),
        "candidate": args.ours,
        "window": {
            "start": window_payload["sermon_window"]["start"],
            "end": window_payload["sermon_window"]["end"],
        },
        "inputs": {
            "capture.json": sha256_file(capture_dir / "capture.json"),
            "sermon.window.json": sha256_file(capture_dir / "sermon.window.json"),
            "session.english.jsonl": sha256_file(capture_dir / "session.english.jsonl"),
            "session.mandarin.jsonl": sha256_file(capture_dir / "session.mandarin.jsonl"),
            "ours": ours_input,
        },
        "parameters": {
            "unit_seconds": args.unit_seconds,
            "unit_max_chars": args.unit_max_chars,
            "sample_size": args.sample_size,
            "seed": args.seed,
            "allow_medium": args.allow_medium,
        },
        "counts": {
            "english_lines": len(english),
            "pastors_lines": len(pastors),
            "ours_rows": len(ours),
            "units": len(units),
            "high": sum(1 for unit in units if unit["confidence"] == "high"),
            "medium": sum(1 for unit in units if unit["confidence"] == "medium"),
            "low": sum(1 for unit in units if unit["confidence"] == "low"),
            "eligible": len(candidates),
            "sampled": len(sample),
        },
        "script_sha256": sha256_file(Path(__file__)),
    }
    write_json(outdir / "comparison.manifest.json", manifest)
    return {
        "outdir": str(outdir),
        "counts": manifest["counts"],
        "strata": {
            stratum: sum(1 for item in sample if item["stratum"] == stratum)
            for stratum in sorted({item["stratum"] for item in sample})
        },
        "sample": sample,
        "warning": warning,
        "packet": str(outdir / "review.packet.md"),
        "ratings": [str(outdir / f"ratings.rater{index}.csv") for index in range(1, args.raters + 1)],
    }


# ---------------------------------------------------------------------------
# scoring


def value(row: dict[str, str], key: str) -> float | None:
    raw = str(row.get(key, "") or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"invalid number in {key}: {raw!r}") from exc


def parse_ratings(path: Path, sample_ids: set[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for number, row in enumerate(reader, 2):
            unit_id = str(row.get("unit_id", "") or "").strip()
            if not unit_id:
                continue
            if unit_id not in sample_ids:
                raise ValueError(f"{path}:{number}: unit_id {unit_id!r} is not in sample.json")
            preference = str(row.get("preference", "") or "").strip().lower()
            if preference not in {"", "a", "b", "tie"}:
                raise ValueError(f"{path}:{number}: preference must be A/B/tie")
            scores = {
                key: value(row, key)
                for key in ("a_adequacy", "a_fluency", "b_adequacy", "b_fluency")
            }
            errors = {
                key: value(row, key)
                for key in ("critical_a", "major_a", "minor_a", "critical_b", "major_b", "minor_b")
            }
            if any(item is not None for item in scores.values()) or preference:
                records.append({"unit_id": unit_id, "preference": preference, "scores": scores, "errors": errors})
    return records


def source_for(position: str, order: str) -> str:
    if order == "pastors_first":
        return "pastors" if position == "a" else "ours"
    return "ours" if position == "a" else "pastors"


def unblind(records: list[dict[str, Any]], sample: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    order = {item["unit_id"]: item["order"] for item in sample["units"]}
    by_unit: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        mapping = order[record["unit_id"]]
        mapped = {"unit_id": record["unit_id"], "preference": None}
        for position in ("a", "b"):
            source = source_for(position, mapping)
            mapped[source] = {
                "adequacy": record["scores"][f"{position}_adequacy"],
                "fluency": record["scores"][f"{position}_fluency"],
                "critical": record["errors"][f"critical_{position}"],
                "major": record["errors"][f"major_{position}"],
                "minor": record["errors"][f"minor_{position}"],
            }
        if record["preference"] in {"a", "b"}:
            mapped["preference"] = source_for(record["preference"], mapping)
        elif record["preference"] == "tie":
            mapped["preference"] = "tie"
        by_unit.setdefault(record["unit_id"], []).append(mapped)
    return by_unit


def consensus(by_unit: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for unit_id, records in by_unit.items():
        preferences = [record["preference"] for record in records if record["preference"]]
        if len(preferences) == 1:
            preference = preferences[0]
        elif preferences and len(set(preferences)) == 1:
            preference = preferences[0]
        elif preferences:
            preference = "disputed"
        else:
            preference = None
        entry: dict[str, Any] = {"unit_id": unit_id, "preference": preference, "raters": len(records)}
        for source in ("pastors", "ours"):
            for metric in ("adequacy", "fluency", "critical", "major", "minor"):
                values = [record[source][metric] for record in records if record[source][metric] is not None]
                entry[f"{source}_{metric}"] = mean(values) if values else None
        result[unit_id] = entry
    return result


def numbers(text: str) -> set[str]:
    return {match.group(0).replace(",", "") for match in NUMBER.finditer(text)}


def machine_checks(unit: dict[str, Any]) -> dict[str, Any]:
    english_numbers = numbers(unit["english"])
    english_scripture = set(SCRIPTURE.findall(unit["english"]))
    result: dict[str, Any] = {}
    for source in ("pastors", "ours"):
        text = unit[f"{source}_zh"]
        candidate_numbers = numbers(text)
        candidate_scripture = set(SCRIPTURE.findall(text))
        result[source] = {
            "empty": not bool(text),
            "missing_numbers": sorted(english_numbers - candidate_numbers),
            "extra_numbers": sorted(candidate_numbers - english_numbers),
            "missing_scripture": sorted(english_scripture - candidate_scripture),
            "extra_scripture": sorted(candidate_scripture - english_scripture),
            "length_ratio": round(len(text) / max(1, len(unit["english"])), 3),
        }
    return result


def bootstrap(values: list[float], statistic, seed: int, samples: int = 10000) -> list[float] | None:
    if not values:
        return None
    rng = random.Random(seed)
    results = [statistic([values[rng.randrange(len(values))] for _ in values]) for _ in range(samples)]
    results.sort()
    return [round(results[int(0.025 * samples)], 4), round(results[int(0.975 * samples)], 4)]


def score(args: argparse.Namespace) -> dict[str, Any]:
    outdir = args.outdir.resolve()
    sample = read_json(outdir / "sample.json", "sample")
    manifest = read_json(outdir / "comparison.manifest.json", "comparison manifest")
    alignment = {row["unit_id"]: row for row in read_jsonl(outdir / "alignment.jsonl")}
    sample_ids = {item["unit_id"] for item in sample["units"]}
    ratings_paths = args.ratings or sorted(outdir.glob("ratings.rater*.csv"))
    if not ratings_paths:
        raise ValueError("no ratings CSV files; fill ratings.rater*.csv first")

    per_rater: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for path in ratings_paths:
        path = path.resolve()
        per_rater[path.stem] = unblind(parse_ratings(path, sample_ids), sample)

    combined: dict[str, list[dict[str, Any]]] = {}
    for records_by_unit in per_rater.values():
        for unit_id, records in records_by_unit.items():
            combined.setdefault(unit_id, []).extend(records)
    unit_results = consensus(combined)
    if not unit_results:
        raise ValueError("no ratings found")

    for unit_id, result in unit_results.items():
        result["stratum"] = next((item["stratum"] for item in sample["units"] if item["unit_id"] == unit_id), None)
        result["machine"] = machine_checks(alignment[unit_id])

    preference_counts = {"ours": 0, "pastors": 0, "tie": 0, "disputed": 0, "unrated": 0}
    for result in unit_results.values():
        preference = result["preference"]
        if preference is None:
            preference_counts["unrated"] += 1
        else:
            preference_counts[preference] += 1
    decisive = preference_counts["ours"] + preference_counts["pastors"]
    win_rate = preference_counts["ours"] / decisive if decisive else None
    win_values = [1.0 if result["preference"] == "ours" else 0.0 for result in unit_results.values() if result["preference"] in {"ours", "pastors"}]
    win_rate_ci = bootstrap(win_values, mean, args.seed, args.bootstrap)

    score_results = {}
    for metric in ("adequacy", "fluency"):
        differences = [
            result[f"ours_{metric}"] - result[f"pastors_{metric}"]
            for result in unit_results.values()
            if result.get(f"ours_{metric}") is not None and result.get(f"pastors_{metric}") is not None
        ]
        score_results[metric] = {
            "ours_mean": round(mean([result[f"ours_{metric}"] for result in unit_results.values() if result.get(f"ours_{metric}") is not None]), 3)
            if any(result.get(f"ours_{metric}") is not None for result in unit_results.values())
            else None,
            "pastors_mean": round(mean([result[f"pastors_{metric}"] for result in unit_results.values() if result.get(f"pastors_{metric}") is not None]), 3)
            if any(result.get(f"pastors_{metric}") is not None for result in unit_results.values())
            else None,
            "difference_mean": round(mean(differences), 3) if differences else None,
            "difference_ci": bootstrap(differences, mean, args.seed, args.bootstrap),
            "n": len(differences),
        }

    error_summary = {}
    for source in ("ours", "pastors"):
        error_summary[source] = {
            metric: round(sum(result.get(f"{source}_{metric}") or 0 for result in unit_results.values()), 3)
            for metric in ("critical", "major", "minor")
        }

    by_stratum: dict[str, dict[str, int]] = {}
    for result in unit_results.values():
        stratum = result["stratum"] or "unknown"
        bucket = by_stratum.setdefault(stratum, {"ours": 0, "pastors": 0, "tie": 0, "disputed": 0, "unrated": 0})
        bucket[result["preference"] or "unrated"] += 1

    machine_summary = {"ours": {"empty": 0, "missing_numbers": 0, "missing_scripture": 0}, "pastors": {"empty": 0, "missing_numbers": 0, "missing_scripture": 0}}
    for result in unit_results.values():
        for source in ("ours", "pastors"):
            check = result["machine"][source]
            machine_summary[source]["empty"] += int(check["empty"])
            machine_summary[source]["missing_numbers"] += int(bool(check["missing_numbers"]))
            machine_summary[source]["missing_scripture"] += int(bool(check["missing_scripture"]))

    inter_rater = None
    if len(per_rater) >= 2:
        names = list(per_rater)
        agreements = []
        differences = []
        for unit_id in sample_ids:
            prefs = []
            for name in names:
                records = per_rater[name].get(unit_id, [])
                if records and records[0]["preference"]:
                    prefs.append(records[0]["preference"])
            if len(prefs) >= 2:
                agreements.append(1 if len(set(prefs)) == 1 else 0)
        for name_a, name_b in zip(names, names[1:]):
            for unit_id in sample_ids:
                a = per_rater[name_a].get(unit_id, [])
                b = per_rater[name_b].get(unit_id, [])
                if not a or not b:
                    continue
                for source in ("ours", "pastors"):
                    for metric in ("adequacy", "fluency"):
                        va, vb = a[0][source][metric], b[0][source][metric]
                        if va is not None and vb is not None:
                            differences.append(abs(va - vb))
        inter_rater = {
            "raters": names,
            "preference_agreement_rate": round(mean(agreements), 3) if agreements else None,
            "preference_units": len(agreements),
            "mean_abs_score_difference": round(mean(differences), 3) if differences else None,
        }

    summary = {
        "schema": SCORE_SCHEMA,
        "generated_at": iso(now_utc()),
        "manifest": {"path": str(outdir / "comparison.manifest.json"), "sha256": sha256_file(outdir / "comparison.manifest.json")},
        "candidate": manifest.get("candidate"),
        "sample": {
            "sampled": len(sample_ids),
            "rated": len(unit_results),
            "raters": list(per_rater),
        },
        "preference": {
            "counts": preference_counts,
            "decisive": decisive,
            "ours_win_rate": round(win_rate, 4) if win_rate is not None else None,
            "ours_win_rate_ci95": win_rate_ci,
            "note": "tie and disputed are excluded from the win-rate denominator",
        },
        "scores": score_results,
        "errors": error_summary,
        "by_stratum": by_stratum,
        "machine_checks": {
            "summary": machine_summary,
            "note": "deterministic regex hints only; not a semantic judgment",
        },
        "inter_rater": inter_rater,
        "caveats": [
            "Human ratings are the primary evidence; machine checks are advisory.",
            "The sample is small and from one service; do not generalize beyond this window.",
            "Alignment uses timestamp proximity; low-confidence units are excluded, but boundary error is still possible.",
            "The pastors.ai Chinese is live/TTS-oriented; our candidate may be a Layer 2 draft or an edited reading edition (see manifest.candidate).",
            "No gold Chinese reference exists; this compares candidates, not absolute quality.",
        ],
        "units": [
            {
                "unit_id": result["unit_id"],
                "stratum": result["stratum"],
                "preference": result["preference"],
                "ours_adequacy": result.get("ours_adequacy"),
                "pastors_adequacy": result.get("pastors_adequacy"),
                "ours_fluency": result.get("ours_fluency"),
                "pastors_fluency": result.get("pastors_fluency"),
                "machine": result["machine"],
            }
            for result in unit_results.values()
        ],
    }
    write_json(outdir / "summary.json", summary)
    write_report(outdir / "report.md", summary)
    return summary


def write_report(path: Path, summary: dict[str, Any]) -> None:
    preference = summary["preference"]
    scores = summary["scores"]
    lines = [
        "# 翻译质量对比报告",
        "",
        f"生成时间：{summary['generated_at']}",
        "",
        "## 方法边界",
        "",
        "- 人工盲评为主；确定性检查只作提示，不替代人工。",
        "- 没有中文金标；这是两个候选之间的相对比较，不是绝对质量判定。",
        "- 样本来自一场/一个窗口，不能外推到所有场次。",
        "",
        "## 样本",
        "",
        f"- 抽样：{summary['sample']['sampled']}；已评：{summary['sample']['rated']}；评分人：{', '.join(summary['sample']['raters'])}",
        "",
        "## 偏好",
        "",
        "| ours | pastors | tie | disputed | unrated | ours 胜率 | 95% CI |",
        "|---:|---:|---:|---:|---:|---:|---|",
        f"| {preference['counts']['ours']} | {preference['counts']['pastors']} | {preference['counts']['tie']} | {preference['counts']['disputed']} | {preference['counts']['unrated']} | {preference['ours_win_rate']} | {preference['ours_win_rate_ci95']} |",
        "",
        "## 分数（ours - pastors）",
        "",
        "| 维度 | ours | pastors | 差值 | 95% CI | n |",
        "|---|---:|---:|---:|---|---:|",
    ]
    for metric in ("adequacy", "fluency"):
        item = scores[metric]
        lines.append(
            f"| {metric} | {item['ours_mean']} | {item['pastors_mean']} | {item['difference_mean']} | {item['difference_ci']} | {item['n']} |"
        )
    lines.extend(
        [
            "",
            "## 错误计数（合计）",
            "",
            "| 来源 | critical | major | minor |",
            "|---|---:|---:|---:|",
        ]
    )
    for source in ("ours", "pastors"):
        item = summary["errors"][source]
        lines.append(f"| {source} | {item['critical']} | {item['major']} | {item['minor']} |")
    lines.extend(
        [
            "",
            "## 确定性检查（提示）",
            "",
            f"- ours：{summary['machine_checks']['summary']['ours']}",
            f"- pastors：{summary['machine_checks']['summary']['pastors']}",
            "",
            "## 评分人一致性",
            "",
            f"- {summary['inter_rater']}",
            "",
            "## 限制",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in summary["caveats"])
    lines.extend(
        [
            "",
            "## 决策建议",
            "",
            "- 只有人工评分显示稳定优势，才考虑改变生产翻译链。",
            "- pastors.ai 中文只能作对照；不得作为 Layer 2 批准文本、训练金标或“已验证样例”。",
            "- 若双方都有 critical 错误，先加确定性门禁，再谈偏好。",
            "- 若差异落在置信区间内，维持现状或扩大样本，不宣布赢家。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Blinded quality comparison of two Chinese translations.")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare_parser = sub.add_parser("prepare", help="build alignment, sample and blind rating sheets")
    prepare_parser.add_argument("--capture-dir", type=Path, required=True)
    prepare_parser.add_argument("--ours-dir", type=Path, required=True)
    prepare_parser.add_argument("--ours", choices=("layer2", "reading"), default="layer2")
    prepare_parser.add_argument("--outdir", type=Path, required=True)
    prepare_parser.add_argument("--unit-seconds", type=float, default=30.0)
    prepare_parser.add_argument("--unit-max-chars", type=int, default=400)
    prepare_parser.add_argument("--sample-size", type=int, default=30)
    prepare_parser.add_argument("--seed", type=int, default=20261115)
    prepare_parser.add_argument("--raters", type=int, choices=range(1, 5), default=2)
    prepare_parser.add_argument("--allow-medium", action="store_true")

    score_parser = sub.add_parser("score", help="unblind and aggregate filled rating sheets")
    score_parser.add_argument("--outdir", type=Path, required=True)
    score_parser.add_argument("--ratings", type=Path, nargs="*", default=None)
    score_parser.add_argument("--bootstrap", type=int, default=10000)
    score_parser.add_argument("--seed", type=int, default=20261115)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(args)
        else:
            result = score(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
