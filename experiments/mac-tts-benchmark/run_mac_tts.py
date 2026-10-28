#!/usr/bin/env python3
"""Render a sentence-first speech table on Apple Silicon MPS as one model x batch 8.

This is a benchmark driver, not the formal renderer: it measures load time, per-batch
wall time, audio seconds and real-time factor, and writes one WAV per sentence plus a
timings log. Seeds follow the formal batch policy (base seed + window start index).
"""
from __future__ import annotations

import argparse
import json
import math
import time
import wave
from pathlib import Path

import numpy as np
import torch


def load_rows(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, row in enumerate(rows):
        row["_index"] = index
    return rows


def take_seconds(rows: list[dict], seconds: float | None) -> list[dict]:
    if seconds is None:
        return rows
    kept, total = [], 0.0
    for row in rows:
        total += float(row.get("estimatedSeconds") or row.get("budgetSeconds") or 0)
        kept.append(row)
        if total >= seconds:
            break
    return kept


def write_wav(path: Path, wave_data, sample_rate: int) -> float:
    array = np.asarray(wave_data, dtype=np.float32).reshape(-1)
    array = np.clip(array, -1.0, 1.0)
    pcm = (array * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(int(sample_rate))
        stream.writeframes(pcm.tobytes())
    return len(array) / float(sample_rate)


def metrics(samples: np.ndarray) -> dict:
    if samples.size == 0:
        return {"peak": 0.0, "rms": 0.0, "clipped": 0}
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    return {"peak": round(peak, 4), "rms": round(rms, 6), "clipped": int(np.sum(np.abs(samples) >= 0.999))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8, choices=(1, 2, 4, 8))
    parser.add_argument("--limit-seconds", type=float, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    units_dir = args.out / "units"
    units_dir.mkdir(exist_ok=True)
    rows = take_seconds(load_rows(args.speech), args.limit_seconds)
    summary = {"schemaVersion": "sermon-mac-tts-benchmark-v1", "batchSize": args.batch_size,
               "device": "mps", "dtype": "float32", "checkpoint": str(args.checkpoint),
               "sentenceCount": len(rows),
               "seedPolicy": "declared original window seed, else base seed + local window start",
               "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    started = time.monotonic()
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained(str(args.checkpoint), device_map="mps", dtype=torch.float32)
    load_seconds = time.monotonic() - started
    summary["loadSeconds"] = round(load_seconds, 3)

    log_path = args.out / "tts-log.jsonl"
    batches = []
    with log_path.open("w", encoding="utf-8") as log:
        for window_start in range(0, len(rows), args.batch_size):
            window = rows[window_start:window_start + args.batch_size]
            declared = {row["seed"] for row in window if "seed" in row}
            if declared:
                if len(declared) != 1 or any("seed" not in row for row in window):
                    raise SystemExit("a batch must carry one declared seed on every row")
                seed = declared.pop()
                if seed != args.seed + int(window[0].get("windowStart", window_start)):
                    raise SystemExit("declared seed differs from base seed + original window start")
            else:
                seed = args.seed + window_start
            torch.manual_seed(seed)
            requests = {"text": [row["spokenText"] for row in window],
                        "language": [row["language"] for row in window],
                        "speaker": [row["speaker"] for row in window],
                        "temperature": 0.7, "repetition_penalty": 1.05, "max_new_tokens": 768}
            batch_started = time.monotonic()
            wavs, sample_rate = model.generate_custom_voice(**requests)
            if torch.backends.mps.is_available():
                torch.mps.synchronize()
            wall = time.monotonic() - batch_started
            if len(wavs) != len(window):
                raise SystemExit(f"batch returned {len(wavs)} waves for {len(window)} requests")
            audio_seconds = 0.0
            for row, wav in zip(window, wavs):
                array = wav.detach().cpu().numpy() if hasattr(wav, "detach") else np.asarray(wav)
                path = units_dir / f"{row['id']}.wav"
                seconds = write_wav(path, array, sample_rate)
                audio_seconds += seconds
                entry = {"id": row["id"], "audioSeconds": round(seconds, 3),
                         "originalIndex": row.get("_originalIndex"), "windowStart": row.get("windowStart"),
                         "estimatedSeconds": row.get("estimatedSeconds"),
                         "budgetSeconds": row.get("budgetSeconds"),
                         "wallSeconds": round(wall, 3),
                         "seed": seed, "sampleRate": sample_rate, **metrics(np.asarray(array).reshape(-1))}
                log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            torch.mps.empty_cache()
            batches.append({"windowStart": window_start, "sentences": len(window), "seed": seed,
                            "wallSeconds": round(wall, 3), "audioSeconds": round(audio_seconds, 3),
                            "realTimeFactor": round(wall / audio_seconds, 4) if audio_seconds else None})
            print(json.dumps({"batch": len(batches), "windowStart": window_start,
                              "sentences": len(window), "wallSeconds": round(wall, 3),
                              "audioSeconds": round(audio_seconds, 3)}), flush=True)

    total_wall = sum(row["wallSeconds"] for row in batches)
    total_audio = sum(row["audioSeconds"] for row in batches)
    summary.update({"finishedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "batchCount": len(batches), "synthesisWallSeconds": round(total_wall, 3),
                    "audioSeconds": round(total_audio, 3),
                    "realTimeFactor": round(total_wall / total_audio, 4) if total_audio else None,
                    "seeds": [row["seed"] for row in batches], "batches": batches})
    (args.out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("sentenceCount", "loadSeconds", "synthesisWallSeconds",
                                              "audioSeconds", "realTimeFactor")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
