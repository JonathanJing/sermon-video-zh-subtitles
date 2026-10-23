#!/usr/bin/env python3
"""Synthesize one WAV per sentence with Qwen3-TTS (experiment only).

``--batch-size`` defaults to 1; batch>1 sends several sentences per model call
(the formal renderer's batch API). Batch>1 changes the sound identity of the
members, so a later single-sentence repair re-synthesizes its batch window.

Runs on the machine that holds the checkpoint and ``qwen_tts`` (normally DGX
Spark). Reads ``speech.jsonl`` rows: id, spokenText, language, speaker, hint.
Existing ``<out>/<id>.wav`` files are skipped, so a stopped run resumes. No
time stretching, no identity binding, no cache beyond the files themselves.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time
import wave


def write_wav(path: Path, samples, rate: int) -> None:
    import numpy as np
    pcm = np.clip(np.asarray(samples, dtype="float64"), -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    tmp = path.with_suffix(".partial.wav")
    with wave.open(str(tmp), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speech", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=("bfloat16", "float32"), default="bfloat16")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--max-new-tokens", type=int, default=768)
    parser.add_argument("--only-speaker", help="synthesize only rows whose speaker key is this (one checkpoint per run)")
    parser.add_argument("--batch-size", type=int, default=1, help="sentences per model call (batch>1 changes sound identity)")
    parser.add_argument("--only-ids-file", type=Path, help="process only these ids in speech order (repair a batch window)")
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.speech.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.only_speaker:
        rows = [row for row in rows if row["speaker"] == args.only_speaker]
        if not rows:
            raise SystemExit(f"no rows with speaker {args.only_speaker!r}")
    if args.only_ids_file:
        wanted = json.loads(args.only_ids_file.read_text(encoding="utf-8"))
        if not isinstance(wanted, list) or not all(isinstance(x, str) for x in wanted):
            raise SystemExit("--only-ids-file must be a JSON list of ids")
        unknown = sorted(set(wanted) - {row["id"] for row in rows})
        if unknown:
            raise SystemExit(f"unknown ids in --only-ids-file: {unknown[:10]}")
        rows = [row for row in rows if row["id"] in set(wanted)]
        if not rows:
            raise SystemExit("--only-ids-file selected no rows")
    args.out.mkdir(parents=True, exist_ok=True)
    pending = [row for row in rows if not (args.out / f"{row['id']}.wav").exists()]
    print(json.dumps({"sentences": len(rows), "pending": len(pending)}), flush=True)
    if not pending:
        return 0
    import torch
    from qwen_tts import Qwen3TTSModel
    model = Qwen3TTSModel.from_pretrained(
        str(args.checkpoint), device_map=args.device,
        dtype=torch.bfloat16 if args.dtype == "bfloat16" else torch.float32)
    log = (args.out / "tts-log.jsonl").open("a", encoding="utf-8")
    batch_log = (args.out / "tts-batches.jsonl").open("a", encoding="utf-8")
    batch_size = max(1, args.batch_size)
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)
        kwargs = {"text": [row["spokenText"] for row in batch],
                  "language": [row["language"] for row in batch],
                  "speaker": [row["speaker"] for row in batch],
                  "temperature": 0.7, "repetition_penalty": 1.05, "max_new_tokens": args.max_new_tokens}
        hints = [row.get("hint") or "" for row in batch]
        if any(hints):
            kwargs["instruct"] = hints
        started = time.monotonic()
        wavs, rate = model.generate_custom_voice(**kwargs)
        wall = time.monotonic() - started
        if len(wavs) != len(batch):
            raise SystemExit(f"batch {batch[0]['id']}: TTS returned {len(wavs)} outputs for {len(batch)} rows")
        per_row = wall / len(batch)
        batch_seconds = 0.0
        for row, wav in zip(batch, wavs):
            target = args.out / f"{row['id']}.wav"
            write_wav(target, wav, rate)
            with wave.open(str(target), "rb") as handle:
                seconds = handle.getnframes() / handle.getframerate()
            batch_seconds += seconds
            entry = {"id": row["id"], "seconds": round(seconds, 3),
                     "wallSeconds": round(per_row, 3), "seed": args.seed, "batchSize": len(batch)}
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            log.flush()
            print(json.dumps(entry), flush=True)
        batch_entry = {"batchIndex": start // batch_size, "ids": [row["id"] for row in batch],
                       "seed": args.seed, "batchSize": len(batch),
                       "wallSeconds": round(wall, 3), "audioSeconds": round(batch_seconds, 3)}
        batch_log.write(json.dumps(batch_entry, ensure_ascii=False) + "\n")
        batch_log.flush()
        print(json.dumps(batch_entry), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
