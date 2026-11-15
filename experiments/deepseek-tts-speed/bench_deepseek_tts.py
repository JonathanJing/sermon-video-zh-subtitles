#!/usr/bin/env python3
"""Time the DeepSeek cloud TTS against our own sentence units (experiment only).

Input is a sentence-first run's ``speech.jsonl`` (one row per unit produced by our
own splitting + translation), so the cloud engine is timed on exactly the text
our production Spark/Qwen3-TTS renderer synthesized. One request per unit, no
text editing: the unit boundary is ours, the voice is DeepSeek's.

Subcommands:

- ``synth``    one HTTP request per sentence unit; records per-request latency,
               time to first audio byte, decoded audio duration, retries.
- ``stats``    aggregate a ``timing.jsonl`` into RTF, latency quantiles, cost.
- ``compare``  join a DeepSeek ``timing.jsonl`` with a Spark ``tts-log.jsonl``
               of the same units and report per-unit duration/delta.
- ``assemble`` concatenate per-unit WAVs in unit order with a fixed gap.
- ``ab``       alternate Spark and DeepSeek renders of the same units.

The service streams WAV with an unpatched header (data size 0xFFFFFFFF), so
``fix_wav_header`` rewrites both sizes before the file hits disk; without that
most players and our own merge see an unknown length.

Nothing here is production identity: no cache, no review, no release labels.
"""
from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import statistics
import struct
import threading
import time

URL = "https://api.deepseek.com/v1/tools/tts"
SAMPLE_RATE = 24000
CHANNELS = 1
SAMPLE_WIDTH = 2
BILLED_USD_PER_10K = 0.225  # limited-time 50% price; list is 0.45
RETRYABLE = {408, 429, 503, 504}


def api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    env = Path.home() / ".config/tongxing/deepseek.env"
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DEEPSEEK_API_KEY not set and not found in ~/.config/tongxing/deepseek.env")


def load_units(path: Path) -> list[dict]:
    units = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        text = (row.get("spokenText") or "").strip()
        if not text:
            continue
        units.append({"id": row["id"], "text": text, "speaker": row.get("speaker"),
                      "budgetSeconds": row.get("budgetSeconds"),
                      "estimatedSeconds": row.get("estimatedSeconds")})
    return units


def billed_chars(text: str) -> int:
    """Chinese characters bill twice, everything else once (per the service guide)."""
    return sum(2 if "\u4e00" <= ch <= "\u9fff" else 1 for ch in text)


def wav_data_offset(data: bytes) -> tuple[int, int]:
    """Return (data_offset, data_size_declared) from a RIFF/WAVE byte string."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE payload")
    pos = 12
    while pos + 8 <= len(data):
        chunk_id = data[pos:pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        if chunk_id == b"data":
            return pos + 8, size
        pos += 8 + size + (size & 1)
    raise ValueError("no data chunk")


def wav_duration(data: bytes) -> float:
    offset, declared = wav_data_offset(data)
    actual = len(data) - offset
    size = actual if declared in (0, 0xFFFFFFFF) or declared > actual else declared
    return size / (SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH)


def fix_wav_header(data: bytes) -> bytes:
    """Rewrite RIFF and data sizes so the streamed file is seekable."""
    offset, _ = wav_data_offset(data)
    actual = len(data) - offset
    body = bytearray(data)
    struct.pack_into("<I", body, 4, len(body) - 8)
    struct.pack_into("<I", body, offset - 4, actual)
    return bytes(body)


class Timed:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.rows: list[dict] = []

    def add(self, row: dict) -> None:
        with self.lock:
            self.rows.append(row)


_local = threading.local()


def session_for_thread():
    import requests

    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=16, max_retries=0)
        session.mount("https://", adapter)
        session.headers.update({"Authorization": f"Bearer {api_key()}",
                                "Content-Type": "application/json"})
        _local.session = session
    return session


def synth_one(unit: dict, *, voice: str, timeout: float, out_dir: Path) -> dict:
    payload = {"text": unit["text"], "voice_id": voice, "format": "wav"}
    attempts = 0
    last_error = None
    while attempts < 4:
        attempts += 1
        session = session_for_thread()
        started = time.perf_counter()
        try:
            response = session.post(URL, json=payload, timeout=timeout, stream=True)
            status = response.status_code
            if status != 200:
                body = response.text[:300]
                response.close()
                if status in RETRYABLE and attempts < 4:
                    time.sleep(min(8.0, 0.8 * 2 ** attempts))
                    last_error = f"HTTP {status}: {body}"
                    continue
                return {"id": unit["id"], "ok": False, "httpStatus": status,
                        "error": body, "attempts": attempts, "latencySeconds": None,
                        "audioSeconds": None, "ttfbSeconds": None, "billedChars": billed_chars(unit["text"]),
                        "chars": len(unit["text"]), "voice": voice}
            chunks, first_at, total = [], None, 0
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                if first_at is None:
                    first_at = time.perf_counter()
                chunks.append(chunk)
                total += len(chunk)
            finished = time.perf_counter()
            response.close()
            data = b"".join(chunks)
            if len(data) < 44:
                raise ValueError(f"short payload ({len(data)} bytes)")
            duration = wav_duration(data)
            if duration <= 0:
                raise ValueError("empty audio")
            (out_dir / f"{unit['id']}.wav").write_bytes(fix_wav_header(data))
            return {"id": unit["id"], "ok": True, "httpStatus": status, "attempts": attempts,
                    "ttfbSeconds": round((first_at or finished) - started, 4),
                    "latencySeconds": round(finished - started, 4),
                    "audioSeconds": round(duration, 4),
                    "rtf": round((finished - started) / duration, 4),
                    "bytes": total, "chars": len(unit["text"]),
                    "billedChars": billed_chars(unit["text"]), "voice": voice}
        except Exception as error:  # network, truncation, parse
            last_error = f"{type(error).__name__}: {error}"
            if attempts < 4:
                time.sleep(min(8.0, 0.8 * 2 ** attempts))
                continue
            return {"id": unit["id"], "ok": False, "httpStatus": None, "error": last_error,
                    "attempts": attempts, "latencySeconds": None, "audioSeconds": None,
                    "ttfbSeconds": None, "billedChars": billed_chars(unit["text"]),
                    "chars": len(unit["text"]), "voice": voice}
    return {"id": unit["id"], "ok": False, "httpStatus": None, "error": last_error,
            "attempts": attempts, "latencySeconds": None, "audioSeconds": None,
            "ttfbSeconds": None, "billedChars": billed_chars(unit["text"]),
            "chars": len(unit["text"]), "voice": voice}


def summarize(rows: list[dict], *, wall_seconds: float | None, concurrency: int,
              voice: str, source: str) -> dict:
    ok = [r for r in rows if r.get("ok")]
    failed = [r for r in rows if not r.get("ok")]
    audio = sum(r["audioSeconds"] for r in ok)
    latency = [r["latencySeconds"] for r in ok]
    ttfb = [r["ttfbSeconds"] for r in ok]
    billed = sum(r["billedChars"] for r in rows)
    wall = wall_seconds if wall_seconds is not None else sum(latency)

    def q(values, p):
        if not values:
            return None
        ordered = sorted(values)
        return round(ordered[min(len(ordered) - 1, int(len(ordered) * p))], 4)

    return {
        "schemaVersion": "deepseek-tts-speed-summary-v1",
        "voice": voice, "source": source, "concurrency": concurrency,
        "requests": len(rows), "ok": len(ok), "failed": len(failed),
        "errorSamples": [{"id": r["id"], "error": r.get("error")} for r in failed[:5]],
        "audioSeconds": round(audio, 2),
        "wallSeconds": round(wall, 2),
        "rtf": round(wall / audio, 4) if audio else None,
        "latencySeconds": {"p50": q(latency, 0.5), "p95": q(latency, 0.95),
                           "mean": round(statistics.fmean(latency), 4) if latency else None,
                           "max": round(max(latency), 4) if latency else None},
        "ttfbSeconds": {"p50": q(ttfb, 0.5), "p95": q(ttfb, 0.95),
                        "mean": round(statistics.fmean(ttfb), 4) if ttfb else None},
        "unitRtf": {"p50": q([r["rtf"] for r in ok], 0.5), "p95": q([r["rtf"] for r in ok], 0.95)},
        "audioPerWall": round(audio / wall, 3) if wall else None,
        "billedChars": billed,
        "costUsd": round(billed * BILLED_USD_PER_10K / 10000, 4),
        "costUsdListPrice": round(billed * 2 * BILLED_USD_PER_10K / 10000, 4),
        "retriedRequests": sum(1 for r in rows if (r.get("attempts") or 0) > 1),
    }


def cmd_synth(args) -> int:
    units = load_units(args.speech)
    if args.limit:
        units = units[:args.limit]
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    timing_path = out_dir / "timing.jsonl"
    done = {}
    if timing_path.exists():
        for line in timing_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if (out_dir / f"{row['id']}.wav").exists():
                    done[row["id"]] = row
    todo = [u for u in units if u["id"] not in done]
    print(f"units {len(units)} already {len(done)} todo {len(todo)} "
          f"voice {args.voice} concurrency {args.concurrency}", flush=True)

    collector = Timed()
    started = time.perf_counter()
    with timing_path.open("a", encoding="utf-8") as sink:
        def record(row: dict) -> None:
            collector.add(row)
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()

        if args.concurrency <= 1:
            for index, unit in enumerate(todo, 1):
                row = synth_one(unit, voice=args.voice, timeout=args.timeout, out_dir=out_dir)
                record(row)
                if index % 10 == 0 or index == len(todo):
                    print(f"  {index}/{len(todo)} {unit['id']} "
                          f"{row.get('latencySeconds')}s audio {row.get('audioSeconds')}s", flush=True)
        else:
            with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
                futures = {pool.submit(synth_one, u, voice=args.voice, timeout=args.timeout,
                                       out_dir=out_dir): u["id"] for u in todo}
                for count, future in enumerate(as_completed(futures), 1):
                    record(future.result())
                    if count % 40 == 0 or count == len(todo):
                        print(f"  {count}/{len(todo)} done", flush=True)
    wall = time.perf_counter() - started

    rows = list(done.values()) + collector.rows
    summary = summarize(rows, wall_seconds=wall if todo else None,
                        concurrency=args.concurrency, voice=args.voice, source=str(args.speech))
    summary["measuredAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    summary["wallScope"] = "this invocation only" if todo else "all rows, cached"
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("requests", "ok", "failed", "audioSeconds",
                                              "wallSeconds", "rtf", "costUsd")}, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 1


def _pcm(path: Path) -> bytes:
    data = path.read_bytes()
    offset, declared = wav_data_offset(data)
    size = len(data) - offset if declared in (0, 0xFFFFFFFF) or declared > len(data) - offset else declared
    return data[offset:offset + size]


def _write_wav(path: Path, pcm: bytes) -> None:
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, CHANNELS, SAMPLE_RATE,
                          SAMPLE_RATE * CHANNELS * SAMPLE_WIDTH, CHANNELS * SAMPLE_WIDTH, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    path.write_bytes(header + pcm)


def cmd_assemble(args) -> int:
    units = load_units(args.speech)
    if args.limit:
        units = units[:args.limit]
    gap = b"\x00" * int(args.gap * SAMPLE_RATE) * SAMPLE_WIDTH
    pcm, timeline, cursor, missing = [], [], 0.0, []
    for unit in units:
        path = args.wavs / f"{unit['id']}.wav"
        if not path.exists():
            missing.append(unit["id"])
            continue
        clip = _pcm(path)
        seconds = len(clip) / (SAMPLE_RATE * SAMPLE_WIDTH)
        pcm.append(clip)
        timeline.append({"id": unit["id"], "start": round(cursor, 3),
                         "end": round(cursor + seconds, 3), "seconds": round(seconds, 3),
                         "text": unit["text"]})
        cursor += seconds
        pcm.append(gap)
        cursor += args.gap
    _write_wav(args.out, b"".join(pcm))
    (args.out.with_suffix(".timeline.json")).write_text(
        json.dumps({"schemaVersion": "deepseek-tts-track-timeline-v1", "gapSeconds": args.gap,
                    "units": timeline, "missing": missing, "audioSeconds": round(cursor, 3)},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} {cursor:.1f}s units {len(timeline)} missing {len(missing)}")
    return 0


def cmd_ab(args) -> int:
    units = load_units(args.speech)
    picks = []
    step = max(1, len(units) // args.count)
    for index in range(0, len(units), step):
        unit = units[index]
        if (args.a / f"{unit['id']}.wav").exists() and (args.b / f"{unit['id']}.wav").exists():
            picks.append(unit)
        if len(picks) >= args.count:
            break
    gap = b"\x00" * int(args.gap * SAMPLE_RATE) * SAMPLE_WIDTH
    pcm, timeline, cursor = [], [], 0.0
    for unit in picks:
        for label, directory in (("spark", args.a), ("deepseek", args.b)):
            clip = _pcm(directory / f"{unit['id']}.wav")
            seconds = len(clip) / (SAMPLE_RATE * SAMPLE_WIDTH)
            pcm.append(clip)
            timeline.append({"id": unit["id"], "engine": label, "start": round(cursor, 3),
                             "end": round(cursor + seconds, 3), "seconds": round(seconds, 3),
                             "text": unit["text"]})
            cursor += seconds
            pcm.append(gap)
            cursor += args.gap
    _write_wav(args.out, b"".join(pcm))
    (args.out.with_suffix(".timeline.json")).write_text(
        json.dumps({"schemaVersion": "deepseek-tts-ab-timeline-v1", "units": timeline,
                    "audioSeconds": round(cursor, 3)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"wrote {args.out} {cursor:.1f}s pairs {len(picks)}")
    return 0


def cmd_stats(args) -> int:
    rows = [json.loads(line) for line in args.timing.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    summary = summarize(rows, wall_seconds=None, concurrency=args.concurrency,
                        voice=args.voice, source=str(args.timing))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_compare(args) -> int:
    timing = {json.loads(line)["id"]: json.loads(line)
              for line in args.timing.read_text(encoding="utf-8").splitlines() if line.strip()}
    spark = {}
    for line in args.spark_log.read_text(encoding="utf-8").splitlines():
        if not line.startswith("{"):
            continue
        row = json.loads(line)
        if "id" in row:
            spark[row["id"]] = row
    shared = [uid for uid in timing if uid in spark and timing[uid].get("ok")]
    deltas = [timing[uid]["audioSeconds"] - spark[uid]["seconds"] for uid in shared]
    ratios = [timing[uid]["audioSeconds"] / spark[uid]["seconds"] for uid in shared if spark[uid]["seconds"]]
    longer = [uid for uid in shared if timing[uid]["audioSeconds"] > spark[uid]["seconds"]]
    report = {
        "schemaVersion": "deepseek-spark-duration-compare-v1",
        "units": len(shared),
        "deepseekAudioSeconds": round(sum(timing[u]["audioSeconds"] for u in shared), 2),
        "sparkAudioSeconds": round(sum(spark[u]["seconds"] for u in shared), 2),
        "deltaSeconds": round(sum(deltas), 2),
        "ratio": round(sum(timing[u]["audioSeconds"] for u in shared)
                       / sum(spark[u]["seconds"] for u in shared), 3),
        "perUnitDeltaSeconds": {"p50": round(statistics.median(deltas), 3),
                                "p95": round(sorted(deltas)[int(len(deltas) * 0.95)], 3),
                                "min": round(min(deltas), 3), "max": round(max(deltas), 3)},
        "perUnitRatio": {"p50": round(statistics.median(ratios), 3),
                         "max": round(max(ratios), 3), "min": round(min(ratios), 3)},
        "longerUnits": len(longer),
        "worst": sorted(((round(timing[u]["audioSeconds"] - spark[u]["seconds"], 3), u,
                          round(spark[u]["seconds"], 2), round(timing[u]["audioSeconds"], 2))
                         for u in shared), reverse=True)[:5],
        "shortest": sorted(((round(timing[u]["audioSeconds"] - spark[u]["seconds"], 3), u,
                            round(spark[u]["seconds"], 2), round(timing[u]["audioSeconds"], 2))
                           for u in shared))[:5],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    synth = sub.add_parser("synth", help="one request per sentence unit")
    synth.add_argument("--speech", type=Path, required=True)
    synth.add_argument("--out", type=Path, required=True)
    synth.add_argument("--voice", default="tide")
    synth.add_argument("--concurrency", type=int, default=1)
    synth.add_argument("--limit", type=int, default=0)
    synth.add_argument("--timeout", type=float, default=120.0)
    synth.set_defaults(func=cmd_synth)

    stats = sub.add_parser("stats", help="aggregate a timing.jsonl")
    stats.add_argument("--timing", type=Path, required=True)
    stats.add_argument("--voice", default="tide")
    stats.add_argument("--concurrency", type=int, default=1)
    stats.set_defaults(func=cmd_stats)

    compare = sub.add_parser("compare", help="join against a Spark tts-log")
    compare.add_argument("--timing", type=Path, required=True)
    compare.add_argument("--spark-log", type=Path, required=True)
    compare.add_argument("--out", type=Path)
    compare.set_defaults(func=cmd_compare)

    assemble = sub.add_parser("assemble", help="concatenate unit WAVs in order")
    assemble.add_argument("--speech", type=Path, required=True)
    assemble.add_argument("--wavs", type=Path, required=True)
    assemble.add_argument("--out", type=Path, required=True)
    assemble.add_argument("--gap", type=float, default=0.05)
    assemble.add_argument("--limit", type=int, default=0)
    assemble.set_defaults(func=cmd_assemble)

    ab = sub.add_parser("ab", help="alternate Spark and DeepSeek renders")
    ab.add_argument("--speech", type=Path, required=True)
    ab.add_argument("--a", type=Path, required=True, help="Spark WAV directory")
    ab.add_argument("--b", type=Path, required=True, help="DeepSeek WAV directory")
    ab.add_argument("--out", type=Path, required=True)
    ab.add_argument("--count", type=int, default=8)
    ab.add_argument("--gap", type=float, default=0.4)
    ab.set_defaults(func=cmd_ab)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
