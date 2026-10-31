#!/usr/bin/env python3
"""Turn a full-episode lanes run's memory evidence into one summary JSON and one SVG curve.

Inputs are metadata the run already writes plus the host sampler's JSONL:
  --samples       sample_host_memory.py output (1 s host MemAvailable)
  --lanes-report  lanes-report.json (stage timeline, ISO timestamps)
  --runtime       LOCALE=<render dir>/replica-runtime.json, once per lane (pool events)
  --asr-memory    LOCALE=<receipt>.memory.json, once per lane (ASR admission receipt)
Writes memory-curve.json and memory-curve.svg under --out. No sermon text or audio is read.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

GIB = 1024 ** 3
RESERVE_GIB = 24
COLOURS = ["#2a6fdb", "#d9822b", "#2e9d5b", "#a347ba"]


def _ts(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _gib(value) -> float | None:
    return round(value / GIB, 2) if isinstance(value, (int, float)) else None


def _pairs(values: list[str], name: str) -> dict[str, Path]:
    out = {}
    for value in values or []:
        locale, sep, path = value.partition("=")
        if not sep or not locale or not path:
            raise SystemExit(f"{name} expects LOCALE=PATH, got {value!r}")
        out[locale] = Path(path)
    return out


def load_samples(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row.get("memAvailableBytes"), int):
                rows.append(row)
    return sorted(rows, key=lambda row: row["timestamp"])


def host_summary(samples: list[dict]) -> dict:
    if not samples:
        return {"status": "no_samples"}
    low = min(samples, key=lambda row: row["memAvailableBytes"])
    swap = [row["swapTotalBytes"] - row["swapFreeBytes"] for row in samples
            if isinstance(row.get("swapTotalBytes"), int) and isinstance(row.get("swapFreeBytes"), int)]
    util = [row["gpuUtilPercent"] for row in samples if isinstance(row.get("gpuUtilPercent"), (int, float))]
    return {"samples": len(samples), "seconds": round(samples[-1]["timestamp"] - samples[0]["timestamp"], 1),
            "memTotalGiB": _gib(samples[0].get("memTotalBytes")),
            "memAvailableGiB": {"first": _gib(samples[0]["memAvailableBytes"]),
                                "minimum": _gib(low["memAvailableBytes"]),
                                "last": _gib(samples[-1]["memAvailableBytes"])},
            "minimumAt": low["timestamp"],
            "swapIncreaseGiB": _gib(max(swap) - swap[0]) if swap else None,
            "peakGpuUtilPercent": max(util) if util else None}


def stage_rows(lanes_report: dict | None, samples: list[dict]) -> list[dict]:
    rows = []
    for row in (lanes_report or {}).get("timeline", []):
        start, end = _ts(row["startedAt"]), _ts(row["endedAt"])
        inside = [s["memAvailableBytes"] for s in samples if start <= s["timestamp"] <= end]
        rows.append({"locale": row["locale"], "stage": row["stage"], "resource": row["resource"],
                     "startedAt": row["startedAt"], "seconds": round(end - start, 1),
                     "minMemAvailableGiB": _gib(min(inside)) if inside else None})
    return rows


def runtime_summary(runtime: dict) -> dict:
    events = runtime.get("events", [])
    by_kind = {}
    for event in events:
        by_kind.setdefault(event.get("kind"), []).append(event)
    results = by_kind.get("result", [])
    windows = [{"window": e.get("index"), "worker": e.get("worker"), "timestamp": e.get("timestamp"),
                "memAvailableGiB": _gib(e.get("memAvailableBytes")),
                "reservedGiB": _gib(((e.get("memory") or {}).get("cuda") or {}).get("reservedBytes"))}
               for e in results]
    mem = [w["memAvailableGiB"] for w in windows if w["memAvailableGiB"] is not None]
    reserved = [w["reservedGiB"] for w in windows if w["reservedGiB"] is not None]
    admission = (by_kind.get("admission") or [{}])[0]
    ready = (by_kind.get("pool_ready") or [{}])[0]
    trips = by_kind.get("reserve_failure", [])
    return {"status": runtime.get("status"), "replicas": runtime.get("replicas"),
            "batchSize": runtime.get("batchSize"), "memoryPolicy": runtime.get("memoryPolicy"),
            "admission": {"status": admission.get("status"),
                          "memAvailableGiB": _gib(admission.get("memAvailableBytes")),
                          "requiredGiB": _gib(admission.get("requiredBytes"))},
            "poolReadyMemAvailableGiB": _gib(ready.get("memAvailableBytes")),
            "windows": len(windows),
            "memAvailableGiB": {"first": mem[0] if mem else None, "minimum": min(mem) if mem else None,
                                "last": mem[-1] if mem else None},
            "drainGiBPerWindow": round((mem[0] - mem[-1]) / (len(mem) - 1), 3) if len(mem) > 1 else None,
            "workerReservedGiBMax": max(reserved) if reserved else None,
            "reserveTripped": bool(trips),
            "reserveFailure": ({"memAvailableGiB": _gib(trips[0].get("memAvailableBytes")),
                                "pendingWindows": trips[0].get("pendingWindows")} if trips else None),
            "perWindow": windows}


def render_svg(samples, stages, runtimes, path: Path) -> None:
    width, height, left, right, top, bottom = 960, 420, 60, 20, 20, 50
    if not samples:
        path.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="400" height="40">'
                        '<text x="10" y="25">no host samples</text></svg>\n', encoding="utf-8")
        return
    t0, t1 = samples[0]["timestamp"], samples[-1]["timestamp"]
    span = max(t1 - t0, 1.0)
    ymax = max(s.get("memTotalBytes", s["memAvailableBytes"]) for s in samples) / GIB
    x = lambda t: left + (t - t0) / span * (width - left - right)
    y = lambda g: top + (1 - g / ymax) * (height - top - bottom)
    locales = sorted({row["locale"] for row in stages} | set(runtimes))
    colour = {locale: COLOURS[i % len(COLOURS)] for i, locale in enumerate(locales)}
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
             f'font-family="sans-serif" font-size="11">',
             f'<rect width="{width}" height="{height}" fill="#fff"/>']
    for row in stages:
        start = _ts(row["startedAt"])
        x0, x1 = x(start), x(start + row["seconds"])
        band = (top, 12) if row["resource"] == "gpu" else (top + 14, 12)
        parts.append(f'<rect x="{x0:.1f}" y="{band[0]}" width="{max(x1 - x0, 1):.1f}" height="{band[1]}" '
                     f'fill="{colour[row["locale"]]}" opacity="{0.55 if row["resource"] == "gpu" else 0.25}">'
                     f'<title>{row["locale"]} {row["stage"]} {row["seconds"]}s</title></rect>')
    for g in range(0, int(ymax) + 1, 20):
        parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(g):.1f}" y2="{y(g):.1f}" stroke="#eee"/>'
                     f'<text x="{left - 6}" y="{y(g) + 4:.1f}" text-anchor="end">{g}</text>')
    parts.append(f'<line x1="{left}" x2="{width - right}" y1="{y(RESERVE_GIB):.1f}" y2="{y(RESERVE_GIB):.1f}" '
                 f'stroke="#c62828" stroke-dasharray="5 4"/><text x="{width - right}" y="{y(RESERVE_GIB) - 4:.1f}" '
                 f'text-anchor="end" fill="#c62828">24 GiB reserve</text>')
    points = " ".join(f"{x(s['timestamp']):.1f},{y(s['memAvailableBytes'] / GIB):.1f}" for s in samples)
    parts.append(f'<polyline points="{points}" fill="none" stroke="#333" stroke-width="1.2"/>')
    for locale, summary in runtimes.items():
        for w in summary["perWindow"]:
            if isinstance(w["timestamp"], (int, float)) and w["memAvailableGiB"] is not None:
                parts.append(f'<circle cx="{x(w["timestamp"]):.1f}" cy="{y(w["memAvailableGiB"]):.1f}" r="2.2" '
                             f'fill="{colour.get(locale, "#000")}"/>')
    minutes = int(span // 60)
    step = max(1, minutes // 10)
    for m in range(0, minutes + 1, step):
        parts.append(f'<text x="{x(t0 + m * 60):.1f}" y="{height - bottom + 16}" text-anchor="middle">{m}</text>')
    parts.append(f'<text x="{(left + width - right) / 2}" y="{height - 8}" text-anchor="middle">minutes from first '
                 f'sample · line = host MemAvailable (GiB) · dots = per-window pool samples · top bands: '
                 f'solid GPU stage, light CPU stage</text>')
    legend = left + 4
    for locale in locales:
        parts.append(f'<rect x="{legend}" y="{top + 30}" width="10" height="10" fill="{colour[locale]}"/>'
                     f'<text x="{legend + 14}" y="{top + 39}">{locale}</text>')
        legend += 70
    parts.append("</svg>")
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--lanes-report", type=Path)
    parser.add_argument("--runtime", action="append", default=[])
    parser.add_argument("--asr-memory", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    samples = load_samples(args.samples)
    lanes = json.loads(args.lanes_report.read_text(encoding="utf-8")) if args.lanes_report else None
    stages = stage_rows(lanes, samples)
    runtimes = {locale: runtime_summary(json.loads(path.read_text(encoding="utf-8")))
                for locale, path in _pairs(args.runtime, "--runtime").items()}
    asr = {locale: json.loads(path.read_text(encoding="utf-8"))
           for locale, path in _pairs(args.asr_memory, "--asr-memory").items()}
    summary = {"schemaVersion": "spark-tts-full-episode-memory-curve-v1", "scope": "diagnostic_only",
               "releaseEligible": False, "host": host_summary(samples),
               "lanes": {"status": (lanes or {}).get("status"), "stages": stages},
               "renders": runtimes, "asrScreens": asr,
               "note": "Host MemAvailable on GB10 unified memory; CUDA reserved is per worker and not "
                       "additive to it. No GPU memory peak is available on GB10."}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "memory-curve.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n",
                                                encoding="utf-8")
    render_svg(samples, stages, runtimes, args.out / "memory-curve.svg")
    brief = {"hostMinGiB": summary["host"].get("memAvailableGiB", {}).get("minimum"),
             "renders": {k: {"windows": v["windows"], "minGiB": v["memAvailableGiB"]["minimum"],
                             "drainGiBPerWindow": v["drainGiBPerWindow"], "tripped": v["reserveTripped"]}
                         for k, v in runtimes.items()}}
    print(json.dumps(brief, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
