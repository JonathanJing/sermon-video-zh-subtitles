#!/usr/bin/env python3
"""Extract the human-confirmed sermon text from a full-service capture.

The capture keeps the whole 10:00–11:20 service.  After a human has written
``sermon.window.json`` with ``mark_window.py``, this deterministic step takes
the source (English) and comparison (Mandarin) lines that fall inside that
window and writes the Layer 1 input:

  sermon.english.jsonl       source lines inside the window, with timestamps
  sermon.english.txt         plain text, one line per source line
  sermon.english.timed.txt   [HH:MM:SS.mmm] + text, offset from capture start
  sermon.mandarin.jsonl      machine Mandarin lines for comparison only
  sermon.mandarin.txt
  sermon.manifest.json       input hashes, window, coverage and counts

No model is called.  The English source is the provider's ASR transcript;
it still needs Layer 1 correction and review.  The Mandarin text is machine
translation and is never an approved Layer 2 text.

Usage
-----
  .venv/bin/python experiments/live-translate-capture/extract_sermon.py \\
      --capture-dir artifacts/live-capture/mariners-north-irvine/2026-11-15

  # use the live arrival log when the provider session log is unavailable
  ... --source live
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from mark_window import check_window, iso_utc, parse_ts, read_json, sha256_file, write_json

SCHEMA = "live-translate-sermon-extract/v1"
COVERAGE_TOLERANCE_S = 20.0
MIN_LINES = 5


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
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row must be an object at {path}:{number}")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def line_time(row: dict[str, Any], actual_start: datetime) -> datetime | None:
    if row.get("ts"):
        return parse_ts(str(row["ts"]))
    if row.get("received_at"):
        return parse_ts(str(row["received_at"]))
    if isinstance(row.get("t_ms"), (int, float)):
        return actual_start + timedelta(milliseconds=float(row["t_ms"]))
    return None


def format_offset(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{sign}{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def pick_source(capture_dir: Path, kind: str, preferred: str, fallback: str) -> tuple[str, Path] | None:
    preferred_path = capture_dir / preferred
    fallback_path = capture_dir / fallback
    if kind in {"auto", "session"} and preferred_path.exists():
        return "session", preferred_path
    if kind in {"auto", "live"} and fallback_path.exists():
        return "live", fallback_path
    return None


def select_lines(
    rows: list[dict[str, Any]],
    start: datetime,
    end: datetime,
    actual_start: datetime,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        text = str(row.get("text") or "").strip()
        if not text:
            continue
        moment = line_time(row, actual_start)
        if moment is None or not (start <= moment <= end):
            continue
        selected.append(
            {
                "ts": iso_utc(moment),
                "offset_s": round((moment - actual_start).total_seconds(), 3),
                "text": text,
            }
        )
    selected.sort(key=lambda item: item["offset_s"])
    return selected


def coverage(rows: list[dict[str, Any]], start: datetime, end: datetime) -> dict[str, Any]:
    warnings: list[str] = []
    if not rows:
        return {"lines": 0, "first_offset_s": None, "last_offset_s": None, "warnings": ["no source lines inside the window"]}
    first = parse_ts(rows[0]["ts"])
    last = parse_ts(rows[-1]["ts"])
    start_lag = (first - start).total_seconds()
    end_lag = (end - last).total_seconds()
    if start_lag > COVERAGE_TOLERANCE_S:
        warnings.append(f"first source line starts {start_lag:.0f}s after the window start")
    if end_lag > COVERAGE_TOLERANCE_S:
        warnings.append(f"last source line ends {end_lag:.0f}s before the window end")
    if len(rows) < MIN_LINES:
        warnings.append(f"only {len(rows)} source lines in the window")
    return {
        "lines": len(rows),
        "chars": sum(len(row["text"]) for row in rows),
        "first_ts": rows[0]["ts"],
        "last_ts": rows[-1]["ts"],
        "first_offset_s": rows[0]["offset_s"],
        "last_offset_s": rows[-1]["offset_s"],
        "start_gap_s": round(start_lag, 3),
        "end_gap_s": round(end_lag, 3),
        "warnings": warnings,
    }


def extract(
    capture_dir: Path,
    *,
    window_path: Path | None = None,
    out_dir: Path | None = None,
    source_kind: str = "auto",
) -> dict[str, Any]:
    capture_dir = capture_dir.resolve()
    capture_path = capture_dir / "capture.json"
    if not capture_path.exists():
        raise ValueError(f"no capture manifest at {capture_path}")
    capture = read_json(capture_path, "capture manifest")
    window_path = (window_path or capture_dir / "sermon.window.json").resolve()
    if not window_path.exists():
        raise ValueError(f"no sermon window at {window_path}; run mark_window.py first")
    check_window(capture_dir, out=window_path)
    window_payload = read_json(window_path, "sermon window")
    window = window_payload.get("sermon_window") or {}
    start = parse_ts(window["start"])
    end = parse_ts(window["end"])
    actual_start = parse_ts(capture["window"]["actual_start"])

    english_choice = pick_source(capture_dir, source_kind, "session.english.jsonl", "english.finals.jsonl")
    if english_choice is None:
        raise ValueError("no English source: neither session.english.jsonl nor english.finals.jsonl exists")
    english_kind, english_path = english_choice
    english_rows = select_lines(read_jsonl(english_path), start, end, actual_start)
    if not english_rows and english_kind == "session" and source_kind == "auto":
        live_path = capture_dir / "english.finals.jsonl"
        if live_path.exists():
            english_kind, english_path = "live", live_path
            english_rows = select_lines(read_jsonl(live_path), start, end, actual_start)
    if not english_rows:
        raise ValueError(f"no English lines inside the window in {english_path}")

    mandarin_choice = pick_source(capture_dir, source_kind, "session.mandarin.jsonl", "mandarin.finals.jsonl")
    mandarin_kind, mandarin_path, mandarin_rows = None, None, []
    if mandarin_choice is not None:
        mandarin_kind, mandarin_path = mandarin_choice
        mandarin_rows = select_lines(read_jsonl(mandarin_path), start, end, actual_start)

    out_dir = (out_dir or capture_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    english_jsonl = out_dir / "sermon.english.jsonl"
    english_txt = out_dir / "sermon.english.txt"
    english_timed = out_dir / "sermon.english.timed.txt"
    mandarin_jsonl = out_dir / "sermon.mandarin.jsonl"
    mandarin_txt = out_dir / "sermon.mandarin.txt"

    write_jsonl(english_jsonl, english_rows)
    english_txt.write_text("\n".join(row["text"] for row in english_rows) + "\n", encoding="utf-8")
    english_timed.write_text(
        "\n".join(f"[{format_offset(row['offset_s'])}] {row['text']}" for row in english_rows) + "\n",
        encoding="utf-8",
    )
    if mandarin_rows:
        write_jsonl(mandarin_jsonl, mandarin_rows)
        mandarin_txt.write_text("\n".join(row["text"] for row in mandarin_rows) + "\n", encoding="utf-8")

    english_coverage = coverage(english_rows, start, end)
    mandarin_coverage = coverage(mandarin_rows, start, end) if mandarin_rows else None
    manifest = {
        "schema": SCHEMA,
        "generated_at": iso_utc(datetime.now(timezone.utc)),
        "capture": {
            "dir": str(capture_dir),
            "manifest_sha256": sha256_file(capture_path),
            "actual_start": iso_utc(actual_start),
            "actual_stop": capture["window"]["actual_stop"],
        },
        "window": {
            "file": str(window_path),
            "sha256": sha256_file(window_path),
            "start": iso_utc(start),
            "end": iso_utc(end),
            "duration_s": round((end - start).total_seconds(), 3),
            "approved_by": window_payload.get("approved_by"),
        },
        "source": {
            "english": {"kind": english_kind, "file": str(english_path), "sha256": sha256_file(english_path)},
            "mandarin": (
                {"kind": mandarin_kind, "file": str(mandarin_path), "sha256": sha256_file(mandarin_path)}
                if mandarin_path is not None
                else None
            ),
        },
        "english": {**english_coverage, "file": str(english_jsonl), "text_file": str(english_txt)},
        "mandarin": (
            {**mandarin_coverage, "file": str(mandarin_jsonl), "comparison_only": True}
            if mandarin_coverage is not None
            else None
        ),
        "outputs": {
            "english_jsonl_sha256": sha256_file(english_jsonl),
            "english_txt_sha256": sha256_file(english_txt),
            "english_timed_txt_sha256": sha256_file(english_timed),
        },
        "note": (
            "English source text inside the human window. It is the provider's ASR and still needs "
            "Layer 1 correction and review. Mandarin is machine translation for comparison only."
        ),
    }
    write_json(out_dir / "sermon.manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract the human-confirmed sermon text from a capture.")
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--window", type=Path, default=None, help="default <capture-dir>/sermon.window.json")
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--source", choices=("auto", "session", "live"), default="auto")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = extract(
            args.capture_dir,
            window_path=args.window,
            out_dir=args.out_dir,
            source_kind=args.source,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
