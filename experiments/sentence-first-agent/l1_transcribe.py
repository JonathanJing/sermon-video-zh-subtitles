#!/usr/bin/env python3
"""Layer 1 transcription for a single-speaker sermon: two OpenAI passes (paid).

  timing pass   one verbose_json call with word and segment timestamps (the timeline identity)
  text pass     the same audio in chunks cut at segment starts, text only (independent cross-check)

Run it through the explicit launcher, never with a key on the command line:

  .venv/bin/python tools/ops/run_with_openai_environment.py --environment prod -- \\
    .venv/bin/python experiments/sentence-first-agent/l1_transcribe.py \\
    --audio <run>/source/sermon-64k.mp3 --out <run>/layer1 --prompt-file <run>/layer1/prompt.txt

Finished work is kept: the timing pass is skipped when raw-whisper.json exists, and each text
chunk is skipped when its text-chunks/chunk-NN.json exists, so a rerun after a failure pays only
for what is missing. transcribe-usage.json records the audio seconds actually sent per model;
it is the settlement input for the weekly budget ledger, not a bill.

This is the 2026-11-21 week-11 script with the episode-specific paths and prompt turned into
arguments. The models come from docs/sentence-first-model-stack.zh.md.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def client():
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY")
    project = os.environ.get("OPENAI_PROJECT_ID")
    if not key or not project:
        raise SystemExit("missing launcher environment: run through tools/ops/run_with_openai_environment.py")
    return OpenAI(api_key=key, project=project, timeout=1800.0, max_retries=3)


def duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    return float(out.stdout.strip())


def write_json(path: Path, value) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def add_usage(out: Path, model: str, seconds: float, calls: int = 1) -> None:
    path = out / "transcribe-usage.json"
    usage = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"models": {}}
    row = usage["models"].setdefault(model, {"audioSeconds": 0.0, "calls": 0})
    row["audioSeconds"] = round(row["audioSeconds"] + seconds, 3)
    row["calls"] += calls
    write_json(path, usage)


def chunk_windows(total: float, segments: list[dict], max_seconds: float = 240.0) -> list[tuple[float, float]]:
    """Cut at the segment start nearest each mark so no segment is halved."""
    starts = sorted(float(s["start"]) for s in segments if float(s["end"]) > float(s["start"]))
    windows = []
    start = 0.0
    while start < total:
        target = start + max_seconds
        if target >= total - 1.0:
            windows.append((start, total))
            break
        candidates = [s for s in starts if abs(s - target) <= 12.0 and s > start + 30.0]
        cut = min(candidates, key=lambda s: abs(s - target)) if candidates else target
        windows.append((start, cut))
        start = cut
    return windows


def segment_word_count(segments: list[dict], lo: float, hi: float) -> int:
    return sum(1 for s in segments
               if lo - 0.01 <= (float(s["start"]) + float(s["end"])) / 2 <= hi + 0.01
               for _ in str(s.get("text", "")).split())


def run_timing(args, api=None) -> dict:
    raw_path = args.out / "raw-whisper.json"
    if raw_path.exists() and not args.force:
        data = json.loads(raw_path.read_text(encoding="utf-8"))
        return {"pass": "timing", "skipped": True, "words": len(data.get("words", []))}
    api = api or client()
    started = time.time()
    seconds = duration(args.audio)
    with args.audio.open("rb") as handle:
        response = api.audio.transcriptions.create(
            model=args.timing_model, file=handle, language="en", prompt=args.prompt,
            response_format="verbose_json", timestamp_granularities=["word", "segment"])
    add_usage(args.out, args.timing_model, seconds)
    data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
    write_json(raw_path, data)
    words = [{"text": w["word"].strip(), "start": float(w["start"]), "end": float(w["end"])}
             for w in data.get("words", []) if str(w.get("word", "")).strip()]
    write_json(args.out / "words.json", words)
    return {"pass": "timing", "model": args.timing_model, "duration": data.get("duration"),
            "segments": len(data.get("segments", [])), "words": len(words),
            "seconds": round(time.time() - started, 1)}


def run_text(args, api=None) -> dict:
    raw = json.loads((args.out / "raw-whisper.json").read_text(encoding="utf-8"))
    segments = raw.get("segments", [])
    windows = chunk_windows(duration(args.audio), segments, args.chunk_seconds)
    slices = args.out / "text-chunks"
    slices.mkdir(parents=True, exist_ok=True)
    records = []
    for index, (lo, hi) in enumerate(windows):
        record_path = slices / f"chunk-{index:02d}.json"
        if record_path.exists() and not args.force:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            if (record.get("start"), record.get("end")) == (round(lo, 3), round(hi, 3)):
                records.append(record)
                continue
        api = api or client()
        slice_path = slices / f"chunk-{index:02d}.mp3"
        if not slice_path.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{lo:.3f}", "-to", f"{hi:.3f}",
                            "-i", str(args.audio), "-c", "copy", str(slice_path)], check=True)
        expected = segment_word_count(segments, lo, hi)
        best, attempts = "", []
        for attempt in range(1, args.max_attempts + 1):
            started = time.time()
            with slice_path.open("rb") as handle:
                response = api.audio.transcriptions.create(
                    model=args.text_model, file=handle, language="en", prompt=args.prompt,
                    response_format="text")
            add_usage(args.out, args.text_model, hi - lo)
            text = response if isinstance(response, str) else str(getattr(response, "text", ""))
            attempts.append({"attempt": attempt, "words": len(text.split()),
                             "seconds": round(time.time() - started, 1)})
            if len(text.split()) > len(best.split()):
                best = text
            if len(text.split()) >= max(1, int(expected * 0.95)):
                best = text
                break
        record = {"chunk": index, "start": round(lo, 3), "end": round(hi, 3), "whisperWords": expected,
                  "words": len(best.split()), "attempts": attempts, "text": best}
        write_json(record_path, record)
        records.append(record)
        print(json.dumps({k: record[k] for k in ("chunk", "start", "end", "whisperWords", "words")}), flush=True)
    write_json(args.out / "gpt-4o-chunks.json", records)
    (args.out / "raw-gpt-4o-transcribe.txt").write_text(
        "\n\n".join(r["text"].strip() for r in records) + "\n", encoding="utf-8")
    short = [r["chunk"] for r in records if r["whisperWords"] and r["words"] < 0.95 * r["whisperWords"]]
    return {"pass": "text", "model": args.text_model, "chunks": len(records),
            "words": sum(r["words"] for r in records),
            "whisperWords": sum(r["whisperWords"] for r in records), "shortChunks": short}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--audio", type=Path, required=True, help="upload audio (mp3 under the API size limit)")
    parser.add_argument("--out", type=Path, required=True, help="the run's layer1 directory")
    prompt = parser.add_mutually_exclusive_group(required=True)
    prompt.add_argument("--prompt", help="this episode's names and terms")
    prompt.add_argument("--prompt-file", type=Path)
    parser.add_argument("--pass", dest="which", choices=["timing", "text", "all"], default="all")
    parser.add_argument("--timing-model", default="whisper-1")
    parser.add_argument("--text-model", default="gpt-4o-transcribe")
    parser.add_argument("--chunk-seconds", type=float, default=240.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--force", action="store_true", help="pay again for passes that already have output")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.prompt_file:
        args.prompt = args.prompt_file.read_text(encoding="utf-8").strip()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.which in ("timing", "all"):
        print(json.dumps(run_timing(args)), flush=True)
    if args.which in ("text", "all"):
        print(json.dumps(run_text(args)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
