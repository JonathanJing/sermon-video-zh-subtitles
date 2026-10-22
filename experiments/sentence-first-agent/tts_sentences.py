#!/usr/bin/env python3
"""Synthesize one WAV per sentence with Qwen3-TTS, batch 1 (experiment only).

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
    args = parser.parse_args()
    rows = [json.loads(line) for line in args.speech.read_text(encoding="utf-8").splitlines() if line.strip()]
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
    for row in pending:
        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)
        kwargs = {"text": row["spokenText"], "language": row["language"], "speaker": row["speaker"],
                  "temperature": 0.7, "repetition_penalty": 1.05, "max_new_tokens": args.max_new_tokens}
        if row.get("hint"):
            kwargs["instruct"] = row["hint"]
        started = time.monotonic()
        wavs, rate = model.generate_custom_voice(**kwargs)
        if len(wavs) != 1:
            raise SystemExit(f"{row['id']}: TTS returned {len(wavs)} outputs")
        target = args.out / f"{row['id']}.wav"
        write_wav(target, wavs[0], rate)
        with wave.open(str(target), "rb") as handle:
            seconds = handle.getnframes() / handle.getframerate()
        entry = {"id": row["id"], "seconds": round(seconds, 3),
                 "wallSeconds": round(time.monotonic() - started, 3), "seed": args.seed}
        log.write(json.dumps(entry, ensure_ascii=False) + "\n")
        log.flush()
        print(json.dumps(entry), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
